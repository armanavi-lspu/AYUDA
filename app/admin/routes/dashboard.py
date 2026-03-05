from flask import render_template, jsonify, redirect, url_for, jsonify, request, flash
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, func, extract, case, cast, Date
from app.admin import admin_bp
from app.models import (
    User, Programs, Applications, Announcements, CommunityUsers
)
from app.extensions import db
import json

def get_monthly_trend_data():
    """Get monthly application trend data for the last 12 months"""
    now = datetime.utcnow()
    twelve_months_ago = now - timedelta(days=365)
    
    # Query database for monthly counts - PostgreSQL syntax
    monthly_data = db.session.query(
        extract('year', Applications.application_date).label('year'),
        extract('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= twelve_months_ago
    ).group_by(
        extract('year', Applications.application_date),
        extract('month', Applications.application_date)
    ).order_by(
        extract('year', Applications.application_date),
        extract('month', Applications.application_date)
    ).all()
    
    # Create a dictionary for easy lookup
    data_dict = {(int(row.year), int(row.month)): row.count for row in monthly_data}
    
    # Generate labels and data for the last 12 months
    labels = []
    counts = []
    
    for i in range(11, -1, -1):  # Start from 11 months ago to current month
        month_date = now - timedelta(days=30 * i)
        month_label = month_date.strftime('%b %Y')
        year = month_date.year
        month = month_date.month
        
        labels.append(month_label)
        counts.append(data_dict.get((year, month), 0))
    
    return {
        'labels': labels,
        'data': counts
    }

def get_weekly_trend_data():
    """Get weekly application trend data for the last 7 days"""
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)
    
    # Query database for daily counts - PostgreSQL syntax
    # Use cast to DATE instead of func.date()
    daily_data = db.session.query(
        cast(Applications.application_date, Date).label('date'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= seven_days_ago
    ).group_by(
        cast(Applications.application_date, Date)
    ).all()
    
    # Create a dictionary for easy lookup
    data_dict = {row.date: row.count for row in daily_data}
    
    # Generate labels and data for the last 7 days
    labels = []
    counts = []
    
    for i in range(6, -1, -1):  # From 6 days ago to today
        day = (now - timedelta(days=i)).date()
        day_label = day.strftime('%a')  # Mon, Tue, Wed, etc.
        
        labels.append(day_label)
        counts.append(data_dict.get(day, 0))
    
    return {
        'labels': labels,
        'data': counts
    }

def get_status_distribution():
    """Get application status distribution"""
    status_data = db.session.query(
        Applications.application_status,
        func.count(Applications.id).label('count')
    ).group_by(Applications.application_status).all()
    
    return {
        'labels': [row.application_status.replace('_', ' ').title() for row in status_data],
        'data': [row.count for row in status_data]
    }

def get_applications_by_program():
    """Get applications count by program type"""
    program_data = db.session.query(
        Programs.program_type,
        func.count(Applications.id).label('count')
    ).outerjoin(
        Applications, Programs.id == Applications.program_id
    ).group_by(Programs.program_type).all()
    
    return {
        'labels': [row.program_type for row in program_data],
        'data': [row.count for row in program_data]
    }

def get_barangay_distribution():
    """Get top 10 barangays by application count"""
    barangay_data = db.session.query(
        CommunityUsers.barangay,
        func.count(Applications.id).label('count')
    ).join(
        User, CommunityUsers.user_id == User.id
    ).join(
        Applications, User.id == Applications.user_id
    ).filter(
        CommunityUsers.barangay.isnot(None)
    ).group_by(
        CommunityUsers.barangay
    ).order_by(desc('count')).limit(10).all()
    
    return {
        'labels': [row.barangay for row in barangay_data],
        'data': [row.count for row in barangay_data]
    }

def get_age_distribution():
    """Get age distribution of applicants"""
    # PostgreSQL syntax for CASE statement
    age_data = db.session.query(
        case(
            (CommunityUsers.age < 18, 'Under 18'),
            (CommunityUsers.age.between(18, 25), '18-25'),
            (CommunityUsers.age.between(26, 35), '26-35'),
            (CommunityUsers.age.between(36, 45), '36-45'),
            (CommunityUsers.age.between(46, 60), '46-60'),
            else_='60+'
        ).label('age_group'),
        func.count(Applications.id).label('count')
    ).join(
        User, CommunityUsers.user_id == User.id
    ).join(
        Applications, User.id == Applications.user_id
    ).filter(
        CommunityUsers.age.isnot(None)
    ).group_by('age_group').all()
    
    # Define the order for age groups
    age_order = ['Under 18', '18-25', '26-35', '36-45', '46-60', '60+']
    data_dict = {row.age_group: row.count for row in age_data}
    
    return {
        'labels': age_order,
        'data': [data_dict.get(age_group, 0) for age_group in age_order]
    }

def get_employment_distribution():
    """Get employment status distribution of applicants"""
    # PostgreSQL uses True/False for boolean values
    employment_stats = db.session.query(
        func.sum(case((CommunityUsers.is_currently_employed == True, 1), else_=0)).label('employed'),
        func.sum(case((CommunityUsers.is_student == True, 1), else_=0)).label('student'),
        func.sum(case((CommunityUsers.is_solo_parent == True, 1), else_=0)).label('solo_parent')
    ).join(
        User, CommunityUsers.user_id == User.id
    ).join(
        Applications, User.id == Applications.user_id
    ).first()
    
    return {
        'labels': ['Employed', 'Student', 'Solo Parent'],
        'data': [
            int(employment_stats.employed) if employment_stats.employed else 0,
            int(employment_stats.student) if employment_stats.student else 0,
            int(employment_stats.solo_parent) if employment_stats.solo_parent else 0
        ]
    }

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    """Admin dashboard view with comprehensive statistics and visualizations"""
    if not current_user.role == 'admin':
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('auth.login'))
    
    today = datetime.utcnow()
    start_of_today = today.replace(hour=0, minute=0, second=0, microsecond=0)

    # User Statistics
    total_users = User.query.count()
    admins_count = User.query.filter_by(role='admin').count()
    community_count = User.query.filter_by(role='community').count()
    active_today = User.query.filter(User.last_activity >= start_of_today).count()

    # Application Statistics
    total_applications = Applications.query.count()
    pending_applications = Applications.query.filter(
        Applications.application_status == 'pending'
    ).count()
    approved_applications = Applications.query.filter_by(application_status='approved').count()
    rejected_applications = Applications.query.filter_by(application_status='rejected').count()

    # Program Statistics
    total_programs = Programs.query.count()
    active_programs = Programs.query.filter_by(is_active=True).count()

    # Recent Applications (Last 10)
    recent_applications = Applications.query.order_by(
        desc(Applications.application_date)
    ).limit(10).all()

    # Get chart data using helper functions
    monthly_trend = get_monthly_trend_data()
    weekly_trend = get_weekly_trend_data()
    status_distribution = get_status_distribution()
    applications_by_program = get_applications_by_program()
    barangay_data = get_barangay_distribution()
    age_distribution = get_age_distribution()
    employment_data = get_employment_distribution()

    # Top Programs by Application Count
    top_programs = db.session.query(
        Programs.program_name,
        Programs.program_type,
        func.count(Applications.id).label('application_count')
    ).outerjoin(
        Applications, Programs.id == Applications.program_id
    ).group_by(
        Programs.id, Programs.program_name, Programs.program_type
    ).order_by(desc(func.count(Applications.id))).limit(5).all()

    # Recent Announcements
    recent_announcements = Announcements.query.filter_by(
        status='published'
    ).order_by(desc(Announcements.created_at)).limit(5).all()

    # Convert data to JSON for JavaScript
    monthly_trend_json = json.dumps(monthly_trend)
    weekly_trend_json = json.dumps(weekly_trend)
    status_distribution_json = json.dumps(status_distribution)
    applications_by_program_json = json.dumps(applications_by_program)
    barangay_data_json = json.dumps(barangay_data)
    age_distribution_json = json.dumps(age_distribution)
    employment_json = json.dumps(employment_data)

    # Debug output
    print("=== DEBUG: Dashboard Data ===")
    print(f"Monthly Trend: {monthly_trend_json}")
    print(f"Weekly Trend: {weekly_trend_json}")
    print(f"Status Distribution: {status_distribution_json}")
    print("============================")
    
    return render_template('admin/dashboard.html',
                           current_date=today,
                           total_users=total_users,
                           admins_count=admins_count,
                           community_count=community_count,
                           active_today=active_today,
                           total_applications=total_applications,
                           pending_applications=pending_applications,
                           approved_applications=approved_applications,
                           rejected_applications=rejected_applications,
                           total_programs=total_programs,
                           active_programs=active_programs,
                           status_distribution_json=status_distribution_json,
                           applications_by_program_json=applications_by_program_json,
                           monthly_trend_json=monthly_trend_json,
                           weekly_trend_json=weekly_trend_json,
                           barangay_data_json=barangay_data_json,
                           age_distribution_json=age_distribution_json,
                           employment_json=employment_json,
                           top_programs=top_programs,
                           recent_applications=recent_applications,
                           recent_announcements=recent_announcements,
                           user=current_user)