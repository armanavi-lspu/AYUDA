from flask import render_template, jsonify, request
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.utils import role_required
from app.models import Applications, Programs, CommunityUsers, User
from app.extensions import db
from sqlalchemy import func, extract
from datetime import datetime, timedelta
import json

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
    # Get date range for filtering (default: last 12 months)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=365)
    
    # 1. Applicants count over time (monthly aggregation)
    applicants_over_time = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()
    
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
        applicants_over_time=applicants_over_time,
        applications_by_type=applications_by_type,
        applicants_by_barangay=applicants_by_barangay,
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