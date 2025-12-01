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
    
    # Get document checklist with requirement details
    documents = db.session.query(
        ApplicationDocuments,
        ProgramRequirements.is_mandatory,
        Requirements.requirement_name,
        Requirements.description
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
    
    return render_template(
        'community/application_details.html',
        application=application,
        documents=documents,
        datetime=datetime,
        user=current_user
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
    """Display printable application slip - only available after admin approval"""    
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    # Only allow access to application slip if application is approved
    if application.application_status != 'approved':
        flash('Application slip is only available after your application has been approved by the admin.', 'warning')
        return redirect(url_for('community.application_detail', application_id=application_id))
    
    # Get requirements for this application - FIXED QUERY
    requirements = db.session.query(
        Requirements,
        ProgramRequirements.is_mandatory
    ).join(
        ApplicationDocuments,
        Requirements.id == ApplicationDocuments.requirement_id
    ).join(
        ProgramRequirements,
        (Requirements.id == ProgramRequirements.requirement_id) &
        (ProgramRequirements.program_id == application.program_id)
    ).filter(
        ApplicationDocuments.application_id == application_id
    ).all()
    
    return render_template(
        'community/application_slip.html',
        application=application,
        requirements=requirements,
        user=current_user
    )