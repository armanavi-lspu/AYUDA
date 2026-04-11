from flask import render_template, request, flash, redirect, url_for, jsonify, send_from_directory, send_file
from flask_login import login_required, current_user
from datetime import datetime
import json
import uuid
from sqlalchemy import desc, or_, func
from sqlalchemy.orm import aliased
from app.admin import admin_bp
from app.models import (
    Assessment, AssessmentDocument, Applications, Programs,
    User, Notifications, ApplicationWorkflowStatus, ProgramWorkflowSteps, UserActivityLog, AdminUsers
)
from app.extensions import db
from app.utils import role_required
from app.activity_logger import log_activity
import os
from werkzeug.utils import secure_filename
from mimetypes import guess_type

# Configuration
ASSESSMENT_UPLOAD_FOLDER = 'static/uploads/assessments'
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _current_admin_municipality():
    """Return the authenticated admin's municipality scope."""
    profile = getattr(current_user, 'admin_profile', None)
    municipality = (profile.municipality or '').strip() if profile else ''
    return municipality or None


def _scoped_applications_query():
    """Applications for programs owned by admins in the current municipality."""
    municipality = _current_admin_municipality()
    if not municipality:
        return Applications.query.filter(False)

    owner_user = aliased(User)
    return Applications.query.join(
        Programs, Applications.program_id == Programs.id
    ).join(
        owner_user, Programs.user_id == owner_user.id
    ).join(
        AdminUsers, AdminUsers.user_id == owner_user.id
    ).filter(
        owner_user.role == 'admin',
        func.lower(func.trim(AdminUsers.municipality)) == municipality.lower()
    )


def _scoped_assessments_query():
    """Assessments linked to municipality-scoped applications."""
    municipality = _current_admin_municipality()
    if not municipality:
        return Assessment.query.filter(False)

    owner_user = aliased(User)
    return Assessment.query.join(
        Applications, Assessment.application_id == Applications.id
    ).join(
        Programs, Applications.program_id == Programs.id
    ).join(
        owner_user, Programs.user_id == owner_user.id
    ).join(
        AdminUsers, AdminUsers.user_id == owner_user.id
    ).filter(
        owner_user.role == 'admin',
        func.lower(func.trim(AdminUsers.municipality)) == municipality.lower()
    )


def _scoped_assessment_or_404(assessment_id):
    """Return one municipality-scoped assessment or 404."""
    assessment = _scoped_assessments_query().filter(Assessment.id == assessment_id).first()
    if not assessment:
        from flask import abort
        abort(404)
    return assessment

SEVERITY_RUBRIC_FACTORS = (
    {'key': 'urgency', 'label': 'Urgency of Need', 'weight': 0.30},
    {'key': 'vulnerability', 'label': 'Household Vulnerability', 'weight': 0.25},
    {'key': 'income_impact', 'label': 'Income and Dependency Burden', 'weight': 0.20},
    {'key': 'risk_level', 'label': 'Health or Disaster Risk', 'weight': 0.15},
    {'key': 'time_sensitivity', 'label': 'Time Sensitivity', 'weight': 0.10},
)


def _default_rubric_factors():
    """Return a mutable copy of default severity rubric factors."""
    return [dict(factor) for factor in SEVERITY_RUBRIC_FACTORS]


def _normalize_rubric_weights(factors):
    """Normalize rubric factor weights so total weight equals 1.0."""
    total_weight = sum(float(factor.get('weight', 0) or 0) for factor in factors)
    if total_weight <= 0:
        return False

    for factor in factors:
        factor['weight'] = float(factor.get('weight', 0) or 0) / total_weight
    return True


def _load_assessment_rubric(assessment):
    """Load rubric factors and score values from stored assessment JSON.

    Supports legacy format:
        {"urgency": 3, ...}
    And enriched format:
        {
          "scores": {"urgency": 3, ...},
          "labels": {"urgency": "...", ...},
          "weights": {"urgency": 0.30, ...}
        }
    """
    factors = _default_rubric_factors()
    scores = {factor['key']: 3 for factor in factors}
    severity_enabled = True

    if not assessment.severity_factors:
        return factors, scores, severity_enabled

    try:
        payload = json.loads(assessment.severity_factors)
    except (TypeError, ValueError):
        return factors, scores, severity_enabled

    if not isinstance(payload, dict):
        return factors, scores, severity_enabled

    payload_flag = payload.get('severity_enabled')
    if isinstance(payload_flag, bool):
        severity_enabled = payload_flag
    elif isinstance(payload_flag, (int, float)):
        severity_enabled = bool(payload_flag)
    elif isinstance(payload_flag, str):
        severity_enabled = payload_flag.strip().lower() not in {'0', 'false', 'off', 'no'}

    # Legacy: top-level key -> score.
    if 'scores' not in payload and 'labels' not in payload and 'weights' not in payload:
        for factor in factors:
            key = factor['key']
            value = payload.get(key)
            if isinstance(value, int) and 1 <= value <= 5:
                scores[key] = value
        return factors, scores, severity_enabled

    payload_scores = payload.get('scores', {})
    payload_labels = payload.get('labels', {})
    payload_weights = payload.get('weights', {})

    for factor in factors:
        key = factor['key']

        label_value = payload_labels.get(key)
        if isinstance(label_value, str) and label_value.strip():
            factor['label'] = label_value.strip()

        weight_value = payload_weights.get(key)
        try:
            parsed_weight = float(weight_value)
            if parsed_weight > 0:
                factor['weight'] = parsed_weight
        except (TypeError, ValueError):
            pass

        score_value = payload_scores.get(key)
        if isinstance(score_value, int) and 1 <= score_value <= 5:
            scores[key] = score_value

    _normalize_rubric_weights(factors)
    return factors, scores, severity_enabled


def _serialize_assessment_rubric(factors, scores, severity_enabled=True):
    """Serialize rubric factors/scores for persistence in severity_factors."""
    payload = {
        'scores': {factor['key']: int(scores.get(factor['key'], 3)) for factor in factors},
        'labels': {factor['key']: factor['label'] for factor in factors},
        'weights': {factor['key']: round(float(factor['weight']), 6) for factor in factors},
        'severity_enabled': bool(severity_enabled),
    }
    return json.dumps(payload)


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def suggest_severity_level(score):
    """Map computed severity score to severity level bands."""
    if score is None:
        return 'unrated'
    if score <= 24:
        return 'low'
    if score <= 49:
        return 'moderate'
    if score <= 74:
        return 'high'
    return 'critical'


def _safe_activity_details(details_text):
    if not details_text:
        return {}
    try:
        if isinstance(details_text, dict):
            return details_text
        return json.loads(details_text)
    except (TypeError, ValueError):
        return {}


def _update_assessment_request_log(assessment, status, admin_notes=None):
    request_log = UserActivityLog.query.filter(
        UserActivityLog.action == 'request_assessment',
        UserActivityLog.entity_type == 'assessment_request',
        UserActivityLog.entity_id == assessment.id,
    ).order_by(desc(UserActivityLog.created_at)).first()

    if not request_log:
        return

    details = _safe_activity_details(request_log.details)
    details['status'] = status
    details['assessment_id'] = assessment.id
    details['assessment_type'] = assessment.assessment_type
    details['assessment_title'] = assessment.title
    details['scheduled_date'] = assessment.scheduled_date.strftime('%Y-%m-%d') if assessment.scheduled_date else None
    details['scheduled_time'] = assessment.scheduled_time
    details['location'] = assessment.location
    if admin_notes:
        details['admin_notes'] = admin_notes

    request_log.details = json.dumps(details)


def _complete_assessment_workflow_step(application, reviewer_id=None):
    """Mark the assessment workflow step as completed for the given application."""
    if not application:
        return

    assessment_step = ProgramWorkflowSteps.query.filter_by(
        program_id=application.program_id,
        step_type='assessment'
    ).order_by(ProgramWorkflowSteps.step_order.asc()).first()

    if not assessment_step:
        return

    workflow_status = ApplicationWorkflowStatus.query.filter_by(
        application_id=application.id,
        workflow_step_id=assessment_step.id
    ).first()

    if not workflow_status:
        return

    now = datetime.utcnow()
    workflow_status.step_status = 'completed'
    workflow_status.completed_at = workflow_status.completed_at or now
    workflow_status.reviewed_at = now
    if reviewer_id:
        workflow_status.reviewed_by = reviewer_id

    _enable_next_workflow_step(application, assessment_step.id)
    _refresh_application_status_from_workflow(application)


def _enable_next_workflow_step(application, completed_step_id):
    """Enable the immediate next workflow step after a completed step."""
    if not application or not application.program or not application.program.workflow_steps:
        return

    workflow_steps = sorted(application.program.workflow_steps, key=lambda step: step.step_order)
    completed_step = next((step for step in workflow_steps if step.id == completed_step_id), None)
    if not completed_step:
        return

    next_step = next((step for step in workflow_steps if step.step_order == completed_step.step_order + 1), None)
    if not next_step:
        return

    next_step_status = ApplicationWorkflowStatus.query.filter_by(
        application_id=application.id,
        workflow_step_id=next_step.id,
    ).first()

    now = datetime.utcnow()
    if not next_step_status:
        next_step_status = ApplicationWorkflowStatus(
            application_id=application.id,
            workflow_step_id=next_step.id,
            step_status='not_started',
        )
        db.session.add(next_step_status)

    if next_step_status.step_status == 'not_started':
        next_step_status.step_status = 'in_progress'
        next_step_status.started_at = now
    next_step_status.updated_at = now


def _refresh_application_status_from_workflow(application):
    """Recompute parent application status from workflow progression."""
    if not application or not application.program or not application.program.workflow_steps:
        return

    workflow_steps = sorted(application.program.workflow_steps, key=lambda step: step.step_order)
    if not workflow_steps:
        return

    workflow_status_rows = ApplicationWorkflowStatus.query.filter_by(application_id=application.id).all()
    status_map = {row.workflow_step_id: row.step_status for row in workflow_status_rows}

    current_step = next(
        (step for step in workflow_steps if status_map.get(step.id) not in ['approved', 'completed']),
        workflow_steps[-1]
    )

    first_step = workflow_steps[0]
    last_step = workflow_steps[-1]

    if current_step.step_order == first_step.step_order:
        new_status = 'pending'
    elif current_step.step_order == last_step.step_order:
        new_status = 'completed'
    else:
        new_status = 'active'

    if application.application_status != new_status:
        application.application_status = new_status
        application.updated_at = datetime.utcnow()


@admin_bp.route('/assessments', endpoint='assessments')
@login_required
@role_required('admin')
def assessments_index():
    """List all assessments with search and filter"""
    page = request.args.get('page', 1, type=int)
    per_page = 10

    # Get filter parameters
    search_query = request.args.get('search', '').strip()
    assessment_type = request.args.get('type', '')
    status_filter = request.args.get('status', '')
    severity_filter = request.args.get('severity', '').strip()
    sort_by = request.args.get('sort_by', 'date').strip().lower()
    sort_order = request.args.get('sort_order', '').strip().lower()

    if sort_by not in ('date', 'alphabetical'):
        sort_by = 'date'

    if sort_order not in ('asc', 'desc'):
        sort_order = 'desc' if sort_by == 'date' else 'asc'

    query = _scoped_assessments_query()

    if search_query:
        query = query.join(User, Applications.user_id == User.id).filter(
            or_(
                Assessment.title.ilike(f'%{search_query}%'),
                User.first_name.ilike(f'%{search_query}%'),
                User.last_name.ilike(f'%{search_query}%'),
            )
        )

    if assessment_type:
        query = query.filter(Assessment.assessment_type == assessment_type)

    if status_filter:
        query = query.filter(Assessment.status == status_filter)

    if severity_filter:
        query = query.filter(Assessment.case_severity == severity_filter)

    if sort_by == 'alphabetical':
        if sort_order == 'desc':
            query = query.order_by(func.lower(Assessment.title).desc())
        else:
            query = query.order_by(func.lower(Assessment.title).asc())
    else:
        if sort_order == 'asc':
            query = query.order_by(
                Assessment.scheduled_date.is_(None),
                Assessment.scheduled_date.asc(),
                Assessment.created_at.asc(),
            )
        else:
            query = query.order_by(
                Assessment.scheduled_date.is_(None),
                Assessment.scheduled_date.desc(),
                desc(Assessment.created_at),
            )

    assessments = query.paginate(
        page=page, per_page=per_page, error_out=False
    )

    has_active_filters = any([
        bool(search_query),
        bool(assessment_type),
        bool(status_filter),
        bool(severity_filter),
    ])

    requested_ids = [item.id for item in assessments.items if item.status == 'requested']
    request_summaries = {}
    if requested_ids:
        request_logs = UserActivityLog.query.filter(
            UserActivityLog.action == 'request_assessment',
            UserActivityLog.entity_type == 'assessment_request',
            UserActivityLog.entity_id.in_(requested_ids),
        ).order_by(desc(UserActivityLog.created_at)).all()

        for log in request_logs:
            if log.entity_id in request_summaries:
                continue
            details = _safe_activity_details(log.details)
            request_summaries[log.entity_id] = {
                'purpose': details.get('purpose') or '',
                'preferred_date': details.get('preferred_date') or '',
                'notes': details.get('notes') or '',
                'requested_at': log.created_at,
                'application_id': details.get('application_id'),
                'application_program': details.get('application_program') or '',
            }

    # Statistics for summary cards
    total_assessments = _scoped_assessments_query().count()
    requested_assessments = _scoped_assessments_query().filter(Assessment.status == 'requested').count()
    scheduled_assessments = _scoped_assessments_query().filter(Assessment.status == 'scheduled').count()
    completed_assessments = _scoped_assessments_query().filter(Assessment.status == 'completed').count()
    cancelled_assessments = _scoped_assessments_query().filter(Assessment.status == 'cancelled').count()

    # Get all approved applications for the schedule form dropdown
    approved_applications = _scoped_applications_query().filter(
        Applications.application_status == 'approved'
    ).order_by(desc(Applications.application_date)).all()

    return render_template(
        'admin/adm_assessment.html',
        assessments=assessments,
        approved_applications=approved_applications,
        total_assessments=total_assessments,
        requested_assessments=requested_assessments,
        scheduled_assessments=scheduled_assessments,
        completed_assessments=completed_assessments,
        cancelled_assessments=cancelled_assessments,
        search_query=search_query,
        assessment_type=assessment_type,
        status_filter=status_filter,
        severity_filter=severity_filter,
        request_summaries=request_summaries,
        sort_by=sort_by,
        sort_order=sort_order,
        has_active_filters=has_active_filters,
        user=current_user,
    )


@admin_bp.route('/assessments/create', methods=['POST'], endpoint='create_assessment')
@login_required
@role_required('admin')
def create_assessment():
    """Create / schedule a new assessment (interview or home visit)"""
    application_id = request.form.get('application_id', type=int)
    a_type = request.form.get('assessment_type', '').strip()
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    scheduled_date_str = request.form.get('scheduled_date', '').strip()
    scheduled_time = request.form.get('scheduled_time', '').strip()
    location = request.form.get('location', '').strip()
    
    # Check if this is an AJAX request
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not application_id or not a_type or not title:
        msg = 'Application, type, and title are required.'
        if is_ajax:
            return jsonify(success=False, message=msg), 400
        flash(msg, 'danger')
        return redirect(url_for('admin.assessments'))

    if a_type not in ('interview', 'home_visit'):
        msg = 'Invalid assessment type.'
        if is_ajax:
            return jsonify(success=False, message=msg), 400
        flash(msg, 'danger')
        return redirect(url_for('admin.assessments'))

    application = _scoped_applications_query().filter(Applications.id == application_id).first()
    if not application:
        msg = 'Application not found.'
        if is_ajax:
            return jsonify(success=False, message=msg), 404
        flash(msg, 'danger')
        return redirect(url_for('admin.assessments'))

    scheduled_date = None
    if scheduled_date_str:
        try:
            scheduled_date = datetime.strptime(scheduled_date_str, '%Y-%m-%d')
        except ValueError:
            msg = 'Invalid date format.'
            if is_ajax:
                return jsonify(success=False, message=msg), 400
            flash(msg, 'danger')
            return redirect(url_for('admin.assessments'))

    assessment = Assessment(
        application_id=application_id,
        assessment_type=a_type,
        title=title,
        description=description,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        location=location,
        conducted_by=current_user.id,
    )
    db.session.add(assessment)

    # Notify the applicant
    notif = Notifications(
        user_id=application.user_id,
        notif_title=f'Assessment Scheduled: {title}',
        notif_message=f'An {a_type.replace("_", " ")} has been scheduled for your application to {application.program.program_name}.',
        related_id=application.id,
        related_type='application',
    )
    db.session.add(notif)

    db.session.commit()
    
    # Return JSON for AJAX requests
    if is_ajax:
        return jsonify(success=True, message='Assessment scheduled successfully.', assessment_id=assessment.id), 201
    
    flash('Assessment scheduled successfully.', 'success')
    return redirect(url_for('admin.view_assessment', assessment_id=assessment.id))


@admin_bp.route('/assessments/<int:assessment_id>', endpoint='view_assessment')
@login_required
@role_required('admin')
def view_assessment(assessment_id):
    """View a single assessment with its documents"""
    assessment = _scoped_assessment_or_404(assessment_id)

    severity_rubric_factors, severity_factors_data, severity_enabled = _load_assessment_rubric(assessment)

    return render_template(
        'admin/view_assessment.html',
        assessment=assessment,
        severity_rubric_factors=severity_rubric_factors,
        severity_factors_data=severity_factors_data,
        severity_enabled=severity_enabled,
        user=current_user,
    )


@admin_bp.route('/assessments/<int:assessment_id>/update', methods=['POST'], endpoint='update_assessment')
@login_required
@role_required('admin')
def update_assessment(assessment_id):
    """Update assessment details (findings, status, etc.)"""
    assessment = _scoped_assessment_or_404(assessment_id)

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    scheduled_date_str = request.form.get('scheduled_date', '').strip()
    scheduled_time = request.form.get('scheduled_time', '').strip()
    location = request.form.get('location', '').strip()
    status = request.form.get('status', '').strip()
    findings = request.form.get('findings', '').strip()
    recommendations = request.form.get('recommendations', '').strip()
    case_severity = request.form.get('case_severity', '').strip().lower()
    severity_score_value = request.form.get('severity_score', '').strip()
    severity_justification = request.form.get('severity_justification', '').strip()
    severity_override = request.form.get('severity_override') == '1'
    severity_enabled_values = request.form.getlist('severity_enabled')
    severity_form_submitted = request.form.get('case_severity') is not None or bool(severity_enabled_values)

    stored_rubric_factors, stored_rubric_scores, stored_severity_enabled = _load_assessment_rubric(assessment)
    if severity_enabled_values:
        severity_enabled = '1' in severity_enabled_values
    else:
        severity_enabled = stored_severity_enabled

    if severity_enabled and not case_severity:
        case_severity = 'unrated'

    stored_rubric_map = {factor['key']: factor for factor in stored_rubric_factors}

    rubric_factors = _default_rubric_factors()
    rubric_errors = []

    if severity_form_submitted:
        editable_rubric_factors = []
        for factor in rubric_factors:
            key = factor['key']
            stored_factor = stored_rubric_map.get(key, factor)

            label_value = request.form.get(
                f'severity_factor_label_{key}',
                stored_factor.get('label', factor['label'])
            )
            label_value = (label_value or '').strip()
            if not label_value:
                rubric_errors.append(f'{factor["label"]}: factor label is required.')
                label_value = stored_factor.get('label', factor['label'])

            weight_default_percent = float(stored_factor.get('weight', factor['weight'])) * 100
            weight_raw_value = request.form.get(f'severity_factor_weight_{key}', str(weight_default_percent))
            try:
                weight_percent = float((weight_raw_value or '').strip())
                if weight_percent <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                rubric_errors.append(f'{label_value}: weight must be greater than 0.')
                weight_percent = weight_default_percent if weight_default_percent > 0 else factor['weight'] * 100

            editable_rubric_factors.append({
                'key': key,
                'label': label_value,
                'weight': weight_percent,
            })

        if editable_rubric_factors:
            if not _normalize_rubric_weights(editable_rubric_factors):
                rubric_errors.append('Rubric weights must total more than 0.')
            rubric_factors = editable_rubric_factors

    rubric_scores = {}
    rubric_submitted = False
    for factor in rubric_factors:
        key = factor['key']
        raw_value = request.form.get(f'severity_factor_{key}', '').strip()
        if raw_value:
            rubric_submitted = True
        if raw_value:
            try:
                score_value = int(raw_value)
                if score_value < 1 or score_value > 5:
                    rubric_errors.append(f"{factor['label']} must be between 1 and 5.")
                else:
                    rubric_scores[key] = score_value
            except ValueError:
                rubric_errors.append(f"{factor['label']} must be a valid number.")
        else:
            rubric_scores[key] = int(stored_rubric_scores.get(key, 3))

    if severity_form_submitted and severity_enabled and case_severity and case_severity not in Assessment.SEVERITY_LEVELS:
        flash('Invalid case severity level.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    if rubric_errors:
        flash(rubric_errors[0], 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    if severity_form_submitted and severity_enabled and case_severity and case_severity != 'unrated' and len(rubric_scores) not in (0, len(rubric_factors)):
        flash('All severity rubric factors must be scored from 1 to 5.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    severity_score = None
    if severity_form_submitted and severity_enabled and rubric_submitted and len(rubric_scores) == len(rubric_factors):
        weighted_score_sum = 0
        for factor in rubric_factors:
            weighted_score_sum += rubric_scores[factor['key']] * factor['weight']
        severity_score = round((weighted_score_sum / 5) * 100)
    elif severity_form_submitted and severity_enabled and severity_score_value:
        try:
            severity_score = int(severity_score_value)
        except ValueError:
            flash('Severity score must be a valid whole number from 0 to 100.', 'danger')
            return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

        if severity_score < 0 or severity_score > 100:
            flash('Severity score must be between 0 and 100.', 'danger')
            return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    suggested_severity = suggest_severity_level(severity_score) if (severity_enabled and severity_score is not None) else 'unrated'

    if severity_form_submitted and severity_enabled and not severity_override and severity_score is not None:
        case_severity = suggested_severity
    elif severity_form_submitted and severity_enabled and severity_override and severity_score is not None and case_severity in ('', 'unrated'):
        flash('Select a manual severity level when override is enabled.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    if severity_form_submitted and severity_enabled and case_severity in ('high', 'critical') and not severity_justification:
        flash('Justification is required for high or critical severity.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    if severity_form_submitted and severity_enabled and case_severity and case_severity != 'unrated' and severity_score is None:
        flash('Severity score could not be computed. Please complete all rubric factors.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    if title:
        assessment.title = title
    if description is not None:
        assessment.description = description
    if scheduled_date_str:
        try:
            assessment.scheduled_date = datetime.strptime(scheduled_date_str, '%Y-%m-%d')
        except ValueError:
            flash('Invalid date format.', 'danger')
            return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))
    if scheduled_time is not None:
        assessment.scheduled_time = scheduled_time
    if location is not None:
        assessment.location = location
    status_changed_to_completed = False
    if status and status in ('requested', 'scheduled', 'completed', 'cancelled'):
        previous_status = assessment.status
        assessment.status = status
        status_changed_to_completed = (status == 'completed' and previous_status != 'completed')
        if status == 'completed' and not assessment.completed_at:
            assessment.completed_at = datetime.utcnow()
    if findings is not None:
        assessment.findings = findings
    if recommendations is not None:
        assessment.recommendations = recommendations

    if severity_form_submitted:
        old_level = assessment.case_severity
        old_score = assessment.severity_score

        if severity_enabled:
            assessment.case_severity = case_severity or 'unrated'
            assessment.severity_score = severity_score if assessment.case_severity != 'unrated' else None
            assessment.severity_justification = severity_justification or None
        else:
            assessment.case_severity = 'unrated'
            assessment.severity_score = None
            assessment.severity_justification = None

        assessment.severity_factors = _serialize_assessment_rubric(
            rubric_factors,
            rubric_scores,
            severity_enabled=severity_enabled,
        )
        assessment.severity_updated_by = current_user.id
        assessment.severity_updated_at = datetime.utcnow()

        new_severity_label = assessment.case_severity if severity_enabled else 'severity_off'

        log_activity(
            action='update_assessment_severity',
            action_type='update',
            entity_type='assessment',
            description=f'Updated severity for Assessment #{assessment.id} from {old_level} to {new_severity_label}',
            entity_id=assessment.id,
            details={
                'application_id': assessment.application_id,
                'old_severity': old_level,
                'new_severity': new_severity_label,
                'old_score': old_score,
                'new_score': assessment.severity_score,
                'rubric_scores': rubric_scores,
                'rubric_labels': {factor['key']: factor['label'] for factor in rubric_factors},
                'rubric_weights': {factor['key']: factor['weight'] for factor in rubric_factors},
                'suggested_severity': suggested_severity,
                'severity_override': severity_override,
                'severity_enabled': severity_enabled,
            }
        )

    # If an assessment gets marked completed from this screen, complete the
    # corresponding Assessment / SCSR workflow step as well.
    if status_changed_to_completed:
        _complete_assessment_workflow_step(assessment.application, current_user.id)

    db.session.commit()
    flash('Assessment updated successfully.', 'success')
    return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))


@admin_bp.route('/assessments/<int:assessment_id>/upload', methods=['POST'], endpoint='upload_assessment_document')
@login_required
@role_required('admin')
def upload_assessment_document(assessment_id):
    """Upload a document / SCSR output for an assessment"""
    assessment = _scoped_assessment_or_404(assessment_id)

    if 'document' not in request.files:
        flash('No file selected.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    file = request.files['document']
    if file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    if not allowed_file(file.filename):
        flash('File type not allowed. Allowed types: PDF, DOC, DOCX, JPG, JPEG, PNG.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    # Check file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    if file_size > MAX_FILE_SIZE:
        flash('File size exceeds 10 MB limit.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    # Ensure upload directory exists
    upload_dir = os.path.join(ASSESSMENT_UPLOAD_FOLDER, str(assessment_id))
    os.makedirs(upload_dir, exist_ok=True)

    filename = secure_filename(file.filename)
    # Prevent collisions by prefixing a UUID to the original filename; the human-readable
    # name is preserved in AssessmentDocument.original_filename for display
    stored_filename = f"{uuid.uuid4().hex}_{filename}"
    file_path = os.path.join(upload_dir, stored_filename)
    file.save(file_path)

    doc_description = request.form.get('description', '').strip()

    # Preserve the human-readable name alongside the stored UUID-prefixed filename
    assessment_doc = AssessmentDocument(
        assessment_id=assessment_id,
        file_path=file_path,
        original_filename=filename,
        file_size=file_size,
        file_type=file.content_type,
        description=doc_description,
        uploaded_by=current_user.id,
    )
    db.session.add(assessment_doc)
    db.session.commit()

    flash('Document uploaded successfully.', 'success')
    return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))


@admin_bp.route('/assessments/<int:assessment_id>/document/<int:document_id>/view', endpoint='view_assessment_document')
@login_required
@role_required('admin')
def view_assessment_document(assessment_id, document_id):
    """View/preview an assessment document"""
    assessment = _scoped_assessment_or_404(assessment_id)
    doc = AssessmentDocument.query.get_or_404(document_id)
    
    # Verify the document belongs to this assessment
    if doc.assessment_id != assessment_id:
        return "Unauthorized", 403
    
    # Check if file exists
    if not os.path.exists(doc.file_path):
        return "File not found", 404
    
    # Get the absolute path
    abs_path = os.path.abspath(doc.file_path)
    
    # Determine MIME type based on file extension
    file_ext = os.path.splitext(doc.original_filename)[1].lower()
    mime_types = {
        '.pdf': 'application/pdf',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }
    mime_type = mime_types.get(file_ext, 'application/octet-stream')
    
    return send_file(abs_path, mimetype=mime_type)


@admin_bp.route('/assessments/<int:assessment_id>/document/<int:document_id>/download', endpoint='download_assessment_document')
@login_required
@role_required('admin')
def download_assessment_document(assessment_id, document_id):
    """Download an assessment document"""
    assessment = _scoped_assessment_or_404(assessment_id)
    doc = AssessmentDocument.query.get_or_404(document_id)
    
    # Verify the document belongs to this assessment
    if doc.assessment_id != assessment_id:
        return "Unauthorized", 403
    
    # Check if file exists
    if not os.path.exists(doc.file_path):
        return "File not found", 404
    
    # Get the absolute path
    abs_path = os.path.abspath(doc.file_path)
    
    return send_file(abs_path, as_attachment=True, download_name=doc.original_filename)


@admin_bp.route('/assessments/<int:assessment_id>/document/<int:document_id>/delete', methods=['POST'], endpoint='delete_assessment_document')
@login_required
@role_required('admin')
def delete_assessment_document(assessment_id, document_id):
    """Delete an assessment document"""
    assessment = _scoped_assessment_or_404(assessment_id)
    doc = AssessmentDocument.query.get_or_404(document_id)
    
    # Verify the document belongs to this assessment
    if doc.assessment_id != assessment_id:
        return "Unauthorized", 403
    
    # Remove file from disk
    if os.path.exists(doc.file_path):
        try:
            os.remove(doc.file_path)
        except OSError as e:
            flash(f'Error deleting file: {str(e)}', 'danger')
            return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))
    
    # Delete record from database
    db.session.delete(doc)
    db.session.commit()
    
    flash('Document deleted successfully.', 'success')
    return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))


@admin_bp.route('/assessments/<int:assessment_id>/document/<int:document_id>/reupload', methods=['POST'], endpoint='reupload_assessment_document')
@login_required
@role_required('admin')
def reupload_assessment_document(assessment_id, document_id):
    """Reupload/replace an assessment document"""
    assessment = _scoped_assessment_or_404(assessment_id)
    doc = AssessmentDocument.query.get_or_404(document_id)
    
    # Verify the document belongs to this assessment
    if doc.assessment_id != assessment_id:
        return "Unauthorized", 403
    
    if 'document' not in request.files:
        flash('No file selected.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    file = request.files['document']
    if file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    if not allowed_file(file.filename):
        flash('File type not allowed. Allowed types: PDF, DOC, DOCX, JPG, JPEG, PNG.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    # Check file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    if file_size > MAX_FILE_SIZE:
        flash('File size exceeds 10 MB limit.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    # Remove old file from disk
    if os.path.exists(doc.file_path):
        try:
            os.remove(doc.file_path)
        except OSError as e:
            flash(f'Error removing old file: {str(e)}', 'danger')
            return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    # Save new file
    upload_dir = os.path.join(ASSESSMENT_UPLOAD_FOLDER, str(assessment_id))
    os.makedirs(upload_dir, exist_ok=True)

    filename = secure_filename(file.filename)
    stored_filename = f"{uuid.uuid4().hex}_{filename}"
    file_path = os.path.join(upload_dir, stored_filename)
    file.save(file_path)

    # Update document record
    doc.file_path = file_path
    doc.original_filename = filename
    doc.file_size = file_size
    doc.file_type = file.content_type
    doc.uploaded_by = current_user.id
    doc.uploaded_at = datetime.utcnow()
    
    # Update description if provided
    doc_description = request.form.get('description', '').strip()
    if doc_description:
        doc.description = doc_description

    db.session.commit()

    flash('Document reloaded successfully.', 'success')
    return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))


@admin_bp.route('/assessments/<int:assessment_id>/complete', methods=['POST'], endpoint='complete_assessment')
@login_required
@role_required('admin')
def complete_assessment(assessment_id):
    """Mark assessment as complete and advance workflow to next step"""
    assessment = _scoped_assessment_or_404(assessment_id)
    application_id = assessment.application_id
    application = assessment.application
    
    # Mark assessment as completed
    assessment.status = 'completed'
    assessment.completed_at = datetime.utcnow()

    _complete_assessment_workflow_step(application, current_user.id)
    
    db.session.commit()
    
    flash('Assessment marked as complete. Proceeding to next step.', 'success')
    return redirect(url_for('admin.view_application', application_id=application_id))


@admin_bp.route('/assessments/<int:assessment_id>/schedule-request', methods=['POST'], endpoint='schedule_requested_assessment')
@login_required
@role_required('admin')
def schedule_requested_assessment(assessment_id):
    """Schedule a community-requested assessment from the assessments list modal."""
    assessment = _scoped_assessment_or_404(assessment_id)

    if assessment.status != 'requested':
        flash('Only assessment requests can be scheduled from this action.', 'warning')
        return redirect(url_for('admin.assessments'))

    a_type = (request.form.get('assessment_type') or '').strip()
    title = (request.form.get('title') or '').strip()
    description = (request.form.get('description') or '').strip()
    scheduled_date_str = (request.form.get('scheduled_date') or '').strip()
    scheduled_time = (request.form.get('scheduled_time') or '').strip()
    location = (request.form.get('location') or '').strip()

    if a_type not in ('interview', 'home_visit'):
        flash('Please select a valid assessment type.', 'danger')
        return redirect(url_for('admin.assessments'))

    if not title:
        flash('Assessment title is required.', 'danger')
        return redirect(url_for('admin.assessments'))

    if not scheduled_date_str:
        flash('Scheduled date is required.', 'danger')
        return redirect(url_for('admin.assessments'))

    try:
        scheduled_date = datetime.strptime(scheduled_date_str, '%Y-%m-%d')
    except ValueError:
        flash('Invalid scheduled date format.', 'danger')
        return redirect(url_for('admin.assessments'))

    assessment.assessment_type = a_type
    assessment.title = title
    assessment.description = description
    assessment.scheduled_date = scheduled_date
    assessment.scheduled_time = scheduled_time
    assessment.location = location
    assessment.status = 'scheduled'
    assessment.conducted_by = current_user.id

    _update_assessment_request_log(assessment, 'scheduled')

    notif = Notifications(
        user_id=assessment.application.user_id,
        notif_title='Assessment Request Scheduled',
        notif_message=(
            f'Your assessment/SCSR request has been scheduled on '
            f'{scheduled_date.strftime("%b %d, %Y")}'
            f'{f" at {scheduled_time}" if scheduled_time else ""}.'
        ),
        related_id=assessment.id,
        related_type='assessment',
    )
    db.session.add(notif)

    db.session.commit()
    flash('Assessment request scheduled successfully.', 'success')
    return redirect(url_for('admin.assessments'))


@admin_bp.route('/assessments/<int:assessment_id>/decline-request', methods=['POST'], endpoint='decline_requested_assessment')
@login_required
@role_required('admin')
def decline_requested_assessment(assessment_id):
    """Decline a community-requested assessment from the assessments list modal."""
    assessment = _scoped_assessment_or_404(assessment_id)

    if assessment.status != 'requested':
        flash('Only assessment requests can be declined from this action.', 'warning')
        return redirect(url_for('admin.assessments'))

    decline_reason = (request.form.get('decline_reason') or '').strip()

    assessment.status = 'cancelled'
    if decline_reason:
        description_prefix = (assessment.description or '').strip()
        decline_note = f'Decline reason: {decline_reason}'
        if description_prefix:
            assessment.description = f'{description_prefix}\n\n{decline_note}'
        else:
            assessment.description = decline_note

    _update_assessment_request_log(assessment, 'cancelled', admin_notes=decline_reason or None)

    notif = Notifications(
        user_id=assessment.application.user_id,
        notif_title='Assessment Request Declined',
        notif_message=(
            'Your assessment/SCSR request was declined.'
            + (f' Reason: {decline_reason}' if decline_reason else '')
        ),
        related_id=assessment.id,
        related_type='assessment',
    )
    db.session.add(notif)

    db.session.commit()
    flash('Assessment request declined.', 'success')
    return redirect(url_for('admin.assessments'))

