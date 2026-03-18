from flask import render_template, request, flash, redirect, url_for, jsonify, send_from_directory, send_file
from flask_login import login_required, current_user
from datetime import datetime
import json
import uuid
from sqlalchemy import desc, or_, func
from app.admin import admin_bp
from app.models import (
    Assessment, AssessmentDocument, Applications, Programs,
    User, Notifications, ApplicationWorkflowStatus, ProgramWorkflowSteps
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

SEVERITY_RUBRIC_FACTORS = (
    {'key': 'urgency', 'label': 'Urgency of Need', 'weight': 0.30},
    {'key': 'vulnerability', 'label': 'Household Vulnerability', 'weight': 0.25},
    {'key': 'income_impact', 'label': 'Income and Dependency Burden', 'weight': 0.20},
    {'key': 'risk_level', 'label': 'Health or Disaster Risk', 'weight': 0.15},
    {'key': 'time_sensitivity', 'label': 'Time Sensitivity', 'weight': 0.10},
)


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

    query = Assessment.query

    if search_query:
        query = query.join(Assessment.application).join(Applications.applicant).filter(
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

    assessments = query.order_by(desc(Assessment.created_at)).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Statistics for summary cards
    total_assessments = Assessment.query.count()
    scheduled_assessments = Assessment.query.filter_by(status='scheduled').count()
    completed_assessments = Assessment.query.filter_by(status='completed').count()
    cancelled_assessments = Assessment.query.filter_by(status='cancelled').count()

    # Get all approved applications for the schedule form dropdown
    approved_applications = Applications.query.filter(
        Applications.application_status == 'approved'
    ).order_by(desc(Applications.application_date)).all()

    return render_template(
        'admin/adm_assessment.html',
        assessments=assessments,
        approved_applications=approved_applications,
        total_assessments=total_assessments,
        scheduled_assessments=scheduled_assessments,
        completed_assessments=completed_assessments,
        cancelled_assessments=cancelled_assessments,
        search_query=search_query,
        assessment_type=assessment_type,
        status_filter=status_filter,
        severity_filter=severity_filter,
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

    application = Applications.query.get(application_id)
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
    assessment = Assessment.query.get_or_404(assessment_id)

    severity_factors_data = {factor['key']: 3 for factor in SEVERITY_RUBRIC_FACTORS}
    if assessment.severity_factors:
        try:
            stored_factors = json.loads(assessment.severity_factors)
            if isinstance(stored_factors, dict):
                for factor in SEVERITY_RUBRIC_FACTORS:
                    key = factor['key']
                    value = stored_factors.get(key)
                    if isinstance(value, int) and 1 <= value <= 5:
                        severity_factors_data[key] = value
        except (ValueError, TypeError):
            pass

    return render_template(
        'admin/view_assessment.html',
        assessment=assessment,
        severity_rubric_factors=SEVERITY_RUBRIC_FACTORS,
        severity_factors_data=severity_factors_data,
        user=current_user,
    )


@admin_bp.route('/assessments/<int:assessment_id>/update', methods=['POST'], endpoint='update_assessment')
@login_required
@role_required('admin')
def update_assessment(assessment_id):
    """Update assessment details (findings, status, etc.)"""
    assessment = Assessment.query.get_or_404(assessment_id)

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

    rubric_scores = {}
    rubric_submitted = False
    rubric_errors = []
    for factor in SEVERITY_RUBRIC_FACTORS:
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

    if case_severity and case_severity not in Assessment.SEVERITY_LEVELS:
        flash('Invalid case severity level.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    if rubric_errors:
        flash(rubric_errors[0], 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    if case_severity and case_severity != 'unrated' and len(rubric_scores) not in (0, len(SEVERITY_RUBRIC_FACTORS)):
        flash('All severity rubric factors must be scored from 1 to 5.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    severity_score = None
    if rubric_submitted and len(rubric_scores) == len(SEVERITY_RUBRIC_FACTORS):
        weighted_score_sum = 0
        for factor in SEVERITY_RUBRIC_FACTORS:
            weighted_score_sum += rubric_scores[factor['key']] * factor['weight']
        severity_score = round((weighted_score_sum / 5) * 100)
    elif severity_score_value:
        try:
            severity_score = int(severity_score_value)
        except ValueError:
            flash('Severity score must be a valid whole number from 0 to 100.', 'danger')
            return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

        if severity_score < 0 or severity_score > 100:
            flash('Severity score must be between 0 and 100.', 'danger')
            return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    suggested_severity = suggest_severity_level(severity_score) if severity_score is not None else 'unrated'

    if not severity_override and severity_score is not None:
        case_severity = suggested_severity
    elif severity_override and severity_score is not None and case_severity in ('', 'unrated'):
        flash('Select a manual severity level when override is enabled.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    if case_severity in ('high', 'critical') and not severity_justification:
        flash('Justification is required for high or critical severity.', 'danger')
        return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))

    if case_severity and case_severity != 'unrated' and severity_score is None:
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
    if status and status in ('scheduled', 'completed', 'cancelled'):
        assessment.status = status
        if status == 'completed' and not assessment.completed_at:
            assessment.completed_at = datetime.utcnow()
    if findings is not None:
        assessment.findings = findings
    if recommendations is not None:
        assessment.recommendations = recommendations

    if case_severity:
        old_level = assessment.case_severity
        old_score = assessment.severity_score

        assessment.case_severity = case_severity
        assessment.severity_score = severity_score if case_severity != 'unrated' else None
        assessment.severity_factors = json.dumps(rubric_scores) if (case_severity != 'unrated' and rubric_scores) else None
        assessment.severity_justification = severity_justification or None
        assessment.severity_updated_by = current_user.id
        assessment.severity_updated_at = datetime.utcnow()

        log_activity(
            action='update_assessment_severity',
            action_type='update',
            entity_type='assessment',
            description=f'Updated severity for Assessment #{assessment.id} from {old_level} to {case_severity}',
            entity_id=assessment.id,
            details={
                'application_id': assessment.application_id,
                'old_severity': old_level,
                'new_severity': case_severity,
                'old_score': old_score,
                'new_score': severity_score,
                'rubric_scores': rubric_scores,
                'suggested_severity': suggested_severity,
                'severity_override': severity_override,
            }
        )

    db.session.commit()
    flash('Assessment updated successfully.', 'success')
    return redirect(url_for('admin.view_assessment', assessment_id=assessment_id))


@admin_bp.route('/assessments/<int:assessment_id>/upload', methods=['POST'], endpoint='upload_assessment_document')
@login_required
@role_required('admin')
def upload_assessment_document(assessment_id):
    """Upload a document / SCSR output for an assessment"""
    assessment = Assessment.query.get_or_404(assessment_id)

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
    assessment = Assessment.query.get_or_404(assessment_id)
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
    assessment = Assessment.query.get_or_404(assessment_id)
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
    assessment = Assessment.query.get_or_404(assessment_id)
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
    assessment = Assessment.query.get_or_404(assessment_id)
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
    assessment = Assessment.query.get_or_404(assessment_id)
    application_id = assessment.application_id
    application = Applications.query.get_or_404(application_id)
    
    # Mark assessment as completed
    assessment.status = 'completed'
    assessment.completed_at = datetime.utcnow()
    
    # Find and update the workflow status for assessment step
    assessment_step = ProgramWorkflowSteps.query.filter_by(
        program_id=application.program_id,
        step_type='assessment'
    ).first()
    
    if assessment_step:
        # Mark the assessment step as completed
        workflow_status = ApplicationWorkflowStatus.query.filter_by(
            application_id=application_id,
            workflow_step_id=assessment_step.id
        ).first()
        
        if workflow_status:
            workflow_status.step_status = 'completed'
            workflow_status.completed_at = datetime.utcnow()
            workflow_status.reviewed_at = datetime.utcnow()
            workflow_status.reviewed_by = current_user.id
    
    db.session.commit()
    
    flash('Assessment marked as complete. Proceeding to next step.', 'success')
    return redirect(url_for('admin.view_application', application_id=application_id))
