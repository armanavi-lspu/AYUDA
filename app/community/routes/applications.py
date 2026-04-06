from flask import render_template, request, flash, redirect, url_for, send_file, current_app, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from app.community import community_bp
from app.utils import role_required, manila_strftime
from app.models import Applications, Programs, ApplicationDocuments, ProgramRequirements, Requirements, ApplicationDocumentUploads, Notifications, User, ApplicationWorkflowStatus, ProgramWorkflowSteps, ShelterPhotos, CommunityUsers
from app.extensions import db
from app.user_activity_logger import log_document_upload
from sqlalchemy import desc, or_
from werkzeug.utils import secure_filename
from PIL import Image
import os

@community_bp.route('/applications')
@login_required
@role_required('community')
def applications():
    """Display all applications submitted by the current user"""
    page = request.args.get('page', 1, type=int)
    per_page = 10
    status_filter = request.args.get('status', 'all')
    
    # Base query for user's applications
    query = Applications.query.filter_by(user_id=current_user.id)
    
    # Apply status filter
    if status_filter != 'all':
        if status_filter == 'pending':
            query = query.filter(Applications.application_status.in_(['pending']))
        elif status_filter == 'returned':
            query = query.filter(or_(
                Applications.application_status == 'rejected',
                Applications.remarks.isnot(None)
            ))  
        elif status_filter == 'active':
            query = query.filter(Applications.application_status.in_(['active']))
        else:
            query = query.filter_by(application_status=status_filter)
    
    query = query.order_by(desc(Applications.application_date))
    
    applications_paginated = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    # Calculate simplified statistics
    total_applications = Applications.query.filter_by(user_id=current_user.id)
    
    stats = {
        'total': total_applications.count(),
        'pending': total_applications.filter(
            Applications.application_status == 'pending'
        ).count(),
        'returned': total_applications.filter(or_(
            Applications.application_status == 'rejected',
            Applications.remarks.isnot(None)
        )).count(),
        'approved': total_applications.filter_by(application_status='approved').count(),
        'active': total_applications.filter_by(application_status='active').count(),
        'completed': total_applications.filter_by(application_status='completed').count()
    }
    
    return render_template(
        'community/applications.html',
        applications=applications_paginated.items,
        pagination=applications_paginated,
        stats=stats,
        current_filter=status_filter,
        user=current_user
    )

@community_bp.route('/applications/<int:application_id>')
@login_required
@role_required('community')
def application_detail(application_id):
    """Redirect to workflow view to track application progress"""
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    # Auto-transition from 'approved' to 'active' when the user opens/views their approved application
    if application.application_status == 'approved':
        application.application_status = 'active'
        application.updated_at = datetime.utcnow()
        db.session.commit()
    
    # Always redirect to workflow view for applications
    return redirect(url_for('community.application_workflow', application_id=application_id))


@community_bp.route('/applications/<int:application_id>/workflow')
@login_required
@role_required('community')
def application_workflow(application_id):
    """Step-by-step workflow interface for community users"""
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    # Auto-transition from 'approved' to 'active' when the user opens/views their approved application
    if application.application_status == 'approved':
        application.application_status = 'active'
        application.updated_at = datetime.utcnow()
        db.session.commit()
    
    # Get workflow steps for this program
    workflow_steps = sorted(application.program.workflow_steps, key=lambda x: x.step_order) if application.program.workflow_steps else []
    
    if not workflow_steps:
        # Show application status information even without workflow steps
        flash('This program does not have a detailed workflow configured. Showing application status.', 'info')
        return render_template(
            'community/application_workflow.html',
            application=application,
            workflow_steps=[],
            workflow_status=[],
            active_step=None,
            current_step=None,
            current_step_status=None,
            step_content={},
            progress_percentage=0,
            datetime=datetime,
            user=current_user,
            no_workflow=True
        )
    
    # Initialize workflow status for all steps if not exists
    _initialize_workflow_status(application, workflow_steps)
    
    # Get current workflow status for all steps
    workflow_status = db.session.query(ApplicationWorkflowStatus).filter_by(
        application_id=application_id
    ).join(ProgramWorkflowSteps).order_by(ProgramWorkflowSteps.step_order).all()
    
    # Check if user is requesting a specific step to view (e.g., from step history)
    requested_step_id = request.args.get('step_id', type=int)
    
    # FIRST: Determine the actual active step (what the user should be working on)
    active_step = None
    active_step_status = None
    
    # Find the step user should be working on
    for status in workflow_status:
        if status.step_status in ['not_started', 'in_progress', 'rejected']:
            active_step = status.workflow_step
            active_step_status = status
            break
    
    # If no in-progress step, check if we can start the next step
    if not active_step:
        for status in workflow_status:
            if status.step_status == 'not_started':
                # Check if previous steps are completed
                previous_steps_completed = True
                for prev_status in workflow_status:
                    if (prev_status.workflow_step.step_order < status.workflow_step.step_order and 
                        prev_status.step_status not in ['approved', 'completed']):
                        previous_steps_completed = False
                        break
                
                if previous_steps_completed:
                    active_step = status.workflow_step
                    active_step_status = status
                    break
    
    # SECOND: Determine which step to display content for (may differ from active step)
    current_step = active_step
    current_step_status = active_step_status
    
    # If specific step is requested, display that step instead
    if requested_step_id:
        # Only allow viewing completed or current steps
        for status in workflow_status:
            if status.workflow_step.id == requested_step_id:
                # Allow viewing if step is completed, approved, or is the current step
                if status.step_status in ['completed', 'approved', 'in_progress', 'pending_review']:
                    current_step = status.workflow_step
                    current_step_status = status
                break
    
    # Get step-specific data based on step type
    step_content = {}
    if current_step:
        step_content = _get_step_content(application, current_step, current_step_status)
    
    # Calculate progress percentage
    completed_steps = len([s for s in workflow_status if s.step_status in ['approved', 'completed']])
    total_steps = len(workflow_steps)
    progress_percentage = int((completed_steps / total_steps) * 100) if total_steps > 0 else 0
    
    return render_template(
        'community/application_workflow.html',
        application=application,
        workflow_steps=workflow_steps,
        workflow_status=workflow_status,
        active_step=active_step,
        current_step=current_step,
        current_step_status=current_step_status,
        step_content=step_content,
        progress_percentage=progress_percentage,
        datetime=datetime,
        user=current_user,
        no_workflow=False
    )


def _initialize_workflow_status(application, workflow_steps):
    """Initialize workflow status for all steps if not exists"""
    for step in workflow_steps:
        existing_status = ApplicationWorkflowStatus.query.filter_by(
            application_id=application.id,
            workflow_step_id=step.id
        ).first()
        
        if not existing_status:
            status = ApplicationWorkflowStatus(
                application_id=application.id,
                workflow_step_id=step.id,
                step_status='not_started'
            )
            db.session.add(status)
    
    db.session.commit()


def _get_step_content(application, step, step_status):
    """Get content specific to the current workflow step"""
    content = {
        'documents': [],
        'uploads': [],
        'requirements': [],
        'instructions': step.step_description or '',
        'form_data': step_status.step_data_json if step_status else {}
    }
    
    if step.step_type in ['document_upload']:
        # Get required documents for this step
        step_config = step.config_data if hasattr(step, 'config_data') else {}
        required_docs = step_config.get('required_documents', [])
        
        if required_docs:
            # Get specific documents required for this step
            documents = db.session.query(Requirements).filter(
                Requirements.id.in_(required_docs)
            ).all()
        else:
            # Get all program documents if no specific requirements
            documents = db.session.query(
                Requirements
            ).join(
                ProgramRequirements, Requirements.id == ProgramRequirements.requirement_id
            ).filter(
                ProgramRequirements.program_id == application.program_id,
                Requirements.requirement_type == 'document'
            ).all()
            
        content['documents'] = documents
        
        # Get existing uploads for these documents
        uploads = ApplicationDocumentUploads.query.filter(
            ApplicationDocumentUploads.application_id == application.id,
            ApplicationDocumentUploads.requirement_id.in_([d.id for d in documents])
        ).all()
        content['uploads'] = uploads

    elif step.step_type in ['document_submission', 'document_submission_office', 'physical_submission']:
        # Read-only checklist view for physically submitted documents at MSWD Office
        step_config = step.config_data if hasattr(step, 'config_data') else {}
        required_docs = step_config.get('required_documents', [])

        checklist_query = db.session.query(
            Requirements,
            ProgramRequirements,
            ApplicationDocuments
        ).join(
            ProgramRequirements,
            Requirements.id == ProgramRequirements.requirement_id
        ).outerjoin(
            ApplicationDocuments,
            db.and_(
                ApplicationDocuments.application_id == application.id,
                ApplicationDocuments.requirement_id == Requirements.id
            )
        ).filter(
            ProgramRequirements.program_id == application.program_id,
            Requirements.requirement_type == 'document'
        )

        if required_docs:
            checklist_query = checklist_query.filter(Requirements.id.in_(required_docs))

        checklist_rows = checklist_query.order_by(Requirements.requirement_name.asc()).all()

        checklist_items = []
        requirement_ids = []
        for req, prog_req, app_doc in checklist_rows:
            requirement_ids.append(req.id)
            checklist_items.append({
                'id': app_doc.id if app_doc else None,
                'requirement_id': req.id,
                'requirement_name': req.requirement_name,
                'description': req.description,
                'is_mandatory': prog_req.is_mandatory,
                'submission_status': app_doc.submission_status if app_doc else 'not_submitted',
                'admin_feedback': app_doc.admin_feedback if app_doc else None,
                'notes': app_doc.notes if app_doc else None,
                'verified_at': app_doc.verified_at if app_doc else None
            })

        # Include uploaded document copies for read-only viewing when available
        uploads = []
        if requirement_ids:
            uploads = ApplicationDocumentUploads.query.filter(
                ApplicationDocumentUploads.application_id == application.id,
                ApplicationDocumentUploads.requirement_id.in_(requirement_ids)
            ).all()

        content['checklist'] = checklist_items
        content['uploads'] = uploads
        content['total_checklist'] = len(checklist_items)
        content['verified_checklist'] = len([
            item for item in checklist_items
            if item['submission_status'] in ['verified', 'approved']
        ])
        
    elif step.step_type == 'photo_upload':
        # Get shelter photos for this application
        photos = ShelterPhotos.query.filter_by(
            application_id=application.id
        ).order_by(ShelterPhotos.uploaded_at.desc()).all()
        content['photos'] = photos
        content['photo_count'] = len(photos)
        content['min_photos'] = 3  # Default minimum
        content['has_min_photos'] = len(photos) >= 3
        # Check verification status
        approved_photos = [p for p in photos if p.verification_status == 'approved']
        rejected_photos = [p for p in photos if p.verification_status == 'rejected']
        pending_photos = [p for p in photos if p.verification_status == 'pending']
        content['approved_count'] = len(approved_photos)
        content['rejected_count'] = len(rejected_photos)
        content['pending_count'] = len(pending_photos)
        content['all_approved'] = len(approved_photos) >= 3
        content['has_rejected'] = len(rejected_photos) > 0
    
    elif step.step_type == 'approval':
        # Get qualification requirements with mandatory status
        qual_data = db.session.query(
            Requirements, ProgramRequirements
        ).join(
            ProgramRequirements, Requirements.id == ProgramRequirements.requirement_id
        ).filter(
            ProgramRequirements.program_id == application.program_id,
            Requirements.requirement_type == 'qualification'
        ).all()
        
        # Get applicant community profile for qualification checking
        community_profile = CommunityUsers.query.filter_by(user_id=application.user_id).first()
        
        qualification_list = []
        for req, prog_req in qual_data:
            is_met = _check_community_qualification(req.requirement_name, community_profile)
            qualification_list.append({
                'id': req.id,
                'name': req.requirement_name,
                'description': req.description,
                'is_mandatory': prog_req.is_mandatory,
                'is_met': is_met  # True, False, or None (needs manual review)
            })
        
        content['qualifications'] = qualification_list
        content['total_qualifications'] = len(qualification_list)
        content['met_count'] = len([q for q in qualification_list if q['is_met'] is True])
        content['not_met_count'] = len([q for q in qualification_list if q['is_met'] is False])
        content['review_count'] = len([q for q in qualification_list if q['is_met'] is None])
        
        # Include basic applicant profile info for display
        if community_profile:
            content['applicant_profile'] = {
                'age': community_profile.age,
                'barangay': community_profile.barangay,
                'municipality': community_profile.municipality,
                'is_employed': community_profile.is_currently_employed,
                'occupation': community_profile.occupation,
                'is_student': community_profile.is_student,
                'is_solo_parent': community_profile.is_solo_parent,
                'is_pwd': community_profile.is_pwd,
                'family_income': str(community_profile.family_annual_income) if community_profile.family_annual_income else None
            }
        
        # Preserve old 'requirements' key for backward compatibility
        content['requirements'] = [req for req, _ in qual_data]
    
    elif step.step_type == 'assessment':
        # Get assessments for this application
        from app.models import Assessment
        assessments = Assessment.query.filter_by(
            application_id=application.id
        ).order_by(Assessment.created_at.desc()).all()
        
        assessments_data = [{
            'id': a.id,
            'assessment_type': a.assessment_type,
            'title': a.title,
            'status': a.status,
            'description': a.description,
            'location': a.location,
            'scheduled_date': manila_strftime(a.scheduled_date, '%b %d, %Y', None),
            'scheduled_time': a.scheduled_time,
            'completed_at': manila_strftime(a.completed_at, '%b %d, %Y', None),
            'document_count': len(a.documents),
        } for a in assessments]
        
        content['assessments'] = assessments_data
        content['assessment_count'] = len(assessments_data)
    
    return content


def _check_community_qualification(qual_name, community_profile):
    """Check if an applicant meets a qualification requirement based on their profile"""
    if not community_profile:
        return None
    
    qual_name_lower = qual_name.lower()
    
    # Employment status
    if 'unemployed' in qual_name_lower:
        return not community_profile.is_currently_employed
    
    # Student status
    if 'student' in qual_name_lower:
        return community_profile.is_student
    
    # Solo parent
    if 'solo parent' in qual_name_lower:
        return community_profile.is_solo_parent
    
    # PWD
    if 'pwd' in qual_name_lower or 'disability' in qual_name_lower or 'person with disability' in qual_name_lower:
        return community_profile.is_pwd
    
    # Senior citizen
    if 'senior' in qual_name_lower:
        return community_profile.age >= 60 if community_profile.age else None
    
    # Low income
    if 'low income' in qual_name_lower or 'indigent' in qual_name_lower:
        if community_profile.family_annual_income is not None:
            return float(community_profile.family_annual_income) < 200000
        return None
    
    # Residency
    if 'resident' in qual_name_lower and 'mabitac' in qual_name_lower:
        return community_profile.municipality and 'mabitac' in community_profile.municipality.lower()
    
    # Manual verification needed for: fire victim, typhoon victim, deceased family, medical emergency
    return None


@community_bp.route('/documents/<int:doc_id>/download')
@login_required
def download_document(doc_id):
    """Download or view a document file"""
    # Get the document
    document = ApplicationDocuments.query.get_or_404(doc_id)
    
    # Security check: ensure user owns the application or is an admin
    if current_user.role != 'admin':
        if document.application.user_id != current_user.id:
            flash('You do not have permission to view this document.', 'danger')
            return redirect(url_for('community.applications'))
    
    # Check if file exists
    if not document.file_path or not os.path.exists(document.file_path):
        flash('Document file not found.', 'danger')
        return redirect(request.referrer or url_for('community.applications'))
    
    try:
        # Send file for download/view
        return send_file(
            document.file_path,
            as_attachment=False,  # False = view in browser, True = force download
            download_name=os.path.basename(document.file_path)
        )
    except Exception as e:
        flash(f'Error accessing document: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('community.applications'))

@community_bp.route('/applications/<int:application_id>/slip')
@login_required
@role_required('community')
def application_slip(application_id):
    """Application slip viewing is disabled for community users"""    
    flash('Application slips can only be obtained from the MSWD Office. Please submit your documents to receive your application slip with verification code.', 'info')
    return redirect(url_for('community.application_workflow', application_id=application_id))


@community_bp.route('/verify-code', methods=['GET', 'POST'])
@login_required
@role_required('community')
def verify_code():
    """Verify application code from physical slip"""
    if request.method == 'POST':
        code = request.form.get('verification_code', '').strip().upper()
        
        if not code:
            flash('Please enter a verification code.', 'warning')
            return render_template('community/verify_code.html', user=current_user)
        
        # Find application by verification code
        application = Applications.query.filter_by(
            verification_code=code,
            user_id=current_user.id
        ).first()
        
        if not application:
            flash('Invalid verification code or the code does not belong to your account.', 'danger')
            return render_template('community/verify_code.html', user=current_user)
        
        # Check if code has already been used
        if application.code_used_at:
            flash(f'This verification code has already been used on {manila_strftime(application.code_used_at, "%B %d, %Y at %I:%M %p", "N/A")}.', 'warning')
            return redirect(url_for('community.application_workflow', application_id=application.id))
        
        # Mark code as used and update application status
        try:
            application.code_used_at = datetime.utcnow()
            application.documents_submitted_at = datetime.utcnow()
            
            # Update all document statuses to pending for review
            for doc in application.document_checklist:
                if doc.submission_status in ['not_submitted', 'returned']:
                    doc.submission_status = 'pending'
                    doc.submitted_at = datetime.utcnow()
            
            db.session.commit()
            
            flash(f'Verification successful! Your documents for {application.program.program_name} are now marked as submitted and pending review.', 'success')
            return redirect(url_for('community.application_workflow', application_id=application.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error processing verification: {str(e)}', 'danger')
            return render_template('community/verify_code.html', user=current_user)
    
    return render_template('community/verify_code.html', user=current_user)

@community_bp.route('/applications/<int:application_id>/cancel', methods=['POST'])
@login_required
@role_required('community')
def cancel_application(application_id):
    """Cancel and completely delete an application with all associated data"""
    try:
        # Get the application and verify user owns it
        application = Applications.query.filter_by(
            id=application_id,
            user_id=current_user.id
        ).first_or_404()

        # Enforce cancellation workflow for approved/active applications.
        if application.application_status in ['approved', 'active']:
            if not (application.cancellation_requested and application.cancellation_status == 'approved'):
                flash('Please submit a cancellation request first and wait for admin approval before deleting this application.', 'warning')
                return redirect(url_for('community.application_detail', application_id=application_id))
        
        program_name = application.program.program_name
        
        # Delete all uploaded document files (ApplicationDocumentUploads has file_path)
        if application.document_uploads:
            for upload in application.document_uploads:
                if upload.file_path and os.path.exists(upload.file_path):
                    try:
                        os.remove(upload.file_path)
                    except:
                        pass
                db.session.delete(upload)
        
        # Delete application document checklist entries (no files, just status tracking)
        app_docs = ApplicationDocuments.query.filter_by(application_id=application_id).all()
        for doc in app_docs:
            db.session.delete(doc)
        
        # Delete all shelter photos and their files
        if application.shelter_photos:
            for photo in application.shelter_photos:
                if photo.photo_path:
                    try:
                        full_path = os.path.join(current_app.static_folder, photo.photo_path)
                        if os.path.exists(full_path):
                            os.remove(full_path)
                    except:
                        pass
                db.session.delete(photo)
        
        # Delete the application itself
        db.session.delete(application)
        db.session.commit()
        
        flash(f'Your application for {program_name} has been cancelled and permanently deleted.', 'success')
        return redirect(url_for('community.applications'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error cancelling application: {str(e)}', 'danger')
        return redirect(url_for('community.application_workflow', application_id=application_id))


@community_bp.route('/applications/<int:application_id>/request-cancel', methods=['POST'])
@login_required
@role_required('community')
def request_cancel_application(application_id):
    """Request cancellation of an approved/active application (requires admin approval)"""
    try:
        # Get the application and verify user owns it
        application = Applications.query.filter_by(
            id=application_id,
            user_id=current_user.id
        ).first_or_404()
        
        # Only allow cancellation requests for approved or active applications
        if application.application_status not in ['approved', 'active']:
            flash('Cancellation requests are only available for approved or active applications.', 'warning')
            return redirect(url_for('community.application_detail', application_id=application_id))
        
        # Check if cancellation already requested
        if application.cancellation_requested and application.cancellation_status == 'pending':
            flash('You have already submitted a cancellation request for this application. Please wait for admin review.', 'info')
            return redirect(url_for('community.application_detail', application_id=application_id))
        
        # Get cancellation reason from form
        cancellation_reason = request.form.get('cancellation_reason', '').strip()
        
        if not cancellation_reason:
            flash('Please provide a reason for cancellation.', 'warning')
            return redirect(url_for('community.application_detail', application_id=application_id))
        
        # Update application with cancellation request
        application.cancellation_requested = True
        application.cancellation_reason = cancellation_reason
        application.cancellation_requested_at = datetime.utcnow()
        application.cancellation_status = 'pending'
        application.updated_at = datetime.utcnow()
        
        # Create notifications for admins
        admin_users = User.query.filter_by(role='admin').all()
        for admin in admin_users:
            notification = Notifications(
                user_id=admin.id,
                notif_title=f'Cancellation Request - {application.program.program_name}',
                notif_message=f'{current_user.first_name} {current_user.last_name} has requested to cancel their {application.application_status} application for {application.program.program_name}.',
                is_read=False,
                related_id=application_id,
                related_type='application'
            )
            db.session.add(notification)
        
        db.session.commit()
        
        flash(f'Your cancellation request has been submitted. An administrator will review your request shortly.', 'success')
        return redirect(url_for('community.application_detail', application_id=application_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error submitting cancellation request: {str(e)}', 'danger')
        return redirect(url_for('community.application_detail', application_id=application_id))


@community_bp.route('/applications/<int:application_id>/upload-documents')
@login_required
@role_required('community')
def upload_documents(application_id):
    """Display document upload page for an application"""
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    # Check if online upload is enabled for this program
    if not application.program.allow_online_upload:
        flash('Online document upload is not available for this program. Please submit your documents physically at the MSWD office.', 'info')
        return redirect(url_for('community.application_workflow', application_id=application_id))
    
    # For ESA programs, check if shelter photos are verified first
    if application.program.program_type == 'ESA':
        if not application.shelter_photos or len(application.shelter_photos) < 3:
            flash('Please upload at least 3 shelter photos before submitting documents.', 'warning')
            return redirect(url_for('community.application_workflow', application_id=application_id))
        
        approved_photos = [p for p in application.shelter_photos if p.verification_status == 'approved']
        if len(approved_photos) < 3:
            flash('Your shelter photos must be verified before you can submit documents. Please wait for admin verification.', 'info')
            return redirect(url_for('community.application_workflow', application_id=application_id))
    
    # Get document requirements for this program (exclude qualifications)
    program_requirements = db.session.query(
        Requirements,
        ProgramRequirements
    ).join(
        ProgramRequirements,
        Requirements.id == ProgramRequirements.requirement_id
    ).filter(
        ProgramRequirements.program_id == application.program_id,
        Requirements.requirement_type == 'document'
    ).all()
    
    # Get existing uploads
    existing_uploads = {
        upload.requirement_id: upload 
        for upload in ApplicationDocumentUploads.query.filter_by(
            application_id=application_id
        ).all()
    }
    
    # Prepare document requirements data
    document_requirements = []
    mandatory_count = 0
    uploaded_count = 0
    
    for req, prog_req in program_requirements:
        has_upload = req.id in existing_uploads
        if has_upload:
            uploaded_count += 1
        if prog_req.is_mandatory:
            mandatory_count += 1
        
        # Parse copy specifications from JSON
        import json
        try:
            copy_specs = json.loads(prog_req.copy_type) if isinstance(prog_req.copy_type, str) else prog_req.copy_type
        except:
            copy_specs = [{"type": "original", "count": 1}]
            
        document_requirements.append({
            'id': req.id,
            'requirement_name': req.requirement_name,
            'description': req.description,
            'is_mandatory': prog_req.is_mandatory,
            'copy_specs': copy_specs,  # New: list of {type, count}
            'has_upload': has_upload,
            'upload': existing_uploads.get(req.id)
        })
    
    total_documents = len(document_requirements)
    upload_progress = round((uploaded_count / total_documents * 100)) if total_documents > 0 else 0
    
    return render_template('community/upload_documents.html',
                         application=application,
                         document_requirements=document_requirements,
                         mandatory_count=mandatory_count,
                         uploaded_count=uploaded_count,
                         total_documents=total_documents,
                         upload_progress=upload_progress)


def validate_and_process_image(file_path, max_size_mb=5):
    """
    Validate and optimize image files using Pillow
    Returns: (success, message, image_info)
    """
    try:
        # Open and validate the image
        with Image.open(file_path) as img:
            # Get original dimensions and format
            original_format = img.format
            original_size = os.path.getsize(file_path) / (1024 * 1024)  # Size in MB
            width, height = img.size
            
            image_info = {
                'format': original_format,
                'width': width,
                'height': height,
                'original_size_mb': round(original_size, 2)
            }
            
            # Check if image is too large (dimensions)
            max_dimension = 4096
            if width > max_dimension or height > max_dimension:
                # Resize while maintaining aspect ratio
                img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
                width, height = img.size
                
            # Optimize and compress if file is too large
            if original_size > max_size_mb:
                # Convert RGBA to RGB if saving as JPEG
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create white background
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
                
                # Save with optimization
                save_format = 'JPEG' if original_format in ['JPEG', 'JPG'] else original_format
                quality = 85  # Good balance between quality and size
                
                img.save(file_path, format=save_format, quality=quality, optimize=True)
                
                new_size = os.path.getsize(file_path) / (1024 * 1024)
                image_info['compressed'] = True
                image_info['new_size_mb'] = round(new_size, 2)
                image_info['width'] = width
                image_info['height'] = height
            
            return True, "Image validated and optimized", image_info
            
    except Exception as e:
        return False, f"Invalid image file: {str(e)}", None


def create_thumbnail(file_path, thumbnail_size=(300, 300)):
    """
    Create a thumbnail for the uploaded image
    Returns: thumbnail_path or None
    """
    try:
        # Generate thumbnail filename
        base, ext = os.path.splitext(file_path)
        thumbnail_path = f"{base}_thumb{ext}"
        
        # Create thumbnail
        with Image.open(file_path) as img:
            # Convert RGBA to RGB if needed
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode == 'RGBA':
                    background.paste(img, mask=img.split()[-1])
                    img = background
            
            # Create thumbnail
            img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)
            img.save(thumbnail_path, format='JPEG', quality=85, optimize=True)
            
        return thumbnail_path
        
    except Exception as e:
        print(f"Error creating thumbnail: {e}")
        return None


@community_bp.route('/applications/<int:application_id>/submit-documents', methods=['POST'])
@login_required
@role_required('community')
def submit_documents(application_id):
    """Handle document upload submission"""
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    # Check if online upload is enabled for this program
    if not application.program.allow_online_upload:
        flash('Online document upload is not available for this program.', 'warning')
        return redirect(url_for('community.application_workflow', application_id=application_id))
    
    try:
        # Get document requirements for this program
        program_requirements = db.session.query(
            Requirements,
            ProgramRequirements.is_mandatory
        ).join(
            ProgramRequirements,
            Requirements.id == ProgramRequirements.requirement_id
        ).filter(
            ProgramRequirements.program_id == application.program_id,
            Requirements.requirement_type == 'document'
        ).all()
        
        upload_count = 0
        
        # Create upload directory if it doesn't exist
        # Store as relative path for portability
        upload_dir_relative = os.path.join('static', 'uploads', 'application_documents', str(application_id))
        
        # Get absolute path for file operations
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        upload_dir_absolute = os.path.join(project_root, upload_dir_relative)
        os.makedirs(upload_dir_absolute, exist_ok=True)
        
        # Process each document requirement
        for req, is_mandatory in program_requirements:
            file_key = f'document_{req.id}'
            
            if file_key in request.files:
                file = request.files[file_key]
                
                if file and file.filename:
                    # Secure the filename
                    filename = secure_filename(file.filename)
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    unique_filename = f'{req.id}_{timestamp}_{filename}'
                    
                    # Store relative path in database, use absolute for file operations
                    file_path_relative = os.path.join(upload_dir_relative, unique_filename)
                    file_path_absolute = os.path.join(upload_dir_absolute, unique_filename)
                    
                    # Save the file temporarily
                    file.save(file_path_absolute)
                    
                    # Validate and process images using Pillow
                    file_type = file.content_type
                    is_image = file_type.startswith('image/')
                    
                    if is_image:
                        # Validate and optimize the image
                        success, message, image_info = validate_and_process_image(file_path_absolute)
                        
                        if not success:
                            # Invalid image, delete and skip
                            os.remove(file_path_absolute)
                            flash(f'Error with {req.requirement_name}: {message}', 'warning')
                            continue
                        
                        # Create thumbnail for preview
                        thumbnail_path = create_thumbnail(file_path_absolute)
                        
                        # Log image optimization
                        if image_info.get('compressed'):
                            flash(f'{req.requirement_name}: Image optimized from {image_info["original_size_mb"]}MB to {image_info["new_size_mb"]}MB', 'info')
                    
                    # Get final file info after processing
                    file_size = os.path.getsize(file_path_absolute)
                    
                    # Check if upload already exists for this requirement
                    existing_upload = ApplicationDocumentUploads.query.filter_by(
                        application_id=application_id,
                        requirement_id=req.id
                    ).first()
                    
                    if existing_upload:
                        # Delete old file if it exists
                        if existing_upload.file_path:
                            old_file_path = existing_upload.file_path
                            if not os.path.isabs(old_file_path):
                                old_file_path = os.path.join(project_root, old_file_path)
                            if os.path.exists(old_file_path):
                                os.remove(old_file_path)
                        
                        # Update existing upload with relative path
                        existing_upload.file_path = file_path_relative
                        existing_upload.original_filename = filename
                        existing_upload.file_size = file_size
                        existing_upload.file_type = file_type
                        existing_upload.verification_status = 'pending'
                        existing_upload.uploaded_at = datetime.utcnow()
                    else:
                        # Create new upload record with relative path
                        new_upload = ApplicationDocumentUploads(
                            application_id=application_id,
                            requirement_id=req.id,
                            file_path=file_path_relative,
                            original_filename=filename,
                            file_size=file_size,
                            file_type=file_type,
                            verification_status='pending'
                        )
                        db.session.add(new_upload)
                    
                    upload_count += 1
        
        # Check if all mandatory documents are uploaded
        mandatory_reqs = [req for req, is_mandatory in program_requirements if is_mandatory]
        uploaded_mandatory = ApplicationDocumentUploads.query.filter(
            ApplicationDocumentUploads.application_id == application_id,
            ApplicationDocumentUploads.requirement_id.in_([req.id for req in mandatory_reqs])
        ).count()
        
        # Update application document upload status
        if uploaded_mandatory >= len(mandatory_reqs):
            application.document_upload_status = 'uploaded'
            
            # Create notifications for all admin users
            admin_users = User.query.filter_by(role='admin').all()
            for admin in admin_users:
                admin_notification = Notifications(
                    user_id=admin.id,
                    notif_title='New Documents Uploaded',
                    notif_message=f'{current_user.first_name} {current_user.last_name} has uploaded documents for application #{application_id}',
                    is_read=False,
                    related_id=application_id,
                    related_type='application'
                )
                db.session.add(admin_notification)
            
            # Notify user
            user_notification = Notifications(
                user_id=current_user.id,
                notif_title='Documents Submitted for Review',
                notif_message=f'Your documents for {application.program.program_name} have been submitted. Our team will review them shortly.',
                is_read=False,
                related_id=application_id,
                related_type='application'
            )
            db.session.add(user_notification)
        
        # Log document upload activity
        if upload_count > 0:
            log_document_upload(application, upload_count, application.program.program_name)
        
        db.session.commit()
        
        if upload_count > 0:
            flash(f'{upload_count} document(s) uploaded successfully! Your documents will be reviewed by our team.', 'success')
        else:
            flash('No new documents were uploaded.', 'info')
        
        return redirect(url_for('community.application_workflow', application_id=application_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error uploading documents: {str(e)}', 'danger')
        return redirect(url_for('community.application_workflow', application_id=application_id))


@community_bp.route('/document-uploads/<int:upload_id>/view')
@login_required
def view_uploaded_document(upload_id):
    """View an uploaded document"""
    upload = ApplicationDocumentUploads.query.get_or_404(upload_id)
    
    # Security check: ensure user owns the application or is an admin
    if current_user.role != 'admin':
        if upload.application.user_id != current_user.id:
            flash('You do not have permission to view this document.', 'danger')
            return redirect(url_for('community.applications'))
    
    # Handle file path - stored paths are relative from project root
    file_path = upload.file_path.replace('\\', '/')  # Normalize path separators
    
    # If path is relative, make it absolute using app root
    if not os.path.isabs(file_path):
        file_path = os.path.join(current_app.root_path, file_path)
    
    # Normalize the path (handles .. and other path issues)
    file_path = os.path.normpath(file_path)
    
    # Check if file exists
    if not os.path.exists(file_path):
        print(f'Document file not found: {file_path}')
        print(f'Stored path: {upload.file_path}')
        print(f'App root: {current_app.root_path}')
        flash(f'Document file not found. Please contact support.', 'danger')
        return redirect(request.referrer or url_for('community.applications'))
    
    try:
        return send_file(
            file_path,
            as_attachment=False,
            download_name=upload.original_filename
        )
    except Exception as e:
        print(f'Error accessing document at {file_path}: {str(e)}')
        flash(f'Error accessing document: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('community.applications'))


@community_bp.route('/document-uploads/<int:upload_id>/view-data')
@login_required
def get_document_view_data(upload_id):
    """Get document URLs for viewing in modal"""
    try:
        upload = ApplicationDocumentUploads.query.get_or_404(upload_id)
        
        # Security check: ensure user owns the application or is an admin
        if current_user.role != 'admin':
            if upload.application.user_id != current_user.id:
                return jsonify({'success': False, 'message': 'Permission denied'}), 403
        
        # Handle file path - stored paths are relative from project root
        file_path = upload.file_path.replace('\\', '/')  # Normalize path separators
        
        # If path is relative, make it absolute using app root
        if not os.path.isabs(file_path):
            file_path = os.path.join(current_app.root_path, file_path)
        
        # Normalize the path
        file_path = os.path.normpath(file_path)
        
        # Check if file exists
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': 'Document file not found'}), 404
        
        # Generate view and download URLs
        view_url = url_for('community.view_uploaded_document', upload_id=upload_id)
        download_url = url_for('community.download_workflow_document', upload_id=upload_id)
        
        return jsonify({
            'success': True,
            'document_url': view_url,
            'download_url': download_url,
            'filename': upload.original_filename
        })
    
    except Exception as e:
        print(f'Error getting document view data: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@community_bp.route('/document-uploads/<int:upload_id>/download')
@login_required
def download_workflow_document(upload_id):
    """Download an uploaded document from workflow"""
    upload = ApplicationDocumentUploads.query.get_or_404(upload_id)
    
    # Security check: ensure user owns the application or is an admin
    if current_user.role != 'admin':
        if upload.application.user_id != current_user.id:
            flash('You do not have permission to download this document.', 'danger')
            return redirect(url_for('community.applications'))
    
    # Handle file path - stored paths are relative from project root
    file_path = upload.file_path.replace('\\', '/')  # Normalize path separators
    
    # If path is relative, make it absolute using app root
    if not os.path.isabs(file_path):
        file_path = os.path.join(current_app.root_path, file_path)
    
    # Normalize the path
    file_path = os.path.normpath(file_path)
    
    # Check if file exists
    if not os.path.exists(file_path):
        flash(f'Document file not found.', 'danger')
        return redirect(request.referrer or url_for('community.applications'))
    
    try:
        return send_file(
            file_path,
            as_attachment=True,
            download_name=upload.original_filename
        )
    except Exception as e:
        print(f'Error downloading document at {file_path}: {str(e)}')
        flash(f'Error downloading document: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('community.applications'))


@community_bp.route('/applications/<int:application_id>/upload-workflow-photo', methods=['POST'])
@login_required
@role_required('community')
def upload_workflow_photo(application_id):
    """Upload shelter photos from the workflow step interface (AJAX)"""
    try:
        application = Applications.query.filter_by(
            id=application_id,
            user_id=current_user.id
        ).first()
        
        if not application:
            return jsonify({'success': False, 'message': 'Application not found'}), 404
        
        # Check if file was uploaded
        if 'shelter_photo' not in request.files:
            return jsonify({'success': False, 'message': 'No file uploaded'}), 400
        
        file = request.files['shelter_photo']
        caption = request.form.get('caption', '').strip()
        
        if not file or file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'}), 400
        
        ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
        MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
        
        # Check file extension
        file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        if file_ext not in ALLOWED_EXTENSIONS:
            return jsonify({'success': False, 'message': f'Invalid file type. Allowed: {", ".join(ALLOWED_EXTENSIONS)}'}), 400
        
        # Check file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > MAX_FILE_SIZE:
            return jsonify({'success': False, 'message': 'File is too large. Maximum size is 5MB.'}), 400
        
        # Create upload directory
        try:
            upload_path = os.path.join(current_app.static_folder, 'uploads', 'shelter_photos', str(application_id))
            os.makedirs(upload_path, exist_ok=True)
            
            if not os.path.isdir(upload_path):
                return jsonify({'success': False, 'message': f'Failed to create upload directory: {upload_path}'}), 500
        except Exception as dir_error:
            return jsonify({'success': False, 'message': f'Directory creation error: {str(dir_error)}'}), 500
        
        # Secure filename and save
        try:
            filename = secure_filename(file.filename)
            if not filename:
                filename = 'photo.jpg'  # Fallback if secure_filename returns empty
            
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            unique_filename = f"{timestamp}_{filename}"
            file_path = os.path.join(upload_path, unique_filename)
            
            file.save(file_path)
            
            # Verify file was saved
            if not os.path.exists(file_path):
                return jsonify({'success': False, 'message': f'File was not saved successfully'}), 500
        except Exception as save_error:
            return jsonify({'success': False, 'message': f'File save error: {str(save_error)}'}), 500
        
        # Store relative path in database
        try:
            # Save to database - store path relative to static folder
            shelter_photo = ShelterPhotos(
                application_id=application_id,
                photo_path=f'uploads/shelter_photos/{application_id}/{unique_filename}',
                caption=caption,
                verification_status='pending'
            )
            db.session.add(shelter_photo)
            db.session.flush()  # Get the ID without committing yet
            
            # Update workflow step status to in_progress if not already
            photo_upload_step = ProgramWorkflowSteps.query.filter_by(
                program_id=application.program_id,
                step_type='photo_upload'
            ).first()
            
            if photo_upload_step:
                workflow_status = ApplicationWorkflowStatus.query.filter_by(
                    application_id=application_id,
                    workflow_step_id=photo_upload_step.id
                ).first()
                
                if workflow_status and workflow_status.step_status == 'not_started':
                    workflow_status.step_status = 'in_progress'
                    workflow_status.started_at = datetime.utcnow()
                    workflow_status.updated_at = datetime.utcnow()
            
            db.session.commit()
        except Exception as db_error:
            db.session.rollback()
            # Try to clean up the saved file
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except:
                pass
            return jsonify({'success': False, 'message': f'Database error: {str(db_error)}'}), 500
        
        # Get updated photo count
        try:
            total_photos = ShelterPhotos.query.filter_by(application_id=application_id).count()
        except Exception as count_error:
            return jsonify({'success': False, 'message': f'Error counting photos: {str(count_error)}'}), 500
        
        return jsonify({
            'success': True,
            'message': f'Photo uploaded successfully! ({total_photos} total)',
            'photo': {
                'id': shelter_photo.id,
                'photo_path': '/' + shelter_photo.photo_path,
                'caption': shelter_photo.caption,
                'verification_status': shelter_photo.verification_status
            },
            'total_photos': total_photos,
            'has_min_photos': total_photos >= 3
        })
        
    except Exception as e:
        db.session.rollback()
        import traceback
        error_msg = f'Upload error: {str(e)}'
        print(f'Photo upload traceback: {traceback.format_exc()}')
        return jsonify({'success': False, 'message': error_msg}), 500


@community_bp.route('/applications/<int:application_id>/delete-workflow-photo/<int:photo_id>', methods=['POST'])
@login_required
@role_required('community')
def delete_workflow_photo(application_id, photo_id):
    """Delete a shelter photo from workflow (AJAX)"""
    photo = ShelterPhotos.query.get_or_404(photo_id)
    
    # Verify ownership
    if photo.application.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403
    
    # Only allow deletion if not approved
    if photo.verification_status == 'approved':
        return jsonify({'success': False, 'message': 'Cannot delete an approved photo'}), 400
    
    try:
        # Delete file from filesystem
        # Convert relative path to absolute path
        file_path = photo.photo_path
        if not os.path.isabs(file_path):
            file_path = os.path.join(current_app.root_path, file_path)
        
        if os.path.exists(file_path):
            os.remove(file_path)
        
        db.session.delete(photo)
        db.session.commit()
        
        # Get updated count
        total_photos = ShelterPhotos.query.filter_by(application_id=application_id).count()
        
        return jsonify({
            'success': True,
            'message': 'Photo deleted successfully',
            'total_photos': total_photos,
            'has_min_photos': total_photos >= 3
        })
        
    except Exception as e:
        db.session.rollback()
        import traceback
        print(f'Delete photo traceback: {traceback.format_exc()}')
        return jsonify({'success': False, 'message': f'Error deleting photo: {str(e)}'}), 500


@community_bp.route('/applications/<int:application_id>/submit-workflow-step', methods=['POST'])
@login_required
@role_required('community')
def submit_workflow_step(application_id):
    """Submit a workflow step for admin review"""
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    data = request.get_json()
    step_id = data.get('step_id')
    
    if not step_id:
        return jsonify({'success': False, 'message': 'Step ID is required'})
    
    # Get workflow status
    workflow_status = ApplicationWorkflowStatus.query.filter_by(
        application_id=application_id,
        workflow_step_id=step_id
    ).first()
    
    if not workflow_status:
        return jsonify({'success': False, 'message': 'Workflow status not found'})
    
    # Validate photo_upload step type - must have minimum 3 photos
    workflow_step = ProgramWorkflowSteps.query.get(step_id)
    if workflow_step and workflow_step.step_type == 'photo_upload':
        photo_count = ShelterPhotos.query.filter_by(application_id=application_id).count()
        if photo_count < 3:
            return jsonify({
                'success': False, 
                'message': f'Please upload at least 3 shelter photos before submitting. Currently uploaded: {photo_count}'
            })
    
    # Update status to pending review
    workflow_status.step_status = 'pending_review'
    workflow_status.completed_at = datetime.utcnow()
    workflow_status.updated_at = datetime.utcnow()
    
    try:
        db.session.commit()
        
        # Create notification for admins
        from app.models import Notifications
        
        admin_users = User.query.filter_by(role='admin').all()
        for admin in admin_users:
            notification = Notifications(
                user_id=admin.id,
                notif_title=f'Workflow Step Submitted - {application.program.program_name}',
                notif_message=f'User {current_user.first_name} {current_user.last_name} has completed a workflow step for Application #{application_id}.',
                is_read=False,
                related_id=application_id,
                related_type='application'
            )
            db.session.add(notification)
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Step submitted successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


@community_bp.route('/upload-workflow-document', methods=['POST'])
@login_required
@role_required('community')
def upload_workflow_document():
    """Upload document for current workflow step"""
    file_path = None
    try:
        application_id = request.form.get('application_id')
        requirement_id = request.form.get('requirement_id')
        
        if not application_id or not requirement_id:
            return jsonify({'success': False, 'message': 'Missing required parameters'}), 400
        
        application = Applications.query.filter_by(
            id=application_id,
            user_id=current_user.id
        ).first()
        
        if not application:
            return jsonify({'success': False, 'message': 'Application not found'}), 404
        
        # Check if file was uploaded
        if 'document' not in request.files:
            return jsonify({'success': False, 'message': 'No file uploaded'}), 400
        
        file = request.files['document']
        if not file or file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'}), 400
        
        # Validate file type
        allowed_extensions = {'pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx'}
        file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        
        if file_ext not in allowed_extensions:
            return jsonify({'success': False, 'message': f'Invalid file type. Allowed: {", ".join(allowed_extensions)}'}), 400
        
        # Check file size (10MB limit for documents)
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        MAX_DOCUMENT_SIZE = 10 * 1024 * 1024  # 10MB
        if file_size > MAX_DOCUMENT_SIZE:
            return jsonify({'success': False, 'message': 'File is too large. Maximum size is 10MB.'}), 400
        
        # Create upload directory
        try:
            upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'application_documents')
            os.makedirs(upload_dir, exist_ok=True)
            
            if not os.path.isdir(upload_dir):
                return jsonify({'success': False, 'message': f'Failed to create upload directory'}), 500
        except Exception as dir_error:
            return jsonify({'success': False, 'message': f'Directory creation error: {str(dir_error)}'}), 500
        
        # Generate unique filename
        try:
            filename = secure_filename(file.filename)
            if not filename:
                filename = f'document.{file_ext}'  # Fallback if secure_filename returns empty
            
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            unique_filename = f'{application_id}_{requirement_id}_{timestamp}_{filename}'
            file_path = os.path.join(upload_dir, unique_filename)
            
            # Save file
            file.save(file_path)
            
            # Verify file was saved
            if not os.path.exists(file_path):
                return jsonify({'success': False, 'message': 'File was not saved successfully'}), 500
        except Exception as save_error:
            return jsonify({'success': False, 'message': f'File save error: {str(save_error)}'}), 500
        
        # Database operations
        try:
            # Remove existing upload for this requirement if exists
            existing_upload = ApplicationDocumentUploads.query.filter_by(
                application_id=application_id,
                requirement_id=requirement_id
            ).first()
            
            if existing_upload:
                # Remove old file
                try:
                    old_file_path = existing_upload.file_path
                    if not old_file_path.startswith('/'):
                        old_file_path = os.path.join(current_app.root_path, old_file_path)
                    if os.path.exists(old_file_path):
                        os.remove(old_file_path)
                except Exception as cleanup_error:
                    print(f'Error cleaning up old file: {cleanup_error}')
                
                db.session.delete(existing_upload)
                db.session.flush()
            
            # Store relative path in database
            relative_path = os.path.join('static', 'uploads', 'application_documents', unique_filename)
            
            # Create new upload record
            upload = ApplicationDocumentUploads(
                application_id=application_id,
                requirement_id=requirement_id,
                file_path=relative_path.replace('\\', '/'),
                original_filename=filename,
                uploaded_at=datetime.utcnow(),
                verification_status='pending'
            )
            
            db.session.add(upload)
            db.session.commit()
        except Exception as db_error:
            db.session.rollback()
            # Clean up saved file on database error
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
            except:
                pass
            return jsonify({'success': False, 'message': f'Database error: {str(db_error)}'}), 500
        
        return jsonify({'success': True, 'message': 'Document uploaded successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        # Clean up file on any error
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except:
            pass
        import traceback
        print(f'Document upload traceback: {traceback.format_exc()}')
        return jsonify({'success': False, 'message': f'Upload error: {str(e)}'}), 500


@community_bp.route('/applications/<int:application_id>/start-workflow-step/<int:step_id>', methods=['POST'])
@login_required
@role_required('community')
def start_workflow_step(application_id, step_id):
    """Start working on a workflow step"""
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    # Get workflow status
    workflow_status = ApplicationWorkflowStatus.query.filter_by(
        application_id=application_id,
        workflow_step_id=step_id
    ).first()
    
    if not workflow_status:
        return jsonify({'success': False, 'message': 'Workflow status not found'})
    
    # Update status to in_progress
    workflow_status.step_status = 'in_progress'
    workflow_status.started_at = datetime.utcnow()
    workflow_status.updated_at = datetime.utcnow()
    
    try:
        db.session.commit()
        return jsonify({'success': True, 'message': 'Step started successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})
