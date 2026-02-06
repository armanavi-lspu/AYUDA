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
        
        # Add actual claiming date event if scheduled (for approved or completed applications)
        if app.application_status in ['approved', 'completed'] and app.claim_date:
            # Create a full datetime from claim_date and claim_time
            claim_datetime = app.claim_date
            if app.claim_time:
                # Parse time and combine with date
                try:
                    time_parts = app.claim_time.split()
                    time_str = time_parts[0]  # Get "09:00" from "09:00 AM"
                    hour, minute = map(int, time_str.split(':'))
                    
                    # Handle AM/PM if present
                    if len(time_parts) > 1 and time_parts[1].upper() == 'PM' and hour != 12:
                        hour += 12
                    elif len(time_parts) > 1 and time_parts[1].upper() == 'AM' and hour == 12:
                        hour = 0
                    
                    claim_datetime = claim_datetime.replace(hour=hour, minute=minute)
                except (ValueError, IndexError):
                    pass  # Use claim_date as is if time parsing fails
            
            # For completed applications, show as scheduled release
            if app.application_status == 'completed':
                status_text = 'completed'
                location_info = f" at {app.claim_location}" if app.claim_location else ""
                instruction_info = f"\n\nInstructions: {app.claim_instructions}" if app.claim_instructions else ""
                description = f'Your application is complete! Visit the office{location_info} to claim your assistance{instruction_info}'
                title = 'Scheduled Release Date ✓'
            else:
                status_text = 'scheduled'
                location_info = f" at {app.claim_location}" if app.claim_location else ""
                instruction_info = f"\n\nInstructions: {app.claim_instructions}" if app.claim_instructions else ""
                description = f'Visit the office{location_info} to claim your assistance{instruction_info}'
                title = 'Assistance Release Date'
            
            schedule_events.append({
                'type': 'claiming',
                'title': title,
                'program': app.program.program_name,
                'application_id': app.id,
                'date': claim_datetime,
                'status': status_text,
                'claim_status': app.claim_status,
                'claim_time': app.claim_time,
                'claim_location': app.claim_location,
                'claim_instructions': app.claim_instructions,
                'description': description
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
