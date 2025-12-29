from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, or_, func
from sqlalchemy.orm import joinedload
from app.admin import admin_bp
from app.models import Programs, Requirements, ProgramRequirements, Applications, FileAttachment
from app.extensions import db
from app.utils import role_required
import os
from werkzeug.utils import secure_filename

# Configuration
UPLOAD_FOLDER = 'static/uploads/programs'
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@admin_bp.route('/programs', endpoint='adm_programs')
@login_required
@role_required('admin')
def programs_index():
    """Display all programs with search and filter"""
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # Get filter parameters
    search = request.args.get('search', '').strip()
    type_filter = request.args.get('type', '').strip()
    period_filter = request.args.get('period', '').strip()
    date_range = request.args.get('date_range', '').strip()
    
    # Base query
    query = Programs.query.options(
        db.joinedload(Programs.program_requirements)
        .joinedload(ProgramRequirements.requirement)
    )
    
    # Apply search filter
    if search:
        search_filter = or_(
            Programs.program_name.contains(search),
            Programs.description.contains(search)
        )
        query = query.filter(search_filter)
    
    # Apply type filter
    if type_filter:
        query = query.filter_by(program_type=type_filter)
    
    # Apply period filter
    if period_filter:
        query = query.filter_by(program_period=period_filter)
    
    # Apply date range filter
    if date_range:
        today = datetime.utcnow()
        if date_range == 'today':
            start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.filter(Programs.date >= start_date)
        elif date_range == 'week':
            start_date = today - timedelta(days=7)
            query = query.filter(Programs.date >= start_date)
        elif date_range == 'month':
            start_date = today - timedelta(days=30)
            query = query.filter(Programs.date >= start_date)
        elif date_range == 'year':
            start_date = today - timedelta(days=365)
            query = query.filter(Programs.date >= start_date)
    
    # Order by creation date (newest first)
    query = query.order_by(desc(Programs.date))
    
    # Paginate results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Get all program types and periods for filters
    program_types = db.session.query(Programs.program_type).distinct().all()
    program_periods = db.session.query(Programs.program_period).distinct().all()
    
    # Calculate statistics
    total_programs = Programs.query.count()
    
    # Programs with applications
    programs_with_apps = db.session.query(func.count(func.distinct(Applications.program_id))).scalar()
    
    # Most popular program type
    popular_type = db.session.query(
        Programs.program_type,
        func.count(Applications.id).label('app_count')
    ).outerjoin(Applications).group_by(Programs.program_type)\
     .order_by(desc('app_count')).first()
    
    # Recent programs count (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_programs = Programs.query.filter(Programs.date >= thirty_days_ago).count()
    
    # Add application count to each program
    for program in pagination.items:
        program.application_count = Applications.query.filter_by(program_id=program.id).count()
        program.requirement_count = ProgramRequirements.query.filter_by(program_id=program.id).count()
    
    # Get all requirements for the add program modal
    all_requirements = Requirements.query.order_by(Requirements.requirement_name).all()
    
    return render_template(
        'admin/adm_programs.html',  
        programs=pagination.items,
        pagination=pagination,
        total_programs=total_programs,
        programs_with_apps=programs_with_apps,
        popular_type=popular_type.program_type if popular_type else 'N/A',
        recent_programs=recent_programs,
        program_types=[t[0] for t in program_types],
        program_periods=[p[0] for p in program_periods],
        requirements=all_requirements,  # Add this line
        user=current_user,
        today=datetime.utcnow().date()
    )

@admin_bp.route('/programs/add', endpoint='add_program', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_program():
    """Add a new program"""
    if request.method == 'GET':
        # Get all requirements for the form
        requirements = Requirements.query.order_by(
            Requirements.requirement_type,
            Requirements.requirement_name
        ).all()
        return render_template('admin/add_program.html', 
                             requirements=requirements,
                             user=current_user)
    
    if request.method == 'POST':
        program_name = request.form.get('program_name', '').strip()
        program_type = request.form.get('program_type', '').strip()
        program_period = request.form.get('program_period', '').strip()
        description = request.form.get('description', '').strip()
        priority_groups = request.form.getlist('priority_group')  # Get selected priority groups
        priority_group = ', '.join(priority_groups) if priority_groups else None  # Convert to comma-separated string
        beneficiary_limit_str = request.form.get('beneficiary_limit', '').strip()
        beneficiary_limit = int(beneficiary_limit_str) if beneficiary_limit_str and beneficiary_limit_str.isdigit() else None
        income_range = request.form.get('income_range', '').strip() or None
        
        # Get duration fields
        start_date_str = request.form.get('start_date', '').strip()
        end_date_str = request.form.get('end_date', '').strip()
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
        
        # Get selected requirements
        requirement_ids = request.form.getlist('requirements')
        mandatory_requirements = request.form.getlist('mandatory_requirements')
        
        # Validation
        if not program_name or not program_type or not program_period:
            flash('Program name, type, and period are required.', 'danger')
            return redirect(url_for('admin.adm_programs'))
        
        # Validate date range
        if start_date and end_date and end_date < start_date:
            flash('Program end date must be after start date.', 'danger')
            return redirect(url_for('admin.add_program'))
        
        # Handle file upload
        file_attachment = None
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file and file.filename and allowed_file(file.filename):
                # Create upload directory
                upload_path = os.path.join(UPLOAD_FOLDER)
                os.makedirs(upload_path, exist_ok=True)
                
                # Secure filename and save
                filename = secure_filename(file.filename)
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                unique_filename = f"{timestamp}_{filename}"
                file_path = os.path.join(upload_path, unique_filename)
                
                file.save(file_path)
                
                # Create file attachment record
                file_attachment = FileAttachment(
                    filename=filename,
                    file_path=file_path.replace('\\', '/'),
                    file_size=os.path.getsize(file_path),
                    file_type=filename.rsplit('.', 1)[1].lower(),
                    uploaded_by_id=current_user.id,
                    attachment_type='program_document'
                )
                db.session.add(file_attachment)
                db.session.flush()
        
        # Create new program
        new_program = Programs(
            program_name=program_name,
            program_type=program_type,
            program_period=program_period,
            priority_group=priority_group,
            beneficiary_limit=beneficiary_limit,
            income_range=income_range,
            start_date=start_date,
            end_date=end_date,
            description=description,
            user_id=current_user.id,
            file_attachment_id=file_attachment.id if file_attachment else None,
            date=datetime.utcnow()
        )
        
        try:
            db.session.add(new_program)
            db.session.flush()  # Get program ID
            
            # Add program requirements
            for req_id in requirement_ids:
                is_mandatory = str(req_id) in mandatory_requirements
                prog_req = ProgramRequirements(
                    program_id=new_program.id,
                    requirement_id=int(req_id),
                    is_mandatory=is_mandatory
                )
                db.session.add(prog_req)
            
            db.session.commit()
            flash(f'Program "{program_name}" created successfully!', 'success')
            return redirect(url_for('admin.adm_programs'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating program: {str(e)}', 'danger')
            return redirect(url_for('admin.adm_programs'))
        
@admin_bp.route('/programs/edit/<int:id>', endpoint='edit_program', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_program(id):
    """View and edit an existing program"""
    program = Programs.query.options(
        db.joinedload(Programs.program_requirements)
        .joinedload(ProgramRequirements.requirement),
        db.joinedload(Programs.applications)  # Load applications for counting
    ).get_or_404(id)
    
    if request.method == 'GET':
        # Get all requirements for the form
        requirements = Requirements.query.order_by(
            Requirements.requirement_type,
            Requirements.requirement_name
        ).all()
        
        # Get existing program requirements
        existing_reqs = {pr.requirement_id: pr.is_mandatory for pr in program.program_requirements}
        
        # Add application and requirement counts
        program.application_count = Applications.query.filter_by(program_id=program.id).count()
        program.requirement_count = ProgramRequirements.query.filter_by(program_id=program.id).count()
        
        return render_template('admin/view_edit_program.html',
                             program=program,
                             requirements=requirements,
                             existing_reqs=existing_reqs,
                             user=current_user,
                             today=datetime.utcnow().date())
    
    # POST request - update program
    program_name = request.form.get('program_name', '').strip()
    program_type = request.form.get('program_type', '').strip()
    program_period = request.form.get('program_period', '').strip()
    description = request.form.get('description', '').strip()
    priority_groups = request.form.getlist('priority_group')  # Get selected priority groups
    priority_group = ', '.join(priority_groups) if priority_groups else None  # Convert to comma-separated string
    beneficiary_limit_str = request.form.get('beneficiary_limit', '').strip()
    beneficiary_limit = int(beneficiary_limit_str) if beneficiary_limit_str and beneficiary_limit_str.isdigit() else None
    income_range = request.form.get('income_range', '').strip() or None
    
    # Get duration fields
    start_date_str = request.form.get('start_date', '').strip()
    end_date_str = request.form.get('end_date', '').strip()
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
    
    # Validation
    if not program_name or not program_type or not program_period:
        flash('Program name, type, and period are required.', 'danger')
        return redirect(url_for('admin.edit_program', id=id))
    
    # Validate date range
    if start_date and end_date and end_date < start_date:
        flash('Program end date must be after start date.', 'danger')
        return redirect(url_for('admin.edit_program', id=id))
    
    # Update program
    program.program_name = program_name
    program.program_type = program_type
    program.program_period = program_period
    program.priority_group = priority_group
    program.beneficiary_limit = beneficiary_limit
    program.income_range = income_range
    program.start_date = start_date
    program.end_date = end_date
    program.description = description
    
    try:
        # Handle file upload
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file and file.filename and allowed_file(file.filename):
                # Delete old file if exists
                if program.file_attachment:
                    old_file_path = program.file_attachment.file_path
                    if os.path.exists(old_file_path):
                        os.remove(old_file_path)
                    db.session.delete(program.file_attachment)
                
                # Create upload directory
                upload_path = os.path.join(UPLOAD_FOLDER)
                os.makedirs(upload_path, exist_ok=True)
                
                # Save new file
                filename = secure_filename(file.filename)
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                unique_filename = f"{timestamp}_{filename}"
                file_path = os.path.join(upload_path, unique_filename)
                
                file.save(file_path)
                
                # Create new file attachment record
                file_attachment = FileAttachment(
                    filename=filename,
                    file_path=file_path.replace('\\', '/'),
                    file_size=os.path.getsize(file_path),
                    file_type=filename.rsplit('.', 1)[1].lower(),
                    uploaded_by_id=current_user.id,
                    attachment_type='program_document'
                )
                db.session.add(file_attachment)
                db.session.flush()
                program.file_attachment_id = file_attachment.id
        
        # Update requirements
        requirement_ids = request.form.getlist('requirements')
        mandatory_requirements = request.form.getlist('mandatory_requirements')
        
        # Delete existing requirements
        ProgramRequirements.query.filter_by(program_id=id).delete()
        
        # Add new requirements
        for req_id in requirement_ids:
            is_mandatory = str(req_id) in mandatory_requirements
            prog_req = ProgramRequirements(
                program_id=id,
                requirement_id=int(req_id),
                is_mandatory=is_mandatory
            )
            db.session.add(prog_req)
        
        db.session.commit()
        flash(f'Program "{program_name}" updated successfully!', 'success')
        return redirect(url_for('admin.edit_program', id=id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating program: {str(e)}', 'danger')
        return redirect(url_for('admin.edit_program', id=id))

@admin_bp.route('/programs/delete/<int:id>', endpoint='delete_program', methods=['POST'])
@login_required
@role_required('admin')
def delete_program(id):
    """Delete a program"""
    program = Programs.query.get_or_404(id)
    program_name = program.program_name
    
    # Check if program has applications
    app_count = Applications.query.filter_by(program_id=id).count()
    if app_count > 0:
        flash(f'Cannot delete program "{program_name}" because it has {app_count} application(s).', 'danger')
        return redirect(url_for('admin.adm_programs'))
    
    try:
        # Delete associated file if exists
        if program.file_attachment:
            file_path = program.file_attachment.file_path
            if os.path.exists(file_path):
                os.remove(file_path)
            db.session.delete(program.file_attachment)
        
        # Delete program requirements
        ProgramRequirements.query.filter_by(program_id=id).delete()
        
        # Delete program
        db.session.delete(program)
        db.session.commit()
        
        flash(f'Program "{program_name}" deleted successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting program: {str(e)}', 'danger')
    
    return redirect(url_for('admin.adm_programs'))

@admin_bp.route('/programs/view/<int:id>', endpoint='view_program')
@login_required
@role_required('admin')
def view_program(id):
    """View program details"""
    program = Programs.query.get_or_404(id)
    
    # Get program requirements
    requirements = db.session.query(
        Requirements,
        ProgramRequirements.is_mandatory
    ).join(
        ProgramRequirements,
        (Requirements.id == ProgramRequirements.requirement_id) &
        (ProgramRequirements.program_id == id)
    ).all()
    
    # Get application statistics
    total_applications = Applications.query.filter_by(program_id=id).count()
    pending_apps = Applications.query.filter_by(
        program_id=id,
        application_status='pending'
    ).count()
    approved_apps = Applications.query.filter_by(
        program_id=id,
        application_status='approved'
    ).count()
    
    # Get recent applications
    recent_applications = Applications.query.filter_by(
        program_id=id
    ).order_by(desc(Applications.application_date)).limit(5).all()
    
    return render_template(
        'admin/view_program.html',
        program=program,
        requirements=requirements,
        total_applications=total_applications,
        pending_apps=pending_apps,
        approved_apps=approved_apps,
        recent_applications=recent_applications,
        user=current_user
    )

@admin_bp.route('/programs/<int:id>/requirements', methods=['GET'])
@login_required
@role_required('admin')
def get_program_requirements(id):
    """Get program requirements as JSON"""
    requirements = db.session.query(
        Requirements.id,
        Requirements.document_name,
        ProgramRequirements.is_mandatory
    ).join(
        ProgramRequirements,
        (Requirements.id == ProgramRequirements.requirement_id) &
        (ProgramRequirements.program_id == id)
    ).all()
    
    return jsonify([{
        'id': req[0],
        'name': req[1],
        'is_mandatory': req[2]
    } for req in requirements])

@admin_bp.route('/requirements/add-ajax', endpoint='add_requirement_ajax', methods=['POST'])
@login_required
@role_required('admin')
def add_requirement_ajax():
    """Add a new requirement via AJAX"""
    try:
        data = request.get_json()
        
        requirement_name = data.get('requirement_name', '').strip()
        requirement_type = data.get('requirement_type', 'document').strip()
        description = data.get('description', '').strip()
        
        # Validation
        if not requirement_name:
            return jsonify({
                'success': False,
                'message': 'Requirement name is required'
            }), 400
        
        if requirement_type not in ['document', 'qualification']:
            return jsonify({
                'success': False,
                'message': 'Invalid requirement type'
            }), 400
        
        # Check if requirement already exists
        existing = Requirements.query.filter_by(
            requirement_name=requirement_name,
            requirement_type=requirement_type
        ).first()
        
        if existing:
            return jsonify({
                'success': False,
                'message': f'A {requirement_type} requirement with this name already exists'
            }), 400
        
        # Create new requirement
        new_requirement = Requirements(
            requirement_name=requirement_name,
            requirement_type=requirement_type,
            description=description if description else None
        )
        
        db.session.add(new_requirement)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Requirement added successfully',
            'requirement': {
                'id': new_requirement.id,
                'name': new_requirement.requirement_name,
                'type': new_requirement.requirement_type,
                'description': new_requirement.description
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error adding requirement: {str(e)}'
        }), 500
