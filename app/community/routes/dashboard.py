from flask import render_template, jsonify, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.community import community_bp
from app.models import Applications, Announcements, Programs, User, Assessment, AdminUsers
from app.extensions import db
from app.utils import role_required, calculate_profile_completion
from sqlalchemy import desc, func
from datetime import datetime, timedelta, date
import pytz


def _municipality_announcements_query():
    """Announcements authored by admins assigned to the current community user's municipality."""
    municipality = (current_user.community_profile.municipality or '').strip() if current_user.community_profile else ''
    if not municipality:
        return Announcements.query.filter(False)

    return Announcements.query.join(
        User, Announcements.author_id == User.id
    ).join(
        AdminUsers, AdminUsers.user_id == User.id
    ).filter(
        User.role == 'admin',
        func.lower(func.trim(AdminUsers.municipality)) == municipality.lower()
    )

@community_bp.route('/dashboard')
@login_required
@role_required('community')
def dashboard():
    """Community dashboard with real-time data"""
    
    # Get profile completion status
    completion_data = calculate_profile_completion(current_user)
    
    # Get user's application statistics
    total_applications = Applications.query.filter_by(user_id=current_user.id).count()
    pending_applications = Applications.query.filter_by(
        user_id=current_user.id
    ).filter(Applications.application_status == 'pending').count()
    returned_applications = Applications.query.filter_by(
        user_id=current_user.id
    ).filter(Applications.application_status == 'rejected').count()
    
    # Get available programs count scoped to admins in the user's municipality
    municipality = (current_user.community_profile.municipality or '').strip() if current_user.community_profile else ''
    if municipality:
        available_programs = Programs.query.join(
            User, Programs.user_id == User.id
        ).join(
            AdminUsers, AdminUsers.user_id == User.id
        ).filter(
            User.role == 'admin',
            func.lower(func.trim(AdminUsers.municipality)) == municipality.lower()
        ).count()
    else:
        available_programs = 0
    
    # Get new announcements (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    new_announcements = _municipality_announcements_query().filter(
        Announcements.status == 'published',
        Announcements.created_at >= thirty_days_ago
    ).count()
    
    # Get recent applications (last 3)
    recent_applications = Applications.query.filter_by(
        user_id=current_user.id
    ).order_by(desc(Applications.application_date)).limit(3).all()
    
    # Get recent announcements (last 3)
    recent_announcements = _municipality_announcements_query().filter(
        Announcements.status == 'published'
    ).order_by(desc(Announcements.created_at)).limit(3).all()
    
    # Get upcoming schedule events
    schedule_events = []
    user_applications = Applications.query.filter_by(
        user_id=current_user.id
    ).join(Programs).order_by(Applications.application_date.desc()).all()
     
    for app in user_applications:
        # Add submission deadline event (placeholder - currently using application_date + 30 days)
        if app.application_status in ['pending'] and app.application_date:
            deadline_date = app.application_date + timedelta(days=30)
            if deadline_date >= datetime.now():
                schedule_events.append({
                    'type': 'deadline',
                    'title': f'Document Submission Deadline',
                    'program': app.program.program_name,
                    'application_id': app.id,
                    'date': deadline_date,
                    'status': app.application_status,
                    'description': 'Complete and submit all required documents'
                })
        
        # Add claiming date event (placeholder - currently using review_date + 7 days)
        if app.application_status == 'approved' and app.review_date:
            claim_date = app.review_date + timedelta(days=7)
            if claim_date >= datetime.now():
                schedule_events.append({
                    'type': 'claiming',
                    'title': f'Assistance Claim Date',
                    'program': app.program.program_name,
                    'application_id': app.id,
                    'date': claim_date,
                    'status': app.application_status,
                    'description': 'Visit the office to claim your assistance'
                })
        
        # Add scheduled assessments
        scheduled_assessments = Assessment.query.filter_by(
            application_id=app.id,
            status='scheduled'
        ).all()
        
        for assessment in scheduled_assessments:
            if assessment.scheduled_date and assessment.scheduled_date >= datetime.now():
                assessment_type_label = assessment.assessment_type.replace('_', ' ').title()
                schedule_events.append({
                    'type': 'assessment',
                    'title': f'{assessment_type_label} Assessment',
                    'program': app.program.program_name,
                    'application_id': app.id,
                    'assessment_id': assessment.id,
                    'date': assessment.scheduled_date,
                    'time': assessment.scheduled_time,
                    'location': assessment.location,
                    'status': 'scheduled',
                    'description': f'{assessment_type_label} scheduled at {assessment.location or "TBD"}'
                })
    
    # Sort events by date and get next 5
    schedule_events.sort(key=lambda x: x['date'])
    upcoming_events = schedule_events[:5]
    
    # Today's date - use date() for consistent comparison
    tz = current_app.config.get('TZ', pytz.timezone('Asia/Manila'))
    today = datetime.now(tz).date()
    
    return render_template('community/dashboard.html',
                         total_applications=total_applications,
                         pending_applications=pending_applications,
                         returned_applications = returned_applications,
                         available_programs=available_programs,
                         new_announcements=new_announcements,
                         recent_applications=recent_applications,
                         recent_announcements=recent_announcements,
                         upcoming_events=upcoming_events,
                         today=today,
                         completion=completion_data)

@community_bp.route('/dismiss-profile-alert', methods=['POST'])
@login_required
@role_required('community')
def dismiss_profile_alert():
    """Dismiss the profile completion alert permanently"""
    try:
        User.query.filter_by(id=current_user.id).update(
            {'profile_complete_alert_dismissed': True}
        )
        db.session.commit()

        # Support both async calls and regular form submits.
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': 'Alert dismissed successfully'})

        flash("Profile complete alert dismissed.", "success")
        return redirect(url_for('community.dashboard'))
    except Exception as e:
        db.session.rollback()
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': str(e)}), 500

        flash('Unable to dismiss profile alert. Please try again.', 'danger')
        return redirect(url_for('community.dashboard'))