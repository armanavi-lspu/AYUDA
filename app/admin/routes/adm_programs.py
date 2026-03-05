from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, or_, func
from sqlalchemy.orm import joinedload
from app.admin import admin_bp
from app.models import Programs, Requirements, ProgramRequirements, Applications, FileAttachment, CommunityUsers, User, Announcements, Notifications
from app.extensions import db
from app.utils import role_required
from app.activity_logger import log_activity
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
    category_filter = request.args.get('category', '').strip()
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
    
    # Apply category filter
    if category_filter:
        query = query.filter_by(program_type=category_filter)
    
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
        program.active_application_count = Applications.query.filter_by(program_id=program.id, application_status='active').count()
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


# ===================== SUBSIDY MANAGEMENT =====================

@admin_bp.route('/subsidy', endpoint='adm_subsidy')
@login_required
@role_required('admin')
def subsidy_index():
    """Display subsidy categories with statistics"""
    
    # Get PWD count
    pwd_count = CommunityUsers.query.filter_by(is_pwd=True).count()
    
    # Get Senior Citizen count (age >= 60)
    senior_count = CommunityUsers.query.filter(CommunityUsers.age >= 60).count()
    
    # Get Solo Parent count
    solo_parent_count = CommunityUsers.query.filter_by(is_solo_parent=True).count()
    
    # Total beneficiaries (unique, as one person could be in multiple categories)
    total_beneficiaries = CommunityUsers.query.filter(
        or_(
            CommunityUsers.is_pwd == True,
            CommunityUsers.age >= 60,
            CommunityUsers.is_solo_parent == True
        )
    ).count()
    
    return render_template(
        'admin/adm_subsidy.html',
        pwd_count=pwd_count,
        senior_count=senior_count,
        solo_parent_count=solo_parent_count,
        total_beneficiaries=total_beneficiaries,
        user=current_user
    )


@admin_bp.route('/subsidy/<category>', endpoint='subsidy_list')
@login_required
@role_required('admin')
def subsidy_list(category):
    """Display list of individuals for a specific subsidy category"""
    page = request.args.get('page', 1, type=int)
    per_page = 15
    search = request.args.get('search', '').strip()
    barangay_filter = request.args.get('barangay', '').strip()
    
    # Base query with user join
    query = CommunityUsers.query.join(User, CommunityUsers.user_id == User.id)
    
    # Filter by category
    if category == 'pwd':
        query = query.filter(CommunityUsers.is_pwd == True)
        category_name = 'Persons with Disability (PWD)'
        category_icon = 'fa-wheelchair'
        category_color = 'primary'
    elif category == 'senior':
        query = query.filter(CommunityUsers.age >= 60)
        category_name = 'Senior Citizens'
        category_icon = 'fa-user-clock'
        category_color = 'success'
    elif category == 'solo_parent':
        query = query.filter(CommunityUsers.is_solo_parent == True)
        category_name = 'Solo Parents'
        category_icon = 'fa-user-friends'
        category_color = 'warning'
    else:
        flash('Invalid subsidy category.', 'danger')
        return redirect(url_for('admin.adm_subsidy'))
    
    # Apply search filter
    if search:
        query = query.filter(
            or_(
                User.first_name.ilike(f'%{search}%'),
                User.last_name.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%'),
                CommunityUsers.barangay.ilike(f'%{search}%')
            )
        )
    
    # Apply barangay filter
    if barangay_filter:
        query = query.filter(CommunityUsers.barangay == barangay_filter)
    
    # Get all barangays for filter dropdown
    barangays = db.session.query(CommunityUsers.barangay)\
        .filter(CommunityUsers.barangay.isnot(None))\
        .distinct()\
        .order_by(CommunityUsers.barangay)\
        .all()
    barangays = [b[0] for b in barangays if b[0]]
    
    # Order by name and paginate
    query = query.order_by(User.last_name, User.first_name)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template(
        'admin/subsidy_list.html',
        beneficiaries=pagination.items,
        pagination=pagination,
        category=category,
        category_name=category_name,
        category_icon=category_icon,
        category_color=category_color,
        search=search,
        barangay_filter=barangay_filter,
        barangays=barangays,
        user=current_user
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
        
        # Get toggle settings
        use_beneficiary_limit = request.form.get('use_beneficiary_limit') == 'on'
        use_income_range = request.form.get('use_income_range') == 'on'
        
        # Get online upload and application slip settings
        allow_online_upload = request.form.get('allow_online_upload') == 'on'
        enable_application_slip = request.form.get('enable_application_slip') == 'on'
        
        # If toggles are off, clear the values
        if not use_beneficiary_limit:
            beneficiary_limit = None
        if not use_income_range:
            income_range = None
        
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
            use_beneficiary_limit=use_beneficiary_limit,
            income_range=income_range,
            use_income_range=use_income_range,
            start_date=start_date,
            end_date=end_date,
            description=description,
            user_id=current_user.id,
            file_attachment_id=file_attachment.id if file_attachment else None,
            date=datetime.utcnow(),
            allow_online_upload=allow_online_upload,
            enable_application_slip=enable_application_slip
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
            
            # Add workflow steps
            from app.models import ProgramWorkflowSteps
            import json
            
            workflow_steps_json = request.form.get('workflow_steps_json', '[]')
            try:
                workflow_steps = json.loads(workflow_steps_json)
            except:
                workflow_steps = []
            
            if workflow_steps:
                # Add custom workflow steps from form (non-ESA programs only)
                for index, step_data in enumerate(workflow_steps, start=1):
                    if step_data.get('step_name', '').strip():
                        step = ProgramWorkflowSteps(
                            program_id=new_program.id,
                            step_order=index,
                            step_name=step_data.get('step_name', '').strip(),
                            step_description=step_data.get('step_description', '').strip() or None,
                            step_type=step_data.get('step_type', 'approval'),
                            is_pre_approval=step_data.get('is_pre_approval', False),
                            requires_verification=step_data.get('requires_verification', True),
                            allowed_file_types=step_data.get('allowed_file_types', '').strip() or None,
                            step_config=step_data.get('step_config', None)
                        )
                        db.session.add(step)
            else:
                # Add default workflow steps based on program type
                if program_type == 'ESA':
                    default_steps = [
                        {'step_name': 'Upload Shelter Photos', 'step_description': 'Upload at least 3 photos of your current shelter/housing situation', 'step_type': 'photo_upload', 'is_pre_approval': True, 'requires_verification': True, 'allowed_file_types': 'jpg,jpeg,png,gif'},
                        {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'allowed_file_types': None},
                        {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'allowed_file_types': None}
                    ]
                else:
                    # Default steps for other programs (AICS, CA, etc.)
                    default_steps = [
                        {'step_name': 'Application Review', 'step_description': 'Wait for admin to review and approve your application', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': False, 'allowed_file_types': None},
                        {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'allowed_file_types': None},
                        {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'allowed_file_types': None}
                    ]
                
                for index, step_data in enumerate(default_steps, start=1):
                    step = ProgramWorkflowSteps(
                        program_id=new_program.id,
                        step_order=index,
                        step_name=step_data['step_name'],
                        step_description=step_data['step_description'],
                        step_type=step_data['step_type'],
                        is_pre_approval=step_data['is_pre_approval'],
                        requires_verification=step_data['requires_verification'],
                        allowed_file_types=step_data['allowed_file_types']
                    )
                    db.session.add(step)
            
            db.session.commit()
            success_msg = f'Program "{program_name}" created successfully!'
            flash(success_msg, 'success')
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
    is_ajax = (request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 
               request.headers.get('Content-Type', '').startswith('application/json'))
    
    # Determine what type of update this is based on form data
    update_type = None
    if 'requirements' in request.form and len(request.form) <= 2:  # Only requirements data
        update_type = 'requirements'
    elif 'workflow_steps_json' in request.form and len(request.form) <= 2:  # Only workflow data
        update_type = 'workflow'
    elif 'program_name' in request.form:  # Program info update
        update_type = 'program_info'
    
    try:
        if update_type == 'requirements':
            # Handle requirements-only update
            requirement_ids = request.form.getlist('requirements')
            
            # Delete existing requirements
            ProgramRequirements.query.filter_by(program_id=id).delete()
            
            # Add new requirements (all as mandatory for now)
            for req_id in requirement_ids:
                prog_req = ProgramRequirements(
                    program_id=id,
                    requirement_id=int(req_id),
                    is_mandatory=True  # Default to mandatory
                )
                db.session.add(prog_req)
            
            # Update the last modified timestamp
            Programs.query.filter_by(id=id).update({'updated_at': datetime.utcnow()})
            
            db.session.commit()
            success_msg = 'Requirements updated successfully!'
            if is_ajax:
                return jsonify({'success': True, 'message': success_msg})
            flash(success_msg, 'success')
            return redirect(url_for('admin.edit_program', id=id))
            
        elif update_type == 'workflow':
            # Handle workflow-only update
            from app.models import ProgramWorkflowSteps, ApplicationWorkflowStatus
            import json
            
            workflow_steps_json = request.form.get('workflow_steps_json', '[]')
            try:
                workflow_steps = json.loads(workflow_steps_json)
            except:
                workflow_steps = []
            
            # Delete dependent application workflow statuses first
            workflow_step_ids = db.session.query(ProgramWorkflowSteps.id).filter_by(program_id=id).all()
            if workflow_step_ids:
                workflow_step_ids = [id[0] for id in workflow_step_ids]
                ApplicationWorkflowStatus.query.filter(ApplicationWorkflowStatus.workflow_step_id.in_(workflow_step_ids)).delete(synchronize_session='fetch')
            
            # Delete existing workflow steps
            ProgramWorkflowSteps.query.filter_by(program_id=id).delete()
            
            # Add workflow steps
            if workflow_steps:
                # Add custom workflow steps (non-ESA programs only)
                for index, step_data in enumerate(workflow_steps, start=1):
                    if step_data.get('step_name', '').strip():
                        step = ProgramWorkflowSteps(
                            program_id=id,
                            step_order=index,
                            step_name=step_data.get('step_name', '').strip(),
                            step_description=step_data.get('step_description', '').strip() or None,
                            step_type=step_data.get('step_type', 'approval'),
                            is_pre_approval=step_data.get('is_pre_approval', False),
                            requires_verification=step_data.get('requires_verification', True),
                            allowed_file_types=step_data.get('allowed_file_types', '').strip() or None,
                            step_config=step_data.get('step_config', None)
                        )
                        db.session.add(step)
            else:
                # Add default workflow steps based on program type
                if program.program_type == 'ESA':
                    default_steps = [
                        {'step_name': 'Upload Shelter Photos', 'step_description': 'Upload at least 3 photos of your current shelter/housing situation', 'step_type': 'photo_upload', 'is_pre_approval': True, 'requires_verification': True, 'allowed_file_types': 'jpg,jpeg,png,gif'},
                        {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'allowed_file_types': None},
                        {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'allowed_file_types': None}
                    ]
                else:
                    # Default steps for other programs (AICS, CA, etc.)
                    default_steps = [
                        {'step_name': 'Application Review', 'step_description': 'Wait for admin to review and approve your application', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': False, 'allowed_file_types': None},
                        {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'allowed_file_types': None},
                        {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'allowed_file_types': None}
                    ]
                
                for index, step_data in enumerate(default_steps, start=1):
                    step = ProgramWorkflowSteps(
                        program_id=id,
                        step_order=index,
                        step_name=step_data['step_name'],
                        step_description=step_data['step_description'],
                        step_type=step_data['step_type'],
                        is_pre_approval=step_data['is_pre_approval'],
                        requires_verification=step_data['requires_verification'],
                        allowed_file_types=step_data['allowed_file_types']
                    )
                    db.session.add(step)
            
            # Update the last modified timestamp
            Programs.query.filter_by(id=id).update({'updated_at': datetime.utcnow()})
            
            db.session.commit()
            success_msg = 'Workflow steps updated successfully!'
            if is_ajax:
                return jsonify({'success': True, 'message': success_msg})
            flash(success_msg, 'success')
            return redirect(url_for('admin.edit_program', id=id))
            
    except Exception as e:
        db.session.rollback()
        error_msg = f'Error updating program: {str(e)}'
        if is_ajax:
            return jsonify({'success': False, 'message': error_msg}), 500
        flash(error_msg, 'danger')
        return redirect(url_for('admin.edit_program', id=id))
    
    # Handle program info update (existing logic)
    program_name = request.form.get('program_name', '').strip()
    program_type = request.form.get('program_type', '').strip()
    program_period = request.form.get('program_period', '').strip()
    description = request.form.get('description', '').strip()
    priority_groups = request.form.getlist('priority_group')  # Get selected priority groups
    priority_group = ', '.join(priority_groups) if priority_groups else None  # Convert to comma-separated string
    beneficiary_limit_str = request.form.get('beneficiary_limit', '').strip()
    beneficiary_limit = int(beneficiary_limit_str) if beneficiary_limit_str and beneficiary_limit_str.isdigit() else None
    income_range = request.form.get('income_range', '').strip() or None
    
    # Get toggle settings
    use_beneficiary_limit = request.form.get('use_beneficiary_limit') == 'on'
    use_income_range = request.form.get('use_income_range') == 'on'
    
    # If toggles are off, clear the values
    if not use_beneficiary_limit:
        beneficiary_limit = None
    if not use_income_range:
        income_range = None
    
    # Get duration fields
    start_date_str = request.form.get('start_date', '').strip()
    end_date_str = request.form.get('end_date', '').strip()
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
    
    # Get online upload and application slip settings
    allow_online_upload = request.form.get('allow_online_upload') == '1' or request.form.get('allow_online_upload') == 'on'
    enable_application_slip = request.form.get('enable_application_slip') == '1' or request.form.get('enable_application_slip') == 'on'
    
    # Validation
    if not program_name or not program_type or not program_period:
        error_msg = 'Program name, type, and period are required.'
        if is_ajax:
            return jsonify({'success': False, 'message': error_msg}), 400
        flash(error_msg, 'danger')
        return redirect(url_for('admin.edit_program', id=id))
    
    # Validate date range
    if start_date and end_date and end_date < start_date:
        error_msg = 'Program end date must be after start date.'
        if is_ajax:
            return jsonify({'success': False, 'message': error_msg}), 400
        flash(error_msg, 'danger')
        return redirect(url_for('admin.edit_program', id=id))
    
    try:
        # Update program info
        program.program_name = program_name
        program.program_type = program_type
        program.program_period = program_period
        program.priority_group = priority_group
        program.beneficiary_limit = beneficiary_limit
        program.use_beneficiary_limit = use_beneficiary_limit
        program.income_range = income_range
        program.use_income_range = use_income_range
        program.start_date = start_date
        program.end_date = end_date
        program.description = description
        program.allow_online_upload = allow_online_upload
        program.enable_application_slip = enable_application_slip
        
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
        
        # Update requirements (only for full program updates, not modal-specific updates)
        if update_type != 'requirements':
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
        
        # Update workflow steps (only for full program updates, not modal-specific updates)
        if update_type != 'workflow':
            from app.models import ProgramWorkflowSteps, ApplicationWorkflowStatus
            import json
            
            workflow_steps_json = request.form.get('workflow_steps_json', '[]')
            try:
                workflow_steps = json.loads(workflow_steps_json)
            except:
                workflow_steps = []
            
            # Delete dependent application workflow statuses first
            workflow_step_ids = db.session.query(ProgramWorkflowSteps.id).filter_by(program_id=id).all()
            if workflow_step_ids:
                workflow_step_ids = [id[0] for id in workflow_step_ids]
                ApplicationWorkflowStatus.query.filter(ApplicationWorkflowStatus.workflow_step_id.in_(workflow_step_ids)).delete(synchronize_session='fetch')
            
            # Delete existing workflow steps
            ProgramWorkflowSteps.query.filter_by(program_id=id).delete()
            
            # Add new workflow steps
            for index, step_data in enumerate(workflow_steps, start=1):
                if step_data.get('step_name', '').strip():
                    step = ProgramWorkflowSteps(
                        program_id=id,
                        step_order=index,
                        step_name=step_data.get('step_name', '').strip(),
                        step_description=step_data.get('step_description', '').strip() or None,
                        step_type=step_data.get('step_type', 'approval'),
                        is_pre_approval=step_data.get('is_pre_approval', False),
                        requires_verification=step_data.get('requires_verification', True),
                        allowed_file_types=step_data.get('allowed_file_types', '').strip() or None,
                        step_config=step_data.get('step_config', None)
                    )
                    db.session.add(step)
        
        # Update the last modified timestamp
        program.updated_at = datetime.utcnow()
        
        # Log program edit
        log_activity(
            action='edit_program',
            action_type='update',
            entity_type='program',
            description=f'Edited program: {program_name}',
            entity_id=id,
            details={
                'program_type': program_type,
                'program_period': program_period,
                'beneficiary_limit': beneficiary_limit,
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None
            }
        )
        
        db.session.commit()
        success_msg = f'Program "{program_name}" updated successfully!'
        if is_ajax:
            return jsonify({'success': True, 'message': success_msg})
        flash(success_msg, 'success')
        return redirect(url_for('admin.edit_program', id=id))
        
    except Exception as e:
        db.session.rollback()
        error_msg = f'Error updating program: {str(e)}'
        if is_ajax:
            return jsonify({'success': False, 'message': error_msg}), 500
        flash(error_msg, 'danger')
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
    approved_apps = Applications.query.filter(
        Applications.program_id == id,
        Applications.application_status.in_(['approved', 'active', 'completed'])
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


@admin_bp.route('/requirements/<int:requirement_id>/edit-ajax', endpoint='edit_requirement_ajax', methods=['PUT'])
@login_required
@role_required('admin')
def edit_requirement_ajax(requirement_id):
    """Edit an existing requirement via AJAX"""
    try:
        requirement = Requirements.query.get_or_404(requirement_id)
        data = request.get_json()
        
        requirement_name = data.get('requirement_name', '').strip()
        description = data.get('description', '').strip()
        
        # Validation
        if not requirement_name:
            return jsonify({
                'success': False,
                'message': 'Requirement name is required'
            }), 400
        
        # Check if requirement name already exists for another requirement of same type
        existing = Requirements.query.filter(
            Requirements.requirement_name == requirement_name,
            Requirements.requirement_type == requirement.requirement_type,
            Requirements.id != requirement_id
        ).first()
        
        if existing:
            return jsonify({
                'success': False,
                'message': f'A {requirement.requirement_type} requirement with this name already exists'
            }), 400
        
        # Update requirement
        requirement.requirement_name = requirement_name
        requirement.description = description if description else None
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Requirement updated successfully',
            'requirement': {
                'id': requirement.id,
                'name': requirement.requirement_name,
                'type': requirement.requirement_type,
                'description': requirement.description
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error updating requirement: {str(e)}'
        }), 500


@admin_bp.route('/requirements/<int:requirement_id>/delete-ajax', endpoint='delete_requirement_ajax', methods=['DELETE'])
@login_required
@role_required('admin')
def delete_requirement_ajax(requirement_id):
    """Delete an existing requirement via AJAX"""
    try:
        requirement = Requirements.query.get_or_404(requirement_id)
        
        # Check if requirement is used in any programs
        from app.models import ProgramRequirements
        usage_count = ProgramRequirements.query.filter_by(requirement_id=requirement_id).count()
        
        if usage_count > 0:
            return jsonify({
                'success': False,
                'message': f'Cannot delete requirement. It is used in {usage_count} program(s). Remove it from programs first.'
            }), 400
        
        requirement_name = requirement.requirement_name
        db.session.delete(requirement)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Requirement "{requirement_name}" deleted successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error deleting requirement: {str(e)}'
        }), 500


@admin_bp.route('/requirements/manage', endpoint='manage_requirements')
@login_required
@role_required('admin')
def manage_requirements():
    """Display comprehensive requirements management page"""
    try:
        # Get all requirements with usage statistics
        requirements = db.session.query(
            Requirements,
            func.count(ProgramRequirements.id).label('usage_count')
        ).outerjoin(
            ProgramRequirements, Requirements.id == ProgramRequirements.requirement_id
        ).group_by(Requirements.id).all()
        
        # Separate by type
        document_requirements = []
        qualification_requirements = []
        
        for req, usage_count in requirements:
            req_data = {
                'requirement': req,
                'usage_count': usage_count,
                'programs': []
            }
            
            # Get programs using this requirement
            program_reqs = ProgramRequirements.query.filter_by(requirement_id=req.id).all()
            for prog_req in program_reqs:
                req_data['programs'].append({
                    'program': prog_req.program,
                    'is_mandatory': prog_req.is_mandatory
                })
            
            if req.requirement_type == 'document':
                document_requirements.append(req_data)
            else:
                qualification_requirements.append(req_data)
        
        # Sort by name
        document_requirements.sort(key=lambda x: x['requirement'].requirement_name)
        qualification_requirements.sort(key=lambda x: x['requirement'].requirement_name)
        
        # Get summary statistics
        total_requirements = len(requirements)
        document_count = len(document_requirements)
        qualification_count = len(qualification_requirements)
        used_requirements = len([req for req, count in requirements if count > 0])
        unused_requirements = total_requirements - used_requirements
        
        stats = {
            'total': total_requirements,
            'document': document_count,
            'qualification': qualification_count,
            'used': used_requirements,
            'unused': unused_requirements
        }
        
        return render_template('admin/manage_requirements.html',
                             document_requirements=document_requirements,
                             qualification_requirements=qualification_requirements,
                             stats=stats)
        
    except Exception as e:
        flash(f'Error loading requirements: {str(e)}', 'danger')
        return redirect(url_for('admin.adm_programs'))


# ============================================
# WORKFLOW STEPS MANAGEMENT ROUTES
# ============================================

@admin_bp.route('/programs/<int:program_id>/workflow-steps', methods=['POST'])
@login_required
@role_required('admin')
def add_workflow_step(program_id):
    """Add a new workflow step to a program"""
    from app.models import ProgramWorkflowSteps
    
    program = Programs.query.get_or_404(program_id)
    
    try:
        data = request.get_json() if request.is_json else request.form
        
        step_name = data.get('step_name', '').strip()
        step_description = data.get('step_description', '').strip()
        step_type = data.get('step_type', 'approval').strip()
        is_pre_approval = data.get('is_pre_approval') in [True, 'true', 'True', '1', 1, 'on']
        requires_verification = data.get('requires_verification') in [True, 'true', 'True', '1', 1, 'on']
        allowed_file_types = data.get('allowed_file_types', '').strip()
        
        if not step_name:
            return jsonify({'success': False, 'message': 'Step name is required'}), 400
        
        # Get the next step order
        max_order = db.session.query(db.func.max(ProgramWorkflowSteps.step_order)).filter_by(program_id=program_id).scalar()
        next_order = (max_order or 0) + 1
        
        new_step = ProgramWorkflowSteps(
            program_id=program_id,
            step_order=next_order,
            step_name=step_name,
            step_description=step_description if step_description else None,
            step_type=step_type,
            is_pre_approval=is_pre_approval,
            requires_verification=requires_verification,
            allowed_file_types=allowed_file_types if allowed_file_types else None
        )
        
        db.session.add(new_step)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Workflow step added successfully',
            'step': {
                'id': new_step.id,
                'step_order': new_step.step_order,
                'step_name': new_step.step_name,
                'step_description': new_step.step_description,
                'step_type': new_step.step_type,
                'is_pre_approval': new_step.is_pre_approval,
                'requires_verification': new_step.requires_verification,
                'allowed_file_types': new_step.allowed_file_types
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error adding workflow step: {str(e)}'}), 500


@admin_bp.route('/programs/<int:program_id>/workflow-steps/<int:step_id>', methods=['PUT'])
@login_required
@role_required('admin')
def update_workflow_step(program_id, step_id):
    """Update a workflow step"""
    from app.models import ProgramWorkflowSteps
    
    step = ProgramWorkflowSteps.query.filter_by(id=step_id, program_id=program_id).first_or_404()
    
    try:
        data = request.get_json() if request.is_json else request.form
        
        if 'step_name' in data:
            step.step_name = data['step_name'].strip()
        if 'step_description' in data:
            step.step_description = data['step_description'].strip() or None
        if 'step_type' in data:
            step.step_type = data['step_type'].strip()
        if 'is_pre_approval' in data:
            step.is_pre_approval = data['is_pre_approval'] in [True, 'true', 'True', '1', 1, 'on']
        if 'requires_verification' in data:
            step.requires_verification = data['requires_verification'] in [True, 'true', 'True', '1', 1, 'on']
        if 'allowed_file_types' in data:
            step.allowed_file_types = data['allowed_file_types'].strip() or None
        if 'step_config' in data:
            step.step_config = data['step_config']
        
        step.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Workflow step updated successfully',
            'step': {
                'id': step.id,
                'step_order': step.step_order,
                'step_name': step.step_name,
                'step_description': step.step_description,
                'step_type': step.step_type,
                'is_pre_approval': step.is_pre_approval,
                'requires_verification': step.requires_verification,
                'allowed_file_types': step.allowed_file_types,
                'step_config': step.step_config
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error updating workflow step: {str(e)}'}), 500


@admin_bp.route('/programs/<int:program_id>/workflow-steps/<int:step_id>', methods=['DELETE'])
@login_required
@role_required('admin')
def delete_workflow_step(program_id, step_id):
    """Delete a workflow step"""
    from app.models import ProgramWorkflowSteps
    
    step = ProgramWorkflowSteps.query.filter_by(id=step_id, program_id=program_id).first_or_404()
    deleted_order = step.step_order
    
    try:
        db.session.delete(step)
        
        # Reorder remaining steps
        remaining_steps = ProgramWorkflowSteps.query.filter(
            ProgramWorkflowSteps.program_id == program_id,
            ProgramWorkflowSteps.step_order > deleted_order
        ).order_by(ProgramWorkflowSteps.step_order).all()
        
        for s in remaining_steps:
            s.step_order -= 1
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Workflow step deleted successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error deleting workflow step: {str(e)}'}), 500


@admin_bp.route('/programs/<int:program_id>/workflow-steps/reorder', methods=['POST'])
@login_required
@role_required('admin')
def reorder_workflow_steps(program_id):
    """Reorder workflow steps"""
    from app.models import ProgramWorkflowSteps
    
    program = Programs.query.get_or_404(program_id)
    
    try:
        data = request.get_json()
        step_order = data.get('step_order', [])  # List of step IDs in new order
        
        if not step_order:
            return jsonify({'success': False, 'message': 'Step order is required'}), 400
        
        for index, step_id in enumerate(step_order, start=1):
            step = ProgramWorkflowSteps.query.filter_by(id=step_id, program_id=program_id).first()
            if step:
                step.step_order = index
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Workflow steps reordered successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error reordering steps: {str(e)}'}), 500


@admin_bp.route('/programs/<int:program_id>/workflow-steps/bulk', methods=['POST'])
@login_required
@role_required('admin')
def save_all_workflow_steps(program_id):
    """Save all workflow steps for a program (used when creating/editing program)"""
    from app.models import ProgramWorkflowSteps
    
    program = Programs.query.get_or_404(program_id)
    
    try:
        data = request.get_json()
        steps_data = data.get('steps', [])
        
        # Delete existing steps
        ProgramWorkflowSteps.query.filter_by(program_id=program_id).delete()
        
        # Add new steps
        for index, step_data in enumerate(steps_data, start=1):
            step = ProgramWorkflowSteps(
                program_id=program_id,
                step_order=index,
                step_name=step_data.get('step_name', '').strip(),
                step_description=step_data.get('step_description', '').strip() or None,
                step_type=step_data.get('step_type', 'approval'),
                is_pre_approval=step_data.get('is_pre_approval', False),
                requires_verification=step_data.get('requires_verification', True),
                min_items=int(step_data.get('min_items', 1)),
                allowed_file_types=step_data.get('allowed_file_types', '').strip() or None,
                step_config=step_data.get('step_config', None)
            )
            db.session.add(step)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'{len(steps_data)} workflow steps saved successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error saving workflow steps: {str(e)}'}), 500


@admin_bp.route('/programs/<int:program_id>/workflow-steps', methods=['GET'])
@login_required
@role_required('admin')
def get_workflow_steps(program_id):
    """Get all workflow steps for a program"""
    from app.models import ProgramWorkflowSteps
    
    program = Programs.query.get_or_404(program_id)
    steps = ProgramWorkflowSteps.query.filter_by(program_id=program_id).order_by(ProgramWorkflowSteps.step_order).all()
    
    return jsonify({
        'success': True,
        'program_id': program_id,
        'program_name': program.program_name,
        'steps': [step.to_dict() for step in steps]
    })


@admin_bp.route('/workflow-templates', methods=['GET'])
@login_required
@role_required('admin')
def get_workflow_templates():
    """Get predefined workflow templates for different program types"""
    
    templates = {
        'ESA': {
            'name': 'Emergency Shelter Assistance',
            'description': 'Workflow for ESA programs with shelter photo verification',
            'steps': [
                {'step_name': 'Upload Shelter Photos', 'step_description': 'Upload at least 3 photos of your current shelter/housing situation', 'step_type': 'photo_upload', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 3, 'allowed_file_types': 'jpg,jpeg,png,gif'},
                {'step_name': 'Application Review', 'step_description': 'Admin reviews shelter photos and application', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'min_items': 1, 'allowed_file_types': ''}
            ]
        },
        'AICS': {
            'name': 'Assistance to Individuals in Crisis Situations',
            'description': 'Standard workflow for AICS programs',
            'steps': [
                {'step_name': 'Application Review', 'step_description': 'Admin reviews and approves your application', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'min_items': 1, 'allowed_file_types': ''}
            ]
        },
        'default': {
            'name': 'Standard Workflow',
            'description': 'Default workflow for general programs',
            'steps': [
                {'step_name': 'Application Review', 'step_description': 'Admin reviews and approves your application', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office or online if enabled', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'min_items': 1, 'allowed_file_types': ''}
            ]
        },
        'online_upload': {
            'name': 'Online Document Upload Workflow',
            'description': 'Workflow with online document upload step',
            'steps': [
                {'step_name': 'Application Review', 'step_description': 'Admin reviews and approves your application', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Submit Documents Online', 'step_description': 'Upload required documents through the online system', 'step_type': 'document_upload', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': 'pdf,jpg,jpeg,png'},
                {'step_name': 'Document Verification', 'step_description': 'Admin verifies uploaded documents', 'step_type': 'verification', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Submit Physical Documents', 'step_description': 'Submit original documents at MSWD Office for final verification', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'min_items': 1, 'allowed_file_types': ''}
            ]
        }
    }
    
    return jsonify({
        'success': True,
        'templates': templates
    })


@admin_bp.route('/programs/<int:program_id>/apply-workflow-template', methods=['POST'])
@login_required
@role_required('admin')
def apply_workflow_template(program_id):
    """Apply a workflow template to a program"""
    from app.models import ProgramWorkflowSteps
    
    program = Programs.query.get_or_404(program_id)
    
    try:
        data = request.get_json()
        template_type = data.get('template_type', 'default')
        
        # Get template based on type
        templates = {
            'ESA': [
                {'step_name': 'Upload Shelter Photos', 'step_description': 'Upload at least 3 photos of your current shelter/housing situation', 'step_type': 'photo_upload', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 3, 'allowed_file_types': 'jpg,jpeg,png,gif'},
                {'step_name': 'Application Review', 'step_description': 'Admin reviews shelter photos and application', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'min_items': 1, 'allowed_file_types': ''}
            ],
            'CA': [
                {'step_name': 'Upload Certificate of Participation', 'step_description': 'Upload your Certificate of Participation from the livelihood training seminar', 'step_type': 'document_upload', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': 'jpg,jpeg,png,pdf'},
                {'step_name': 'Upload Capital Assistance Proposal', 'step_description': 'Upload your business plan/proposal for the capital assistance', 'step_type': 'document_upload', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': 'jpg,jpeg,png,pdf,doc,docx'},
                {'step_name': 'Application Review', 'step_description': 'Admin reviews documents and approves application', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'min_items': 1, 'allowed_file_types': ''}
            ],
            'online_upload': [
                {'step_name': 'Application Review', 'step_description': 'Admin reviews and approves your application', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Submit Documents Online', 'step_description': 'Upload required documents through the online system', 'step_type': 'document_upload', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': 'pdf,jpg,jpeg,png'},
                {'step_name': 'Document Verification', 'step_description': 'Admin verifies uploaded documents', 'step_type': 'verification', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Submit Physical Documents', 'step_description': 'Submit original documents at MSWD Office for final verification', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'min_items': 1, 'allowed_file_types': ''}
            ],
            'default': [
                {'step_name': 'Application Review', 'step_description': 'Admin reviews and approves your application', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'min_items': 1, 'allowed_file_types': ''}
            ]
        }
        
        template_steps = templates.get(template_type, templates['default'])
        
        # Delete existing steps
        ProgramWorkflowSteps.query.filter_by(program_id=program_id).delete()
        
        # Add new steps from template
        for index, step_data in enumerate(template_steps, start=1):
            step = ProgramWorkflowSteps(
                program_id=program_id,
                step_order=index,
                step_name=step_data['step_name'],
                step_description=step_data['step_description'],
                step_type=step_data['step_type'],
                is_pre_approval=step_data['is_pre_approval'],
                requires_verification=step_data['requires_verification'],
                min_items=step_data['min_items'],
                allowed_file_types=step_data['allowed_file_types'] or None
            )
            db.session.add(step)
        
        db.session.commit()
        
        # Get the new steps to return
        new_steps = ProgramWorkflowSteps.query.filter_by(program_id=program_id).order_by(ProgramWorkflowSteps.step_order).all()
        
        return jsonify({
            'success': True,
            'message': f'Applied {template_type} workflow template successfully',
            'steps': [step.to_dict() for step in new_steps]
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error applying template: {str(e)}'}), 500

@admin_bp.route('/schedule_subsidy_payout', methods=['POST'], endpoint='schedule_subsidy_payout')
@login_required
@role_required('admin')
def schedule_subsidy_payout():
    """Schedule a subsidy payout and return beneficiary list for announcement"""
    try:
        # Get form data
        payout_date = request.form.get('payout_date')
        payout_time = request.form.get('payout_time')
        categories = request.form.getlist('categories')
        payout_location = request.form.get('payout_location')
        payout_notes = request.form.get('payout_notes', '')
        
        # Validate inputs
        if not all([payout_date, payout_time, categories, payout_location]):
            return jsonify({'success': False, 'message': 'Please fill in all required fields'}), 400
            
        # Combine date and time
        payout_datetime = datetime.strptime(f"{payout_date} {payout_time}", '%Y-%m-%d %H:%M')
        
        # Check if date is in the future
        if payout_datetime <= datetime.now():
            return jsonify({'success': False, 'message': 'Payout date must be in the future'}), 400
            
        # Get beneficiaries for selected categories
        query = CommunityUsers.query.join(User).filter(User.role == 'community')
        
        # Filter by categories - ensure we only get beneficiaries that match at least one selected category
        category_filters = []
        if 'pwd' in categories:
            category_filters.append(CommunityUsers.is_pwd == True)
        if 'senior' in categories:
            category_filters.append(CommunityUsers.age >= 60)
        if 'solo_parent' in categories:
            category_filters.append(CommunityUsers.is_solo_parent == True)
            
        if category_filters:
            from sqlalchemy import or_
            query = query.filter(or_(*category_filters))
        else:
            return jsonify({'success': False, 'message': 'No categories selected'}), 400
            
        beneficiaries = query.all()
        
        if not beneficiaries:
            category_names_str = ', '.join([category_names.get(cat, cat) for cat in categories])
            return jsonify({'success': False, 'message': f'No beneficiaries found for selected categories: {category_names_str}'}), 400
            
        # Create payout record (we'll store this in a simple way for now)
        payout_id = f"PAYOUT-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        # Generate beneficiary list text
        beneficiary_list = []
        category_names = {
            'pwd': 'PWD',
            'senior': 'Senior Citizens', 
            'solo_parent': 'Solo Parents'
        }
        
        # Group beneficiaries by category
        grouped_beneficiaries = {}
        for category in categories:
            grouped_beneficiaries[category] = []
            
        for beneficiary in beneficiaries:
            if 'pwd' in categories and beneficiary.is_pwd:
                grouped_beneficiaries['pwd'].append(beneficiary)
            if 'senior' in categories and beneficiary.age >= 60:
                grouped_beneficiaries['senior'].append(beneficiary)
            if 'solo_parent' in categories and beneficiary.is_solo_parent:
                grouped_beneficiaries['solo_parent'].append(beneficiary)
        
        # Create text list
        beneficiary_text_parts = []
        beneficiary_html_parts = []
        
        for category in categories:
            if grouped_beneficiaries[category]:
                beneficiary_text_parts.append(f"\\n{category_names[category]}:")
                beneficiary_html_parts.append(f'<strong class="text-primary">{category_names[category]}:</strong><br>')
                
                for i, beneficiary in enumerate(grouped_beneficiaries[category], 1):
                    name = f"{beneficiary.user.first_name} {beneficiary.user.last_name}"
                    barangay = beneficiary.barangay or "Not specified"
                    beneficiary_text_parts.append(f"{i}. {name} - {barangay}")
                    beneficiary_html_parts.append(f"{i}. {name} - <small class='text-muted'>{barangay}</small><br>")
                
                beneficiary_text_parts.append("")  # Empty line between categories
                beneficiary_html_parts.append("<br>")
        
        beneficiary_list_text = "\\n".join(beneficiary_text_parts)
        beneficiary_list_html = "".join(beneficiary_html_parts)
        
        # Generate suggested announcement content
        total_beneficiaries = len(beneficiaries)
        category_list = [category_names[cat] for cat in categories]
        category_text = ", ".join(category_list)
        
        suggested_title = f"Subsidy Payout Schedule - {category_text}"
        suggested_content = f"""Dear Beneficiaries,

We are pleased to announce the upcoming subsidy payout for {category_text}.

PAYOUT DETAILS:
📅 Date: {datetime.strptime(payout_date, '%Y-%m-%d').strftime('%B %d, %Y')}
🕘 Time: {datetime.strptime(payout_time, '%H:%M').strftime('%I:%M %p')}
 Location: {payout_location}
👥 Total Beneficiaries: {total_beneficiaries}

IMPORTANT REMINDERS:
• Please bring a valid ID for verification
• Come on time to avoid delays
• Follow health protocols during distribution
{f'• {payout_notes}' if payout_notes else ''}

LIST OF BENEFICIARIES:
{beneficiary_list_text}

Please share this information with other beneficiaries in your area.

For questions or concerns, please contact the barangay office.

Thank you."""
        
        return jsonify({
            'success': True,
            'payout_id': payout_id,
            'suggested_title': suggested_title,
            'suggested_content': suggested_content,
            'beneficiary_list_html': beneficiary_list_html,
            'total_beneficiaries': total_beneficiaries,
            'message': 'Payout scheduled successfully!'
        })
        
    except ValueError as e:
        return jsonify({'success': False, 'message': 'Invalid date/time format or amount'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error scheduling payout: {str(e)}'}), 500

@admin_bp.route('/create_subsidy_announcement', methods=['POST'], endpoint='create_subsidy_announcement')
@login_required
@role_required('admin')
def create_subsidy_announcement():
    """Create an announcement for the scheduled subsidy payout"""
    try:
        # Get form data
        payout_id = request.form.get('payout_id')
        announcement_title = request.form.get('announcement_title')
        announcement_content = request.form.get('announcement_content')
        
        # Validate inputs
        if not all([payout_id, announcement_title, announcement_content]):
            flash('Please fill in all required fields', 'error')
            return redirect(url_for('admin.adm_subsidy'))
            
        # Create announcement
        announcement = Announcements(
            announcement_title=announcement_title,
            announcement_content=announcement_content,
            category='subsidy',
            status='published',
            author_id=current_user.id,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        db.session.add(announcement)
        db.session.commit()
        
        flash(f'Subsidy announcement "{announcement_title}" has been created and published successfully!', 'success')
        return redirect(url_for('admin.adm_announcements'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating announcement: {str(e)}', 'error')
        return redirect(url_for('admin.adm_subsidy'))


# ===================== SUBSIDY ELIGIBILITY MANAGEMENT =====================

@admin_bp.route('/search_eligible_users', methods=['GET'], endpoint='search_eligible_users')
@login_required
@role_required('admin')
def search_eligible_users():
    """Search for users eligible for a specific subsidy category who aren't already in the list"""
    query = request.args.get('query', '').strip()
    category = request.args.get('category', '').strip()
    
    if not query or len(query) < 2:
        return jsonify({'users': []})
    
    try:
        # Base query for community users with user details
        base_query = CommunityUsers.query.join(User, CommunityUsers.user_id == User.id)
        
        # Search filter
        search_filter = or_(
            User.first_name.ilike(f'%{query}%'),
            User.last_name.ilike(f'%{query}%'),
            User.email.ilike(f'%{query}%'),
            CommunityUsers.barangay.ilike(f'%{query}%')
        )
        base_query = base_query.filter(search_filter)
        
        # Get users already in the current category list
        existing_users_query = CommunityUsers.query.join(User, CommunityUsers.user_id == User.id)
        
        if category == 'pwd':
            # For PWD: search verified PWD users not already in the list
            eligible_query = base_query.filter(
                CommunityUsers.pwd_verification == 'approved',
                CommunityUsers.is_pwd == False  # Not already marked as PWD in main profile
            )
            existing_users_query = existing_users_query.filter(CommunityUsers.is_pwd == True)
            verification_field = 'pwd_verification'
            
        elif category == 'senior':
            # For Senior Citizens: search users 60+ who aren't verified as senior yet
            eligible_query = base_query.filter(
                CommunityUsers.age >= 60,
                CommunityUsers.senior_citizen_verification != 'approved'
            )
            existing_users_query = existing_users_query.filter(CommunityUsers.age >= 60)
            verification_field = 'senior_citizen_verification'
            
        elif category == 'solo_parent':
            # For Solo Parents: search verified solo parents not already in the list
            eligible_query = base_query.filter(
                CommunityUsers.solo_parent_verification == 'approved',
                CommunityUsers.is_solo_parent == False  # Not already marked as solo parent
            )
            existing_users_query = existing_users_query.filter(CommunityUsers.is_solo_parent == True)
            verification_field = 'solo_parent_verification'
            
        else:
            return jsonify({'users': []})
        
        # Get existing user IDs to exclude
        existing_user_ids = [u.user_id for u in existing_users_query.all()]
        if existing_user_ids:
            eligible_query = eligible_query.filter(~CommunityUsers.user_id.in_(existing_user_ids))
        
        # Execute query and limit results
        results = eligible_query.limit(10).all()
        
        # Format results
        users = []
        for community_user in results:
            user = community_user.user
            verification_status = getattr(community_user, verification_field, 'none')
            
            users.append({
                'id': user.id,
                'name': f"{user.first_name} {user.last_name}",
                'email': user.email,
                'barangay': community_user.barangay,
                'municipality': community_user.municipality,
                'age': community_user.age,
                'verification_status': verification_status
            })
        
        return jsonify({'users': users})
        
    except Exception as e:
        print(f"Error searching eligible users: {str(e)}")
        return jsonify({'users': [], 'error': str(e)}), 500


@admin_bp.route('/notify_subsidy_eligibility', methods=['POST'], endpoint='notify_subsidy_eligibility')
@login_required
@role_required('admin')
def notify_subsidy_eligibility():
    """Notify a user about their subsidy eligibility and add them to the category"""
    user_id = request.form.get('user_id')
    category = request.form.get('category')
    category_name = request.form.get('category_name')
    
    if not all([user_id, category, category_name]):
        return jsonify({'success': False, 'message': 'Missing required parameters'})
    
    try:
        # Get the user and their community profile
        user = User.query.get(user_id)
        if not user or not user.community_profile:
            return jsonify({'success': False, 'message': 'User not found or no community profile'})
        
        community_user = user.community_profile
        
        # Update the appropriate category flag
        updated = False
        notification_message = ""
        required_documents = []
        
        if category == 'pwd':
            if community_user.pwd_verification == 'approved' and not community_user.is_pwd:
                community_user.is_pwd = True
                updated = True
                notification_message = f"You have been added to the Persons with Disability (PWD) subsidy program. You are now eligible for PWD benefits and assistance programs."
                required_documents = ["Valid PWD ID", "Medical Certificate", "Barangay Certification"]
                
        elif category == 'senior':
            if community_user.age >= 60:
                # Mark as senior citizen
                community_user.senior_citizen_verification = 'approved'
                updated = True
                notification_message = f"You have been added to the Senior Citizens subsidy program. You are now eligible for senior citizen benefits and assistance programs."
                required_documents = ["Valid Senior Citizen ID", "Birth Certificate", "Barangay Certification"]
                
        elif category == 'solo_parent':
            if community_user.solo_parent_verification == 'approved' and not community_user.is_solo_parent:
                community_user.is_solo_parent = True
                updated = True
                notification_message = f"You have been added to the Solo Parents subsidy program. You are now eligible for solo parent benefits and assistance programs."
                required_documents = ["Solo Parent ID", "Child's Birth Certificate", "Barangay Certification"]
        
        if not updated:
            return jsonify({'success': False, 'message': 'User is not eligible for this subsidy category or already added'})
        
        # Create notification for the user
        from app.models import Notifications
        notification = Notifications(
            user_id=user.id,
            notification_title=f"Subsidy Eligibility Notification - {category_name}",
            notification_content=f"{notification_message}\n\nRequired documents to submit:\n" + 
                               "\n".join([f"• {doc}" for doc in required_documents]) +
                               f"\n\nPlease prepare these documents and visit the barangay office to complete your registration. You will receive further instructions on how to claim your benefits.",
            notification_type="subsidy_eligibility",
            is_read=False,
            created_at=datetime.now()
        )
        
        db.session.add(notification)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'{user.first_name} {user.last_name} has been successfully added to {category_name} and notified about their eligibility.'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error notifying subsidy eligibility: {str(e)}")
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

