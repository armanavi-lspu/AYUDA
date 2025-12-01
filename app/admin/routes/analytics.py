from flask import render_template, jsonify, request
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.utils import role_required
from app.models import Applications, Programs, CommunityUsers, User
from app.extensions import db
from app.recommender import generate_beneficiary_recommendations
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
    """API endpoint to generate beneficiary recommendations using content-based filtering"""
    data = request.get_json()
    
    # Extract and validate parameters
    program_id = data.get('program_id')
    
    try:
        max_beneficiaries = int(data.get('max_beneficiaries', 50))
        if max_beneficiaries < 1:
            max_beneficiaries = 50
    except (ValueError, TypeError):
        max_beneficiaries = 50
    
    priority_barangay = data.get('priority_barangay')
    
    try:
        min_income = float(data.get('min_income', 0))
        if min_income < 0:
            min_income = 0
    except (ValueError, TypeError):
        min_income = 0
    
    try:
        max_income = float(data.get('max_income', 999999999))
        if max_income < 0:
            max_income = 999999999
    except (ValueError, TypeError):
        max_income = 999999999
    
    solo_parent_priority = data.get('solo_parent_priority', False)
    student_priority = data.get('student_priority', False)
    
    # Query all community users with their profile data
    query = db.session.query(
        User.id.label('user_id'),
        User.first_name,
        User.last_name,
        User.email,
        CommunityUsers.barangay,
        CommunityUsers.sitio,
        CommunityUsers.municipality,
        CommunityUsers.family_annual_income,
        CommunityUsers.is_solo_parent,
        CommunityUsers.is_student,
        CommunityUsers.is_pwd,
        CommunityUsers.is_currently_employed,
        CommunityUsers.occupation,
        CommunityUsers.age
    ).join(
        CommunityUsers, User.id == CommunityUsers.user_id
    )
    
    # Get all beneficiaries as a list of dictionaries
    beneficiaries = []
    for r in query.all():
        beneficiaries.append({
            'user_id': r.user_id,
            'first_name': r.first_name,
            'last_name': r.last_name,
            'email': r.email,
            'barangay': r.barangay,
            'sitio': r.sitio,
            'municipality': r.municipality,
            'family_annual_income': float(r.family_annual_income) if r.family_annual_income else 0,
            'is_solo_parent': r.is_solo_parent,
            'is_student': r.is_student,
            'is_pwd': r.is_pwd,
            'is_currently_employed': r.is_currently_employed,
            'occupation': r.occupation,
            'age': r.age
        })
    
    # Prepare filters for the recommender
    filters = {
        'priority_barangay': priority_barangay if priority_barangay else None,
        'min_income': min_income,
        'max_income': max_income,
        'solo_parent_priority': solo_parent_priority,
        'student_priority': student_priority
    }
    
    # Generate recommendations using content-based filtering
    recommendations = generate_beneficiary_recommendations(
        beneficiaries=beneficiaries,
        filters=filters,
        max_results=max_beneficiaries
    )
    
    return jsonify({
        'success': True,
        'count': len(recommendations),
        'recommendations': recommendations,
        'message': 'Recommendations generated successfully using content-based filtering (TF-IDF + NearestNeighbors)'
    })