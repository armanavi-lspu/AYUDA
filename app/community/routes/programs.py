from flask import render_template, jsonify, redirect, url_for, request, flash, send_file
from flask_login import login_required, current_user
from app.community import community_bp
from datetime import datetime
from app.models import Programs, Requirements, ProgramRequirements, Applications, ApplicationDocuments, Notifications
from app.extensions import db
from app.utils import role_required
from sqlalchemy import desc, func

@community_bp.route('/programs')
@login_required
@role_required('community')
def programs():
    """Display financial assistance programs by category"""
    
    # Define program categories with their types
    categories = {
        'AICS': 'Assistance to Individuals in Crisis Situation (AICS)',
        'Emergency Shelter': 'Emergency Shelter Assistance', 
        '4Ps': 'Pantawid Pamilyang Pilipino Program (4Ps)',
        'SLP': 'Sustainable Livelihood Program (SLP)'
    }
    
    # Get program counts by category
    program_stats = {}
    total_programs = 0
    
    for category_key, category_name in categories.items():
        count = Programs.query.filter_by(program_type=category_key).count()
        program_stats[category_key] = {
            'name': category_name,
            'count': count
        }
        total_programs += count
    
    # Total categories count
    total_categories = len(categories)
    
    return render_template('community/programs_category.html',
                         categories=program_stats,
                         total_categories=total_categories,
                         total_programs=total_programs)

@community_bp.route('/programs/category/<category>')
@login_required  
@role_required('community')
def programs_by_category(category):
    """Display programs for a specific category"""
    
    # Category mapping
    category_names = {
        'AICS': 'Assistance to Individuals in Crisis Situation (AICS)',
        'Emergency Shelter Assistance': 'Emergency Shelter Assistance',
        '4Ps': 'Pantawid Pamilyang Pilipino Program (4Ps)', 
        'SLP': 'Sustainable Livelihood Program (SLP)'
    }
    
    if category not in category_names:
        return redirect(url_for('community.programs_category'))
    
    # Get programs for this category
    programs = Programs.query.filter_by(program_type=category).order_by(desc(Programs.date)).all()
    
    return render_template('community/programs_list.html',
                         programs=programs,
                         category=category,
                         category_name=category_names[category],
                         total_programs=len(programs))

@community_bp.route('/program/<int:program_id>')
@login_required
@role_required('community')
def program_detail(program_id):
    """Display detailed information about a specific program"""
    program = Programs.query.get_or_404(program_id)
    
    # Get program requirements with is_mandatory info from junction table
    program_requirements = db.session.query(
        Requirements, ProgramRequirements.is_mandatory
    ).join(
        ProgramRequirements, 
        Requirements.id == ProgramRequirements.requirement_id
    ).filter(
        ProgramRequirements.program_id == program_id
    ).all()
    
    # Format requirements for template
    requirements = [
        {
            'id': req.id,
            'document_name': req.document_name,
            'description': req.description,
            'is_mandatory': is_mandatory
        }
        for req, is_mandatory in program_requirements
    ]
    
    return render_template('community/program_detail.html',
                         program=program,
                         requirements=requirements)
    
@community_bp.route('/program/<int:program_id>/apply', methods=['POST'])
@login_required
@role_required('community')
def submit_application(program_id):
    """Create an application for a program"""
    program = Programs.query.get_or_404(program_id)
    
    # Check if user already has a pending application
    existing_application = Applications.query.filter_by(
        user_id=current_user.id,
        program_id=program_id
    ).filter(Applications.application_status.in_(['pending', 'submitted', 'under_review'])).first()
    
    if existing_application:
        flash('You already have a pending application for this program.', 'warning')
        return redirect(url_for('community.program_detail', program_id=program_id))
    
    # Create new application
    new_application = Applications(
        user_id=current_user.id,
        program_id=program_id,
        application_status='pending',
        application_date=datetime.utcnow()
    )
    
    db.session.add(new_application)
    db.session.flush()  # Get the ID
    
    # Get requirements and create application documents checklist
    program_requirements = ProgramRequirements.query.filter_by(program_id=program_id).all()
    for req_link in program_requirements:
        app_doc = ApplicationDocuments(
            application_id=new_application.id,
            requirement_id=req_link.requirement_id,
            submission_status='not_submitted'
        )
        db.session.add(app_doc)
    
    # Create notification
    notification = Notifications(
        user_id=current_user.id,
        notif_title='Application Submitted',
        notif_message=f'Your application for {program.program_name} has been created. Application ID: {new_application.id}',
        is_read=False
    )
    db.session.add(notification)
    db.session.commit()
    
    flash('Application created successfully! Print your application slip.', 'success')
    
    # Redirect to application slip
    return redirect(url_for('community.application_slip', application_id=new_application.id))