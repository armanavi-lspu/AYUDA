from flask import render_template, jsonify, redirect, url_for, jsonify, request, flash
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, func, extract, case
from app.admin import admin_bp
from app.models import (
User, Programs, Applications, Announcements, CommunityUsers
)
from app.extensions import db
import json

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
        Applications.application_status.in_(['pending', 'submitted', 'under_review'])
    ).count()
    approved_applications = Applications.query.filter_by(application_status='approved').count()
    rejected_applications = Applications.query.filter_by(application_status='rejected').count()

    # Program Statistics
    total_programs = Programs.query.count()
    active_programs = Programs.query.filter_by(is_active=True).count()

    # 1. Recent Applications (Last 10)
    recent_applications = Applications.query.order_by(
        desc(Applications.application_date)
    ).limit(10).all()

    # 2. Application Status Distribution (for Pie Chart)
    status_distribution = db.session.query(
        Applications.application_status,
        func.count(Applications.id).label('count')
    ).group_by(Applications.application_status).all()

    status_distribution_json = json.dumps([
        {'status': status.application_status, 'count': status.count}
        for status in status_distribution
    ])

    # 3. Program Type Distribution (for Doughnut Chart)
    program_type_distribution = db.session.query(
        Programs.program_type,
        func.count(Programs.id).label('count')
    ).group_by(Programs.program_type).all()

    program_type_json = json.dumps([
        {'type': prog.program_type, 'count': prog.count}
        for prog in program_type_distribution
    ])

    # 4. Applications by Program Type (for Bar Chart)
    applications_by_program = db.session.query(
        Programs.program_type,
        func.count(Applications.id).label('application_count')
    ).outerjoin(
        Applications, Programs.id == Applications.program_id
    ).group_by(Programs.program_type).all()

    applications_by_program_json = json.dumps([
        {'program_type': app.program_type, 'count': app.application_count}
        for app in applications_by_program
    ])

    # 5. Monthly Application Trend (Last 12 months)
    twelve_months_ago = today - timedelta(days=365)
    
    monthly_trend = db.session.query(
        extract('year', Applications.application_date).label('year'),
        extract('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= twelve_months_ago
    ).group_by('year', 'month').order_by('year', 'month').all()

    # Format for chart
    monthly_trend_data = []
    for i in range(12):
        month_date = today - timedelta(days=30 * (11 - i))
        month_name = month_date.strftime('%b %Y')
        
        # Find matching data
        count = 0
        for trend in monthly_trend:
            if trend.year == month_date.year and trend.month == month_date.month:
                count = trend.count
                break
        
        monthly_trend_data.append({
            'month': month_name,
            'count': count
        })

    monthly_trend_json = json.dumps(monthly_trend_data)

    # 6. Applications by Barangay (Top 10)
    applications_by_barangay = db.session.query(
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

    barangay_data_json = json.dumps([
        {'barangay': brgy.barangay, 'count': brgy.count}
        for brgy in applications_by_barangay
    ])

    # 7. Age Distribution of Applicants - FIXED
    age_distribution = db.session.query(
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

    age_distribution_json = json.dumps([
        {'age_group': age.age_group, 'count': age.count}
        for age in age_distribution
    ])

    # 8. Employment Status of Applicants - FIXED
    employment_stats = db.session.query(
        func.sum(case((CommunityUsers.is_currently_employed == True, 1), else_=0)).label('employed'),
        func.sum(case((CommunityUsers.is_currently_employed == False, 1), else_=0)).label('unemployed'),
        func.sum(case((CommunityUsers.is_student == True, 1), else_=0)).label('student'),
        func.sum(case((CommunityUsers.is_solo_parent == True, 1), else_=0)).label('solo_parent')
    ).join(
        User, CommunityUsers.user_id == User.id
    ).join(
        Applications, User.id == Applications.user_id
    ).first()

    employment_json = json.dumps({
        'employed': int(employment_stats.employed) if employment_stats.employed else 0,
        'unemployed': int(employment_stats.unemployed) if employment_stats.unemployed else 0,
        'student': int(employment_stats.student) if employment_stats.student else 0,
        'solo_parent': int(employment_stats.solo_parent) if employment_stats.solo_parent else 0
    })

    # 9. Weekly Application Trend (Last 7 days)
    seven_days_ago = today - timedelta(days=7)
    
    weekly_trend = db.session.query(
        func.date(Applications.application_date).label('date'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= seven_days_ago
    ).group_by(
        func.date(Applications.application_date)
    ).order_by('date').all()

    # Fill in missing dates
    weekly_data = []
    trend_dict = {row.date: row.count for row in weekly_trend}
    
    for i in range(7):
        date = (today - timedelta(days=6 - i)).date()
        day_name = date.strftime('%a')
        weekly_data.append({
            'day': day_name,
            'count': trend_dict.get(date, 0)
        })

    weekly_trend_json = json.dumps(weekly_data)

    # Recent Admin Activities
    recent_admin_activities = [
        {
            'title': 'Application Approved',
            'description': 'Financial Assistance application was approved',
            'time': '2 hours ago',
            'icon': 'check-circle',
            'icon_color': 'success'
        },
        {
            'title': 'New Application Received',
            'description': 'Educational Assistance application submitted',
            'time': '4 hours ago',
            'icon': 'file-alt',
            'icon_color': 'info'
        },
        {
            'title': 'Program Created',
            'description': 'New Medical Assistance Program created',
            'time': '1 day ago',
            'icon': 'folder-plus',
            'icon_color': 'primary'
        },
    ]

    # Recent Announcements
    recent_announcements = Announcements.query.filter_by(
        status='published'
    ).order_by(desc(Announcements.created_at)).limit(5).all()

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

    # ADD THESE DEBUG PRINTS BEFORE return
    print("=== DEBUG: Dashboard Data ===")
    print(f"Status Distribution: {status_distribution_json}")
    print(f"Monthly Trend: {monthly_trend_json}")
    print(f"Weekly Trend: {weekly_trend_json}")
    print(f"Program Data: {applications_by_program_json}")
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
                           program_type_json=program_type_json,
                           applications_by_program_json=applications_by_program_json,
                           monthly_trend_json=monthly_trend_json,
                           weekly_trend_json=weekly_trend_json,
                           barangay_data_json=barangay_data_json,
                           age_distribution_json=age_distribution_json,
                           employment_json=employment_json,
                           top_programs=top_programs,
                           recent_applications=recent_applications,
                           recent_announcements=recent_announcements,
                           recent_admin_activities=recent_admin_activities,
                           user=current_user)