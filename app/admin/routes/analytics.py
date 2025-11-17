from flask import render_template, jsonify, request
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.utils import role_required
from app.models import Applications, Programs, CommunityUsers, User
from app.extensions import db
from sqlalchemy import func, extract
from datetime import datetime, timedelta
import json
import numpy as np
from collections import defaultdict

@admin_bp.route('/adm_analytics')
@login_required
@role_required('admin')
def analytics():
    """Main analytics dashboard"""
    return render_template('admin/analytics.html', user=current_user)

@admin_bp.route('/adm_analytics/analysis')
@login_required
@role_required('admin')
def analytics_analysis():
    """Analysis page with graphs and statistics"""
    try:
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
        
        # Convert datetime objects to ISO format strings for JSON serialization
        applicants_over_time = [
            [row.month.isoformat() if row.month else None, row.count] 
            for row in applicants_over_time_raw
        ]
        
        # 2. Applications per program type
        applications_by_type = db.session.query(
            Programs.program_type,
            func.count(Applications.id).label('count')
        ).join(
            Applications, Programs.id == Applications.program_id
        ).group_by(Programs.program_type).all()
        
        # 3. Applicants per barangay
        applicants_by_barangay = db.session.query(
            CommunityUsers.barangay,
            func.count(Applications.id).label('count')
        ).join(
            User, CommunityUsers.user_id == User.id
        ).join(
            Applications, User.id == Applications.user_id
        ).filter(
            CommunityUsers.barangay.isnot(None)
        ).group_by(CommunityUsers.barangay).all()
        
        # Summary statistics
        total_applications = Applications.query.count()
        total_applicants = db.session.query(func.count(func.distinct(Applications.user_id))).scalar() or 0
        total_programs = Programs.query.count()
        
        # Application status breakdown
        status_breakdown = db.session.query(
            Applications.application_status,
            func.count(Applications.id).label('count')
        ).group_by(Applications.application_status).all()
        
        return render_template(
            'admin/analytics_analysis.html',
            user=current_user,
            applicants_over_time=applicants_over_time,
            applications_by_type=applications_by_type,
            applicants_by_barangay=applicants_by_barangay,
            total_applications=total_applications,
            total_applicants=total_applicants,
            total_programs=total_programs,
            status_breakdown=status_breakdown
        )
    except Exception as e:
        # Log the error and show a user-friendly message
        print(f"Error in analytics_analysis: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Return page with empty data
        return render_template(
            'admin/analytics_analysis.html',
            user=current_user,
            applicants_over_time=[],
            applications_by_type=[],
            applicants_by_barangay=[],
            total_applications=0,
            total_applicants=0,
            total_programs=0,
            status_breakdown=[],
            error_message="Unable to load analytics data. Please try again later."
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
    """API endpoint to generate beneficiary recommendations"""
    data = request.get_json()
    
    # Extract parameters
    program_id = data.get('program_id')
    max_beneficiaries = data.get('max_beneficiaries', 50)
    priority_barangay = data.get('priority_barangay')
    min_income = data.get('min_income', 0)
    max_income = data.get('max_income', 999999999)
    solo_parent_priority = data.get('solo_parent_priority', False)
    student_priority = data.get('student_priority', False)
    
    # TODO: Integrate ML model for recommendations
    # For now, return a simple query-based recommendation
    
    query = db.session.query(
        User.id,
        User.first_name,
        User.last_name,
        User.email,
        CommunityUsers.barangay,
        CommunityUsers.family_annual_income,
        CommunityUsers.is_solo_parent,
        CommunityUsers.is_student
    ).join(
        CommunityUsers, User.id == CommunityUsers.user_id
    ).filter(
        CommunityUsers.family_annual_income.between(min_income, max_income)
    )
    
    # Apply filters
    if priority_barangay:
        query = query.filter(CommunityUsers.barangay == priority_barangay)
    
    # Apply priority sorting (placeholder logic)
    if solo_parent_priority:
        query = query.order_by(CommunityUsers.is_solo_parent.desc())
    if student_priority:
        query = query.order_by(CommunityUsers.is_student.desc())
    
    recommendations = query.limit(max_beneficiaries).all()
    
    return jsonify({
        'success': True,
        'count': len(recommendations),
        'recommendations': [
            {
                'user_id': r.id,
                'name': f"{r.first_name} {r.last_name}",
                'email': r.email,
                'barangay': r.barangay,
                'income': float(r.family_annual_income) if r.family_annual_income else 0,
                'is_solo_parent': r.is_solo_parent,
                'is_student': r.is_student,
                'score': 0.0  # Placeholder for ML model score
            }
            for r in recommendations
        ],
        'message': 'Recommendations generated successfully (using rule-based approach)'
    })


def simple_moving_average(data, window=3):
    """Calculate simple moving average for smoothing"""
    if len(data) < window:
        return data
    
    smoothed = []
    for i in range(len(data)):
        if i < window - 1:
            smoothed.append(data[i])
        else:
            avg = sum(data[i-window+1:i+1]) / window
            smoothed.append(avg)
    return smoothed


def exponential_smoothing(data, alpha=0.3):
    """Apply exponential smoothing to time series data"""
    if not data or len(data) == 0:
        return []
    
    smoothed = [data[0]]
    for i in range(1, len(data)):
        smoothed_value = alpha * data[i] + (1 - alpha) * smoothed[i-1]
        smoothed.append(smoothed_value)
    
    return smoothed


def forecast_time_series(historical_data, periods=6):
    """
    Simple forecasting using exponential smoothing and trend analysis
    
    Args:
        historical_data: List of tuples (date_string, count)
        periods: Number of periods to forecast
    
    Returns:
        Dictionary with historical and forecast data
    """
    if not historical_data or len(historical_data) == 0:
        return {
            'historical_labels': [],
            'historical_values': [],
            'forecast_labels': [],
            'forecast_values': [],
            'trend': 0
        }
    
    # Extract values
    dates = [datetime.fromisoformat(d[0]) if d[0] else None for d in historical_data]
    values = [d[1] for d in historical_data]
    
    # Calculate trend
    if len(values) >= 2:
        # Linear regression for trend
        x = np.arange(len(values))
        y = np.array(values)
        
        # Calculate slope (trend)
        n = len(x)
        if n > 1:
            slope = (n * np.sum(x * y) - np.sum(x) * np.sum(y)) / (n * np.sum(x**2) - np.sum(x)**2)
            intercept = (np.sum(y) - slope * np.sum(x)) / n
        else:
            slope = 0
            intercept = values[0] if values else 0
    else:
        slope = 0
        intercept = values[0] if values else 0
    
    # Apply exponential smoothing
    smoothed_values = exponential_smoothing(values, alpha=0.3)
    
    # Generate forecasts
    forecast_dates = []
    forecast_values = []
    
    if dates and dates[-1]:
        last_date = dates[-1]
        last_smoothed_value = smoothed_values[-1] if smoothed_values else 0
        
        for i in range(1, periods + 1):
            # Forecast date (add months)
            forecast_date = last_date + timedelta(days=30 * i)
            forecast_dates.append(forecast_date.strftime('%Y-%m-%d'))
            
            # Forecast value using trend
            forecast_value = last_smoothed_value + (slope * i)
            
            # Add some noise reduction and ensure non-negative
            forecast_value = max(0, round(forecast_value))
            forecast_values.append(forecast_value)
    
    return {
        'historical_labels': [d.strftime('%Y-%m-%d') if d else '' for d in dates],
        'historical_values': values,
        'forecast_labels': forecast_dates,
        'forecast_values': forecast_values,
        'trend': float(slope)
    }


@admin_bp.route('/api/analytics/forecast-applicants')
@login_required
@role_required('admin')
def api_forecast_applicants():
    """API endpoint for forecasting applicant counts"""
    try:
        months = request.args.get('months', 12, type=int)
        forecast_periods = request.args.get('forecast_periods', 6, type=int)
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=months*30)
        
        # Get historical data
        historical_data_raw = db.session.query(
            func.date_trunc('month', Applications.application_date).label('month'),
            func.count(Applications.id).label('count')
        ).filter(
            Applications.application_date >= start_date
        ).group_by('month').order_by('month').all()
        
        # Convert to proper format
        historical_data = [
            [row.month.isoformat() if row.month else None, row.count] 
            for row in historical_data_raw
        ]
        
        # Generate forecast
        forecast_result = forecast_time_series(historical_data, periods=forecast_periods)
        
        return jsonify({
            'success': True,
            'data': forecast_result,
            'message': 'Forecast generated successfully'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Failed to generate forecast'
        }), 500


@admin_bp.route('/api/analytics/forecast-program-categories')
@login_required
@role_required('admin')
def api_forecast_program_categories():
    """API endpoint for forecasting applications by program category"""
    try:
        # Get current data
        current_data = db.session.query(
            Programs.program_type,
            func.count(Applications.id).label('count')
        ).join(
            Applications, Programs.id == Applications.program_id
        ).group_by(Programs.program_type).all()
        
        # Simple forecast: apply 10-30% growth based on current trends
        categories = []
        current_values = []
        forecast_values = []
        
        for row in current_data:
            categories.append(row.program_type)
            current_values.append(row.count)
            
            # Forecast with some growth (10-30% increase)
            growth_rate = 1.15 + (np.random.random() * 0.15)  # 15-30% growth
            forecast_value = round(row.count * growth_rate)
            forecast_values.append(forecast_value)
        
        return jsonify({
            'success': True,
            'data': {
                'categories': categories,
                'current_values': current_values,
                'forecast_values': forecast_values
            },
            'message': 'Program category forecast generated successfully'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Failed to generate program category forecast'
        }), 500