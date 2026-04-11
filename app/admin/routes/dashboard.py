from flask import render_template, jsonify, redirect, url_for, jsonify, request, flash, current_app
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, func, extract, case, cast, Date, and_, or_
from app.admin import admin_bp
from app.models import (
    User, Programs, Applications, Announcements, CommunityUsers, AdminUsers
)
from app.extensions import db
import json
import pytz


def _scoped_programs_query(municipality):
    """Programs owned by admins in the given municipality."""
    municipality_value = (municipality or '').strip()
    if not municipality_value:
        return Programs.query.filter(False)

    return Programs.query.join(
        User, Programs.user_id == User.id
    ).join(
        AdminUsers, AdminUsers.user_id == User.id
    ).filter(
        User.role == 'admin',
        func.lower(func.trim(AdminUsers.municipality)) == municipality_value.lower()
    )


def _scoped_applications_query(municipality):
    """Applications tied to municipality-owned programs."""
    municipality_value = (municipality or '').strip()
    if not municipality_value:
        return Applications.query.filter(False)

    return Applications.query.join(
        Programs, Applications.program_id == Programs.id
    ).join(
        User, Programs.user_id == User.id
    ).join(
        AdminUsers, AdminUsers.user_id == User.id
    ).filter(
        User.role == 'admin',
        func.lower(func.trim(AdminUsers.municipality)) == municipality_value.lower()
    )


def _scoped_announcements_query(municipality):
    """Announcements authored by admins in the given municipality."""
    municipality_value = (municipality or '').strip()
    if not municipality_value:
        return Announcements.query.filter(False)

    return Announcements.query.join(
        User, Announcements.author_id == User.id
    ).join(
        AdminUsers, AdminUsers.user_id == User.id
    ).filter(
        User.role == 'admin',
        func.lower(func.trim(AdminUsers.municipality)) == municipality_value.lower()
    )

def get_monthly_trend_data(municipality=None):
    """Get monthly application trend data for the last 12 months"""
    now = datetime.utcnow()
    twelve_months_ago = now - timedelta(days=365)

    # Query database for monthly counts - PostgreSQL syntax
    monthly_query = db.session.query(
        extract('year', Applications.application_date).label('year'),
        extract('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= twelve_months_ago
    )

    if municipality:
        monthly_query = monthly_query.join(
            User, Applications.user_id == User.id
        ).join(
            CommunityUsers, CommunityUsers.user_id == User.id
        ).filter(
            CommunityUsers.municipality == municipality
        )

    monthly_data = monthly_query.group_by(
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

def get_weekly_trend_data(municipality=None):
    """Get weekly application trend data for the last 7 days"""
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)

    # Query database for daily counts - PostgreSQL syntax
    # Use cast to DATE instead of func.date()
    daily_query = db.session.query(
        cast(Applications.application_date, Date).label('date'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= seven_days_ago
    )

    if municipality:
        daily_query = daily_query.join(
            User, Applications.user_id == User.id
        ).join(
            CommunityUsers, CommunityUsers.user_id == User.id
        ).filter(
            CommunityUsers.municipality == municipality
        )

    daily_data = daily_query.group_by(
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

def get_status_distribution(municipality=None):
    """Get application status distribution"""
    status_query = db.session.query(
        Applications.application_status,
        func.count(Applications.id).label('count')
    )

    if municipality:
        status_query = status_query.join(
            User, Applications.user_id == User.id
        ).join(
            CommunityUsers, CommunityUsers.user_id == User.id
        ).filter(
            CommunityUsers.municipality == municipality
        )

    status_data = status_query.group_by(Applications.application_status).all()
    
    return {
        'labels': [row.application_status.replace('_', ' ').title() for row in status_data],
        'data': [row.count for row in status_data]
    }

def get_applications_by_program(municipality=None):
    """Get applications count by program type"""
    if municipality:
        program_data = db.session.query(
            Programs.program_type,
            func.count(Applications.id).label('count')
        ).join(
            Applications, Programs.id == Applications.program_id
        ).join(
            User, Applications.user_id == User.id
        ).join(
            CommunityUsers, CommunityUsers.user_id == User.id
        ).filter(
            CommunityUsers.municipality == municipality
        ).group_by(Programs.program_type).all()
    else:
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

def get_barangay_distribution(municipality=None):
    """Get top 10 barangays by application count"""
    barangay_query = db.session.query(
        CommunityUsers.barangay,
        func.count(Applications.id).label('count')
    ).join(
        User, CommunityUsers.user_id == User.id
    ).join(
        Applications, User.id == Applications.user_id
    ).filter(
        CommunityUsers.barangay.isnot(None)
    )

    if municipality:
        barangay_query = barangay_query.filter(CommunityUsers.municipality == municipality)

    barangay_data = barangay_query.group_by(
        CommunityUsers.barangay
    ).order_by(desc('count')).limit(10).all()
    
    return {
        'labels': [row.barangay for row in barangay_data],
        'data': [row.count for row in barangay_data]
    }

def get_age_distribution(municipality=None):
    """Get age distribution of applicants"""
    # PostgreSQL syntax for CASE statement
    age_query = db.session.query(
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
    )

    if municipality:
        age_query = age_query.filter(CommunityUsers.municipality == municipality)

    age_data = age_query.group_by('age_group').all()
    
    # Define the order for age groups
    age_order = ['Under 18', '18-25', '26-35', '36-45', '46-60', '60+']
    data_dict = {row.age_group: row.count for row in age_data}
    
    return {
        'labels': age_order,
        'data': [data_dict.get(age_group, 0) for age_group in age_order]
    }

def get_employment_distribution(municipality=None):
    """Get employment status distribution of applicants"""
    # PostgreSQL uses True/False for boolean values
    employment_query = db.session.query(
        func.sum(case((CommunityUsers.is_currently_employed == True, 1), else_=0)).label('employed'),
        func.sum(case((CommunityUsers.is_student == True, 1), else_=0)).label('student'),
        func.sum(case((CommunityUsers.is_solo_parent == True, 1), else_=0)).label('solo_parent')
    ).join(
        User, CommunityUsers.user_id == User.id
    ).join(
        Applications, User.id == Applications.user_id
    )

    if municipality:
        employment_query = employment_query.filter(CommunityUsers.municipality == municipality)

    employment_stats = employment_query.first()
    
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
    if current_user.role != 'admin':
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('auth.login'))
    
    tz = current_app.config.get('TZ', pytz.timezone('Asia/Manila'))
    local_now = datetime.now(tz)
    today = datetime.utcnow()
    start_of_today = today.replace(hour=0, minute=0, second=0, microsecond=0)

    admin_municipality = None
    if current_user.role == 'admin':
        admin_profile = getattr(current_user, 'admin_profile', None)
        admin_municipality = (admin_profile.municipality or '').strip() if admin_profile else ''
        if not admin_municipality:
            flash('Your admin account has no municipality assigned. Please update your profile.', 'danger')
            return redirect(url_for('admin.admin_profile'))

    # User Statistics
    if admin_municipality:
        admins_count = User.query.join(
            AdminUsers, AdminUsers.user_id == User.id
        ).filter(
            User.role == 'admin',
            AdminUsers.municipality == admin_municipality,
        ).count()

        community_count = User.query.filter(
            User.role == 'community',
            User.community_profile.has(municipality=admin_municipality),
        ).count()

        total_users = admins_count + community_count

        active_today = User.query.outerjoin(
            AdminUsers, AdminUsers.user_id == User.id
        ).outerjoin(
            CommunityUsers, CommunityUsers.user_id == User.id
        ).filter(
            User.last_activity >= start_of_today
        ).filter(
            or_(
                and_(User.role == 'admin', AdminUsers.municipality == admin_municipality),
                and_(User.role == 'community', CommunityUsers.municipality == admin_municipality),
            )
        ).count()
    else:
        total_users = User.query.count()
        admins_count = User.query.filter_by(role='admin').count()
        community_count = User.query.filter_by(role='community').count()
        active_today = User.query.filter(User.last_activity >= start_of_today).count()

    # Application Statistics
    if admin_municipality:
        scoped_applications = _scoped_applications_query(admin_municipality)

        total_applications = scoped_applications.count()
        pending_applications = scoped_applications.filter(
            Applications.application_status == 'pending'
        ).count()
        approved_applications = scoped_applications.filter(
            Applications.application_status == 'approved'
        ).count()
        rejected_applications = scoped_applications.filter(
            Applications.application_status == 'rejected'
        ).count()
    else:
        total_applications = Applications.query.count()
        pending_applications = Applications.query.filter(
            Applications.application_status == 'pending'
        ).count()
        approved_applications = Applications.query.filter_by(application_status='approved').count()
        rejected_applications = Applications.query.filter_by(application_status='rejected').count()

    # Program Statistics
    scoped_programs = _scoped_programs_query(admin_municipality)
    total_programs = scoped_programs.count()
    active_programs = scoped_programs.filter(Programs.is_active.is_(True)).count()

    # Recent Applications (Last 10)
    if admin_municipality:
        recent_applications = _scoped_applications_query(admin_municipality).order_by(
            desc(Applications.application_date)
        ).limit(10).all()
    else:
        recent_applications = Applications.query.order_by(
            desc(Applications.application_date)
        ).limit(10).all()

    # Get chart data using helper functions
    monthly_trend = get_monthly_trend_data(admin_municipality)
    weekly_trend = get_weekly_trend_data(admin_municipality)
    status_distribution = get_status_distribution(admin_municipality)
    applications_by_program = get_applications_by_program(admin_municipality)
    barangay_data = get_barangay_distribution(admin_municipality)
    age_distribution = get_age_distribution(admin_municipality)
    employment_data = get_employment_distribution(admin_municipality)

    # Top Programs by Application Count
    if admin_municipality:
        top_programs = db.session.query(
            Programs.program_name,
            Programs.program_type,
            func.count(Applications.id).label('application_count')
        ).join(
            Applications, Programs.id == Applications.program_id
        ).join(
            User, Programs.user_id == User.id
        ).join(
            AdminUsers, AdminUsers.user_id == User.id
        ).filter(
            User.role == 'admin',
            func.lower(func.trim(AdminUsers.municipality)) == admin_municipality.lower()
        ).group_by(
            Programs.id, Programs.program_name, Programs.program_type
        ).order_by(desc(func.count(Applications.id))).limit(5).all()
    else:
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
    recent_announcements = _scoped_announcements_query(admin_municipality).filter(
        Announcements.status == 'published'
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
                           current_date=local_now,
                           dashboard_scope_label=f'Municipality scope: {admin_municipality}' if admin_municipality else 'Global scope: all municipalities',
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