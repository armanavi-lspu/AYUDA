"""
Activity Logger Utility for Admin Actions
==========================================
Provides a simple interface to log admin activities across all admin routes.
"""

import json
from datetime import datetime, timezone
from flask import request
from flask_login import current_user
from app.extensions import db
from app.models import AdminActivityLog


def log_activity(action, action_type, entity_type, description, entity_id=None, details=None):
    """
    Log an admin activity.
    
    Args:
        action: Short action identifier (e.g., 'approve_application', 'verify_document')
        action_type: Category ('create', 'update', 'delete', 'approve', 'reject', 'verify', 'generate', 'export')
        entity_type: Type of entity ('application', 'document', 'announcement', 'user', 'admin', 'verification', 'beneficiaries_list', 'recommendation')
        description: Human-readable description of the action
        entity_id: ID of the affected entity (optional)
        details: Dict of extra context (optional, stored as JSON)
    """
    try:
        admin_id = current_user.id if current_user and current_user.is_authenticated else None
        if not admin_id:
            return
        
        ip_address = request.remote_addr if request else None
        
        log_entry = AdminActivityLog(
            admin_id=admin_id,
            action=action,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
            details=json.dumps(details) if details else None,
            ip_address=ip_address,
            created_at=datetime.now(timezone.utc)
        )
        
        db.session.add(log_entry)
        # Don't commit here - let the calling function handle the commit
        # This ensures the log is part of the same transaction
    except Exception as e:
        # Never let logging failure break the main operation
        print(f"[ACTIVITY LOG ERROR] Failed to log activity: {e}")


# ============================================================
# Convenience functions for specific action categories
# ============================================================

def log_application_status_update(application, old_status, new_status, remarks=None):
    """Log application status change"""
    applicant = application.applicant
    applicant_name = f"{applicant.first_name} {applicant.last_name}" if applicant else f"User #{application.user_id}"
    program_name = application.program.program_name if application.program else f"Program #{application.program_id}"
    
    description = f"Updated application #{application.id} status from '{old_status}' to '{new_status}' for {applicant_name} ({program_name})"
    
    details = {
        'old_status': old_status,
        'new_status': new_status,
        'applicant_name': applicant_name,
        'program_name': program_name,
    }
    if remarks:
        details['remarks'] = remarks
    
    log_activity(
        action=f'{new_status}_application',
        action_type='approve' if new_status in ['approved', 'active', 'completed'] else ('reject' if new_status == 'rejected' else 'update'),
        entity_type='application',
        description=description,
        entity_id=application.id,
        details=details
    )


def log_bulk_application_status_update(application_ids, new_status, updated_count):
    """Log bulk application status update"""
    description = f"Bulk updated {updated_count} application(s) to '{new_status}' (IDs: {', '.join(str(i) for i in application_ids[:10])}{'...' if len(application_ids) > 10 else ''})"
    
    log_activity(
        action='bulk_update_status',
        action_type='approve' if new_status in ['approved', 'active', 'completed'] else ('reject' if new_status == 'rejected' else 'update'),
        entity_type='application',
        description=description,
        details={
            'application_ids': application_ids,
            'new_status': new_status,
            'updated_count': updated_count
        }
    )


def log_document_verification(upload, status, feedback=None):
    """Log document approval/rejection"""
    application = upload.application
    applicant = application.applicant
    applicant_name = f"{applicant.first_name} {applicant.last_name}" if applicant else f"User #{application.user_id}"
    req_name = upload.requirement.requirement_name if upload.requirement else f"Requirement #{upload.requirement_id}"
    
    if status == 'approved':
        description = f"Approved document '{req_name}' for {applicant_name} (Application #{application.id})"
    elif status == 'rejected':
        description = f"Rejected document '{req_name}' for {applicant_name} (Application #{application.id})"
    else:
        description = f"Updated document '{req_name}' status to '{status}' for {applicant_name} (Application #{application.id})"
    
    details = {
        'document_name': req_name,
        'verification_status': status,
        'applicant_name': applicant_name,
        'application_id': application.id,
    }
    if feedback:
        details['admin_feedback'] = feedback
    
    log_activity(
        action=f'{status}_document',
        action_type='approve' if status == 'approved' else ('reject' if status == 'rejected' else 'update'),
        entity_type='document',
        description=description,
        entity_id=upload.id,
        details=details
    )


def log_document_status_toggle(doc, new_status):
    """Log MSWD office document verification toggle"""
    application = doc.application
    applicant = application.applicant
    applicant_name = f"{applicant.first_name} {applicant.last_name}" if applicant else f"User #{application.user_id}"
    req_name = doc.requirement.requirement_name if doc.requirement else f"Requirement #{doc.requirement_id}"
    
    action_word = 'Verified' if new_status == 'verified' else 'Unverified'
    description = f"{action_word} document '{req_name}' (MSWD office) for {applicant_name} (Application #{application.id})"
    
    log_activity(
        action='verify_document_status',
        action_type='verify' if new_status == 'verified' else 'update',
        entity_type='document',
        description=description,
        entity_id=doc.id,
        details={
            'document_name': req_name,
            'new_status': new_status,
            'applicant_name': applicant_name,
            'application_id': application.id,
        }
    )


def log_verification_request(user, verification_type, action, rejection_reason=None):
    """Log processing of verification requests (Senior Citizen, PWD, Solo Parent)"""
    user_name = f"{user.first_name} {user.last_name}" if user else 'Unknown User'
    type_label = verification_type.replace('_', ' ').title()
    action_labels = {
        'approve': 'Approved',
        'decline': 'Declined',
        'return': 'Returned',
        # Keep legacy terms mapped for historical compatibility.
        'reject': 'Declined',
        'reupload': 'Returned',
    }
    action_label = action_labels.get(action, action.replace('_', ' ').title())
    
    description = f"{action_label} {type_label} verification for {user_name}"
    
    details = {
        'user_name': user_name,
        'user_id': user.id,
        'verification_type': verification_type,
        'action': action,
    }
    if rejection_reason:
        details['rejection_reason'] = rejection_reason
    
    log_activity(
        action=f'{action}_verification',
        action_type='approve' if action == 'approve' else ('return' if action in {'return', 'reupload'} else 'reject'),
        entity_type='verification',
        description=description,
        entity_id=user.id,
        details=details
    )


def log_beneficiaries_list_generated(count):
    """Log generation of beneficiaries list"""
    description = f"Generated saved beneficiaries list with {count} approved beneficiaries"
    
    log_activity(
        action='generate_beneficiaries_list',
        action_type='generate',
        entity_type='beneficiaries_list',
        description=description,
        details={'beneficiary_count': count}
    )


def log_announcement(announcement, action='create'):
    """Log announcement creation/update/deletion"""
    action_labels = {
        'create': 'Created',
        'update': 'Updated',
        'delete': 'Deleted',
        'publish': 'Published',
    }
    action_label = action_labels.get(action, action.title())
    
    title = announcement.announcement_title if hasattr(announcement, 'announcement_title') else str(announcement)
    
    description = f"{action_label} announcement: \"{title}\""
    
    details = {
        'announcement_title': title,
        'status': announcement.status if hasattr(announcement, 'status') else None,
        'category': announcement.category if hasattr(announcement, 'category') else None,
    }
    
    log_activity(
        action=f'{action}_announcement',
        action_type=action if action in ['create', 'update', 'delete'] else 'update',
        entity_type='announcement',
        description=description,
        entity_id=announcement.id if hasattr(announcement, 'id') else None,
        details=details
    )


def log_user_modification(target_user, action, extra_details=None):
    """Log user modifications (suspend, password reset, delete, etc.)"""
    action_labels = {
        'suspend': 'Suspended',
        'unsuspend': 'Unsuspended',
        'reset_password': 'Reset password for',
        'delete': 'Deleted',
        'update': 'Updated',
    }
    action_label = action_labels.get(action, action.title())
    user_name = f"{target_user.first_name} {target_user.last_name}" if target_user else 'Unknown User'
    
    description = f"{action_label} user: {user_name} ({target_user.email})"
    
    details = {
        'user_name': user_name,
        'user_email': target_user.email,
        'user_role': target_user.role,
    }
    if extra_details:
        details.update(extra_details)
    
    log_activity(
        action=f'{action}_user',
        action_type='delete' if action == 'delete' else 'update',
        entity_type='user',
        description=description,
        entity_id=target_user.id,
        details=details
    )


def log_admin_management(target_admin, action, extra_details=None):
    """Log admin management actions (create, edit, delete, reset password)"""
    action_labels = {
        'create': 'Created',
        'update': 'Updated',
        'delete': 'Deleted',
        'reset_password': 'Reset password for',
    }
    action_label = action_labels.get(action, action.title())
    admin_name = f"{target_admin.first_name} {target_admin.last_name}" if target_admin else 'Unknown Admin'
    admin_email = target_admin.email if target_admin else 'unknown'
    
    description = f"{action_label} admin account: {admin_name} ({admin_email})"
    
    details = {
        'admin_name': admin_name,
        'admin_email': admin_email,
    }
    if extra_details:
        details.update(extra_details)
    
    log_activity(
        action=f'{action}_admin',
        action_type=action if action in ['create', 'update', 'delete'] else 'update',
        entity_type='admin',
        description=description,
        entity_id=target_admin.id if target_admin else None,
        details=details
    )


def log_recommendation_saved(program_name, recommendation_count, details_extra=None):
    """Log saved recommendation list"""
    description = f"Saved recommendation list for '{program_name}' with {recommendation_count} recommended beneficiaries"
    
    details = {
        'program_name': program_name,
        'recommendation_count': recommendation_count,
    }
    if details_extra:
        details.update(details_extra)
    
    log_activity(
        action='save_recommendation',
        action_type='generate',
        entity_type='recommendation',
        description=description,
        details=details
    )
