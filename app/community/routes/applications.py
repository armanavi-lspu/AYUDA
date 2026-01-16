from flask import render_template, request, flash, redirect, url_for, send_file
from flask_login import login_required, current_user
from datetime import datetime
from app.community import community_bp
from app.utils import role_required
from app.models import Applications, Programs, ApplicationDocuments, ProgramRequirements, Requirements
from app.extensions import db
from sqlalchemy import desc, or_
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
        elif status_filter == 'on-hold':
            query = query.filter(Applications.application_status.in_(['on-hold']))
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
            Applications.application_status.in_(['pending'])
        ).count(),
        'returned': total_applications.filter(or_(
            Applications.application_status == 'rejected',
            Applications.remarks.isnot(None)
        )).count(),
        'approved': total_applications.filter_by(application_status='approved').count()
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
    """Display detailed information about a specific application"""
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    # Get all requirements with their details
    all_requirements = db.session.query(
        ApplicationDocuments,
        ProgramRequirements.is_mandatory,
        Requirements.requirement_name,
        Requirements.description,
        Requirements.requirement_type
    ).join(
        Requirements,
        ApplicationDocuments.requirement_id == Requirements.id
    ).join(
        ProgramRequirements,
        (ApplicationDocuments.requirement_id == ProgramRequirements.requirement_id) &
        (ProgramRequirements.program_id == application.program_id)
    ).filter(
        ApplicationDocuments.application_id == application_id
    ).all()
    
    # Separate documents and qualifications
    document_requirements = []
    qualification_requirements = []
    
    for doc, is_mandatory, req_name, description, req_type in all_requirements:
        if req_type == 'document':
            document_requirements.append((doc, is_mandatory, req_name, description))
        elif req_type == 'qualification':
            qualification_requirements.append((doc, is_mandatory, req_name, description))
    
    return render_template(
        'community/application_details.html',
        application=application,
        document_requirements=document_requirements,
        qualification_requirements=qualification_requirements,
        datetime=datetime,
        user=current_user,
        today=datetime.utcnow().date()
    )


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
    return redirect(url_for('community.application_detail', application_id=application_id))


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
            flash(f'This verification code has already been used on {application.code_used_at.strftime("%B %d, %Y at %I:%M %p")}.', 'warning')
            return redirect(url_for('community.application_detail', application_id=application.id))
        
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
            return redirect(url_for('community.application_detail', application_id=application.id))
            
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
        
        program_name = application.program.program_name
        
        # Delete all application documents and their files
        app_docs = ApplicationDocuments.query.filter_by(application_id=application_id).all()
        for doc in app_docs:
            if doc.file_path and os.path.exists(doc.file_path):
                try:
                    os.remove(doc.file_path)
                except:
                    pass
            db.session.delete(doc)
        
        # Delete all shelter photos and their files
        if application.shelter_photos:
            for photo in application.shelter_photos:
                if photo.photo_path and os.path.exists(photo.photo_path):
                    try:
                        os.remove(photo.photo_path)
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
        return redirect(url_for('community.application_detail', application_id=application_id))
