from flask import render_template, jsonify, redirect, url_for, request, flash, send_file, session
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, or_, func
from app.admin import admin_bp
from app.utils import role_required
from app.models import Programs, Requirements, ProgramRequirements, Applications, ApplicationDocuments, Notifications, User, CommunityUsers, ShelterPhotos, ApplicationDocumentUploads, ApplicationWorkflowStatus, ProgramWorkflowSteps, Assessment, AssessmentDocument
from app.extensions import db
from app.activity_logger import log_application_status_update, log_bulk_application_status_update, log_document_verification, log_document_status_toggle, log_beneficiaries_list_generated
import re
from PIL import Image, ImageDraw, ImageFont
import io


def check_qualification(requirement, user_profile):
    """Check if user meets a qualification requirement"""
    if not user_profile:
        return False
    
    req_name = requirement.requirement_name.lower()
    req_desc = requirement.description.lower() if requirement.description else ''
    combined = req_name + ' ' + req_desc
    
    # Age-based qualifications
    if 'age' in combined or 'years old' in combined or 'senior' in combined:
        if user_profile.age:
            if 'senior' in combined or '60' in combined:
                return user_profile.age >= 60
            elif '18' in combined:
                return user_profile.age >= 18
            # Check for age range patterns
            age_match = re.search(r'(\d+)[-\s](?:to|and)[-\s](\d+)', combined)
            if age_match:
                min_age, max_age = int(age_match.group(1)), int(age_match.group(2))
                return min_age <= user_profile.age <= max_age
    
    # Employment status
    if 'employed' in combined or 'employment' in combined:
        return user_profile.is_currently_employed
    
    # Student status
    if 'student' in combined:
        return user_profile.is_student
    
    # Solo parent
    if 'solo parent' in combined or 'single parent' in combined:
        return user_profile.is_solo_parent
    
    # PWD status
    if 'pwd' in combined or 'disability' in combined or 'disabled' in combined:
        return user_profile.is_pwd
    
    # Location-based
    if 'resident' in combined or 'barangay' in combined or 'mabitac' in combined:
        return user_profile.barangay is not None
    
    # Income-based
    if 'income' in combined or 'indigent' in combined or 'poverty' in combined:
        if user_profile.family_annual_income:
            # Assuming low income threshold is 250,000 PHP per year
            if 'low income' in combined or 'indigent' in combined:
                return user_profile.family_annual_income <= 20000
    
    # Default: unable to determine
    return None


def check_all_qualifications(application):
    """
    Check if an applicant meets all qualification requirements for a program.
    Returns: (meets_all: bool, met_requirements: list, unmet_requirements: list)
    """
    program = application.program
    user = application.applicant
    user_profile = user.community_profile if user else None
    
    met_requirements = []
    unmet_requirements = []
    
    # Get all qualification requirements for the program
    program_requirements = ProgramRequirements.query.filter_by(
        program_id=program.id
    ).join(Requirements).filter(
        Requirements.requirement_type == 'qualification',
        ProgramRequirements.is_mandatory == True
    ).all()
    
    for prog_req in program_requirements:
        requirement = prog_req.requirement
        result = check_qualification(requirement, user_profile)
        
        if result is True:
            met_requirements.append(requirement.requirement_name)
        elif result is False:
            unmet_requirements.append(requirement.requirement_name)
        # If None, we can't determine - treat as met (benefit of doubt)
        else:
            met_requirements.append(f"{requirement.requirement_name} (unverified)")
    
    meets_all = len(unmet_requirements) == 0
    return meets_all, met_requirements, unmet_requirements


@admin_bp.route('/applications')
@login_required
@role_required('admin')
def applications():
    """Display all applications with filters"""
    page = request.args.get('page', 1, type=int)
    per_page = 15
    
    # Get filter parameters
    status_filter = request.args.get('status', '').strip()
    program_filter = request.args.get('program', '').strip()
    search = request.args.get('search', '').strip()
    date_range = request.args.get('date_range', '').strip()
    
    # Base query
    query = Applications.query
    
    # Apply status filter
    if status_filter:
        query = query.filter_by(application_status=status_filter)
    
    # Apply program filter
    if program_filter:
        query = query.filter_by(program_id=int(program_filter))
    
    # Apply search filter (search by applicant name or email)
    if search:
        query = query.join(User).filter(
            or_(
                User.first_name.contains(search),
                User.last_name.contains(search),
                User.email.contains(search)
            )
        )
    
    # Apply date range filter
    if date_range:
        today = datetime.utcnow()
        if date_range == 'today':
            start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.filter(Applications.application_date >= start_date)
        elif date_range == 'week':
            start_date = today - timedelta(days=7)
            query = query.filter(Applications.application_date >= start_date)
        elif date_range == 'month':
            start_date = today - timedelta(days=30)
            query = query.filter(Applications.application_date >= start_date)
    
    # Order by application date (newest first)
    query = query.order_by(desc(Applications.application_date))
    
    # Paginate results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Check qualification requirements for each application
    for app in pagination.items:
        # Get qualification requirements for this program
        qualification_reqs = db.session.query(Requirements).join(
            ProgramRequirements,
            (Requirements.id == ProgramRequirements.requirement_id) &
            (ProgramRequirements.program_id == app.program_id)
        ).filter(Requirements.requirement_type == 'qualification').all()
        
        # Get user profile
        user_profile = app.applicant.community_profile
        
        # Check if user meets all qualifications
        app.total_qualifications = len(qualification_reqs)
        app.met_qualifications = 0
        app.unknown_qualifications = 0
        
        if not qualification_reqs:
            # No qualifications required
            app.meets_all_qualifications = None
        elif not user_profile:
            # No profile data available
            app.meets_all_qualifications = False
        else:
            # Check each qualification
            for req in qualification_reqs:
                result = check_qualification(req, user_profile)
                if result is True:
                    app.met_qualifications += 1
                elif result is None:
                    app.unknown_qualifications += 1
            
            # User meets all qualifications if they met all checkable ones
            # and there are no unknown/undetermined qualifications
            if app.unknown_qualifications == 0:
                app.meets_all_qualifications = (app.met_qualifications == app.total_qualifications)
            else:
                # Some qualifications couldn't be determined
                app.meets_all_qualifications = False if app.met_qualifications < app.total_qualifications else True
    
    # Get statistics
    total_apps = Applications.query.count()
    pending_apps = Applications.query.filter_by(application_status='pending').count()
    approved_apps = Applications.query.filter_by(application_status='approved').count()
    rejected_apps = Applications.query.filter_by(application_status='rejected').count()
    active_apps = Applications.query.filter_by(application_status='active').count()
    completed_apps = Applications.query.filter_by(application_status='completed').count()
    
    # Get all programs for filter dropdown
    programs = Programs.query.filter_by(is_active=True).order_by(Programs.program_name).all()
    
    return render_template(
        'admin/adm_applications.html',
        applications=pagination.items,
        pagination=pagination,
        total_apps=total_apps,
        pending_apps=pending_apps,
        approved_apps=approved_apps,
        rejected_apps=rejected_apps,
        active_apps=active_apps,
        completed_apps=completed_apps,
        programs=programs,
        user=current_user
    )


@admin_bp.route('/applications/<int:application_id>')
@login_required
@role_required('admin')
def view_application(application_id):
    """View detailed application information"""
    application = Applications.query.get_or_404(application_id)
    
    # Get program-specific requirements with their application document status
    # Join ProgramRequirements with Requirements and left join with ApplicationDocuments
    program_requirements = db.session.query(
        ProgramRequirements,
        Requirements,
        ApplicationDocuments
    ).join(
        Requirements, ProgramRequirements.requirement_id == Requirements.id
    ).outerjoin(
        ApplicationDocuments,
        db.and_(
            ApplicationDocuments.application_id == application_id,
            ApplicationDocuments.requirement_id == Requirements.id
        )
    ).filter(
        ProgramRequirements.program_id == application.program_id
    ).order_by(
        ProgramRequirements.is_mandatory.desc(),
        Requirements.requirement_name
    ).all()
    
    # Get applicant's community profile for qualification checking
    applicant = application.applicant
    community_profile = CommunityUsers.query.filter_by(user_id=applicant.id).first()
    
    # Helper function to check if applicant meets a qualification
    def check_qualification(qual_name, community_profile):
        """Check if applicant meets the qualification requirement"""
        if not community_profile:
            return False
        
        qual_name_lower = qual_name.lower()
        
        # Check student status
        if 'student' in qual_name_lower:
            return community_profile.is_student
        
        # Check solo parent status
        if 'solo parent' in qual_name_lower:
            return community_profile.is_solo_parent
        
        # Check PWD status (would need PWD field in model)
        if 'pwd' in qual_name_lower or 'disability' in qual_name_lower:
            # If you have a PWD field: return community_profile.is_pwd
            return False  # Default to False if field doesn't exist
        
        # Check senior citizen (60+)
        if 'senior' in qual_name_lower:
            return community_profile.age >= 60 if community_profile.age else False
        
        # Check low income family (below 200k annual)
        if 'low income' in qual_name_lower or 'indigent' in qual_name_lower:
            if community_profile.family_annual_income:
                return community_profile.family_annual_income < 20000
            return False
        
        # Check residency
        if 'resident' in qual_name_lower and 'mabitac' in qual_name_lower:
            return community_profile.municipality and 'mabitac' in community_profile.municipality.lower()
        
        # Check disaster victims (would need additional tracking)
        if 'fire victim' in qual_name_lower or 'typhoon victim' in qual_name_lower:
            # This would require additional fields or tables to track disaster victims
            return None  # Return None for unknown/manual verification needed
        
        # Check family member of deceased (for burial assistance)
        if 'deceased' in qual_name_lower or 'family member' in qual_name_lower:
            return None  # Requires manual verification
        
        # Check medical emergency
        if 'medical emergency' in qual_name_lower:
            return None  # Requires manual verification
        
        # Default: return None for manual verification
        return None
    
    # Format requirements for template - separate documents from qualifications
    document_requirements = []
    qualification_requirements = []
    
    for prog_req, requirement, app_doc in program_requirements:
        # Base requirement info
        req_info = {
            'requirement_id': requirement.id,
            'requirement_name': requirement.requirement_name,
            'requirement_type': requirement.requirement_type,
            'is_mandatory': prog_req.is_mandatory,
            'description': requirement.description
        }
        
        if requirement.requirement_type == 'document':
            # Document requirements - include verification fields
            if app_doc is None:
                doc_info = {
                    **req_info,
                    'id': None,
                    'submission_status': 'not_submitted',
                    'admin_feedback': None,
                    'notes': None,
                    'verified_at': None,
                    'verified_by': None,
                    'file_path': None,
                    'file_name': None,
                    'uploaded_at': None
                }
            else:
                doc_info = {
                    **req_info,
                    'id': app_doc.id,
                    'submission_status': app_doc.submission_status,
                    'admin_feedback': app_doc.admin_feedback,
                    'notes': app_doc.notes,
                    'verified_at': app_doc.verified_at,
                    'verified_by': app_doc.verified_by,
                    'file_path': getattr(app_doc, 'file_path', None),
                    'file_name': getattr(app_doc, 'file_name', None),
                    'uploaded_at': getattr(app_doc, 'uploaded_at', None)
                }
            document_requirements.append(doc_info)
        else:
            # Qualification requirements - check if applicant meets them
            is_qualified = check_qualification(requirement.requirement_name, community_profile)
            req_info['is_qualified'] = is_qualified  # True, False, or None (manual verification needed)
            qualification_requirements.append(req_info)
    
    from datetime import timedelta
    
    # Get uploaded documents for this application
    uploaded_documents = db.session.query(
        ApplicationDocumentUploads,
        Requirements
    ).join(
        Requirements,
        ApplicationDocumentUploads.requirement_id == Requirements.id
    ).filter(
        ApplicationDocumentUploads.application_id == application_id
    ).all()
    
    # Map uploaded documents by requirement_id for easy lookup
    uploads_by_requirement = {upload.requirement_id: upload for upload, _ in uploaded_documents}
    
    # Organize content by workflow steps
    workflow_steps_data = []
    workflow_steps_json = []
    if application.program.workflow_steps:
        import json
        
        # Get all workflow steps sorted by order
        workflow_steps = sorted(application.program.workflow_steps, key=lambda x: x.step_order)
        
        for step in workflow_steps:
            # Serialize step object to dictionary
            step_dict = {
                'id': step.id,
                'step_name': step.step_name,
                'step_type': step.step_type,
                'step_order': step.step_order,
                'description': step.step_description,
                'config_data': step.config_data if hasattr(step, 'config_data') else {}
            }
            
            step_data = {
                'step': step_dict,
                'documents': [],
                'uploads': [],
                'requirements': []
            }
            
            # Get step configuration to find associated requirements
            step_config = step.config_data if hasattr(step, 'config_data') else {}
            required_docs = step_config.get('required_documents', []) if step_config else []
            
            # If step has specific document requirements, filter by those
            if required_docs:
                # Match documents by requirement ID or name
                for doc_req in document_requirements:
                    if (doc_req['requirement_id'] in required_docs or 
                        doc_req['requirement_name'].lower() in [req.lower() for req in required_docs]):
                        step_data['documents'].append(doc_req)
                        
                        # Add corresponding uploads
                        if doc_req['requirement_id'] in uploads_by_requirement:
                            upload_obj = uploads_by_requirement[doc_req['requirement_id']]
                            # Serialize upload object to dictionary
                            upload_dict = {
                                'id': upload_obj.id,
                                'file_name': upload_obj.original_filename,
                                'file_path': upload_obj.file_path,
                                'uploaded_at': upload_obj.uploaded_at.isoformat() if upload_obj.uploaded_at else None,
                                'requirement_id': upload_obj.requirement_id,
                                'file_size': getattr(upload_obj, 'file_size', None)
                            }
                            step_data['uploads'].append(upload_dict)
            else:
                # For steps without specific document config, show based on step type
                if step.step_type in ['document_upload', 'document_submission']:
                    # Show all document requirements for this step
                    step_data['documents'] = document_requirements.copy()
                    # Serialize uploads
                    for upload_obj in uploads_by_requirement.values():
                        upload_dict = {
                            'id': upload_obj.id,
                            'file_name': upload_obj.original_filename,
                            'file_path': upload_obj.file_path,
                            'uploaded_at': upload_obj.uploaded_at.isoformat() if upload_obj.uploaded_at else None,
                            'requirement_id': upload_obj.requirement_id,
                            'file_size': getattr(upload_obj, 'file_size', None)
                        }
                        step_data['uploads'].append(upload_dict)
                elif step.step_type == 'approval':
                    # Show qualification requirements for approval steps (already serialized)
                    step_data['requirements'] = qualification_requirements.copy()
                elif step.step_type == 'assessment':
                    # Fetch assessments linked to this application
                    from sqlalchemy.orm import joinedload
                    app_assessments = Assessment.query.options(
                        joinedload(Assessment.documents)
                    ).filter_by(
                        application_id=application_id
                    ).order_by(Assessment.created_at.desc()).all()
                    step_data['assessments'] = [{
                        'id': a.id,
                        'assessment_type': a.assessment_type,
                        'title': a.title,
                        'status': a.status,
                        'scheduled_date': a.scheduled_date.strftime('%b %d, %Y') if a.scheduled_date else None,
                        'scheduled_time': a.scheduled_time,
                        'completed_at': a.completed_at.strftime('%b %d, %Y') if a.completed_at else None,
                        'document_count': len(a.documents),
                    } for a in app_assessments]
            
            workflow_steps_data.append(step_data)
        
        # Extract just the step information for JSON serialization in template
        workflow_steps_json = [step_data['step'] for step_data in workflow_steps_data]
    
    # Calculate date values for deadline picker
    today = datetime.utcnow()
    min_date = (today + timedelta(days=1)).strftime('%Y-%m-%d')
    default_deadline = (today + timedelta(days=30)).strftime('%Y-%m-%d')
    
    # Get workflow status for this application
    workflow_status = ApplicationWorkflowStatus.query.filter_by(
        application_id=application_id
    ).all()
    
    return render_template(
        'admin/view_application.html',
        application=application,
        document_requirements=document_requirements,
        qualification_requirements=qualification_requirements,
        uploads_by_requirement=uploads_by_requirement,
        workflow_steps_data=workflow_steps_data,
        workflow_steps_json=workflow_steps_json,
        workflow_status=workflow_status,
        min_date=min_date,
        default_deadline=default_deadline,
        datetime=datetime,
        user=current_user
    )


@admin_bp.route('/applications/<int:application_id>/update-status', methods=['POST'])
@login_required
@role_required('admin')
def update_application_status(application_id):
    """Update application status (approve, reject, hold)"""
    application = Applications.query.get_or_404(application_id)
    
    new_status = request.form.get('status')  # 'pending', 'approved', 'rejected', 'active', 'completed'
    remarks = request.form.get('remarks', '').strip()
    submission_deadline = request.form.get('submission_deadline', '').strip()
    
    if new_status not in ['pending', 'approved', 'rejected', 'active', 'completed']:
        return jsonify(success=False, message='Invalid status'), 400
    
    try:
        # Update application
        old_status = application.application_status
        application.application_status = new_status
        application.remarks = remarks
        application.reviewed_by = current_user.id
        application.review_date = datetime.utcnow()
        application.updated_at = datetime.utcnow()
        
        # Set submission deadline if status is approved and deadline is provided
        if new_status == 'approved' and submission_deadline:
            try:
                deadline_date = datetime.strptime(submission_deadline, '%Y-%m-%d')
                application.submission_deadline = deadline_date
            except ValueError:
                flash('Invalid deadline date format.', 'warning')
        
        # Update workflow status based on application status change
        if application.program.workflow_steps:
            workflow_steps = sorted(application.program.workflow_steps, key=lambda x: x.step_order)
            
            if new_status == 'approved':
                # Mark approval steps as completed
                for step in workflow_steps:
                    if step.step_type == 'approval' and step.is_pre_approval:
                        workflow_status = ApplicationWorkflowStatus.query.filter_by(
                            application_id=application_id,
                            workflow_step_id=step.id
                        ).first()
                        if workflow_status:
                            workflow_status.step_status = 'approved'
                            workflow_status.completed_at = datetime.utcnow()
                            workflow_status.reviewed_by = current_user.id
                            workflow_status.updated_at = datetime.utcnow()
            
            elif new_status == 'active':
                # Mark initial steps as completed, enable document submission
                for step in workflow_steps:
                    workflow_status = ApplicationWorkflowStatus.query.filter_by(
                        application_id=application_id,
                        workflow_step_id=step.id
                    ).first()
                    if workflow_status:
                        if step.step_type in ['approval', 'verification'] and step.step_order < 3:
                            workflow_status.step_status = 'approved'
                            workflow_status.completed_at = datetime.utcnow()
                        elif step.step_type == 'document_submission':
                            workflow_status.step_status = 'in_progress'
                            workflow_status.started_at = datetime.utcnow()
                        workflow_status.updated_at = datetime.utcnow()
            
            elif new_status == 'completed':
                # Mark all steps as completed
                for step in workflow_steps:
                    workflow_status = ApplicationWorkflowStatus.query.filter_by(
                        application_id=application_id,
                        workflow_step_id=step.id
                    ).first()
                    if workflow_status and workflow_status.step_status != 'approved':
                        workflow_status.step_status = 'completed'
                        workflow_status.completed_at = datetime.utcnow()
                        workflow_status.updated_at = datetime.utcnow()
            
            elif new_status == 'rejected':
                # Mark current step as rejected
                for step in workflow_steps:
                    workflow_status = ApplicationWorkflowStatus.query.filter_by(
                        application_id=application_id,
                        workflow_step_id=step.id
                    ).first()
                    if workflow_status and workflow_status.step_status in ['in_progress', 'pending_review']:
                        workflow_status.step_status = 'rejected'
                        workflow_status.reviewed_at = datetime.utcnow()
                        workflow_status.reviewed_by = current_user.id
                        workflow_status.updated_at = datetime.utcnow()
                        break
        
        # Create notification for applicant
        if new_status == 'approved':
            deadline_text = f" Please submit all required documents by {application.submission_deadline.strftime('%B %d, %Y')} to complete your application." if application.submission_deadline else ""
            notif_message = f'Your application for {application.program.program_name} has been approved! You can now download your application slip and submit the required documents at the MSWD Office.{deadline_text}'
        else:
            status_messages = {
                'rejected': f'Your application for {application.program.program_name} has been rejected. Please check the remarks for more information.',
                'active': f'Your application for {application.program.program_name} is now active. Please proceed with the required steps.',
                'pending': f'Your application for {application.program.program_name} status has been updated to pending.',
                'completed': f'Your application for {application.program.program_name} has been completed and is ready for release/claiming.'
            }
            notif_message = status_messages.get(new_status, 'Your application status has been updated.')
        
        notification = Notifications(
            user_id=application.user_id,
            notif_title=f'Application Status Update',
            notif_message=notif_message,
            is_read=False,
            related_id=application.id,
            related_type='application',
            created_at=datetime.utcnow()
        )
        
        db.session.add(notification)
        
        # Log activity
        log_application_status_update(application, old_status, new_status, remarks)
        
        db.session.commit()
        
        flash(f'Application status updated to {new_status.replace("_", " ").title()}.', 'success')
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=True, status=new_status, message='Status updated successfully')
        
        return redirect(url_for('admin.view_application', application_id=application_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating application status: {str(e)}', 'danger')
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message=str(e)), 500
        
        return redirect(url_for('admin.view_application', application_id=application_id))


@admin_bp.route('/applications/bulk-approve', methods=['POST'])
@login_required
@role_required('admin')
def bulk_approve_applications():
    """Approve multiple applications at once - checks qualification requirements"""
    try:
        data = request.get_json()
        application_ids = data.get('application_ids', [])
        
        if not application_ids:
            return jsonify(success=False, message='No applications selected'), 400
        
        approved_count = 0
        rejected_count = 0
        errors = []
        undo_data = []  # Store data for undo
        notification_ids = []  # Track created notifications
        unqualified_applicants = []  # Track applicants who don't meet qualifications
        
        for app_id in application_ids:
            try:
                application = Applications.query.get(app_id)
                
                if not application:
                    errors.append(f'Application #{app_id} not found')
                    continue
                
                if application.application_status != 'pending':
                    errors.append(f'Application #{app_id} is not pending')
                    continue
                
                # Check if applicant meets all qualification requirements
                meets_all, met_reqs, unmet_reqs = check_all_qualifications(application)
                
                # Store previous state for undo
                undo_data.append({
                    'id': application.id,
                    'previous_status': application.application_status,
                    'previous_reviewed_by': application.reviewed_by,
                    'previous_review_date': application.review_date.isoformat() if application.review_date else None,
                    'user_id': application.user_id,
                    'program_name': application.program.program_name
                })
                
                if meets_all:
                    # Approve the application
                    application.application_status = 'approved'
                    application.reviewed_by = current_user.id
                    application.review_date = datetime.utcnow()
                    application.updated_at = datetime.utcnow()
                    
                    # Create notification for approved applicant
                    notification = Notifications(
                        user_id=application.user_id,
                        notif_title='Application Approved',
                        notif_message=f'Your application for {application.program.program_name} has been approved! You can now download your application slip and submit the required documents at the MSWD Office.',
                        is_read=False,
                        related_id=application.id,
                        related_type='application',
                        created_at=datetime.utcnow()
                    )
                    
                    db.session.add(notification)
                    db.session.flush()
                    notification_ids.append(notification.id)
                    approved_count += 1
                else:
                    # Reject - does not meet all qualifications
                    application.application_status = 'rejected'
                    application.reviewed_by = current_user.id
                    application.review_date = datetime.utcnow()
                    application.updated_at = datetime.utcnow()
                    application.remarks = f"Does not meet qualification requirements: {', '.join(unmet_reqs)}"
                    
                    # Create notification for rejected applicant
                    notification = Notifications(
                        user_id=application.user_id,
                        notif_title='Application Rejected',
                        notif_message=f'Your application for {application.program.program_name} has been rejected. Some qualification requirements were not met. Please check the remarks for details.',
                        is_read=False,
                        related_id=application.id,
                        related_type='application',
                        created_at=datetime.utcnow()
                    )
                    
                    db.session.add(notification)
                    db.session.flush()
                    notification_ids.append(notification.id)
                    rejected_count += 1
                    
                    # Track for admin notification
                    applicant_name = f"{application.applicant.first_name} {application.applicant.last_name}"
                    unqualified_applicants.append({
                        'app_id': application.id,
                        'name': applicant_name,
                        'program': application.program.program_name,
                        'unmet_requirements': unmet_reqs
                    })
                
            except Exception as e:
                errors.append(f'Error processing application #{app_id}: {str(e)}')
                continue
        
        # Notify all admins about unqualified applicants
        if unqualified_applicants:
            admin_users = User.query.filter_by(role='admin').all()
            
            # Build notification message
            unqualified_summary = []
            for uq in unqualified_applicants[:5]:  # Limit to first 5 in message
                unqualified_summary.append(f"• {uq['name']} (#{uq['app_id']}) - Missing: {', '.join(uq['unmet_requirements'][:2])}")
            
            summary_text = '\n'.join(unqualified_summary)
            if len(unqualified_applicants) > 5:
                summary_text += f"\n... and {len(unqualified_applicants) - 5} more"
            
            for admin in admin_users:
                admin_notification = Notifications(
                    user_id=admin.id,
                    notif_title='Applicants Rejected - Unqualified',
                    notif_message=f'{len(unqualified_applicants)} applicant(s) do not meet all qualification requirements and have been rejected:\n{summary_text}',
                    is_read=False,
                    related_type='admin_alert',
                    created_at=datetime.utcnow()
                )
                db.session.add(admin_notification)
        
        db.session.commit()
        
        # Store undo data in session
        if undo_data:
            session['bulk_approval_undo'] = {
                'undo_data': undo_data,
                'notification_ids': notification_ids,
                'timestamp': datetime.utcnow().isoformat()
            }
        
        message = f'Processed {len(application_ids)} application(s): {approved_count} approved, {rejected_count} rejected (did not meet qualifications).'
        if errors:
            message += f' {len(errors)} error(s): ' + '; '.join(errors[:3])
        
        return jsonify(
            success=True,
            approved_count=approved_count,
            rejected_count=rejected_count,
            message=message,
            errors=errors,
            unqualified_count=len(unqualified_applicants),
            can_undo=len(undo_data) > 0
        )
        
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error: {str(e)}'), 500


@admin_bp.route('/applications/bulk-approve/undo', methods=['POST'])
@login_required
@role_required('admin')
def undo_bulk_approve():
    """Undo the last bulk approval action"""
    try:
        undo_info = session.get('bulk_approval_undo')
        
        if not undo_info:
            return jsonify(success=False, message='No recent approval to undo'), 400
        
        # Check if undo data is still valid (within reasonable time)
        timestamp = datetime.fromisoformat(undo_info['timestamp'])
        if (datetime.utcnow() - timestamp).total_seconds() > 300:  # 5 minutes
            session.pop('bulk_approval_undo', None)
            return jsonify(success=False, message='Undo period has expired'), 400
        
        undo_data = undo_info['undo_data']
        notification_ids = undo_info['notification_ids']
        reverted_count = 0
        
        # Revert applications to previous state
        for item in undo_data:
            application = Applications.query.get(item['id'])
            if application:
                application.application_status = item['previous_status']
                application.reviewed_by = item['previous_reviewed_by']
                application.review_date = datetime.fromisoformat(item['previous_review_date']) if item['previous_review_date'] else None
                application.updated_at = datetime.utcnow()
                reverted_count += 1
        
        # Delete the approval notifications
        for notif_id in notification_ids:
            notification = Notifications.query.get(notif_id)
            if notification:
                db.session.delete(notification)
        
        # Create undo notification for applicants
        for item in undo_data:
            undo_notification = Notifications(
                user_id=item['user_id'],
                notif_title='Application Status Update',
                notif_message=f'Your application for {item["program_name"]} is back under review.',
                is_read=False,
                created_at=datetime.utcnow()
            )
            db.session.add(undo_notification)
        
        db.session.commit()
        
        # Clear undo data from session
        session.pop('bulk_approval_undo', None)
        
        return jsonify(
            success=True,
            reverted_count=reverted_count,
            message=f'Successfully reverted {reverted_count} application(s) to pending status.'
        )
        
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error: {str(e)}'), 500


@admin_bp.route('/applications/<int:application_id>/documents/<int:doc_id>/update', methods=['POST'])
@login_required
@role_required('admin')
def admin_update_document(application_id, doc_id):
    """Update document status"""
    data = request.json or {}
    is_complete = data.get('is_complete', False)  # True/False for complete/incomplete
    notes = data.get('notes', '').strip()
    admin_feedback = data.get('admin_feedback', '').strip()

    try:
        app_doc = ApplicationDocuments.query.filter_by(
            id=doc_id, 
            application_id=application_id
        ).first_or_404()
        
        # Update document completion status
        if is_complete:
            app_doc.submission_status = 'approved'  # Mark as approved when complete
        else:
            app_doc.submission_status = 'submitted'  # Mark as submitted when incomplete
        
        # Update feedback and notes
        if admin_feedback:
            app_doc.admin_feedback = admin_feedback
        if notes:
            app_doc.notes = notes
            
        app_doc.verified_by = current_user.id
        app_doc.verified_at = datetime.utcnow()
        app_doc.updated_at = datetime.utcnow()
        
        application = app_doc.application
        
        # Auto-complete application if 100% completion (all documents approved)
        completion_pct = application.completion_percentage
        if completion_pct == 100 and application.documents_complete and application.application_status not in ['completed', 'rejected']:
            application.application_status = 'completed'
            application.updated_at = datetime.utcnow()
            
            # Create notification for the applicant
            completion_notif = Notifications(
                user_id=application.user_id,
                notif_title='🎉 Application Completed!',
                notif_message=(
                    f'Congratulations! Your application for {application.program.program_name} is now COMPLETE!\n\n'
                    f'📋 Application ID: #{application.id}\n'
                    f'✅ All requirements have been verified and approved.\n\n'
                    f'📍 Next Steps:\n'
                    f'• Visit the MSWD Office to get your Application Slip/Stub\n'
                    f'• Bring a valid ID when claiming your stub\n'
                    f'• Wait for the scheduled release date notification\n\n'
                    f'Location: MSWD Office, Municipal Building, Mabitac, Laguna\n'
                    f'Office Hours: Monday-Friday, 8:00 AM - 5:00 PM'
                ),
                is_read=False,
                created_at=datetime.utcnow()
            )
            db.session.add(completion_notif)
        
        db.session.commit()

        # Notify applicant if there's feedback
        if admin_feedback or notes:
            feedback_text = admin_feedback or notes
            notif = Notifications(
                user_id=application.user_id,
                notif_title='Document Feedback',
                notif_message=f'Admin has provided feedback on your document "{app_doc.requirement.requirement_name}" for {application.program.program_name}: {feedback_text}',
                is_read=False,
                created_at=datetime.utcnow()
            )
            db.session.add(notif)
            db.session.commit()

        return jsonify(
            success=True, 
            is_complete=is_complete,
            completion_percentage=application.completion_percentage,
            application_completed=(application.application_status == 'completed')
        )
        
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500


@admin_bp.route('/application/<int:application_id>/shelter-photos/verify', methods=['POST'])
@login_required
@role_required('admin')
def verify_all_shelter_photos(application_id):
    """Verify or reject all shelter photos for an application"""
    application = Applications.query.get_or_404(application_id)
    
    action = request.form.get('action')  # 'approve' or 'reject'
    admin_notes = request.form.get('admin_notes', '').strip()
    
    if action not in ['approve', 'reject']:
        flash('Invalid action.', 'danger')
        return redirect(url_for('admin.view_application', application_id=application_id))
    
    # Check if application has minimum 3 photos
    if len(application.shelter_photos) < 3:
        flash(f'ESA applications require a minimum of 3 shelter photos. Only {len(application.shelter_photos)} photos uploaded.', 'warning')
        return redirect(url_for('admin.view_application', application_id=application_id))
    
    try:
        # Update all shelter photos with same status
        for photo in application.shelter_photos:
            if action == 'approve':
                photo.verification_status = 'approved'
                photo.admin_notes = admin_notes if admin_notes else None
            else:  # reject
                if not admin_notes:
                    flash('Please provide a reason for rejection.', 'warning')
                    return redirect(url_for('admin.view_application', application_id=application_id))
                
                photo.verification_status = 'rejected'
                photo.admin_notes = admin_notes
            
            photo.verified_by = current_user.id
            photo.verified_at = datetime.utcnow()
        
        # If approved, also update the shelter requirement qualification to approved
        if action == 'approve':
            # Find and update shelter photo requirement status
            shelter_requirement = db.session.query(Requirements).filter(
                Requirements.requirement_name.ilike('%shelter%')
            ).first()
            
            if shelter_requirement:
                # Check if there's already a document record for this requirement
                existing_doc = ApplicationDocuments.query.filter_by(
                    application_id=application_id,
                    requirement_id=shelter_requirement.id
                ).first()
                
                if existing_doc:
                    existing_doc.submission_status = 'approved'
                    existing_doc.verified_by = current_user.id
                    existing_doc.verified_at = datetime.utcnow()
                    existing_doc.admin_feedback = 'Shelter photos verified and approved.'
                else:
                    # Create new document record for shelter photo requirement
                    new_doc = ApplicationDocuments(
                        application_id=application_id,
                        requirement_id=shelter_requirement.id,
                        submission_status='approved',
                        verified_by=current_user.id,
                        verified_at=datetime.utcnow(),
                        admin_feedback='Shelter photos verified and approved.',
                        uploaded_at=datetime.utcnow()
                    )
                    db.session.add(new_doc)
        
        # Sync workflow step status with photo verification
        photo_upload_step = ProgramWorkflowSteps.query.filter_by(
            program_id=application.program_id,
            step_type='photo_upload'
        ).first()
        
        if photo_upload_step:
            workflow_status_obj = ApplicationWorkflowStatus.query.filter_by(
                application_id=application_id,
                workflow_step_id=photo_upload_step.id
            ).first()
            
            if workflow_status_obj:
                if action == 'approve':
                    workflow_status_obj.step_status = 'approved'
                    workflow_status_obj.reviewed_at = datetime.utcnow()
                    workflow_status_obj.reviewed_by = current_user.id
                    workflow_status_obj.admin_feedback = admin_notes or 'Photos approved'
                    workflow_status_obj.completed_at = datetime.utcnow()
                else:
                    workflow_status_obj.step_status = 'rejected'
                    workflow_status_obj.reviewed_at = datetime.utcnow()
                    workflow_status_obj.reviewed_by = current_user.id
                    workflow_status_obj.admin_feedback = admin_notes or 'Photos rejected'
                workflow_status_obj.updated_at = datetime.utcnow()
        
        # Create notification for applicant
        if action == 'approve':
            # For ESA programs, after photos are approved, update application to 'approved'
            # so admin can set document submission deadline
            if application.program.program_type == 'ESA':
                application.application_status = 'active'
                application.reviewed_by = current_user.id
                application.review_date = datetime.utcnow()
                application.updated_at = datetime.utcnow()
                flash_msg = 'Shelter photos approved! Application is now ACTIVE for document processing. You can now set a document submission deadline.'
                notif_msg = (
                    f'Great news! Your shelter photos for {application.program.program_name} have been approved!\n\n'
                    f'📸 Shelter verification: PASSED\n\n'
                    f'Your application is now active and being processed. '
                    f'Please wait for the admin to set a deadline for document submission. '
                    f'You will be notified of the required documents and submission deadline.'
                )
            else:
                flash_msg = 'All shelter photos approved successfully. Shelter requirement marked as qualified.'
                notif_msg = f'All your shelter photos have been approved for {application.program.program_name} application. Your shelter requirement is now qualified.'
        else:
            flash_msg = 'All shelter photos rejected.'
            notif_msg = f'Your shelter photos for {application.program.program_name} application were rejected. Please check admin notes and resubmit new photos.'
        
        notification = Notifications(
            user_id=application.user_id,
            notif_title='Shelter Photos Update',
            notif_message=notif_msg,
            is_read=False,
            related_id=application.id,
            related_type='application',
            created_at=datetime.utcnow()
        )
        
        db.session.add(notification)
        db.session.commit()
        
        flash(flash_msg, 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating shelter photos: {str(e)}', 'danger')
    
    return redirect(url_for('admin.view_application', application_id=application_id))


@admin_bp.route('/shelter-photo/<int:photo_id>/verify', methods=['POST'])
@login_required
@role_required('admin')
def verify_shelter_photo(photo_id):
    """Verify or reject a shelter photo"""
    photo = ShelterPhotos.query.get_or_404(photo_id)
    
    action = request.form.get('action')  # 'approve' or 'reject'
    admin_notes = request.form.get('admin_notes', '').strip()
    
    if action not in ['approve', 'reject']:
        flash('Invalid action.', 'danger')
        return redirect(url_for('admin.view_application', application_id=photo.application_id))
    
    try:
        if action == 'approve':
            photo.verification_status = 'approved'
            photo.admin_notes = admin_notes if admin_notes else None
            flash_msg = 'Shelter photo approved successfully.'
            notif_msg = f'Your shelter photo has been approved for {photo.application.program.program_name} application.'
        else:  # reject
            if not admin_notes:
                flash('Please provide a reason for rejection.', 'warning')
                return redirect(url_for('admin.view_application', application_id=photo.application_id))
            
            photo.verification_status = 'rejected'
            photo.admin_notes = admin_notes
            flash_msg = 'Shelter photo rejected.'
            notif_msg = f'Your shelter photo for {photo.application.program.program_name} application was rejected. Please check admin notes and resubmit.'
        
        photo.verified_by = current_user.id
        photo.verified_at = datetime.utcnow()
        
        # Create notification for applicant
        notification = Notifications(
            user_id=photo.application.user_id,
            notif_title='Shelter Photo Update',
            notif_message=notif_msg,
            is_read=False,
            related_id=photo.application_id,
            related_type='application',
            created_at=datetime.utcnow()
        )
        
        db.session.add(notification)
        db.session.commit()
        
        flash(flash_msg, 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating shelter photo: {str(e)}', 'danger')
    
    return redirect(url_for('admin.view_application', application_id=photo.application_id))


# ===================== CA (Capital Assistance) Document Verification =====================

from app.models import CALDocuments

@admin_bp.route('/application/<int:application_id>/verify-ca-documents', methods=['POST'])
@login_required
@role_required('admin')
def verify_all_ca_documents(application_id):
    """Verify or reject both CA documents (Certificate and Proposal)"""
    application = Applications.query.get_or_404(application_id)
    
    action = request.form.get('action')  # 'approve' or 'reject'
    admin_notes = request.form.get('admin_notes', '').strip()
    
    if action not in ['approve', 'reject']:
        flash('Invalid action.', 'danger')
        return redirect(url_for('admin.view_application', application_id=application_id))
    
    # Check if both documents exist
    certificate = CALDocuments.query.filter_by(
        application_id=application_id,
        document_type='certificate'
    ).first()
    proposal = CALDocuments.query.filter_by(
        application_id=application_id,
        document_type='proposal'
    ).first()
    
    if not certificate or not proposal:
        flash('Both Certificate of Participation and Proposal must be uploaded before verification.', 'warning')
        return redirect(url_for('admin.view_application', application_id=application_id))
    
    try:
        # Update both documents
        for doc in [certificate, proposal]:
            if action == 'approve':
                doc.verification_status = 'approved'
                doc.admin_notes = admin_notes if admin_notes else 'Document verified and approved.'
            else:  # reject
                if not admin_notes:
                    flash('Please provide a reason for rejection.', 'warning')
                    return redirect(url_for('admin.view_application', application_id=application_id))
                doc.verification_status = 'rejected'
                doc.admin_notes = admin_notes
            
            doc.verified_by = current_user.id
            doc.verified_at = datetime.utcnow()
        
        # Create notification for applicant
        if action == 'approve':
            # For CA programs, after documents are approved, update application to 'active'
            application.application_status = 'active'
            application.reviewed_by = current_user.id
            application.review_date = datetime.utcnow()
            application.updated_at = datetime.utcnow()
            
            flash_msg = 'CA documents approved! Application is now ACTIVE for document processing. You can now set a document submission deadline.'
            notif_msg = (
                f'Great news! Your CA application documents have been approved!\n\n'
                f'📜 Certificate of Participation: VERIFIED\n'
                f'📋 Capital Assistance Proposal: APPROVED\n\n'
                f'Your application is now active and being processed. '
                f'Please wait for the admin to set a deadline for additional document submission. '
                f'You will be notified of the required documents and submission deadline.'
            )
        else:
            flash_msg = 'CA documents rejected. Applicant has been notified.'
            notif_msg = (
                f'Your CA application documents for {application.program.program_name} were rejected.\n\n'
                f'Reason: {admin_notes}\n\n'
                f'Please review the feedback and resubmit your Certificate and Proposal.'
            )
        
        notification = Notifications(
            user_id=application.user_id,
            notif_title='CA Documents Update',
            notif_message=notif_msg,
            is_read=False,
            related_id=application.id,
            related_type='application',
            created_at=datetime.utcnow()
        )
        
        db.session.add(notification)
        db.session.commit()
        
        flash(flash_msg, 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating CA documents: {str(e)}', 'danger')
    
    return redirect(url_for('admin.view_application', application_id=application_id))


@admin_bp.route('/ca-document/<int:doc_id>/verify', methods=['POST'])
@login_required
@role_required('admin')
def verify_ca_document(doc_id):
    """Verify or reject a single CA document"""
    cal_doc = CALDocuments.query.get_or_404(doc_id)
    application = cal_doc.application
    
    action = request.form.get('action')  # 'approve' or 'reject'
    admin_notes = request.form.get('admin_notes', '').strip()
    
    if action not in ['approve', 'reject']:
        flash('Invalid action.', 'danger')
        return redirect(url_for('admin.view_application', application_id=application.id))
    
    try:
        if action == 'approve':
            cal_doc.verification_status = 'approved'
            cal_doc.admin_notes = admin_notes if admin_notes else 'Document verified and approved.'
            flash_msg = f'{cal_doc.document_type.title()} approved successfully.'
            notif_msg = f'Your {cal_doc.document_type} has been approved for {application.program.program_name} application.'
        else:  # reject
            if not admin_notes:
                flash('Please provide a reason for rejection.', 'warning')
                return redirect(url_for('admin.view_application', application_id=application.id))
            
            cal_doc.verification_status = 'rejected'
            cal_doc.admin_notes = admin_notes
            flash_msg = f'{cal_doc.document_type.title()} rejected.'
            notif_msg = f'Your {cal_doc.document_type} for {application.program.program_name} was rejected. Reason: {admin_notes}'
        
        cal_doc.verified_by = current_user.id
        cal_doc.verified_at = datetime.utcnow()
        
        # Check if both documents are now approved - if so, approve the application
        if action == 'approve':
            certificate = CALDocuments.query.filter_by(
                application_id=application.id,
                document_type='certificate',
                verification_status='approved'
            ).first()
            proposal = CALDocuments.query.filter_by(
                application_id=application.id,
                document_type='proposal',
                verification_status='approved'
            ).first()
            
            if certificate and proposal:
                application.application_status = 'active'
                application.reviewed_by = current_user.id
                application.review_date = datetime.utcnow()
                application.updated_at = datetime.utcnow()
                flash_msg += ' Both CA documents are now approved - application is now ACTIVE for processing.'
                notif_msg = (
                    f'Both your CA documents have been approved for {application.program.program_name}!\n\n'
                    f'📜 Certificate: VERIFIED\n📋 Proposal: APPROVED\n\n'
                    f'Your application is now active and being processed. '
                    f'Please wait for the admin to set a deadline for additional document submission.'
                )
        
        # Create notification
        notification = Notifications(
            user_id=application.user_id,
            notif_title=f'CA {cal_doc.document_type.title()} Update',
            notif_message=notif_msg,
            is_read=False,
            related_id=application.id,
            related_type='application',
            created_at=datetime.utcnow()
        )
        
        db.session.add(notification)
        db.session.commit()
        
        flash(flash_msg, 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating CA document: {str(e)}', 'danger')
    
    return redirect(url_for('admin.view_application', application_id=application.id))


@admin_bp.route('/applications/export', methods=['GET'])
@login_required
@role_required('admin')
def export_applications():
    """Export applications to CSV"""
    import csv
    from io import StringIO
    from flask import Response
    
    # Get filter parameters
    status_filter = request.args.get('status', '').strip()
    program_filter = request.args.get('program', '').strip()
    
    # Base query
    query = Applications.query
    
    if status_filter:
        query = query.filter_by(application_status=status_filter)
    
    if program_filter:
        query = query.filter_by(program_id=int(program_filter))
    
    applications = query.order_by(desc(Applications.application_date)).all()
    
    # Create CSV
    si = StringIO()
    writer = csv.writer(si)
    
    # Write header
    writer.writerow([
        'Application ID', 'Applicant Name', 'Email', 'Program',
        'Status', 'Application Date', 'Review Date', 'Reviewed By',
        'Completion %', 'Remarks'
    ])
    
    # Write data
    for app in applications:
        reviewer_name = ''
        if app.reviewed_by:
            reviewer = User.query.get(app.reviewed_by)
            if reviewer:
                reviewer_name = f"{reviewer.first_name} {reviewer.last_name}"
        
        writer.writerow([
            app.id,
            f"{app.applicant.first_name} {app.applicant.last_name}",
            app.applicant.email,
            app.program.program_name,
            app.application_status,
            app.application_date.strftime('%Y-%m-%d %H:%M:%S') if app.application_date else '',
            app.review_date.strftime('%Y-%m-%d %H:%M:%S') if app.review_date else '',
            reviewer_name,
            f"{app.completion_percentage}%",
            app.remarks or ''
        ])
    
    # Create response
    output = si.getvalue()
    si.close()
    
    return Response(
        output,
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename=applications_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
        }
    )


@admin_bp.route('/applications/<int:application_id>/schedule-claim', methods=['POST'])
@login_required
@role_required('admin')
def schedule_claim(application_id):
    """Schedule claim date for approved/completed financial assistance application"""
    application = Applications.query.get_or_404(application_id)
    
    # Verify that application is eligible for scheduling (active or completed without schedule)
    if application.application_status not in ['active', 'approved', 'completed']:
        return jsonify(success=False, message='Application must be active, approved, or completed before scheduling.')
    
    # Removed restriction - scheduling now available for all program types
    # if application.program.program_type not in ['AICS', 'CA']:
    #     return jsonify(success=False, message='Claim scheduling is only available for AICS and CA programs.')
    
    if not application.documents_complete:
        return jsonify(success=False, message='All required documents must be verified before scheduling.')
    
    data = request.json or {}
    claim_date_str = data.get('claim_date')
    claim_time = data.get('claim_time')
    claim_location = data.get('claim_location', 'MSWD Office, Municipal Building, Mabitac, Laguna')
    claim_instructions = data.get('claim_instructions', '').strip()
    
    if not claim_date_str or not claim_time:
        return jsonify(success=False, message='Claim date and time are required.')
    
    try:
        # Parse the claim date
        claim_date = datetime.strptime(claim_date_str, '%Y-%m-%d')
        
        # Ensure claim date is in the future
        if claim_date.date() <= datetime.now().date():
            return jsonify(success=False, message='Claim date must be in the future.')
        
        # Update application with claim schedule
        application.claim_date = claim_date
        application.claim_time = claim_time
        application.claim_location = claim_location
        application.claim_instructions = claim_instructions
        application.claim_status = 'scheduled'
        application.claim_scheduled_by = current_user.id
        application.claim_scheduled_at = datetime.utcnow()
        application.updated_at = datetime.utcnow()
        
        # Mark application as COMPLETED once release is scheduled (if not already)
        was_already_completed = (application.application_status == 'completed')
        application.application_status = 'completed'
        
        db.session.commit()
        
        # Create notification for the applicant
        if was_already_completed:
            notif_message = (
                f'📅 Release Date Scheduled!\n\n'
                f'Your financial assistance for {application.program.program_name} has been scheduled for release:\n\n'
                f'📅 Date: {claim_date.strftime("%A, %B %d, %Y")}\n'
                f'🕐 Time: {claim_time}\n'
                f'📍 Location: {claim_location}\n'
            )
            notif_title = 'Release Date Scheduled'
        else:
            notif_message = (
                f'🎉 Great news! Your application for {application.program.program_name} is now COMPLETED!\n\n'
                f'Your financial assistance release has been scheduled:\n\n'
                f'📅 Date: {claim_date.strftime("%A, %B %d, %Y")}\n'
                f'🕐 Time: {claim_time}\n'
                f'📍 Location: {claim_location}\n'
            )
            notif_title = 'Application Completed - Release Scheduled'
            
        if claim_instructions:
            notif_message += f'📝 Instructions: {claim_instructions}\n'
        
        notif_message += '\nPlease be present on the scheduled date and time to claim your assistance. Bring your valid ID and application slip.'
        
        notif = Notifications(
            user_id=application.user_id,
            notif_title=notif_title,
            notif_message=notif_message,
            is_read=False,
            created_at=datetime.utcnow()
        )
        db.session.add(notif)
        db.session.commit()
        
        return jsonify(success=True, message='Release scheduled successfully!')
        
    except ValueError as e:
        return jsonify(success=False, message='Invalid date format.')
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error scheduling release: {str(e)}')


@admin_bp.route('/applications/<int:application_id>/remove-schedule', methods=['POST'])
@login_required
@role_required('admin')
def remove_schedule(application_id):
    """Remove the scheduled release date and revert application status to active"""
    application = Applications.query.get_or_404(application_id)
    
    # Verify that application has a schedule
    if not application.claim_date:
        return jsonify(success=False, message='This application does not have a scheduled release date.')
    
    # Verify that application is in completed status
    if application.application_status != 'completed':
        return jsonify(success=False, message='Only completed applications with a schedule can have their schedule removed.')
    
    try:
        # Store the old schedule info for the notification
        old_claim_date = application.claim_date.strftime('%A, %B %d, %Y') if application.claim_date else 'Not set'
        old_claim_time = application.claim_time or 'Not set'
        
        # Clear the schedule details
        application.claim_date = None
        application.claim_time = None
        application.claim_location = None
        application.claim_instructions = None
        application.claim_status = None
        application.claim_scheduled_by = None
        application.claim_scheduled_at = None
        
        # Revert application status to active
        application.application_status = 'active'
        application.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        # Create notification for the applicant
        notif_message = (
            f'📅 Release Schedule Removed\n\n'
            f'The previously scheduled release date for your {application.program.program_name} application has been removed:\n\n'
            f'❌ Previous Date: {old_claim_date}\n'
            f'❌ Previous Time: {old_claim_time}\n\n'
            f'Your application status has been reverted to Active. '
            f'You will be notified when a new release date is scheduled.\n\n'
            f'If you have any questions, please contact the MSWD Office.'
        )
        
        notif = Notifications(
            user_id=application.user_id,
            notif_title='Release Schedule Removed',
            notif_message=notif_message,
            is_read=False,
            created_at=datetime.utcnow()
        )
        db.session.add(notif)
        db.session.commit()
        
        return jsonify(success=True, message='Release schedule removed successfully!')
        
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error removing schedule: {str(e)}')


@admin_bp.route('/applications/<int:application_id>/send-approval-notification', methods=['POST'])
@login_required
@role_required('admin')
def send_approval_notification(application_id):
    """Send notification to applicant that their application is approved and ready for release"""
    application = Applications.query.get_or_404(application_id)
    
    # Verify that application is approved or active
    if application.application_status not in ['approved', 'active']:
        return jsonify(success=False, message='Application must be approved or active to send this notification.')
    
    try:
        # Create notification for the applicant
        notif_message = (
            f'🎉 Congratulations! Your application for {application.program.program_name} has been APPROVED!\n\n'
            f'📋 Application ID: #{application.id}\n'
            f'📅 Application Date: {application.application_date.strftime("%B %d, %Y") if application.application_date else "N/A"}\n\n'
            f'✅ Next Steps:\n'
            f'1. Visit the MSWD Office to get your Application Slip/Stub\n'
            f'2. Bring a valid ID when claiming your stub\n'
            f'3. Wait for the scheduled release date notification\n\n'
            f'📍 Location: MSWD Office, Municipal Building, Mabitac, Laguna\n'
            f'🕐 Office Hours: Monday-Friday, 8:00 AM - 5:00 PM\n\n'
            f'Please keep your Application Slip/Stub safe as you will need it to claim your financial assistance.'
        )
        
        notif = Notifications(
            user_id=application.user_id,
            notif_title='Application Approved - Get Your Claim Stub',
            notif_message=notif_message,
            is_read=False,
            created_at=datetime.utcnow()
        )
        db.session.add(notif)
        db.session.commit()
        
        return jsonify(success=True, message='Approval notification sent to applicant successfully!')
        
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error sending notification: {str(e)}')


@admin_bp.route('/applications/<int:application_id>/update-claim-status', methods=['POST'])
@login_required
@role_required('admin')
def update_claim_status(application_id):
    """Update claim status (claimed, missed, etc.)"""
    application = Applications.query.get_or_404(application_id)
    
    data = request.json or {}
    new_status = data.get('claim_status')
    
    if not new_status or new_status not in ['scheduled', 'claimed', 'missed', 'not_scheduled']:
        return jsonify(success=False, message='Invalid claim status.')
    
    try:
        old_status = application.claim_status
        application.claim_status = new_status
        application.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        # Create appropriate notification
        if new_status == 'claimed':
            notif_message = (
                f'Congratulations! Your financial assistance for {application.program.program_name} '
                f'has been successfully claimed on {datetime.now().strftime("%B %d, %Y")}.\n\n'
                f'Thank you for availing our services. We hope this assistance helps with your needs.'
            )
            notif_title = 'Assistance Successfully Claimed'
        elif new_status == 'missed':
            notif_message = (
                f'You missed your scheduled claim date for {application.program.program_name} '
                f'on {application.claim_date.strftime("%B %d, %Y") if application.claim_date else "the scheduled date"}.\n\n'
                f'Please contact the MSWD office to reschedule your claim appointment.'
            )
            notif_title = 'Missed Claim Appointment'
        else:
            notif_message = f'Your claim status for {application.program.program_name} has been updated to: {new_status.replace("_", " ").title()}'
            notif_title = 'Claim Status Updated'
        
        notif = Notifications(
            user_id=application.user_id,
            notif_title=notif_title,
            notif_message=notif_message,
            is_read=False,
            created_at=datetime.utcnow()
        )
        db.session.add(notif)
        db.session.commit()
        
        return jsonify(success=True, message=f'Claim status updated to: {new_status}')
        
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error updating claim status: {str(e)}')


@admin_bp.route('/applications/<int:application_id>/mark-claimed-without-schedule', methods=['POST'])
@login_required
@role_required('admin')
def mark_claimed_without_schedule(application_id):
    """Mark application as claimed and completed without setting a schedule - also closes the scheduling workflow step"""
    application = Applications.query.get_or_404(application_id)
    
    data = request.json or {}
    workflow_step_id = data.get('workflow_step_id')
    
    try:
        # Update application status to completed
        application.application_status = 'completed'
        application.claim_status = 'claimed'
        application.updated_at = datetime.utcnow()
        
        # Mark the scheduling workflow step as approved/completed
        if workflow_step_id:
            workflow_status = ApplicationWorkflowStatus.query.filter_by(
                application_id=application_id,
                workflow_step_id=workflow_step_id
            ).first()
            
            if workflow_status:
                workflow_status.step_status = 'approved'
                workflow_status.reviewed_at = datetime.utcnow()
                workflow_status.reviewed_by = current_user.id
                workflow_status.admin_feedback = 'Application marked as claimed without formal scheduling.'
                workflow_status.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        # Create notification for user
        notif_message = (
            f'Congratulations! Your financial assistance for {application.program.program_name} '
            f'has been successfully marked as completed and claimed.\n\n'
            f'Thank you for availing our services. We hope this assistance helps with your needs.'
        )
        notif_title = 'Application Completed - Assistance Claimed'
        
        notif = Notifications(
            user_id=application.user_id,
            notif_title=notif_title,
            notif_message=notif_message,
            related_type='application',
            related_id=application_id
        )
        db.session.add(notif)
        db.session.commit()
        
        return jsonify(success=True, message='Application marked as claimed and completed successfully!')
        
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error marking application as claimed: {str(e)}')


@admin_bp.route('/applications/<int:application_id>/slip')
@login_required
@role_required('admin')
def application_slip(application_id):
    """Display printable application slip with verification code - Admin only"""
    application = Applications.query.get_or_404(application_id)
    
    # Check if application slip is enabled for this program
    if not application.program.enable_application_slip:
        flash('Application slip printing is not enabled for this program.', 'warning')
        return redirect(url_for('admin.view_application', application_id=application_id))
    
    # Only allow slip printing for approved or active applications
    if application.application_status not in ['approved', 'active', 'completed']:
        flash('Application slip can only be printed for approved or active applications.', 'warning')
        return redirect(url_for('admin.view_application', application_id=application_id))
    
    # Generate verification code if not already generated
    if not application.verification_code:
        application.generate_verification_code()
        db.session.commit()
    
    # Get applicant details
    applicant = User.query.get(application.user_id)
    community_user = CommunityUsers.query.filter_by(user_id=applicant.id).first()
    
    # Format full address
    address_parts = []
    if community_user.address:
        address_parts.append(community_user.address)
    if community_user.sitio:
        address_parts.append(community_user.sitio)
    if community_user.barangay:
        address_parts.append(f"Brgy. {community_user.barangay}")
    if community_user.municipality:
        address_parts.append(community_user.municipality)
    
    full_address = ', '.join(address_parts) if address_parts else 'N/A'
    
    # Get program and requirements - filter for document-type only
    program = application.program
    program_requirements = db.session.query(
        ProgramRequirements,
        Requirements
    ).join(
        Requirements, ProgramRequirements.requirement_id == Requirements.id
    ).filter(
        ProgramRequirements.program_id == application.program_id,
        Requirements.requirement_type == 'document'
    ).order_by(
        ProgramRequirements.is_mandatory.desc(),
        Requirements.requirement_name
    ).all()
    
    return render_template(
        'admin/application_slip.html',
        application=application,
        applicant=applicant,
        community_user=community_user,
        full_address=full_address,
        program=program,
        program_requirements=program_requirements,
        user=current_user
    )


@admin_bp.route('/applications/bulk-update-status', methods=['POST'])
@login_required
@role_required('admin')
def bulk_update_status():
    """Update status of multiple applications at once"""
    try:
        data = request.get_json()
        application_ids = data.get('application_ids', [])
        new_status = data.get('new_status', '')
        remarks = data.get('remarks', '').strip()
        
        if not application_ids or not new_status:
            return jsonify(success=False, message='Missing required parameters'), 400
        
        if new_status not in ['pending', 'approved', 'rejected', 'active', 'completed']:
            return jsonify(success=False, message='Invalid status'), 400
        
        updated_count = 0
        errors = []
        
        status_messages = {
            'approved': 'Your application has been approved! You can now download your application slip.',
            'rejected': 'Your application has been reviewed and unfortunately was not approved.',
            'active': 'Your application is now being processed. Please submit the required documents.',
            'pending': 'Your application is under review.',
            'completed': 'Your application has been completed and is ready for release/claiming.'
        }
        
        for app_id in application_ids:
            try:
                application = Applications.query.get(app_id)
                
                if not application:
                    errors.append(f'Application #{app_id} not found')
                    continue
                
                # Update application status
                application.application_status = new_status
                application.reviewed_by = current_user.id
                application.review_date = datetime.utcnow()
                application.updated_at = datetime.utcnow()
                
                # Update remarks if provided
                if remarks:
                    application.remarks = remarks
                
                # Create notification
                notif_message = status_messages.get(new_status, 'Your application status has been updated.')
                if remarks:
                    notif_message += f'\n\nAdmin Remarks: {remarks}'
                
                notification = Notifications(
                    user_id=application.user_id,
                    notif_title=f'Application {new_status.replace("-", " ").title()}',
                    notif_message=f'{notif_message}\n\nProgram: {application.program.program_name}',
                    is_read=False,
                    related_id=application.id,
                    related_type='application',

                    created_at=datetime.utcnow()
                    
                )
                
                db.session.add(notification)
                updated_count += 1
                
            except Exception as e:
                errors.append(f'Error processing application #{app_id}: {str(e)}')
                continue
        
        db.session.commit()
        
        # Log activity
        log_bulk_application_status_update(application_ids, new_status, updated_count)
        
        message = f'Successfully updated {updated_count} application(s) to {new_status}.'
        if errors:
            message += f' {len(errors)} error(s) occurred.'
        
        return jsonify(
            success=True,
            updated_count=updated_count,
            message=message,
            errors=errors
        )
        
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error: {str(e)}'), 500


@admin_bp.route('/applications/send-bulk-notification', methods=['POST'])
@login_required
@role_required('admin')
def send_bulk_notification():
    """Send notification to multiple applicants about schedule/release"""
    try:
        data = request.get_json()
        application_ids = data.get('application_ids', [])
        title = data.get('title', '').strip()
        message = data.get('message', '').strip()
        schedule = data.get('schedule', '').strip()
        location = data.get('location', '').strip()
        
        if not application_ids or not title or not message:
            return jsonify(success=False, message='Missing required parameters'), 400
        
        sent_count = 0
        errors = []
        
        for app_id in application_ids:
            try:
                application = Applications.query.get(app_id)
                
                if not application:
                    errors.append(f'Application #{app_id} not found')
                    continue
                
                # Create notification
                notification = Notifications(
                    user_id=application.user_id,
                    notif_title=title,
                    notif_message=message,
                    is_read=False,
                    related_id=application.id,
                    related_type='application',
                    created_at=datetime.utcnow()
                )
                
                db.session.add(notification)
                sent_count += 1
                
            except Exception as e:
                errors.append(f'Error sending to application #{app_id}: {str(e)}')
                continue
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'sent_count': sent_count,
            'errors': errors
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/applications/<int:application_id>/verify-upload/<int:upload_id>', methods=['POST'])
@login_required
@role_required('admin')
def verify_uploaded_document(application_id, upload_id):
    """Verify or reject an uploaded document"""
    upload = ApplicationDocumentUploads.query.filter_by(
        id=upload_id,
        application_id=application_id
    ).first_or_404()
    
    try:
        verification_status = request.form.get('verification_status')  # 'approved' or 'rejected'
        admin_feedback = request.form.get('admin_feedback', '').strip()
        
        if verification_status not in ['approved', 'rejected']:
            return jsonify(success=False, message='Invalid verification status'), 400
        
        # Update upload record
        upload.verification_status = verification_status
        upload.admin_feedback = admin_feedback
        upload.verified_by = current_user.id
        upload.verified_at = datetime.utcnow()
        
        # Log document verification activity
        log_document_verification(upload, verification_status, admin_feedback)
        
        # Check if all mandatory documents are verified
        application = upload.application
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
        
        mandatory_req_ids = [req.id for req, is_mandatory in program_requirements if is_mandatory]
        
        # Get all uploads for mandatory documents
        mandatory_uploads = ApplicationDocumentUploads.query.filter(
            ApplicationDocumentUploads.application_id == application_id,
            ApplicationDocumentUploads.requirement_id.in_(mandatory_req_ids)
        ).all()
        
        # Check if all mandatory documents are uploaded and approved
        all_approved = all(
            upload.verification_status == 'approved' 
            for upload in mandatory_uploads
        ) and len(mandatory_uploads) == len(mandatory_req_ids)
        
        any_rejected = any(
            upload.verification_status == 'rejected' 
            for upload in mandatory_uploads
        )
        
        # Update application document_upload_status
        if all_approved:
            application.document_upload_status = 'verified'
            
            # Notify user that documents are verified
            notification = Notifications(
                user_id=application.user_id,
                notif_title='Documents Verified',
                notif_message=f'Your documents for {application.program.program_name} have been verified. You may now proceed to physical submission at the MSWD office.',
                is_read=False,
                related_id=application_id,
                related_type='application'
            )
            db.session.add(notification)
        elif any_rejected:
            application.document_upload_status = 'rejected'
            
            # Notify user about rejected documents
            notification = Notifications(
                user_id=application.user_id,
                notif_title='Document Revision Required',
                notif_message=f'Some documents for {application.program.program_name} need revision. Please check the feedback and resubmit.',
                is_read=False,
                related_id=application_id,
                related_type='application'
            )
            db.session.add(notification)
        
        # Auto-complete application if 100% completion (all documents approved)
        completion_pct = application.completion_percentage
        if completion_pct == 100 and application.documents_complete and application.application_status not in ['completed', 'rejected']:
            application.application_status = 'completed'
            application.updated_at = datetime.utcnow()
            
            # Create notification for the applicant
            completion_notif = Notifications(
                user_id=application.user_id,
                notif_title='🎉 Application Completed!',
                notif_message=(
                    f'Congratulations! Your application for {application.program.program_name} is now COMPLETE!\n\n'
                    f'📋 Application ID: #{application.id}\n'
                    f'✅ All requirements have been verified and approved.\n\n'
                    f'📍 Next Steps:\n'
                    f'• Visit the MSWD Office to get your Application Slip/Stub\n'
                    f'• Bring a valid ID when claiming your stub\n'
                    f'• Wait for the scheduled release date notification\n\n'
                    f'Location: MSWD Office, Municipal Building, Mabitac, Laguna\n'
                    f'Office Hours: Monday-Friday, 8:00 AM - 5:00 PM'
                ),
                is_read=False,
                related_id=application_id,
                related_type='application',
                created_at=datetime.utcnow()
            )
            db.session.add(completion_notif)
        
        db.session.commit()
        
        flash(f'Document {verification_status} successfully!', 'success')
        return jsonify(
            success=True, 
            message=f'Document {verification_status}',
            application_completed=(application.application_status == 'completed')
        )
        
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500


@admin_bp.route('/applications/<int:application_id>/document/<int:doc_id>/verify-status', methods=['POST'])
@login_required
@role_required('admin')
def verify_document_status(application_id, doc_id):
    """Toggle doc  ument verification status (verified/pending)"""
    doc = ApplicationDocuments.query.filter_by(
        id=doc_id,
        application_id=application_id
    ).first_or_404()
    
    try:
        submission_status = request.form.get('submission_status')  # 'verified' or 'pending'
        
        if submission_status not in ['verified', 'pending']:
            return jsonify(success=False, message='Invalid submission status'), 400
        
        # Update document record
        doc.submission_status = submission_status
        doc.verified_by = current_user.id
        doc.verified_at = datetime.utcnow()
        
        # Log activity
        log_document_status_toggle(doc, submission_status)
        
        db.session.commit()
        
        return jsonify(
            success=True,
            message=f'Document {submission_status}',
            new_status=submission_status
        )
        
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500


@admin_bp.route('/beneficiaries-list/preview')
@login_required
@role_required('admin')
def preview_beneficiaries_list():
    """Return JSON preview of filtered beneficiaries list"""
    program_ids = request.args.get('program_ids', '').strip()
    program_type = request.args.get('program_type', '').strip()

    query = Applications.query.filter(
        Applications.application_status.in_(['approved', 'active', 'completed'])
    ).join(User, Applications.user_id == User.id).join(CommunityUsers, User.id == CommunityUsers.user_id)

    if program_ids:
        id_list = [int(x) for x in program_ids.split(',') if x.strip().isdigit()]
        if id_list:
            query = query.filter(Applications.program_id.in_(id_list))

    if program_type:
        query = query.join(Programs, Applications.program_id == Programs.id).filter(Programs.program_type == program_type)

    apps = query.order_by(Applications.id).all()

    results = []
    for app in apps:
        full_name = f"{app.applicant.first_name} {app.applicant.middle_name or ''} {app.applicant.last_name}".strip()
        barangay = app.applicant.community_profile.barangay if app.applicant.community_profile else 'N/A'
        results.append({
            'id': app.id,
            'name': full_name,
            'barangay': barangay,
            'program': app.program.program_name,
            'program_type': app.program.program_type,
            'status': app.application_status
        })

    return jsonify({'count': len(results), 'beneficiaries': results})


@admin_bp.route('/generate-beneficiaries-list')
@login_required
@role_required('admin')
def generate_beneficiaries_list():
    """Generate a JPG image of approved beneficiaries list"""
    try:
        program_ids = request.args.get('program_ids', '').strip()
        program_type = request.args.get('program_type', '').strip()

        query = Applications.query.filter(
            Applications.application_status.in_(['approved', 'active', 'completed'])
        ).join(User, Applications.user_id == User.id).join(CommunityUsers, User.id == CommunityUsers.user_id)

        if program_ids:
            id_list = [int(x) for x in program_ids.split(',') if x.strip().isdigit()]
            if id_list:
                query = query.filter(Applications.program_id.in_(id_list))

        if program_type:
            query = query.join(Programs, Applications.program_id == Programs.id).filter(Programs.program_type == program_type)

        # Get all approved/active/completed applications with user and community profile data
        approved_applications = query.order_by(Applications.id).all()
        
        if not approved_applications:
            flash('No approved applications found.', 'warning')
            return redirect(url_for('admin.applications'))
        
        # Create image with table
        # Calculate dimensions based on number of rows
        row_height = 40
        header_height = 60
        padding = 40
        num_rows = len(approved_applications)
        
        img_width = 800
        img_height = header_height + (num_rows * row_height) + padding * 2
        
        # Create white background
        img = Image.new('RGB', (img_width, img_height), color='white')
        draw = ImageDraw.Draw(img)
        
        # Try to use a nice font, fallback to default
        try:
            title_font = ImageFont.truetype("arial.ttf", 24)
            header_font = ImageFont.truetype("arialbd.ttf", 16)
            cell_font = ImageFont.truetype("arial.ttf", 14)
        except:
            title_font = ImageFont.load_default()
            header_font = ImageFont.load_default()
            cell_font = ImageFont.load_default()
        
        # Title
        if program_type:
            title = f"LIST OF APPROVED BENEFICIARIES – {program_type.upper()}"
        else:
            title = "LIST OF APPROVED BENEFICIARIES"
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        draw.text(((img_width - title_width) / 2, padding), title, fill='black', font=title_font)
        
        # Table headers
        y_offset = padding + 40
        col_widths = [120, 400, 240]  # Application #, Name, Barangay
        col_positions = [40, 160, 560]
        
        # Draw header background
        draw.rectangle([30, y_offset, img_width - 30, y_offset + 40], fill='#0032A0')
        
        # Header text
        headers = ['Application #', 'Name', 'Barangay']
        for i, header in enumerate(headers):
            draw.text((col_positions[i], y_offset + 12), header, fill='white', font=header_font)
        
        y_offset += 40
        
        # Draw table rows
        for idx, app in enumerate(approved_applications):
            # Alternate row colors
            if idx % 2 == 0:
                draw.rectangle([30, y_offset, img_width - 30, y_offset + row_height], fill='#f8f9fc')
            
            # Application number
            draw.text((col_positions[0], y_offset + 12), f"#{app.id}", fill='black', font=cell_font)
            
            # Full name
            full_name = f"{app.applicant.first_name} {app.applicant.middle_name or ''} {app.applicant.last_name}".strip()
            # Truncate if too long
            if len(full_name) > 40:
                full_name = full_name[:37] + "..."
            draw.text((col_positions[1], y_offset + 12), full_name, fill='black', font=cell_font)
            
            # Barangay
            barangay = app.applicant.community_profile.barangay if app.applicant.community_profile else 'N/A'
            draw.text((col_positions[2], y_offset + 12), barangay, fill='black', font=cell_font)
            
            y_offset += row_height
        
        # Draw table border
        draw.rectangle([30, padding + 40, img_width - 30, y_offset], outline='#dee2e6', width=2)
        
        # Add footer with generation date
        footer_text = f"Generated on: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}"
        footer_bbox = draw.textbbox((0, 0), footer_text, font=cell_font)
        footer_width = footer_bbox[2] - footer_bbox[0]
        draw.text(((img_width - footer_width) / 2, y_offset + 20), footer_text, fill='gray', font=cell_font)
        
        # Save to BytesIO object
        img_io = io.BytesIO()
        img.save(img_io, 'JPEG', quality=95)
        img_io.seek(0)
        
        # Generate filename with timestamp
        filename = f"beneficiaries_list_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        
        # Log activity
        log_beneficiaries_list_generated(len(approved_applications))
        db.session.commit()
        
        return send_file(
            img_io,
            mimetype='image/jpeg',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        flash(f'Error generating beneficiaries list: {str(e)}', 'error')
        return redirect(url_for('admin.applications'))


@admin_bp.route('/applications/<int:application_id>/workflow-step/<int:step_id>/approve', methods=['POST'])
@login_required
@role_required('admin')
def approve_workflow_step(application_id, step_id):
    """Approve a specific workflow step"""
    application = Applications.query.get_or_404(application_id)
    
    # Get workflow status
    workflow_status = ApplicationWorkflowStatus.query.filter_by(
        application_id=application_id,
        workflow_step_id=step_id
    ).first()
    
    if not workflow_status:
        return jsonify({'success': False, 'message': 'Workflow status not found'})
    
    data = request.get_json()
    feedback = data.get('feedback', '')
    
    # Update workflow status
    workflow_status.step_status = 'approved'
    workflow_status.reviewed_at = datetime.utcnow()
    workflow_status.reviewed_by = current_user.id
    workflow_status.admin_feedback = feedback
    workflow_status.updated_at = datetime.utcnow()

    # If this is the Application Review step, set application status to 'approved'
    # Status will transition to 'active' when the user opens/views the application
    step = workflow_status.workflow_step
    if step and 'application review' in step.step_name.lower():
        application.application_status = 'approved'
        application.reviewed_by = current_user.id
        application.review_date = datetime.utcnow()
        application.updated_at = datetime.utcnow()

    try:
        db.session.commit()
        
        # Check if this enables the next step
        _check_and_enable_next_step(application, step_id)

        # Determine notification message based on step type
        if step and 'application review' in step.step_name.lower():
            notif_title = f'Application Approved - {application.program.program_name}'
            notif_message = f'Congratulations! Your application for {application.program.program_name} has been approved! Please open your application to view the next steps.'
        else:
            notif_title = f'Workflow Step Approved - {application.program.program_name}'
            notif_message = f'Your workflow step has been approved. You can now proceed to the next step.'

        # Create notification for user
        notification = Notifications(
            user_id=application.user_id,
            notif_title=notif_title,
            notif_message=notif_message,
            related_type='application',
            related_id=application_id
        )
        db.session.add(notification)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Step approved successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/applications/<int:application_id>/workflow-step/<int:step_id>/reject', methods=['POST'])
@login_required
@role_required('admin')
def reject_workflow_step(application_id, step_id):
    """Reject a specific workflow step"""
    application = Applications.query.get_or_404(application_id)
    
    # Get workflow status
    workflow_status = ApplicationWorkflowStatus.query.filter_by(
        application_id=application_id,
        workflow_step_id=step_id
    ).first()
    
    if not workflow_status:
        return jsonify({'success': False, 'message': 'Workflow status not found'})
    
    data = request.get_json()
    feedback = data.get('feedback', '')
    
    if not feedback:
        return jsonify({'success': False, 'message': 'Feedback is required for rejection'})
    
    # Update workflow status
    workflow_status.step_status = 'rejected'
    workflow_status.reviewed_at = datetime.utcnow()
    workflow_status.reviewed_by = current_user.id
    workflow_status.admin_feedback = feedback
    workflow_status.updated_at = datetime.utcnow()
    
    try:
        db.session.commit()
        
        # Create notification for user
        notification = Notifications(
            user_id=application.user_id,
            notif_title=f'Workflow Step Rejected - {application.program.program_name}',
            notif_message=f'Your workflow step has been rejected. Please review the feedback and resubmit.',
            related_type='application',
            related_id=application_id
        )
        db.session.add(notification)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Step rejected successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/applications/<int:application_id>/approve-workflow-approval', methods=['POST'])
@login_required
@role_required('admin')
def approve_workflow_approval_step(application_id):
    """Approve an application through the workflow approval step - updates both workflow status and application status"""
    application = Applications.query.get_or_404(application_id)
    
    feedback = request.form.get('feedback', '').strip()
    submission_deadline = request.form.get('submission_deadline', '').strip()
    
    try:
        # Find the approval workflow step for this program
        approval_step = ProgramWorkflowSteps.query.filter_by(
            program_id=application.program_id,
            step_type='approval'
        ).first()
        
        if approval_step:
            # Update the workflow status for the approval step
            workflow_status = ApplicationWorkflowStatus.query.filter_by(
                application_id=application_id,
                workflow_step_id=approval_step.id
            ).first()
            
            if workflow_status:
                workflow_status.step_status = 'approved'
                workflow_status.reviewed_at = datetime.utcnow()
                workflow_status.reviewed_by = current_user.id
                workflow_status.admin_feedback = feedback if feedback else None
                workflow_status.completed_at = datetime.utcnow()
                workflow_status.updated_at = datetime.utcnow()
        
        # Update the application status to approved
        application.application_status = 'approved'
        application.reviewed_by = current_user.id
        application.review_date = datetime.utcnow()
        application.updated_at = datetime.utcnow()
        
        if feedback:
            application.remarks = feedback
        
        # Set submission deadline if provided
        if submission_deadline:
            try:
                deadline_date = datetime.strptime(submission_deadline, '%Y-%m-%d')
                application.submission_deadline = deadline_date
            except ValueError:
                pass
        
        db.session.commit()
        
        # Enable next workflow step
        if approval_step:
            _check_and_enable_next_step(application, approval_step.id)
        
        # Create notification for applicant
        deadline_text = ''
        if application.submission_deadline:
            deadline_text = f" Please complete the next steps by {application.submission_deadline.strftime('%B %d, %Y')}."
        
        notification = Notifications(
            user_id=application.user_id,
            notif_title='Application Approved!',
            notif_message=f'Your application for {application.program.program_name} has been approved.{deadline_text}',
            is_read=False,
            related_id=application.id,
            related_type='application',
            created_at=datetime.utcnow()
        )
        db.session.add(notification)
        db.session.commit()
        
        flash(f'Application #{application_id} has been approved successfully.', 'success')
        return redirect(url_for('admin.view_application', application_id=application_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error approving application: {str(e)}', 'danger')
        return redirect(url_for('admin.view_application', application_id=application_id))


@admin_bp.route('/applications/<int:application_id>/decline-workflow-approval', methods=['POST'])
@login_required
@role_required('admin')
def decline_workflow_approval_step(application_id):
    """Decline an application through the workflow approval step - updates both workflow status and application status"""
    application = Applications.query.get_or_404(application_id)
    
    feedback = request.form.get('feedback', '').strip()
    
    if not feedback:
        flash('Please provide a reason for declining the application.', 'warning')
        return redirect(url_for('admin.view_application', application_id=application_id))
    
    try:
        # Find the approval workflow step for this program
        approval_step = ProgramWorkflowSteps.query.filter_by(
            program_id=application.program_id,
            step_type='approval'
        ).first()
        
        if approval_step:
            # Update the workflow status for the approval step
            workflow_status = ApplicationWorkflowStatus.query.filter_by(
                application_id=application_id,
                workflow_step_id=approval_step.id
            ).first()
            
            if workflow_status:
                workflow_status.step_status = 'rejected'
                workflow_status.reviewed_at = datetime.utcnow()
                workflow_status.reviewed_by = current_user.id
                workflow_status.admin_feedback = feedback
                workflow_status.updated_at = datetime.utcnow()
        
        # Update the application status to rejected
        application.application_status = 'rejected'
        application.reviewed_by = current_user.id
        application.review_date = datetime.utcnow()
        application.remarks = feedback
        application.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        # Create notification for applicant
        notification = Notifications(
            user_id=application.user_id,
            notif_title='Application Update',
            notif_message=f'Your application for {application.program.program_name} has been reviewed. Reason: {feedback}',
            is_read=False,
            related_id=application.id,
            related_type='application',
            created_at=datetime.utcnow()
        )
        db.session.add(notification)
        db.session.commit()
        
        flash(f'Application #{application_id} has been declined.', 'info')
        return redirect(url_for('admin.view_application', application_id=application_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error declining application: {str(e)}', 'danger')
        return redirect(url_for('admin.view_application', application_id=application_id))


def _check_and_enable_next_step(application, completed_step_id):
    """Check if the next workflow step can be enabled"""
    # Get all workflow steps for this application
    workflow_steps = sorted(application.program.workflow_steps, key=lambda x: x.step_order)
    
    # Find the completed step
    completed_step = None
    for step in workflow_steps:
        if step.id == completed_step_id:
            completed_step = step
            break
    
    if not completed_step:
        return
    
    # Find the next step
    next_step = None
    for step in workflow_steps:
        if step.step_order == completed_step.step_order + 1:
            next_step = step
            break
    
    if not next_step:
        return
    
    # Get or create workflow status for next step
    next_step_status = ApplicationWorkflowStatus.query.filter_by(
        application_id=application.id,
        workflow_step_id=next_step.id
    ).first()
    
    if not next_step_status:
        next_step_status = ApplicationWorkflowStatus(
            application_id=application.id,
            workflow_step_id=next_step.id,
            step_status='not_started'
        )
        db.session.add(next_step_status)
    
    # Enable the next step if it's not already started
    if next_step_status.step_status == 'not_started':
        next_step_status.step_status = 'in_progress'
        next_step_status.started_at = datetime.utcnow()
        next_step_status.updated_at = datetime.utcnow()
    
    db.session.commit()


@admin_bp.route('/applications/<int:application_id>/reset-workflow-step/<int:step_id>', methods=['POST'])
@login_required
@role_required('admin')
def reset_workflow_step(application_id, step_id):
    """Reset a workflow step to allow resubmission"""
    application = Applications.query.get_or_404(application_id)
    
    # Get workflow status
    workflow_status = ApplicationWorkflowStatus.query.filter_by(
        application_id=application_id,
        workflow_step_id=step_id
    ).first()
    
    if not workflow_status:
        return jsonify({'success': False, 'message': 'Workflow status not found'})
    
    # Reset workflow status
    workflow_status.step_status = 'not_started'
    workflow_status.started_at = None
    workflow_status.completed_at = None
    workflow_status.reviewed_at = None
    workflow_status.reviewed_by = None
    workflow_status.admin_feedback = None
    workflow_status.updated_at = datetime.utcnow()
    
    try:
        db.session.commit()
        
        # Create notification for user
        notification = Notifications(
            user_id=application.user_id,
            title=f'Workflow Step Reset - {application.program.program_name}',
            message=f'A workflow step has been reset. You can now resubmit this step.',
            category='workflow_update',
            is_read=False,
            link=f'/applications/{application_id}/workflow'
        )
        db.session.add(notification)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Step reset successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/applications/<int:application_id>/review-cancellation', methods=['POST'])
@login_required
@role_required('admin')
def review_cancellation_request(application_id):
    """Approve or reject a cancellation request from a community user"""
    try:
        application = Applications.query.get_or_404(application_id)
        
        # Verify cancellation is pending
        if not application.cancellation_requested or application.cancellation_status != 'pending':
            flash('No pending cancellation request found for this application.', 'warning')
            return redirect(url_for('admin.view_application', application_id=application_id))
        
        decision = request.form.get('decision')  # 'approve' or 'reject'
        admin_notes = request.form.get('admin_notes', '').strip()
        
        if decision not in ['approve', 'reject']:
            flash('Invalid decision.', 'danger')
            return redirect(url_for('admin.view_application', application_id=application_id))
        
        # Update cancellation status
        application.cancellation_status = 'approved' if decision == 'approve' else 'rejected'
        application.cancellation_reviewed_by = current_user.id
        application.cancellation_reviewed_at = datetime.utcnow()
        application.cancellation_admin_notes = admin_notes
        application.updated_at = datetime.utcnow()
        
        if decision == 'approve':
            # Mark application as cancelled
            application.application_status = 'cancelled'
            
            # Create notification for user
            notification = Notifications(
                user_id=application.user_id,
                notif_title=f'Cancellation Approved - {application.program.program_name}',
                notif_message=f'Your cancellation request has been approved. Your application for {application.program.program_name} has been cancelled.',
                is_read=False,
                related_id=application_id,
                related_type='application'
            )
            db.session.add(notification)
            
            flash(f'Cancellation request approved. Application #{application_id} has been cancelled.', 'success')
        else:
            # Rejected - application continues as normal
            notification = Notifications(
                user_id=application.user_id,
                notif_title=f'Cancellation Request Declined - {application.program.program_name}',
                notif_message=f'Your cancellation request has been declined. {admin_notes if admin_notes else "Your application will continue as normal."}',
                is_read=False,
                related_id=application_id,
                related_type='application'
            )
            db.session.add(notification)
            
            flash(f'Cancellation request rejected. Application #{application_id} will continue as normal.', 'info')
        
        db.session.commit()
        return redirect(url_for('admin.view_application', application_id=application_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error processing cancellation request: {str(e)}', 'danger')
        return redirect(url_for('admin.view_application', application_id=application_id))
