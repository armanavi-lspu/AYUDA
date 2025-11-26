from flask import render_template, jsonify, redirect, url_for, request, flash, send_file
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, or_, func
from app.admin import admin_bp
from app.utils import role_required
from app.models import Programs, Requirements, ProgramRequirements, Applications, ApplicationDocuments, Notifications, User
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
        ProgramRequirements.program_id == application.program_id,
        Requirements.requirement_type == 'document'  # Only show document requirements
    ).order_by(
        ProgramRequirements.is_mandatory.desc(),
        Requirements.requirement_name
    ).all()
    
    # Format documents for template - combine program requirements with application documents
    documents = []
    for prog_req, requirement, app_doc in program_requirements:
        # Create or use existing application document
        if app_doc is None:
            # Create a temporary object for display purposes
            class TempDoc:
                def __init__(self, req, prog_req):
                    self.id = None
                    self.requirement = req
                    self.is_mandatory = prog_req.is_mandatory
                    self.submission_status = 'not_submitted'
                    self.admin_feedback = None
                    self.notes = None
                    self.verified_at = None
                    self.verified_by = None
            
            doc = TempDoc(requirement, prog_req)
        else:
            # Use existing application document
            doc = app_doc
            doc.is_mandatory = prog_req.is_mandatory
            doc.requirement = requirement
        
        documents.append(doc)
    
    return render_template(
        'admin/view_application.html',
        application=application,
        documents=documents,
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
        
        # Create notification for applicant
        status_messages = {
            'approved': f'Your application for {application.program.program_name} has been approved! You can now download your application slip and submit the required documents at the MSWD Office.',
            'rejected': f'Your application for {application.program.program_name} has been rejected. Please check the remarks for more information.',
            'on-hold': f'Your application for {application.program.program_name} is on hold. Please check the remarks for more information.',
            'pending': f'Your application for {application.program.program_name} status has been updated to pending.'
        }
        
        notification = Notifications(
            user_id=application.user_id,
            notif_title=f'Application Status Update',
            notif_message=status_messages.get(new_status, 'Your application status has been updated.'),
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