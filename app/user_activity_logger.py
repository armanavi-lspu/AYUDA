"""
User Activity Logger - Utility functions to log community user activities.
Adds log entries to the session without committing, so they are included 
in the calling function's existing commit.
"""

from flask import request
from flask_login import current_user
from app.extensions import db
from app.models import UserActivityLog
import json


def log_user_activity(action, action_type, entity_type, description, entity_id=None, details=None, user_id=None):
    """
    Core function to log a user activity.
    Adds to session without committing - caller must commit.
    """
    try:
        uid = user_id or (current_user.id if current_user and current_user.is_authenticated else None)
        if not uid:
            return
        
        log_entry = UserActivityLog(
            user_id=uid,
            action=action,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
            details=json.dumps(details) if details else None,
            ip_address=request.remote_addr if request else None
        )
        db.session.add(log_entry)
    except Exception as e:
        print(f"[USER ACTIVITY LOG] Error logging activity: {e}")


def log_program_detail_view(program):
    """Log when a user views a program's detail page."""
    log_user_activity(
        action='view_program_detail',
        action_type='view',
        entity_type='program',
        description=f'Viewed program details: {program.program_name}',
        entity_id=program.id,
        details={'program_type': program.program_type, 'program_name': program.program_name}
    )


def log_save_program(program):
    """Log when a user saves/bookmarks a program."""
    log_user_activity(
        action='save_program',
        action_type='save',
        entity_type='program',
        description=f'Saved program: {program.program_name}',
        entity_id=program.id,
        details={'program_type': program.program_type}
    )


def log_unsave_program(program):
    """Log when a user removes a program from saved list."""
    log_user_activity(
        action='unsave_program',
        action_type='delete',
        entity_type='program',
        description=f'Removed saved program: {program.program_name}',
        entity_id=program.id
    )


def log_hide_program(program):
    """Log when a user hides/marks a program as not interested."""
    log_user_activity(
        action='hide_program',
        action_type='hide',
        entity_type='program',
        description=f'Marked as not interested: {program.program_name}',
        entity_id=program.id,
        details={'program_type': program.program_type}
    )


def log_unhide_program(program):
    """Log when a user unhides a program."""
    log_user_activity(
        action='unhide_program',
        action_type='update',
        entity_type='program',
        description=f'Unhid program: {program.program_name}',
        entity_id=program.id
    )


def log_application_started(application, program):
    """Log when a user starts/submits an application."""
    log_user_activity(
        action='apply_started',
        action_type='create',
        entity_type='application',
        description=f'Started application for: {program.program_name}',
        entity_id=application.id,
        details={'program_id': program.id, 'program_name': program.program_name}
    )


def log_document_upload(application, doc_count, program_name):
    """Log when a user uploads documents for an application."""
    log_user_activity(
        action='document_upload',
        action_type='upload',
        entity_type='document',
        description=f'Uploaded {doc_count} document(s) for application: {program_name}',
        entity_id=application.id,
        details={'document_count': doc_count, 'program_name': program_name}
    )


def log_search_query(query_text, filters=None, result_count=None):
    """Log when a user searches or filters programs."""
    details = {}
    if query_text:
        details['query'] = query_text
    if filters:
        details['filters'] = filters
    if result_count is not None:
        details['result_count'] = result_count
    
    desc_parts = []
    if query_text:
        desc_parts.append(f'Search: "{query_text}"')
    if filters:
        filter_strs = [f'{k}={v}' for k, v in filters.items() if v]
        if filter_strs:
            desc_parts.append(f'Filters: {", ".join(filter_strs)}')
    
    description = ' | '.join(desc_parts) if desc_parts else 'Browsed programs'
    
    log_user_activity(
        action='search_programs',
        action_type='search',
        entity_type='search',
        description=description,
        details=details
    )


def log_profile_edit(changed_fields=None):
    """Log when a user edits their profile."""
    details = {}
    if changed_fields:
        details['changed_fields'] = changed_fields
    
    field_count = len(changed_fields) if changed_fields else 0
    log_user_activity(
        action='edit_profile',
        action_type='update',
        entity_type='profile',
        description=f'Updated profile ({field_count} field(s) changed)' if field_count else 'Updated profile',
        details=details if details else None
    )


def log_login(user_id):
    """Log when a user logs in."""
    log_user_activity(
        action='login',
        action_type='auth',
        entity_type='session',
        description='Logged in',
        user_id=user_id
    )


def log_logout():
    """Log when a user logs out."""
    log_user_activity(
        action='logout',
        action_type='auth',
        entity_type='session',
        description='Logged out'
    )
