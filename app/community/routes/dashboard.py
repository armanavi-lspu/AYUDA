from flask import render_template
from flask_login import login_required, current_user
from app.community import community_bp
from app.models import Applications, Announcements, Programs
from app.extensions import db
from app.utils import role_required
from sqlalchemy import desc, func
from datetime import datetime, timedelta, date

@community_bp.route('/dashboard')
@login_required
@role_required('community')
def dashboard():
    """Community dashboard with real-time data"""
    
    # Get user's application statistics
    total_applications = Applications.query.filter_by(user_id=current_user.id).count()
    pending_applications = Applications.query.filter_by(
        user_id=current_user.id
    ).filter(Applications.application_status.in_(['pending', 'submitted', 'under_review'])).count()
    returned_applications = Applications.query.filter_by(
        user_id=current_user.id
    ).filter(Applications.application_status.in_(['returned', 'missing', 'incomplete'])).count()
    
    # Get available programs count
    available_programs = Programs.query.count()
    
    # Get new announcements (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    new_announcements = Announcements.query.filter(
        Announcements.status == 'published',
        Announcements.created_at >= thirty_days_ago
    ).count()
    
    # Get recent applications (last 3)
    recent_applications = Applications.query.filter_by(
        user_id=current_user.id
    ).order_by(desc(Applications.application_date)).limit(3).all()
    
    # Get recent announcements (last 3)
    recent_announcements = Announcements.query.filter_by(
        status='published'
    ).order_by(desc(Announcements.created_at)).limit(3).all()
    
    # Today's date - use date() for consistent comparison
    today = date.today()
    
    return render_template('community/dashboard.html',
                         total_applications=total_applications,
                         pending_applications=pending_applications,
                         returned_applications = returned_applications,
                         available_programs=available_programs,
                         new_announcements=new_announcements,
                         recent_applications=recent_applications,
                         recent_announcements=recent_announcements,
                         today=today)