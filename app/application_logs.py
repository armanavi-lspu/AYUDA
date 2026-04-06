from sqlalchemy import and_, or_

from app.models import AdminActivityLog, ApplicationWorkflowStatus, ProgramWorkflowSteps, UserActivityLog


def _name_or_fallback(user_obj, fallback):
    if not user_obj:
        return fallback
    first_name = (getattr(user_obj, 'first_name', '') or '').strip()
    last_name = (getattr(user_obj, 'last_name', '') or '').strip()
    full_name = f"{first_name} {last_name}".strip()
    return full_name or fallback


def _extract_notes_from_details(details_dict):
    if not details_dict:
        return None

    note_keys = [
        'admin_feedback',
        'remarks',
        'rejection_reason',
        'feedback',
        'note',
        'notes',
    ]
    for key in note_keys:
        value = details_dict.get(key)
        if value:
            return str(value)

    return None


def _workflow_review_activity(step_status, step_label):
    if step_status == 'approved':
        return f"Approved {step_label}"
    if step_status == 'rejected':
        return f"Rejected {step_label}"
    if step_status == 'completed':
        return f"Completed {step_label}"
    return f"Reviewed {step_label}"


def build_application_activity_entries(application, include_admin_activity=True, include_user_activity=True):
    """Build a unified chronological log feed for one application."""
    if not application:
        return []

    entries = []
    applicant_name = _name_or_fallback(getattr(application, 'applicant', None), f"User #{application.user_id}")

    def add_entry(timestamp, actor, source, activity, notes=None):
        if not timestamp or not activity:
            return
        entries.append({
            'timestamp': timestamp,
            'actor': actor or 'System',
            'source': source,
            'activity': activity,
            'notes': notes,
        })

    # Baseline lifecycle events from application record.
    add_entry(
        application.application_date,
        applicant_name,
        'application',
        f"Submitted application for {application.program.program_name if application.program else 'selected program'}",
        None,
    )

    if application.review_date and application.reviewed_by:
        reviewer = getattr(application, 'reviewer', None)
        reviewer_name = _name_or_fallback(reviewer, f"Admin #{application.reviewed_by}")
        add_entry(
            application.review_date,
            reviewer_name,
            'application',
            f"Application status set to {application.application_status.replace('_', ' ').title()}",
            application.remarks,
        )

    if application.claim_scheduled_at:
        scheduler = getattr(application, 'claim_scheduler', None)
        scheduler_name = _name_or_fallback(scheduler, 'Admin')
        claim_notes = None
        if application.claim_date:
            claim_notes = f"Scheduled date: {application.claim_date}"
        add_entry(
            application.claim_scheduled_at,
            scheduler_name,
            'application',
            'Scheduled claim release',
            claim_notes,
        )

    # Workflow-level events with exact reviewer identity.
    workflow_rows = (
        ApplicationWorkflowStatus.query
        .filter_by(application_id=application.id)
        .join(ProgramWorkflowSteps)
        .order_by(ProgramWorkflowSteps.step_order.asc())
        .all()
    )

    for status in workflow_rows:
        step = status.workflow_step
        step_label = f"Step {step.step_order}: {step.step_name}" if step else 'workflow step'

        if status.started_at:
            add_entry(
                status.started_at,
                applicant_name,
                'workflow',
                f"Started {step_label}",
                None,
            )

        if status.completed_at and status.step_status in {'pending_review', 'completed', 'approved'}:
            add_entry(
                status.completed_at,
                applicant_name,
                'workflow',
                f"Submitted {step_label} for review",
                None,
            )

        if status.reviewed_at:
            reviewer_name = _name_or_fallback(status.reviewer, f"Admin #{status.reviewed_by}" if status.reviewed_by else 'Admin')
            add_entry(
                status.reviewed_at,
                reviewer_name,
                'workflow',
                _workflow_review_activity(status.step_status, step_label),
                status.admin_feedback,
            )

    # Admin audit logs tied to this application.
    if include_admin_activity:
        application_id_patterns = [
            f'"application_id": {application.id}',
            f'"application_id":{application.id}',
            f'"application_id":"{application.id}"',
        ]

        details_application_match = or_(*[AdminActivityLog.details.contains(pattern) for pattern in application_id_patterns])

        admin_logs = (
            AdminActivityLog.query
            .filter(
                or_(
                    and_(
                        AdminActivityLog.entity_type == 'application',
                        AdminActivityLog.entity_id == application.id,
                    ),
                    and_(
                        AdminActivityLog.entity_type == 'application',
                        AdminActivityLog.details.isnot(None),
                        details_application_match,
                    ),
                    and_(
                        AdminActivityLog.entity_type == 'document',
                        AdminActivityLog.details.isnot(None),
                        details_application_match,
                    ),
                )
            )
            .order_by(AdminActivityLog.created_at.desc())
            .limit(250)
            .all()
        )

        for log in admin_logs:
            add_entry(
                log.created_at,
                log.admin_name,
                'admin_activity',
                log.description,
                _extract_notes_from_details(log.details_dict),
            )

    # Community activity logs tied to this application.
    if include_user_activity:
        user_logs = (
            UserActivityLog.query
            .filter(
                UserActivityLog.user_id == application.user_id,
                or_(
                    and_(
                        UserActivityLog.entity_type == 'application',
                        UserActivityLog.entity_id == application.id,
                    ),
                    and_(
                        UserActivityLog.entity_type == 'document',
                        UserActivityLog.entity_id == application.id,
                    ),
                ),
            )
            .order_by(UserActivityLog.created_at.desc())
            .limit(250)
            .all()
        )

        for log in user_logs:
            add_entry(
                log.created_at,
                applicant_name,
                'community_activity',
                log.description,
                _extract_notes_from_details(log.details_dict),
            )

    # Stable reverse-chronological feed with basic deduplication.
    sorted_entries = sorted(entries, key=lambda row: row['timestamp'], reverse=True)
    seen = set()
    deduped_entries = []

    for row in sorted_entries:
        dedupe_key = (
            row['timestamp'],
            row['actor'],
            row['source'],
            row['activity'],
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped_entries.append(row)

    return deduped_entries
