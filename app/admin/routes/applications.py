from flask import render_template, jsonify, redirect, url_for, request, flash, send_file, session
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, or_, func
from app.admin import admin_bp
from app.utils import role_required
from app.models import Programs, Requirements, ProgramRequirements, Applications, ApplicationDocuments, Notifications, User, CommunityUsers, ShelterPhotos, ApplicationDocumentUploads
from app.extensions import db
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
        if 'unemployed' in combined or 'not employed' in combined:
            return not user_profile.is_currently_employed
        else:
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
    on_hold_apps = Applications.query.filter_by(application_status='on_hold').count()
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
        on_hold_apps=on_hold_apps,
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
    
    # Calculate date values for deadline picker
    today = datetime.utcnow()
    min_date = (today + timedelta(days=1)).strftime('%Y-%m-%d')
    default_deadline = (today + timedelta(days=30)).strftime('%Y-%m-%d')
    
    return render_template(
        'admin/view_application.html',
        application=application,
        document_requirements=document_requirements,
        qualification_requirements=qualification_requirements,
        uploads_by_requirement=uploads_by_requirement,
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
            related_id=application.id,
            related_type='application',
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
        on_hold_count = 0
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
                
                if application.application_status not in ['pending', 'submitted']:
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
                    # Put on hold - does not meet all qualifications
                    application.application_status = 'on_hold'
                    application.reviewed_by = current_user.id
                    application.review_date = datetime.utcnow()
                    application.updated_at = datetime.utcnow()
                    application.remarks = f"Does not meet qualification requirements: {', '.join(unmet_reqs)}"
                    
                    # Create notification for on-hold applicant
                    notification = Notifications(
                        user_id=application.user_id,
                        notif_title='Application On Hold',
                        notif_message=f'Your application for {application.program.program_name} has been put on hold for review. Some qualification requirements need verification.',
                        is_read=False,
                        related_id=application.id,
                        related_type='application',
                        created_at=datetime.utcnow()
                    )
                    
                    db.session.add(notification)
                    db.session.flush()
                    notification_ids.append(notification.id)
                    on_hold_count += 1
                    
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
                    notif_title='Applicants Need Manual Review',
                    notif_message=f'{len(unqualified_applicants)} applicant(s) do not meet all qualification requirements and have been put on hold:\n{summary_text}',
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
        
        message = f'Processed {len(application_ids)} application(s): {approved_count} approved, {on_hold_count} put on hold.'
        if errors:
            message += f' {len(errors)} error(s): ' + '; '.join(errors[:3])
        
        return jsonify(
            success=True,
            approved_count=approved_count,
            on_hold_count=on_hold_count,
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
    
    # Verify that application is eligible for scheduling (approved or completed without schedule)
    if application.application_status not in ['approved', 'completed']:
        return jsonify(success=False, message='Application must be approved or completed before scheduling.')
    
    # Removed restriction - scheduling now available for all program types
    # if application.program.program_type not in ['AICS', 'CAL']:
    #     return jsonify(success=False, message='Claim scheduling is only available for AICS and CAL programs.')
    
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


@admin_bp.route('/applications/<int:application_id>/send-approval-notification', methods=['POST'])
@login_required
@role_required('admin')
def send_approval_notification(application_id):
    """Send notification to applicant that their application is approved and ready for release"""
    application = Applications.query.get_or_404(application_id)
    
    # Verify that application is approved
    if application.application_status != 'approved':
        return jsonify(success=False, message='Application must be approved to send this notification.')
    
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


@admin_bp.route('/applications/<int:application_id>/slip')
@login_required
@role_required('admin')
def application_slip(application_id):
    """Display printable application slip with verification code - Admin only"""
    application = Applications.query.get_or_404(application_id)
    
    # Only allow slip printing for approved applications
    if application.application_status != 'approved':
        flash('Application slip can only be printed for approved applications.', 'warning')
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
        
        if new_status not in ['pending', 'approved', 'rejected', 'on-hold']:
            return jsonify(success=False, message='Invalid status'), 400
        
        updated_count = 0
        errors = []
        
        status_messages = {
            'approved': 'Your application has been approved! You can now download your application slip.',
            'rejected': 'Your application has been reviewed and unfortunately was not approved.',
            'on-hold': 'Your application has been placed on hold. Please check the remarks for more information.',
            'pending': 'Your application is under review.'
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


@admin_bp.route('/generate-beneficiaries-list')
@login_required
@role_required('admin')
def generate_beneficiaries_list():
    """Generate a JPG image of approved beneficiaries list"""
    try:
        # Get all approved applications with user and community profile data
        approved_applications = Applications.query.filter_by(
            application_status='approved'
        ).join(
            User, Applications.user_id == User.id
        ).join(
            CommunityUsers, User.id == CommunityUsers.user_id
        ).order_by(Applications.id).all()
        
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
        
        return send_file(
            img_io,
            mimetype='image/jpeg',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        flash(f'Error generating beneficiaries list: {str(e)}', 'error')
        return redirect(url_for('admin.applications'))