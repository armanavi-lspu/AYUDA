from flask import render_template, jsonify, redirect, url_for, request, flash, send_file
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, or_, func
from app.admin import admin_bp
from app.utils import role_required
from app.models import Programs, Requirements, ProgramRequirements, Applications, ApplicationDocuments, Notifications, User, CommunityUsers, ShelterPhotos
from app.extensions import db


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
    
    # Get statistics
    total_apps = Applications.query.count()
    pending_apps = Applications.query.filter_by(application_status='pending').count()
    approved_apps = Applications.query.filter_by(application_status='approved').count()
    rejected_apps = Applications.query.filter_by(application_status='rejected').count()
    on_hold_apps = Applications.query.filter_by(application_status='on-hold').count()
    
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
        on_hold_apps=on_hold_apps,
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
        
        # Check employment status
        if 'unemployed' in qual_name_lower:
            return not community_profile.is_currently_employed
        
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
            'requirement': requirement,
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
    
    # Calculate date values for deadline picker
    today = datetime.utcnow()
    min_date = (today + timedelta(days=1)).strftime('%Y-%m-%d')
    default_deadline = (today + timedelta(days=30)).strftime('%Y-%m-%d')
    
    return render_template(
        'admin/view_application.html',
        application=application,
        document_requirements=document_requirements,
        qualification_requirements=qualification_requirements,
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
    
    new_status = request.form.get('status')  # 'approved', 'rejected', 'on-hold'
    remarks = request.form.get('remarks', '').strip()
    submission_deadline = request.form.get('submission_deadline', '').strip()
    
    if new_status not in ['approved', 'rejected', 'on-hold', 'pending']:
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
        
        # Create notification for applicant
        if new_status == 'approved':
            deadline_text = f" Please submit all required documents by {application.submission_deadline.strftime('%B %d, %Y')} to complete your application." if application.submission_deadline else ""
            notif_message = f'Your application for {application.program.program_name} has been approved! You can now download your application slip and submit the required documents at the MSWD Office.{deadline_text}'
        else:
            status_messages = {
                'rejected': f'Your application for {application.program.program_name} has been rejected. Please check the remarks for more information.',
                'on-hold': f'Your application for {application.program.program_name} is on hold. Please check the notes for more information.',
                'pending': f'Your application for {application.program.program_name} status has been updated to pending.'
            }
            notif_message = status_messages.get(new_status, 'Your application status has been updated.')
        
        notification = Notifications(
            user_id=application.user_id,
            notif_title=f'Application Status Update',
            notif_message=notif_message,
            is_read=False,
            created_at=datetime.utcnow()
        )
        
        db.session.add(notification)
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
        
        # Check if all mandatory documents are complete
        application = app_doc.application
        mandatory_docs = []
        for doc in application.document_checklist:
            prog_req = db.session.query(ProgramRequirements).filter_by(
                program_id=application.program_id,
                requirement_id=doc.requirement_id,
                is_mandatory=True
            ).first()
            if prog_req:
                mandatory_docs.append(doc)
        
        # Auto-update application status if all mandatory docs are complete
        if mandatory_docs:
            all_complete = all(doc.submission_status == 'approved' for doc in mandatory_docs)
            if all_complete and application.application_status == 'pending':
                application.application_status = 'approved'
                application.reviewed_by = current_user.id
                application.review_date = datetime.utcnow()
        
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
            completion_percentage=application.completion_percentage
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
        
        # Create notification for applicant
        if action == 'approve':
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
            created_at=datetime.utcnow()
        )
        
        db.session.add(notification)
        db.session.commit()
        
        flash(flash_msg, 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating shelter photo: {str(e)}', 'danger')
    
    return redirect(url_for('admin.view_application', application_id=photo.application_id))


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
    """Schedule claim date for approved financial assistance application"""
    application = Applications.query.get_or_404(application_id)
    
    # Verify that application is eligible for scheduling
    if application.application_status != 'approved':
        return jsonify(success=False, message='Application must be approved before scheduling.')
    
    if application.program.program_type not in ['AICS', 'CAL']:
        return jsonify(success=False, message='Claim scheduling is only available for AICS and CAL programs.')
    
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
        
        db.session.commit()
        
        # Create notification for the applicant
        notif_message = (
            f'Your claim schedule for {application.program.program_name} has been set!\n\n'
            f'📅 Date: {claim_date.strftime("%A, %B %d, %Y")}\n'
            f'🕐 Time: {claim_time}\n'
            f'📍 Location: {claim_location}\n'
        )
        if claim_instructions:
            notif_message += f'📝 Instructions: {claim_instructions}\n'
        
        notif_message += '\nPlease be present on the scheduled date and time to claim your assistance.'
        
        notif = Notifications(
            user_id=application.user_id,
            notif_title='Claim Schedule Set',
            notif_message=notif_message,
            is_read=False,
            created_at=datetime.utcnow()
        )
        db.session.add(notif)
        db.session.commit()
        
        return jsonify(success=True, message='Claim schedule saved successfully.')
        
    except ValueError as e:
        return jsonify(success=False, message='Invalid date format.')
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error scheduling claim: {str(e)}')


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