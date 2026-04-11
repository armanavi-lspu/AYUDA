"""SQLAlchemy realtime hooks for websocket broadcasts."""

from sqlalchemy import event, select

from app.models import (
    ApplicationDocuments,
    ApplicationDocumentUploads,
    ApplicationWorkflowStatus,
    Applications,
    Announcements,
    Assessment,
    CALDocuments,
    Notifications,
    Programs,
    ShelterPhotos,
)
from app.socketio_events import (
    emit_application_workflow_update,
    emit_admin_analytics_update,
    emit_admin_dashboard_update,
    emit_community_dashboard_update,
    emit_notification_created,
    emit_notification_updated,
)


def _emit_admin_data_change(reason):
    payload = {'changed': True, 'reason': reason}
    emit_admin_dashboard_update(payload)
    emit_admin_analytics_update(payload)


def _resolve_workflow_context(target, connection=None):
    """Resolve application/user identifiers for workflow-scoped realtime events."""
    if isinstance(target, Applications):
        return target.id, target.user_id

    application_id = getattr(target, 'application_id', None)
    user_id = None

    application = getattr(target, 'application', None)
    if application is not None:
        user_id = getattr(application, 'user_id', None)

    if application_id is None and isinstance(target, Assessment):
        application_id = target.application_id

    # During mapper events the relationship can be unavailable; fall back to DB lookup.
    if application_id and user_id is None and connection is not None:
        user_id = connection.execute(
            select(Applications.user_id).where(Applications.id == application_id)
        ).scalar_one_or_none()

    return application_id, user_id


def _emit_workflow_change(target, reason, connection=None):
    application_id, user_id = _resolve_workflow_context(target, connection=connection)
    if not application_id:
        return

    payload = {
        'changed': True,
        'reason': reason,
        'application_id': application_id,
    }
    if user_id:
        payload['user_id'] = user_id

    emit_application_workflow_update(payload)


@event.listens_for(Notifications, 'after_insert')
def on_notification_insert(mapper, connection, target):
    """Push newly-created notifications in realtime to the owning user room."""
    emit_notification_created(target)


@event.listens_for(Notifications, 'after_update')
def on_notification_update(mapper, connection, target):
    """Push notification state updates (read/unread) in realtime."""
    emit_notification_updated(target)


@event.listens_for(Applications, 'after_insert')
@event.listens_for(Applications, 'after_update')
@event.listens_for(Applications, 'after_delete')
def on_applications_changed(mapper, connection, target):
    """Broadcast when application data changes."""
    _emit_admin_data_change('applications')
    emit_community_dashboard_update({'changed': True, 'reason': 'applications'})
    _emit_workflow_change(target, 'applications', connection=connection)


@event.listens_for(Programs, 'after_insert')
@event.listens_for(Programs, 'after_update')
@event.listens_for(Programs, 'after_delete')
def on_programs_changed(mapper, connection, target):
    """Broadcast when programs change."""
    _emit_admin_data_change('programs')
    emit_community_dashboard_update({'changed': True, 'reason': 'programs'})


@event.listens_for(Announcements, 'after_insert')
@event.listens_for(Announcements, 'after_update')
@event.listens_for(Announcements, 'after_delete')
def on_announcements_changed(mapper, connection, target):
    """Broadcast when announcements change."""
    _emit_admin_data_change('announcements')
    emit_community_dashboard_update({'changed': True, 'reason': 'announcements'})


@event.listens_for(Assessment, 'after_insert')
@event.listens_for(Assessment, 'after_update')
@event.listens_for(Assessment, 'after_delete')
def on_assessments_changed(mapper, connection, target):
    """Broadcast community schedule/dashboard updates when assessments change."""
    emit_community_dashboard_update({'changed': True, 'reason': 'assessments'})
    _emit_workflow_change(target, 'assessments', connection=connection)


@event.listens_for(ApplicationWorkflowStatus, 'after_insert')
@event.listens_for(ApplicationWorkflowStatus, 'after_update')
@event.listens_for(ApplicationWorkflowStatus, 'after_delete')
def on_workflow_status_changed(mapper, connection, target):
    """Broadcast workflow step progression updates in realtime."""
    _emit_workflow_change(target, 'workflow_status', connection=connection)


@event.listens_for(ApplicationDocuments, 'after_insert')
@event.listens_for(ApplicationDocuments, 'after_update')
@event.listens_for(ApplicationDocuments, 'after_delete')
def on_application_documents_changed(mapper, connection, target):
    """Broadcast workflow updates when document checklist statuses change."""
    _emit_workflow_change(target, 'application_documents', connection=connection)


@event.listens_for(ApplicationDocumentUploads, 'after_insert')
@event.listens_for(ApplicationDocumentUploads, 'after_update')
@event.listens_for(ApplicationDocumentUploads, 'after_delete')
def on_document_uploads_changed(mapper, connection, target):
    """Broadcast workflow updates when uploaded files are reviewed/changed."""
    _emit_workflow_change(target, 'document_uploads', connection=connection)


@event.listens_for(ShelterPhotos, 'after_insert')
@event.listens_for(ShelterPhotos, 'after_update')
@event.listens_for(ShelterPhotos, 'after_delete')
def on_shelter_photos_changed(mapper, connection, target):
    """Broadcast workflow updates for shelter photo workflow steps."""
    _emit_workflow_change(target, 'shelter_photos', connection=connection)


@event.listens_for(CALDocuments, 'after_insert')
@event.listens_for(CALDocuments, 'after_update')
@event.listens_for(CALDocuments, 'after_delete')
def on_cal_documents_changed(mapper, connection, target):
    """Broadcast workflow updates for CAL document workflow steps."""
    _emit_workflow_change(target, 'cal_documents', connection=connection)
