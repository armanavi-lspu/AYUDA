from flask import render_template, redirect, flash, url_for, request
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, func
from app.community import community_bp
from app.models import (
    Programs, User, Applications, Announcements, Notifications
)
from app.extensions import db
from app.utils import role_required

@community_bp.route('/dashboard')
@login_required
@role_required(['community'])
def dashboard():
    # Get the current date for welcome message
    today = datetime.utcnow()
    
    # Get user's application statistics
    pending_applications = Applications.query.filter_by(
        user_id=current_user.id, 
        application_status='pending'
    ).count()
    
    total_applications = Applications.query.filter_by(
        user_id=current_user.id
    ).count()
    
    # Get available programs/services count
    available_programs = Programs.query.count()
    
    # Get unread notifications count (or new announcements if no notifications table)
    # Option 1: If using notifications
    unread_notifications = Notifications.query.filter_by(
        user_id=current_user.id,
        is_read=False
    ).count()
    
    # Option 2: If counting new announcements (last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    new_announcements = Announcements.query.filter(
        Announcements.created_at >= week_ago,
        Announcements.status == 'published'
    ).count()
    
    # Get recent announcements for the announcements section
    recent_announcements = Announcements.query.filter_by(
        status='published'
    ).order_by(desc(Announcements.created_at)).limit(3).all()
    
    # Get user's recent applications for activity tracking
    user_applications = Applications.query.filter_by(
        user_id=current_user.id
    ).order_by(desc(Applications.created_at)).limit(5).all()
    
    return render_template('community/dashboard.html', 
                           user=current_user,
                           today=today,
                           pending_applications=pending_applications,
                           total_applications=total_applications,
                           available_programs=available_programs,
                           unread_notifications=unread_notifications,
                           new_announcements=new_announcements,
                           recent_announcements=recent_announcements,
                           user_applications=user_applications)