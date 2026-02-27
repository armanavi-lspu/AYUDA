
from flask import render_template, jsonify, request, redirect, url_for
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.utils import role_required
from app.models import Applications, Programs, CommunityUsers, User
from app.extensions import db
from app.forecasting import arima_forecast, forecast_program_growth
from app.recommender import get_recommendations
from sqlalchemy import func, extract
from datetime import datetime, timedelta
import json

@admin_bp.route('/adm_analytics')
@login_required
@role_required('admin')
def analytics():
    """Main analytics dashboard - redirect to analysis page"""
    return redirect(url_for('admin.analytics_analysis'))

@admin_bp.route('/adm_analytics/analysis')
@login_required
@role_required('admin')
def analytics_analysis():
    """Analysis page with graphs and statistics"""
    # Get date range for filtering (default: last 12 months)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=365)
    
    # 1. Applicants count over time (monthly aggregation)
    applicants_over_time_raw = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()
    
    # Convert to JSON-friendly format
    applicants_over_time = {
        'labels': [row.month.strftime('%B %Y') if row.month else '' for row in applicants_over_time_raw],
        'data': [row.count for row in applicants_over_time_raw]
    }
    
    # 2. Applications per program type
    applications_by_type_raw = db.session.query(
        Programs.program_type,
        func.count(Applications.id).label('count')
    ).join(
        Applications, Programs.id == Applications.program_id
    ).group_by(Programs.program_type).all()
    
    applications_by_type = {
        'labels': [row.program_type for row in applications_by_type_raw],
        'data': [row.count for row in applications_by_type_raw]
    }
    
    # 3. Applicants per barangay
    applicants_by_barangay_raw = db.session.query(
        CommunityUsers.barangay,
        func.count(Applications.id).label('count')
    ).join(
        User, CommunityUsers.user_id == User.id
    ).join(
        Applications, User.id == Applications.user_id
    ).filter(
        CommunityUsers.barangay.isnot(None)
    ).group_by(CommunityUsers.barangay).order_by(func.count(Applications.id).desc()).limit(10).all()
    
    applicants_by_barangay = {
        'labels': [row.barangay for row in applicants_by_barangay_raw],
        'data': [row.count for row in applicants_by_barangay_raw]
    }
    
    # Summary statistics
    total_applications = Applications.query.count()
    total_applicants = db.session.query(func.count(func.distinct(Applications.user_id))).scalar()
    total_programs = Programs.query.count()
    
    # Application status breakdown
    status_breakdown = db.session.query(
        Applications.application_status,
        func.count(Applications.id).label('count')
    ).group_by(Applications.application_status).all()
    
    return render_template(
        'admin/analytics_analysis.html',
        user=current_user,
        applicants_over_time_json=json.dumps(applicants_over_time),
        applications_by_type_json=json.dumps(applications_by_type),
        applicants_by_barangay_json=json.dumps(applicants_by_barangay),
        total_applications=total_applications,
        total_applicants=total_applicants,
        total_programs=total_programs,
        status_breakdown=status_breakdown
    )

@admin_bp.route('/adm_analytics/recommend')
@login_required
@role_required('admin')
def analytics_recommend():
    """Recommendation page for beneficiary selection"""
    # Get all programs for selection
    programs = Programs.query.all()
    
    # Get available barangays
    barangays = db.session.query(
        CommunityUsers.barangay
    ).filter(
        CommunityUsers.barangay.isnot(None)
    ).distinct().all()
    
    return render_template(
        'admin/analytics_recommend.html',
        user=current_user,
        programs=programs,
        barangays=[b[0] for b in barangays]
    )

@admin_bp.route('/api/program/<int:program_id>/parameters')
@login_required
@role_required('admin')
def api_get_program_parameters(program_id):
    """API endpoint to fetch program parameters for auto-fill"""
    program = Programs.query.get_or_404(program_id)
    
    return jsonify({
        'success': True,
        'priority_group': program.priority_group,
        'income_range': program.income_range,
        'beneficiary_limit': program.beneficiary_limit
    })

@admin_bp.route('/api/analytics/applicants-timeseries')
@login_required
@role_required('admin')
def api_applicants_timeseries():
    """API endpoint for applicants time series data"""
    months = request.args.get('months', 12, type=int)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=months*30)
    
    data = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()
    
    return jsonify({
        'labels': [d.month.strftime('%B %Y') for d in data],
        'values': [d.count for d in data]
    })

@admin_bp.route('/api/analytics/generate-recommendations', methods=['POST'])
@login_required
@role_required('admin')
def api_generate_recommendations():
    """
    API endpoint to generate beneficiary recommendations using content-based filtering.
    
    Request Body (JSON):
        program_id: Target program ID for recommendations
        max_beneficiaries: Maximum number of recommendations to return (default: 50)
        priority_barangays: List of barangay names to filter by. If empty list or not 
                           provided, all barangays are included in recommendations.
        min_income: Minimum annual income filter (default: 0)
        max_income: Maximum annual income filter (default: 999999999)
        solo_parent_priority: Boolean to prioritize solo parents in scoring (default: False)
        student_priority: Boolean to prioritize students in scoring (default: False)
        pwd_priority: Boolean to prioritize PWDs in scoring (default: False)
    
    Returns:
        JSON with success status, count, recommendations list, and message
    """
    data = request.get_json()
    
    # Extract parameters with validation
    program_id = data.get('program_id')
    
    try:
        max_beneficiaries = int(data.get('max_beneficiaries', 50))
        if max_beneficiaries < 1:
            return jsonify({'success': False, 'message': 'Max beneficiaries must be at least 1'}), 400
        if max_beneficiaries > 1000:
            return jsonify({'success': False, 'message': 'Max beneficiaries cannot exceed 1000'}), 400
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid max_beneficiaries value'}), 400
    
    # priority_barangays is a list of barangay names; empty list means include all barangays
    priority_barangays = data.get('priority_barangays', [])
    
    # Validate income range with comprehensive error handling
    try:
        min_income = float(data.get('min_income', 0) or 0)
        max_income = float(data.get('max_income', 10000000) or 10000000)
        
        # Validate min_income
        if min_income < 0:
            return jsonify({'success': False, 'message': 'Minimum income cannot be negative'}), 400
        if min_income > 10000000:
            return jsonify({'success': False, 'message': 'Minimum income exceeds maximum allowed value (₱10,000,000)'}), 400
        
        # Validate max_income
        if max_income < 0:
            return jsonify({'success': False, 'message': 'Maximum income cannot be negative'}), 400
        if max_income > 10000000:
            return jsonify({'success': False, 'message': 'Maximum income exceeds maximum allowed value (₱10,000,000)'}), 400
        
        # Validate range logic
        if min_income > max_income:
            return jsonify({'success': False, 'message': 'Minimum income cannot be greater than maximum income'}), 400
            
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': f'Invalid income range format: {str(e)}'}), 400
    
    solo_parent_priority = data.get('solo_parent_priority', False)
    student_priority = data.get('student_priority', False)
    pwd_priority = data.get('pwd_priority', False)
    
    # Query all community users with their profiles
    query = db.session.query(
        User.id,
        User.first_name,
        User.last_name,
        User.email,
        CommunityUsers.age,
        CommunityUsers.barangay,
        CommunityUsers.family_annual_income,
        CommunityUsers.is_solo_parent,
        CommunityUsers.is_student,
        CommunityUsers.is_pwd,
        CommunityUsers.is_currently_employed,
        CommunityUsers.occupation
    ).join(
        CommunityUsers, User.id == CommunityUsers.user_id
    )
    
    all_users = query.all()
    
    # Convert to list of dictionaries for the recommender with income validation
    beneficiaries_data = [
        {
            'user_id': u.id,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'email': u.email,
            'age': u.age,
            'barangay': u.barangay,
            'family_annual_income': float(u.family_annual_income) if u.family_annual_income and 0 <= u.family_annual_income <= 10000000 else 0,
            'is_solo_parent': u.is_solo_parent,
            'is_student': u.is_student,
            'is_pwd': u.is_pwd,
            'is_currently_employed': u.is_currently_employed,
            'occupation': u.occupation
        }
        for u in all_users
    ]
    
    # Use content-based filtering to get recommendations
    recommendations = get_recommendations(
        beneficiaries_data=beneficiaries_data,
        max_beneficiaries=max_beneficiaries,
        solo_parent_priority=solo_parent_priority,
        student_priority=student_priority,
        pwd_priority=pwd_priority,
        priority_barangays=priority_barangays if priority_barangays else None,
        min_income=min_income,
        max_income=max_income
    )
    
    return jsonify({
        'success': True,
        'count': len(recommendations),
        'recommendations': [
            {
                'user_id': r.get('user_id'),
                'name': f"{r.get('first_name', '')} {r.get('last_name', '')}",
                'email': r.get('email', ''),
                'barangay': r.get('barangay', 'N/A'),
                'income': r.get('family_annual_income', 0),
                'is_solo_parent': r.get('is_solo_parent', False),
                'is_student': r.get('is_student', False),
                'is_pwd': r.get('is_pwd', False),
                'score': r.get('score', 0.0)
            }
            for r in recommendations
        ],
        'message': 'Recommendations generated using content-based filtering algorithm'
    })

@admin_bp.route('/api/analytics/arima-forecast')
@login_required
@role_required('admin')
def api_arima_forecast():
    """API endpoint for ARIMA-based applicants forecast"""
    # Get parameters
    months = request.args.get('months', 12, type=int)
    forecast_periods = request.args.get('forecast_periods', 6, type=int)
    force_arima = request.args.get('force_arima', 'false').lower() == 'true'
    
    # Limit forecast periods for stability
    forecast_periods = min(forecast_periods, 12)
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=months * 30)
    
    # Query historical data
    historical_data = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()
    
    # Prepare data for ARIMA
    labels = [d.month.strftime('%B %Y') for d in historical_data if d.month]
    values = [d.count for d in historical_data]
    
    # Generate ARIMA forecast with force mode
    forecast_result = arima_forecast(values, labels, periods=forecast_periods, force_arima=force_arima)
    
    return jsonify({
        'historical': {
            'labels': labels,
            'values': values
        },
        'forecast': forecast_result,
        'model': forecast_result.get('model', 'unknown'),
        'data_points': len(values),
        'force_arima_mode': force_arima,
        'arima_error': forecast_result.get('arima_error', None)
    })

@admin_bp.route('/api/analytics/program-forecast')
@login_required
@role_required('admin')
def api_program_forecast():
    """API endpoint for program category growth forecast"""
    growth_rate = request.args.get('growth_rate', type=float)
    
    # Query current program applications
    applications_by_type = db.session.query(
        Programs.program_type,
        func.count(Applications.id).label('count')
    ).join(
        Applications, Programs.id == Applications.program_id
    ).group_by(Programs.program_type).all()
    
    program_data = {
        'labels': [row.program_type for row in applications_by_type],
        'data': [row.count for row in applications_by_type]
    }
    
    # Generate program growth forecast
    forecast_result = forecast_program_growth(program_data, growth_rate)
    
    return jsonify(forecast_result)

@admin_bp.route('/api/analytics/test-arima')
@login_required
@role_required('admin')
def api_test_arima():
    """Test endpoint to validate ARIMA model performance"""
    # Get all historical data
    all_data = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).group_by('month').order_by('month').all()
    
    labels = [d.month.strftime('%B %Y') for d in all_data if d.month]
    values = [d.count for d in all_data]
    
    # Test with different configurations
    results = {}
    
    # Test 1: Standard ARIMA (12 months minimum)
    forecast_12 = arima_forecast(values, labels, periods=6, force_arima=False)
    results['standard_12mo'] = {
        'model': forecast_12.get('model'),
        'success': forecast_12.get('success'),
        'data_points': len(values),
        'error': forecast_12.get('arima_error')
    }
    
    # Test 2: Forced ARIMA mode
    forecast_forced = arima_forecast(values, labels, periods=6, force_arima=True)
    results['forced_mode'] = {
        'model': forecast_forced.get('model'),
        'success': forecast_forced.get('success'),
        'data_points': len(values),
        'error': forecast_forced.get('arima_error')
    }
    
    # Test 3: Last 6 months only
    if len(values) >= 6:
        forecast_6 = arima_forecast(values[-6:], labels[-6:], periods=3, force_arima=False)
        results['last_6mo'] = {
            'model': forecast_6.get('model'),
            'success': forecast_6.get('success'),
            'data_points': 6,
            'error': forecast_6.get('arima_error')
        }
    
    return jsonify({
        'total_data_points': len(values),
        'date_range': f"{labels[0]} to {labels[-1]}" if labels else "No data",
        'tests': results,
        'recommendations': {
            'min_points_for_arima': 12,
            'min_points_for_seasonality': 36,
            'current_status': 'ARIMA ready' if len(values) >= 12 else 'Need more data'
        }
    })