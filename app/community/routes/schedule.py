from flask import render_template
from flask_login import login_required, current_user
from app.community import community_bp
from app.models import Applications, Programs
from app.utils import role_required
from datetime import datetime, timedelta


@community_bp.route('/schedule')
@login_required
@role_required('community')
def schedule():
    """
    Display schedule of important events for the community user
    including submission deadlines and assistance claim dates
    """
    
    # Get user's applications with their associated programs
    user_applications = Applications.query.filter_by(
        user_id=current_user.id
    ).join(Programs).order_by(Applications.application_date.desc()).all()
    
    # Prepare schedule events data
    schedule_events = []
    
    for app in user_applications:
        # Add submission deadline event (placeholder - currently using application_date + 30 days)
        if app.application_status == 'pending' or app.application_status == 'on_hold':
            deadline_date = app.application_date + timedelta(days=30) if app.application_date else None
            if deadline_date:
                schedule_events.append({
                    'type': 'deadline',
                    'title': f'Document Submission Deadline',
                    'program': app.program.program_name,
                    'application_id': app.id,
                    'date': deadline_date,
                    'status': app.application_status,
                    'description': 'Complete and submit all required documents before this date'
                })
        
        # Add claiming date event (placeholder - currently using review_date + 7 days)
        if app.application_status == 'approved' and app.review_date:
            claim_date = app.review_date + timedelta(days=7)
            schedule_events.append({
                'type': 'claiming',
                'title': f'Assistance Claim Date',
                'program': app.program.program_name,
                'application_id': app.id,
                'date': claim_date,
                'status': app.application_status,
                'description': 'Visit the office to claim your assistance on this date'
            })
    
    # Sort events by date
    schedule_events.sort(key=lambda x: x['date'])
    
    # Separate upcoming and past events
    today = datetime.now()
    upcoming_events = [e for e in schedule_events if e['date'] >= today]
    past_events = [e for e in schedule_events if e['date'] < today]
    
    return render_template('community/schedule.html',
                         upcoming_events=upcoming_events,
                         past_events=past_events,
                         current_date=today)
