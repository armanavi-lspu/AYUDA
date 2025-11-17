from flask import render_template
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, func
from app.admin import admin_bp
from app.utils import role_required
from app.models import User, Programs, Applications, Announcements, ApplicationDocuments
from app.extensions import db

@admin_bp.route('/dashboard')
@login_required
@role_required(['admin'])
def dashboard():
    """Admin dashboard view — renders admin/dashboard.html (existing template)"""
    today = datetime.utcnow()
    start_of_today = today.replace(hour=0, minute=0, second=0, microsecond=0)

    total_users = User.query.count()
    admins_count = User.query.filter_by(role='admin').count()
    community_count = User.query.filter_by(role='community').count()
    active_today = User.query.filter(User.last_activity >= start_of_today).count()

    total_applications = Applications.query.count()
    pending_applications = Applications.query.filter(Applications.application_status.in_(['pending', 'submitted', 'under_review'])).count()
    approved_applications = Applications.query.filter_by(application_status='approved').count()
    rejected_applications = Applications.query.filter_by(application_status='rejected').count()

    total_programs = Programs.query.count()

    recent_applications = Applications.query.order_by(desc(Applications.application_date)).limit(10).all()
    recent_announcements = Announcements.query.filter_by(status='published').order_by(desc(Announcements.created_at)).limit(5).all()

    program_categories = db.session.query(
        Programs.program_type,
        func.count(Applications.id).label('application_count')
    ).outerjoin(Applications, Programs.id == Applications.program_id).group_by(Programs.program_type).all()

    top_programs = db.session.query(
        Programs.program_name,
        Programs.program_type,
        func.count(Applications.id).label('application_count')
    ).outerjoin(Applications, Programs.id == Applications.program_id)\
     .group_by(Programs.id, Programs.program_name, Programs.program_type)\
     .order_by(desc(func.count(Applications.id))).limit(5).all()

    return render_template('admin/dashboard.html',
                           total_users=total_users,
                           admins_count=admins_count,
                           community_count=community_count,
                           active_today=active_today,
                           total_applications=total_applications,
                           pending_applications=pending_applications,
                           approved_applications=approved_applications,
                           rejected_applications=rejected_applications,
                           total_programs=total_programs,
                           program_categories=program_categories,
                           top_programs=top_programs,
                           recent_applications=recent_applications,
                           recent_announcements=recent_announcements,
                           user=current_user)