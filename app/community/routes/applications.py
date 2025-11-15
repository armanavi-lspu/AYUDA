from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app.community import community_bp
from app.utils import role_required
from app.models import Applications, Programs, ApplicationDocuments, ProgramRequirements
from app.extensions import db
from sqlalchemy import desc, or_

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
            # Pending includes: pending, submitted, under_review
            query = query.filter(Applications.application_status.in_(['pending', 'submitted', 'under_review']))
        elif status_filter == 'returned':
            # Returned includes: rejected, needs_revision (applications with admin feedback)
            query = query.filter(or_(
                Applications.application_status == 'rejected',
                Applications.remarks.isnot(None)
            ))
        else:
            query = query.filter_by(application_status=status_filter)
    
    # Order by application date (newest first)
    query = query.order_by(desc(Applications.application_date))
    
    # Paginate results
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
            Applications.application_status.in_(['pending', 'submitted', 'under_review'])
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
        ProgramRequirements.is_mandatory
    ).join(
        ProgramRequirements,
        (ApplicationDocuments.requirement_id == ProgramRequirements.requirement_id) &
        (ProgramRequirements.program_id == application.program_id)
    ).filter(
        ApplicationDocuments.application_id == application_id
    ).all()
    
    return render_template(
        'community/application_detail.html',
        application=application,
        documents=documents,
        user=current_user
    )

@community_bp.route('/applications/<int:application_id>/slip')
@login_required
@role_required('community')
def application_slip(application_id):
    """Display printable application slip"""
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    # Get requirements for this application
    requirements = db.session.query(
        ApplicationDocuments.requirement,
        ProgramRequirements.is_mandatory
    ).join(
        ProgramRequirements,
        (ApplicationDocuments.requirement_id == ProgramRequirements.requirement_id) &
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