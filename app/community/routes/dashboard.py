from flask import render_template, jsonify
from flask_login import login_required, current_user
from app.community import community_bp
from app.models import Applications, Announcements, Programs
from app.extensions import db
from app.utils import role_required, calculate_profile_completion
from sqlalchemy import desc, func
from datetime import datetime, timedelta, date

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
    
    # Get upcoming schedule events
    schedule_events = []
    user_applications = Applications.query.filter_by(
        user_id=current_user.id
    ).join(Programs).order_by(Applications.application_date.desc()).all()
     
    for app in user_applications:
        # Add submission deadline event (placeholder - currently using application_date + 30 days)
        if app.application_status in ['pending', 'on_hold'] and app.application_date:
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
    
    # Sort events by date and get next 5
    schedule_events.sort(key=lambda x: x['date'])
    upcoming_events = schedule_events[:5]
    
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
                         upcoming_events=upcoming_events,
                         today=today,
                         completion=completion_data)

@community_bp.route('/dismiss-profile-alert', methods=['POST'])
@login_required
@role_required('community')
def dismiss_profile_alert():
    """Dismiss the profile completion alert permanently"""
    try:
        current_user.profile_complete_alert_dismissed = True
        db.session.commit()
        return jsonify({'success': True, 'message': 'Alert dismissed successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500