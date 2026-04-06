from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import and_, desc, or_, func
from sqlalchemy.orm import joinedload
from app.admin import admin_bp
from app.models import Programs, Requirements, ProgramRequirements, Applications, FileAttachment, CommunityUsers, User, Announcements, Notifications, Assessment, ApplicationDocuments, ApplicationDocumentUploads, SubsidyPayout, UserActivityLog
from app.extensions import db
from app.utils import role_required, manila_strftime
from app.activity_logger import log_activity
from app.recommender import get_recommendations, SENIOR_CITIZEN_AGE
from app.community.routes.profile import get_income_range_display
import os
import json
from werkzeug.utils import secure_filename

# Configuration
UPLOAD_FOLDER = 'static/uploads/programs'
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
DEFAULT_TARGET_AGE = 30

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _parse_program_income_upper_bound(income_range):
    """Parse a program income range string and return a reasonable upper bound."""
    if not income_range:
        return 250000

    normalized = str(income_range).replace(',', '').strip().lower()
    numbers = []
    current = ''
    for ch in normalized:
        if ch.isdigit() or ch == '.':
            current += ch
        elif current:
            try:
                numbers.append(float(current))
            except ValueError:
                pass
            current = ''
    if current:
        try:
            numbers.append(float(current))
        except ValueError:
            pass

    if not numbers:
        return 250000

    if 'below' in normalized or 'under' in normalized:
        return max(numbers)
    if 'above' in normalized or 'over' in normalized:
        return max(numbers) * 1.5
    if len(numbers) >= 2:
        return max(numbers)
    return numbers[0]

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

    # Active applications across all programs
    active_applications = Applications.query.filter_by(application_status='active').count()
    
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
        active_applications=active_applications,
        recent_programs=recent_programs,
        program_types=[t[0] for t in program_types],
        program_periods=[p[0] for p in program_periods],
        requirements=all_requirements,  # Add this line
        user=current_user,
        today=datetime.utcnow().date()
    )


# ===================== SUBSIDY MANAGEMENT =====================

def _get_subsidy_request_log(request_id):
    return UserActivityLog.query.options(joinedload(UserActivityLog.user)).filter(
        UserActivityLog.id == request_id,
        UserActivityLog.action == 'request_subsidy',
        UserActivityLog.entity_type == 'subsidy'
    ).first()


def _safe_subsidy_details(log):
    details = log.details_dict if hasattr(log, 'details_dict') else {}
    return details if isinstance(details, dict) else {}


def _normalize_required_document_specs(details):
    specs = details.get('required_documents_specs')
    normalized_specs = []

    if isinstance(specs, list):
        for item in specs:
            if not isinstance(item, dict):
                continue

            name = str(item.get('name', '')).strip()
            if not name:
                continue

            raw_copy_specs = item.get('copy_specs') if isinstance(item.get('copy_specs'), list) else []
            copy_specs = []
            for copy_spec in raw_copy_specs:
                if not isinstance(copy_spec, dict):
                    continue
                copy_type = str(copy_spec.get('type', 'original')).strip() or 'original'
                try:
                    copy_count = max(1, int(copy_spec.get('count', 1)))
                except (TypeError, ValueError):
                    copy_count = 1
                copy_specs.append({'type': copy_type, 'count': copy_count})

            if not copy_specs:
                copy_specs = [{'type': 'original', 'count': 1}]

            requirement_id = item.get('requirement_id')
            try:
                requirement_id = int(requirement_id) if requirement_id is not None else None
            except (TypeError, ValueError):
                requirement_id = None

            normalized_specs.append({
                'requirement_id': requirement_id,
                'name': name,
                'copy_specs': copy_specs
            })

    if normalized_specs:
        return normalized_specs

    fallback_docs = details.get('required_documents')
    if not isinstance(fallback_docs, list):
        return []

    fallback_specs = []
    for doc_name in fallback_docs:
        clean_name = str(doc_name).strip()
        if clean_name:
            fallback_specs.append({
                'requirement_id': None,
                'name': clean_name,
                'copy_specs': [{'type': 'original', 'count': 1}]
            })
    return fallback_specs


def _copy_type_label(copy_type):
    copy_type_map = {
        'original': 'Original',
        'photocopy': 'Photocopy',
        'certified_true_copy': 'Certified True Copy'
    }
    return copy_type_map.get(str(copy_type).strip().lower(), str(copy_type).replace('_', ' ').title())


def _senior_subsidy_membership_filter():
    """Senior subsidy list membership: age-qualified and not explicitly removed."""
    return and_(
        CommunityUsers.age >= 60,
        or_(
            CommunityUsers.senior_citizen_verification.is_(None),
            CommunityUsers.senior_citizen_verification != 'removed'
        )
    )


def _normalize_subsidy_category_key(raw_value):
    """Normalize subsidy category values from request details."""
    value = str(raw_value or '').strip().lower().replace('-', '_')
    value = value.replace('(', '').replace(')', '')
    value = '_'.join(value.split())
    alias_map = {
        'pwd': 'pwd',
        'persons_with_disability': 'pwd',
        'persons_with_disability_pwd': 'pwd',
        'senior': 'senior',
        'senior_citizen': 'senior',
        'senior_citizens': 'senior',
        'solo_parent': 'solo_parent',
        'solo_parents': 'solo_parent'
    }
    return alias_map.get(value, '')


def _is_subsidy_list_active(details):
    """Return True if details indicate active list inclusion."""
    status_value = str(details.get('status', '')).lower()
    if status_value != 'completed':
        return False
    if details.get('removed_from_subsidy_list') is True:
        return False
    if details.get('subsidy_list_active') is False:
        return False
    return True


def _get_subsidy_member_user_ids(category_key):
    """Get user IDs included in a subsidy list from completed subsidy requests."""
    normalized_category = _normalize_subsidy_category_key(category_key)
    if not normalized_category:
        return set()

    logs = UserActivityLog.query.filter(
        UserActivityLog.action == 'request_subsidy',
        UserActivityLog.entity_type == 'subsidy'
    ).all()

    member_user_ids = set()
    for log in logs:
        details = _safe_subsidy_details(log)
        log_category = _normalize_subsidy_category_key(details.get('category') or details.get('category_name'))
        if log_category != normalized_category:
            continue
        if _is_subsidy_list_active(details):
            member_user_ids.add(log.user_id)

    return member_user_ids


def _is_user_verified_for_subsidy_category(community_user, category_key):
    """Verify whether a user can be included in a subsidy category."""
    if not community_user:
        return False

    normalized_category = _normalize_subsidy_category_key(category_key)
    if normalized_category == 'pwd':
        return community_user.pwd_verification == 'approved'
    if normalized_category == 'senior':
        return bool(community_user.age and community_user.age >= 60) or community_user.senior_citizen_verification == 'approved'
    if normalized_category == 'solo_parent':
        return community_user.solo_parent_verification == 'approved'
    return False

@admin_bp.route('/subsidy', endpoint='adm_subsidy')
@login_required
@role_required('admin')
def subsidy_index():
    """Display subsidy categories with statistics"""

    # Subsidy list counts are based on completed subsidy requests marked active.
    pwd_user_ids = _get_subsidy_member_user_ids('pwd')
    senior_user_ids = _get_subsidy_member_user_ids('senior')
    solo_parent_user_ids = _get_subsidy_member_user_ids('solo_parent')

    pwd_count = len(pwd_user_ids)
    senior_count = len(senior_user_ids)
    solo_parent_count = len(solo_parent_user_ids)
    total_beneficiaries = len(pwd_user_ids.union(senior_user_ids).union(solo_parent_user_ids))

    document_requirements_catalog = Requirements.query.filter_by(requirement_type='document').order_by(
        Requirements.requirement_name.asc()
    ).all()

    recent_subsidy_logs = UserActivityLog.query.options(
        joinedload(UserActivityLog.user)
    ).filter(
        UserActivityLog.action == 'request_subsidy',
        UserActivityLog.entity_type == 'subsidy'
    ).order_by(
        UserActivityLog.created_at.desc()
    ).limit(10).all()

    recent_subsidy_requests = []
    for log in recent_subsidy_logs:
        details = _safe_subsidy_details(log)
        category_name = details.get('category_name') or details.get('category') or 'Subsidy Request'
        status_value = str(details.get('status', 'pending')).replace('_', ' ').title()
        requester_name = log.user_name if hasattr(log, 'user_name') else f'User #{log.user_id}'
        required_documents = details.get('required_documents')
        if not isinstance(required_documents, list):
            required_documents = []
        required_documents_specs = _normalize_required_document_specs(details)

        recent_subsidy_requests.append({
            'id': log.id,
            'user_id': log.user_id,
            'requester_name': requester_name,
            'category_name': category_name,
            'status': status_value,
            'description': log.description,
            'created_at': log.created_at,
            'admin_instructions': details.get('admin_instructions') or '',
            'required_documents': required_documents,
            'required_documents_specs': required_documents_specs,
            'office_submission_note': details.get('office_submission_note') or 'Please submit the required documents in the office within the week.',
            'category_key': details.get('category') or '',
            'status_key': str(details.get('status', 'pending')).lower(),
            'requester_email': log.user.email if log.user else ''
        })
    
    return render_template(
        'admin/adm_subsidy.html',
        pwd_count=pwd_count,
        senior_count=senior_count,
        solo_parent_count=solo_parent_count,
        total_beneficiaries=total_beneficiaries,
        recent_subsidy_requests=recent_subsidy_requests,
        document_requirements_catalog=document_requirements_catalog,
        user=current_user
    )


@admin_bp.route('/subsidy/requests/<int:request_id>/respond', methods=['POST'], endpoint='respond_subsidy_request')
@login_required
@role_required('admin')
def respond_subsidy_request(request_id):
    """Send office submission instructions and required documents for a subsidy request."""
    request_log = _get_subsidy_request_log(request_id)

    if not request_log:
        flash('Subsidy request not found.', 'danger')
        return redirect(url_for('admin.adm_subsidy'))

    instructions = request.form.get('instructions', '').strip()
    selected_requirement_ids = request.form.getlist('document_requirement_ids')

    if not instructions:
        flash('Instructions are required before sending this update.', 'warning')
        return redirect(url_for('admin.adm_subsidy'))

    if not selected_requirement_ids:
        flash('Please select at least one required document.', 'warning')
        return redirect(url_for('admin.adm_subsidy'))

    requirement_ids = []
    for req_id in selected_requirement_ids:
        try:
            requirement_ids.append(int(req_id))
        except (TypeError, ValueError):
            continue

    if not requirement_ids:
        flash('Please select valid required documents.', 'warning')
        return redirect(url_for('admin.adm_subsidy'))

    requirement_rows = Requirements.query.filter(
        Requirements.id.in_(requirement_ids),
        Requirements.requirement_type == 'document'
    ).all()
    requirement_map = {req.id: req for req in requirement_rows}

    required_documents = []
    required_documents_specs = []
    valid_copy_types = {'original', 'photocopy', 'certified_true_copy'}

    for req_id in requirement_ids:
        requirement = requirement_map.get(req_id)
        if not requirement:
            continue

        copy_types = request.form.getlist(f'copy_type_{req_id}[]')
        copy_counts = request.form.getlist(f'copy_count_{req_id}[]')
        row_count = max(len(copy_types), len(copy_counts), 1)

        copy_specs = []
        for index in range(row_count):
            copy_type = (copy_types[index] if index < len(copy_types) else 'original').strip().lower()
            if copy_type not in valid_copy_types:
                copy_type = 'original'

            raw_count = copy_counts[index] if index < len(copy_counts) else '1'
            try:
                copy_count = max(1, min(10, int(raw_count)))
            except (TypeError, ValueError):
                copy_count = 1

            copy_specs.append({
                'type': copy_type,
                'count': copy_count
            })

        required_documents.append(requirement.requirement_name)
        required_documents_specs.append({
            'requirement_id': requirement.id,
            'name': requirement.requirement_name,
            'copy_specs': copy_specs
        })

    if not required_documents_specs:
        flash('Please select at least one valid required document.', 'warning')
        return redirect(url_for('admin.adm_subsidy'))

    details = _safe_subsidy_details(request_log)

    category_name = details.get('category_name') or details.get('category') or 'Subsidy Request'
    office_note = 'Please submit the required documents in the office within the week.'

    details['status'] = 'documents_required'
    details['admin_instructions'] = instructions
    details['required_documents'] = required_documents
    details['required_documents_specs'] = required_documents_specs
    details['office_submission_note'] = office_note
    details['admin_reviewed_by'] = current_user.id
    details['admin_reviewed_at'] = datetime.utcnow().isoformat()

    request_log.details = json.dumps(details)
    request_log.description = f'Reviewed subsidy request for {category_name}; requested office documents.'

    docs_lines = []
    for spec in required_documents_specs:
        copy_desc = ', '.join([f"{row['count']} { _copy_type_label(row['type']) }" for row in spec['copy_specs']])
        docs_lines.append(f"• {spec['name']} ({copy_desc})")
    docs_text = "\n".join(docs_lines)

    user_notification = Notifications(
        user_id=request_log.user_id,
        notif_title=f'Subsidy Application Update: {category_name}',
        notif_message=(
            f'Your subsidy application for {category_name} was reviewed.\n\n'
            f'Instructions:\n{instructions}\n\n'
            f"Required documents to submit in the office:\n{docs_text}\n\n"
            f'{office_note}'
        ),
        related_type='subsidy'
    )

    db.session.add(user_notification)
    db.session.commit()

    flash('Instructions and required documents were sent to the user.', 'success')
    return redirect(url_for('admin.adm_subsidy'))


@admin_bp.route('/subsidy/requests/<int:request_id>/status', methods=['POST'], endpoint='update_subsidy_request_status')
@login_required
@role_required('admin')
def update_subsidy_request_status(request_id):
    """Update status of a subsidy request."""
    request_log = _get_subsidy_request_log(request_id)
    if not request_log:
        flash('Subsidy request not found.', 'danger')
        return redirect(url_for('admin.adm_subsidy'))

    details = _safe_subsidy_details(request_log)
    current_status = str(details.get('status', 'pending')).lower()
    new_status = request.form.get('status', '').strip().lower()

    allowed_statuses = {
        'pending', 'submitted', 'under_review', 'documents_required',
        'processing', 'approved', 'rejected', 'cancelled'
    }
    if new_status not in allowed_statuses:
        flash('Invalid subsidy request status selected.', 'warning')
        return redirect(url_for('admin.adm_subsidy'))

    if current_status == 'completed':
        flash('Completed subsidy requests can no longer be updated.', 'warning')
        return redirect(url_for('admin.adm_subsidy'))

    if current_status == new_status:
        flash('Status is already up to date.', 'info')
        return redirect(url_for('admin.adm_subsidy'))

    category_name = details.get('category_name') or details.get('category') or 'Subsidy Request'

    details['status'] = new_status
    details['status_updated_by'] = current_user.id
    details['status_updated_at'] = datetime.utcnow().isoformat()

    request_log.details = json.dumps(details)
    request_log.description = f"Updated subsidy request for {category_name} to {new_status.replace('_', ' ')}."

    status_readable = new_status.replace('_', ' ').title()
    notif = Notifications(
        user_id=request_log.user_id,
        notif_title=f'Subsidy Application Status: {status_readable}',
        notif_message=(
            f'Your subsidy application for {category_name} has been updated to {status_readable}. '
            f'Please check your subsidy application details for next steps.'
        ),
        related_type='subsidy'
    )

    db.session.add(notif)
    db.session.commit()

    flash(f'Subsidy request status updated to {status_readable}.', 'success')
    return redirect(url_for('admin.adm_subsidy'))


@admin_bp.route('/subsidy/requests/<int:request_id>/complete', methods=['POST'], endpoint='complete_subsidy_request')
@login_required
@role_required('admin')
def complete_subsidy_request(request_id):
    """Mark a subsidy request as completed. Allowed only when status is approved."""
    request_log = _get_subsidy_request_log(request_id)
    if not request_log:
        flash('Subsidy request not found.', 'danger')
        return redirect(url_for('admin.adm_subsidy'))

    details = _safe_subsidy_details(request_log)
    current_status = str(details.get('status', 'pending')).lower()
    if current_status != 'approved':
        flash('Only approved subsidy requests can be marked as completed.', 'warning')
        return redirect(url_for('admin.adm_subsidy'))

    category_key = _normalize_subsidy_category_key(details.get('category') or details.get('category_name'))
    if not category_key:
        flash('Subsidy request category is invalid and cannot be completed.', 'warning')
        return redirect(url_for('admin.adm_subsidy'))

    community_user = CommunityUsers.query.filter_by(user_id=request_log.user_id).first()
    if not _is_user_verified_for_subsidy_category(community_user, category_key):
        flash('User is not verified for this subsidy category yet.', 'warning')
        return redirect(url_for('admin.adm_subsidy'))

    category_name = details.get('category_name') or details.get('category') or 'Subsidy Request'
    details['category'] = category_key
    details['status'] = 'completed'
    details['completed_at'] = datetime.utcnow().isoformat()
    details['completed_by'] = current_user.id
    details['subsidy_list_active'] = True
    details['removed_from_subsidy_list'] = False
    details['subsidy_list_added_at'] = datetime.utcnow().isoformat()
    details['subsidy_list_added_by'] = current_user.id

    request_log.details = json.dumps(details)
    request_log.description = f'Completed subsidy request for {category_name} and added to subsidy list.'

    notif = Notifications(
        user_id=request_log.user_id,
        notif_title=f'Subsidy Application Completed: {category_name}',
        notif_message=(
            f'Your subsidy application for {category_name} has been marked as completed and you were added to the subsidy list. '
            f'Please monitor your account for any additional announcements.'
        ),
        related_type='subsidy'
    )

    db.session.add(notif)
    db.session.commit()

    flash('Subsidy request marked as completed and beneficiary was added to the subsidy list.', 'success')
    return redirect(url_for('admin.adm_subsidy'))


@admin_bp.route('/subsidy/<category>', endpoint='subsidy_list')
@login_required
@role_required('admin')
def subsidy_list(category):
    """Display list of individuals for a specific subsidy category"""
    page = request.args.get('page', 1, type=int)
    per_page = 15
    search = request.args.get('search', '').strip()
    barangay_filter = request.args.get('barangay', '').strip()

    category = _normalize_subsidy_category_key(category)
    if not category:
        flash('Invalid subsidy category.', 'danger')
        return redirect(url_for('admin.adm_subsidy'))
    
    # Base query with user join
    query = CommunityUsers.query.join(User, CommunityUsers.user_id == User.id)

    member_user_ids = _get_subsidy_member_user_ids(category)
    if member_user_ids:
        query = query.filter(CommunityUsers.user_id.in_(list(member_user_ids)))
    else:
        query = query.filter(CommunityUsers.user_id == -1)
    
    # Filter by category
    if category == 'pwd':
        category_name = 'Persons with Disability (PWD)'
        category_icon = 'fa-wheelchair'
        category_color = 'primary'
    elif category == 'senior':
        category_name = 'Senior Citizens'
        category_icon = 'fa-user-clock'
        category_color = 'success'
    elif category == 'solo_parent':
        category_name = 'Solo Parents'
        category_icon = 'fa-user-friends'
        category_color = 'warning'
    
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


@admin_bp.route('/subsidy/remove-beneficiary', methods=['POST'], endpoint='remove_subsidy_beneficiary')
@login_required
@role_required('admin')
def remove_subsidy_beneficiary():
    """Remove a community user from a subsidy beneficiary category."""
    category = _normalize_subsidy_category_key(request.form.get('category'))
    community_user_id = request.form.get('community_user_id', type=int)
    return_url = (request.form.get('return_url') or '').strip()

    category_labels = {
        'pwd': 'PWD',
        'senior': 'Senior Citizens',
        'solo_parent': 'Solo Parents'
    }

    if category not in category_labels or not community_user_id:
        flash('Invalid remove request.', 'danger')
        return redirect(url_for('admin.adm_subsidy'))

    community_user = CommunityUsers.query.get(community_user_id)
    if not community_user or not community_user.user:
        flash('Beneficiary record not found.', 'danger')
        return redirect(url_for('admin.subsidy_list', category=category))

    subsidy_logs = UserActivityLog.query.filter(
        UserActivityLog.user_id == community_user.user_id,
        UserActivityLog.action == 'request_subsidy',
        UserActivityLog.entity_type == 'subsidy'
    ).all()

    updated_logs = 0
    for log in subsidy_logs:
        details = _safe_subsidy_details(log)
        log_category = _normalize_subsidy_category_key(details.get('category') or details.get('category_name'))
        if log_category != category:
            continue
        if not _is_subsidy_list_active(details):
            continue

        details['subsidy_list_active'] = False
        details['removed_from_subsidy_list'] = True
        details['removed_from_subsidy_list_at'] = datetime.utcnow().isoformat()
        details['removed_from_subsidy_list_by'] = current_user.id

        log.details = json.dumps(details)
        log.description = f"Removed subsidy list membership for {category_labels[category]}"
        updated_logs += 1

    if updated_logs == 0:
        flash(f'No changes applied. User is not currently in the {category_labels[category]} subsidy list.', 'warning')
        return redirect(url_for('admin.subsidy_list', category=category))

    user_name = f"{community_user.user.first_name} {community_user.user.last_name}".strip()

    log_activity(
        action='remove_subsidy_beneficiary',
        action_type='delete',
        entity_type='beneficiaries_list',
        description=f"Removed {user_name} from {category_labels[category]} subsidy list",
        entity_id=community_user.id,
        details={
            'category': category,
            'category_label': category_labels[category],
            'community_user_id': community_user.id,
            'user_id': community_user.user_id,
            'user_name': user_name,
            'updated_request_logs': updated_logs
        }
    )

    db.session.commit()
    flash(f'{user_name} has been removed from the {category_labels[category]} subsidy list.', 'success')

    if return_url.startswith('/admin/subsidy/'):
        return redirect(return_url)
    return redirect(url_for('admin.subsidy_list', category=category))


@admin_bp.route('/subsidy/scheduled-lists', endpoint='scheduled_beneficiaries_list')
@login_required
@role_required('admin')
def scheduled_beneficiaries_list():
    """Display all scheduled/saved subsidy beneficiary lists."""
    page = request.args.get('page', 1, type=int)
    per_page = 12
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '').strip().lower()

    query = SubsidyPayout.query

    if search:
        search_pattern = f'%{search}%'
        query = query.filter(
            or_(
                SubsidyPayout.payout_id.ilike(search_pattern),
                SubsidyPayout.category_label.ilike(search_pattern),
                SubsidyPayout.payout_location.ilike(search_pattern)
            )
        )

    allowed_statuses = {'draft', 'saved', 'announced'}
    if status_filter in allowed_statuses:
        query = query.filter(SubsidyPayout.status == status_filter)

    query = query.order_by(SubsidyPayout.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    status_counts = {
        'draft': SubsidyPayout.query.filter_by(status='draft').count(),
        'saved': SubsidyPayout.query.filter_by(status='saved').count(),
        'announced': SubsidyPayout.query.filter_by(status='announced').count()
    }

    return render_template(
        'admin/scheduled_beneficiaries_list.html',
        payout_lists=pagination.items,
        pagination=pagination,
        search=search,
        status_filter=status_filter,
        status_counts=status_counts,
        user=current_user
    )


@admin_bp.route('/subsidy/scheduled/<string:payout_id>', endpoint='scheduled_beneficiaries')
@login_required
@role_required('admin')
def scheduled_beneficiaries(payout_id):
    """Display a scheduled payout with its beneficiary list and actions."""
    payout = SubsidyPayout.query.filter_by(payout_id=payout_id).first_or_404()
    beneficiaries = payout.snapshot_data

    return render_template(
        'admin/scheduled_beneficiaries.html',
        payout=payout,
        beneficiaries=beneficiaries,
        user=current_user
    )


@admin_bp.route('/subsidy/scheduled/<string:payout_id>/save', methods=['POST'], endpoint='save_scheduled_beneficiaries')
@login_required
@role_required('admin')
def save_scheduled_beneficiaries(payout_id):
    """Mark a scheduled payout list as saved in the system."""
    payout = SubsidyPayout.query.filter_by(payout_id=payout_id).first_or_404()

    if payout.saved_in_system:
        flash('This beneficiary list is already saved in the system.', 'info')
        return redirect(url_for('admin.scheduled_beneficiaries', payout_id=payout.payout_id))

    payout.saved_in_system = True
    payout.saved_at = datetime.utcnow()
    if payout.status == 'draft':
        payout.status = 'saved'

    db.session.commit()

    flash('Beneficiary list saved in system successfully.', 'success')
    return redirect(url_for('admin.scheduled_beneficiaries', payout_id=payout.payout_id))


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

        barangays = [
            row[0] for row in db.session.query(CommunityUsers.barangay)
            .filter(CommunityUsers.barangay.isnot(None))
            .distinct()
            .order_by(CommunityUsers.barangay)
            .all()
        ]

        return render_template('admin/add_program.html', 
                             requirements=requirements,
                             barangays=barangays,
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
        if not program_name or not program_type or not program_period or not description:
            flash('Program name, type, period, and description are required.', 'danger')
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
                
                # Get multiple copy specifications
                copy_specs_key = f'copy_specs_{req_id}'
                copy_specs_json = request.form.get(copy_specs_key, '[]')
                
                # Parse and validate copy specifications
                import json
                try:
                    copy_specs = json.loads(copy_specs_json)
                except:
                    copy_specs = []
                
                # Validate each specification
                valid_copy_types = ['original', 'photocopy', 'certified_true_copy']
                validated_specs = []
                
                for spec in copy_specs:
                    try:
                        copy_type = spec.get('type', 'original')
                        copy_count = int(spec.get('count', 1))
                        
                        if copy_type not in valid_copy_types:
                            copy_type = 'original'
                        if copy_count < 1 or copy_count > 10:
                            copy_count = 1
                        
                        validated_specs.append({
                            'type': copy_type,
                            'count': copy_count
                        })
                    except (ValueError, TypeError, AttributeError):
                        continue
                
                # If no valid specs, use default
                if not validated_specs:
                    validated_specs = [{'type': 'original', 'count': 1}]
                
                prog_req = ProgramRequirements(
                    program_id=new_program.id,
                    requirement_id=int(req_id),
                    is_mandatory=is_mandatory
                )
                prog_req.set_copy_specifications(validated_specs)
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
                        {'step_name': 'Assessment / SCSR', 'step_description': 'Admin schedules interview or home visit and uploads Social Case Study Report', 'step_type': 'assessment', 'is_pre_approval': False, 'requires_verification': True, 'allowed_file_types': None},
                        {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'allowed_file_types': None}
                    ]
                else:
                    # Default steps for other programs (AICS, CA, etc.)
                    default_steps = [
                        {'step_name': 'Application Review', 'step_description': '', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': False, 'allowed_file_types': None},
                        {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'allowed_file_types': None},
                        {'step_name': 'Assessment / SCSR', 'step_description': 'Admin schedules interview or home visit and uploads Social Case Study Report', 'step_type': 'assessment', 'is_pre_approval': False, 'requires_verification': True, 'allowed_file_types': None},
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
        db.joinedload(Programs.applications),  # Load applications for counting
        db.joinedload(Programs.workflow_steps)  # Load workflow steps
    ).get_or_404(id)
    
    if request.method == 'GET':
        # Get all requirements for the form
        requirements = Requirements.query.order_by(
            Requirements.requirement_type,
            Requirements.requirement_name
        ).all()
        
        # Get existing program requirements
        existing_reqs = {pr.requirement_id: pr.is_mandatory for pr in program.program_requirements}
        
        # Get all barangays for filter dropdown
        barangays = [
            row[0] for row in db.session.query(CommunityUsers.barangay)
            .filter(CommunityUsers.barangay.isnot(None))
            .distinct()
            .order_by(CommunityUsers.barangay)
            .all()
        ]
        
        # Get count of eligible unscheduled applications
        eligible_unscheduled_count = Applications.query.filter(
            Applications.program_id == program.id,
            Applications.application_status == 'completed',
            Applications.claim_status == 'not_scheduled'
        ).count()
        
        # Add application and requirement counts
        program.application_count = Applications.query.filter_by(program_id=program.id).count()
        program.requirement_count = ProgramRequirements.query.filter_by(program_id=program.id).count()
        
        return render_template('admin/view_edit_program.html',
                             program=program,
                             requirements=requirements,
                             existing_reqs=existing_reqs,
                             barangays=barangays,
                             eligible_unscheduled_count=eligible_unscheduled_count,
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
    
    def _extract_copy_specs_from_form(form, req_id, mode='default'):
        """Extract copy specs from form data with fallbacks.

        mode='edit' expects edit tab naming first, mode='default' expects add/modal naming first.
        """
        import json

        valid_copy_types = ['original', 'photocopy', 'certified_true_copy']
        specs = []

        if mode == 'edit':
            json_keys = [f'copy_specs_edit_{req_id}', f'copy_specs_{req_id}']
            type_keys = [f'copy_type_edit_{req_id}[]', f'copy_type_{req_id}[]']
            count_keys = [f'copy_count_edit_{req_id}[]', f'copy_count_{req_id}[]']
            legacy_count_key = f'copies_{req_id}'
            legacy_type_key = f'copy_type_{req_id}'
        else:
            json_keys = [f'copy_specs_{req_id}', f'copy_specs_edit_{req_id}']
            type_keys = [f'copy_type_{req_id}[]', f'copy_type_edit_{req_id}[]']
            count_keys = [f'copy_count_{req_id}[]', f'copy_count_edit_{req_id}[]']
            legacy_count_key = f'copies_{req_id}'
            legacy_type_key = f'copy_type_{req_id}'

        # 1) Preferred hidden JSON payload
        for key in json_keys:
            raw = form.get(key)
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        specs = parsed
                        break
                except Exception:
                    continue

        # 2) Array payload fallback: copy_type_*[] + copy_count_*[]
        if not specs:
            type_values = []
            count_values = []
            for key in type_keys:
                vals = form.getlist(key)
                if vals:
                    type_values = vals
                    break
            for key in count_keys:
                vals = form.getlist(key)
                if vals:
                    count_values = vals
                    break

            if type_values:
                for idx, t in enumerate(type_values):
                    c = count_values[idx] if idx < len(count_values) else 1
                    specs.append({'type': t, 'count': c})

        # 3) Legacy single-value fallback
        if not specs:
            specs = [{
                'type': form.get(legacy_type_key, 'original'),
                'count': form.get(legacy_count_key, 1)
            }]

        validated_specs = []
        for spec in specs:
            try:
                copy_type = spec.get('type', 'original')
                copy_count = int(spec.get('count', 1))
            except Exception:
                continue

            if copy_type not in valid_copy_types:
                copy_type = 'original'
            if copy_count < 1 or copy_count > 10:
                copy_count = 1

            validated_specs.append({'type': copy_type, 'count': copy_count})

        return validated_specs or [{'type': 'original', 'count': 1}]

    try:
        if update_type == 'requirements':
            # Handle requirements-only update
            requirement_ids = request.form.getlist('requirements')
            
            # Delete existing requirements
            ProgramRequirements.query.filter_by(program_id=id).delete()
            
            # Add new requirements with their copy specifications
            for req_id in requirement_ids:
                copy_specs = _extract_copy_specs_from_form(request.form, req_id, mode='default')
                
                prog_req = ProgramRequirements(
                    program_id=id,
                    requirement_id=int(req_id),
                    is_mandatory=True  # Default to mandatory
                )
                prog_req.set_copy_specifications(copy_specs)
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
                        {'step_name': 'Assessment / SCSR', 'step_description': 'Admin schedules interview or home visit and uploads Social Case Study Report', 'step_type': 'assessment', 'is_pre_approval': False, 'requires_verification': True, 'allowed_file_types': None},
                        {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'allowed_file_types': None}
                    ]
                else:
                    # Default steps for other programs (AICS, CA, etc.)
                    default_steps = [
                        {'step_name': 'Application Review', 'step_description': '', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': False, 'allowed_file_types': None},
                        {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'allowed_file_types': None},
                        {'step_name': 'Assessment / SCSR', 'step_description': 'Admin schedules interview or home visit and uploads Social Case Study Report', 'step_type': 'assessment', 'is_pre_approval': False, 'requires_verification': True, 'allowed_file_types': None},
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
            
            # Add new requirements with copy specifications
            for req_id in requirement_ids:
                is_mandatory = str(req_id) in mandatory_requirements
                copy_specs = _extract_copy_specs_from_form(request.form, req_id, mode='edit')
                
                prog_req = ProgramRequirements(
                    program_id=id,
                    requirement_id=int(req_id),
                    is_mandatory=is_mandatory
                )
                prog_req.set_copy_specifications(copy_specs)
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


@admin_bp.route('/programs/<int:program_id>/ranked-list', endpoint='program_ranked_list')
@login_required
@role_required('admin')
def program_ranked_list(program_id):
    """Dedicated page for generating ranked beneficiaries for a program."""
    program = Programs.query.get_or_404(program_id)

    barangays = [
        row[0] for row in db.session.query(CommunityUsers.barangay)
        .filter(CommunityUsers.barangay.isnot(None))
        .distinct()
        .order_by(CommunityUsers.barangay)
        .all()
    ]

    eligible_unscheduled_count = Applications.query.filter(
        Applications.program_id == program_id,
        Applications.application_status == 'completed',
        Applications.claim_status == 'not_scheduled'
    ).count()

    return render_template(
        'admin/program_ranked_list.html',
        program=program,
        barangays=barangays,
        eligible_unscheduled_count=eligible_unscheduled_count,
        user=current_user
    )


@admin_bp.route('/programs/<int:program_id>/generate-ranked-list', methods=['POST'], endpoint='generate_program_ranked_list')
@login_required
@role_required('admin')
def generate_program_ranked_list(program_id):
    """Generate ranked beneficiaries for a specific program from completed/unscheduled applications only."""
    program = Programs.query.get_or_404(program_id)
    data = request.get_json() or {}

    try:
        max_beneficiaries = int(data.get('max_beneficiaries', 50))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid max beneficiaries value.'}), 400

    if max_beneficiaries < 1:
        return jsonify({'success': False, 'message': 'Max beneficiaries must be at least 1.'}), 400
    if max_beneficiaries > 1000:
        return jsonify({'success': False, 'message': 'Max beneficiaries cannot exceed 1000.'}), 400

    try:
        min_income = float(data.get('min_income', 0) or 0)
        max_income = float(data.get('max_income', 10000000) or 10000000)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid income range values.'}), 400

    if min_income < 0 or max_income < 0 or min_income > 10000000 or max_income > 10000000:
        return jsonify({'success': False, 'message': 'Income range must be between 0 and 10,000,000.'}), 400
    if min_income > max_income:
        return jsonify({'success': False, 'message': 'Minimum income cannot be greater than maximum income.'}), 400

    priority_barangays = data.get('priority_barangays', []) or []
    priority_groups = (data.get('priority_groups') or program.priority_group or '').strip()
    case_severity = (data.get('case_severity') or '').strip()
    solo_parent_priority = bool(data.get('solo_parent_priority', False))
    student_priority = bool(data.get('student_priority', False))
    pwd_priority = bool(data.get('pwd_priority', False))
    senior_citizen_priority = bool(data.get('senior_citizen_priority', False))

    # Restrict candidate pool to completed applications that are not yet scheduled for claiming.
    query = db.session.query(
        Applications.id.label('application_id'),
        Applications.application_date,
        User.id.label('user_id'),
        User.first_name,
        User.last_name,
        User.email,
        CommunityUsers.age,
        CommunityUsers.barangay,
        CommunityUsers.family_annual_income,
        CommunityUsers.is_solo_parent,
        CommunityUsers.is_student,
        CommunityUsers.is_pwd,
        CommunityUsers.is_currently_employed,
        CommunityUsers.occupation
    ).join(
        User, Applications.user_id == User.id
    ).join(
        CommunityUsers, User.id == CommunityUsers.user_id
    ).filter(
        Applications.program_id == program_id,
        Applications.application_status == 'completed',
        Applications.claim_status == 'not_scheduled'
    )
    
    # Apply severity case filtering if specified
    if case_severity and case_severity in ['unrated', 'low', 'moderate', 'high', 'critical']:
        # Order severity levels for filtering: we want to include the specified level and higher
        severity_levels = ['critical', 'high', 'moderate', 'low', 'unrated']
        severity_index = severity_levels.index(case_severity)
        included_severities = severity_levels[:severity_index + 1]
        
        # Subquery to get the most severe case for each application
        max_severity_subquery = db.session.query(
            func.max(Assessment.case_severity).label('max_severity'),
            Assessment.application_id
        ).group_by(Assessment.application_id).subquery()
        
        query = query.outerjoin(
            max_severity_subquery,
            Applications.id == max_severity_subquery.c.application_id
        ).filter(
            or_(
                max_severity_subquery.c.max_severity.in_(included_severities),
                max_severity_subquery.c.max_severity.is_(None)  # Include applicants without assessments
            )
        )
    
    eligible_rows = query.all()

    if not eligible_rows:
        return jsonify({
            'success': True,
            'count': 0,
            'eligible_pool_count': 0,
            'recommendations': [],
            'message': 'No eligible beneficiaries found. Only completed applications that are not yet scheduled are included.'
        })

    user_ids = [row.user_id for row in eligible_rows]

    # Map user_id to application_id and application_date for quick actions from ranked results.
    application_id_map = {row.user_id: row.application_id for row in eligible_rows}
    application_date_map = {row.user_id: row.application_date for row in eligible_rows}

    # Build compact application history signal for better CBF relevance.
    app_history_rows = db.session.query(
        Applications.user_id,
        Programs.program_name,
        Programs.program_type
    ).join(
        Programs, Applications.program_id == Programs.id
    ).filter(
        Applications.user_id.in_(user_ids),
        Applications.application_status.in_(['approved', 'active', 'completed'])
    ).all()

    app_history_map = {}
    for user_id, program_name, program_type in app_history_rows:
        token = ' '.join(filter(None, [program_name, program_type]))
        if user_id in app_history_map:
            app_history_map[user_id] += ' ' + token
        else:
            app_history_map[user_id] = token

    # Build severity map for each application
    severity_map = {}
    if user_ids:
        severity_rows = db.session.query(
            Applications.user_id,
            func.max(Assessment.case_severity).label('max_severity')
        ).join(
            Assessment, Assessment.application_id == Applications.id
        ).filter(
            Applications.user_id.in_(user_ids)
        ).group_by(Applications.user_id).all()
        
        for user_id, max_severity in severity_rows:
            severity_map[user_id] = max_severity or 'unrated'

    beneficiaries_data = [
        {
            'user_id': row.user_id,
            'first_name': row.first_name,
            'last_name': row.last_name,
            'email': row.email,
            'age': row.age,
            'barangay': row.barangay,
            'family_annual_income': float(row.family_annual_income) if row.family_annual_income and 0 <= row.family_annual_income <= 10000000 else 0,
            'is_solo_parent': row.is_solo_parent,
            'is_student': row.is_student,
            'is_pwd': row.is_pwd,
            'is_currently_employed': row.is_currently_employed,
            'occupation': row.occupation,
            'past_applications': app_history_map.get(row.user_id, ''),
            'case_severity': severity_map.get(row.user_id, 'unrated'),
        }
        for row in eligible_rows
    ]

    requirements = db.session.query(Requirements).join(
        ProgramRequirements, Requirements.id == ProgramRequirements.requirement_id
    ).filter(
        ProgramRequirements.program_id == program_id,
        Requirements.requirement_type == 'qualification'
    ).all()

    req_text = ' '.join([
        req.requirement_name + ' ' + (req.description or '')
        for req in requirements
    ])
    priority_group = (program.priority_group or '').lower()
    priority_tokens = [token.strip() for token in priority_group.split(',') if token.strip()]
    senior_targeted = any(
        token in {'senior', 'senior citizen', 'senior citizens', 'seniors', 'elderly'} or 'senior' in token
        for token in priority_tokens
    )

    max_income_target = _parse_program_income_upper_bound(program.income_range)
    target_profile = {
        'age': SENIOR_CITIZEN_AGE if senior_targeted else DEFAULT_TARGET_AGE,
        'family_annual_income': max_income_target / 2 if max_income_target > 0 else 0,
        'barangay': 'Unknown',
        'is_solo_parent': 'solo parent' in priority_group or 'solo_parent' in priority_group,
        'is_student': 'student' in priority_group,
        'is_pwd': 'pwd' in priority_group or 'disability' in priority_group,
        'is_currently_employed': False,
        'occupation': req_text or program.description or '',
        'past_applications': ' '.join(filter(None, [
            program.program_name,
            program.program_type,
            program.priority_group or ''
        ])),
    }

    ranked = get_recommendations(
        beneficiaries_data=beneficiaries_data,
        target_profile=target_profile,
        max_beneficiaries=max_beneficiaries,
        solo_parent_priority=solo_parent_priority,
        student_priority=student_priority,
        pwd_priority=pwd_priority,
        senior_citizen_priority=senior_citizen_priority,
        priority_barangays=priority_barangays if priority_barangays else None,
        priority_groups=priority_groups,
        min_income=min_income,
        max_income=max_income,
        case_severity_prioritization=bool(case_severity),
    )

    recommendations = []
    for row in ranked:
        user_id = row.get('user_id')
        
        # Use 'score' if available (from rule-based path), otherwise compute from similarity_score
        if 'score' in row:
            score_value = row.get('score', 0.0)
        elif 'similarity_score' in row:
            # CBF path: compute combined score with case severity
            breakdown = row.get('score_breakdown', {})
            score_value = (
                breakdown.get('severity_component', 0) +
                breakdown.get('income_score', 0) +
                breakdown.get('solo_parent_bonus', 0) +
                breakdown.get('student_bonus', 0) +
                breakdown.get('pwd_bonus', 0) +
                breakdown.get('senior_bonus', 0)
            )
        else:
            score_value = 0.0
        
        family_annual_income = row.get('family_annual_income', 0)
        # Ensure income is numeric for the display function
        try:
            income_numeric = float(family_annual_income) if family_annual_income else 0.0
        except (ValueError, TypeError):
            income_numeric = 0.0
        
        # Format application date
        app_date = application_date_map.get(user_id)
        application_date_str = manila_strftime(app_date, '%B %d, %Y at %I:%M %p', 'N/A')
        
        recommendations.append({
            'application_id': application_id_map.get(user_id),
            'user_id': user_id,
            'name': f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
            'email': row.get('email', ''),
            'barangay': row.get('barangay', 'N/A'),
            'income': family_annual_income,
            'income_range': get_income_range_display(income_numeric),
            'application_date': application_date_str,
            'case_severity': row.get('case_severity', 'unrated'),
            'age': row.get('age'),
            'is_solo_parent': row.get('is_solo_parent', False),
            'is_student': row.get('is_student', False),
            'is_pwd': row.get('is_pwd', False),
            'is_senior': (row.get('age') or 0) >= SENIOR_CITIZEN_AGE,
            'score': float(score_value),
            'score_breakdown': row.get('score_breakdown', {}),
        })

    return jsonify({
        'success': True,
        'count': len(recommendations),
        'eligible_pool_count': len(beneficiaries_data),
        'recommendations': recommendations,
        'message': 'Ranked list generated from completed and unscheduled applications only.'
    })

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

        # Remove all dependent references first so deletion works even when linked.
        usage_count = ProgramRequirements.query.filter_by(requirement_id=requirement_id).count()
        application_docs_count = ApplicationDocuments.query.filter_by(requirement_id=requirement_id).count()
        upload_docs_count = ApplicationDocumentUploads.query.filter_by(requirement_id=requirement_id).count()

        ProgramRequirements.query.filter_by(requirement_id=requirement_id).delete(synchronize_session=False)
        ApplicationDocuments.query.filter_by(requirement_id=requirement_id).delete(synchronize_session=False)
        ApplicationDocumentUploads.query.filter_by(requirement_id=requirement_id).delete(synchronize_session=False)

        requirement_name = requirement.requirement_name
        db.session.delete(requirement)
        db.session.commit()

        cleanup_summary = []
        if usage_count:
            cleanup_summary.append(f'unlinked from {usage_count} program(s)')
        if application_docs_count:
            cleanup_summary.append(f'removed {application_docs_count} application requirement record(s)')
        if upload_docs_count:
            cleanup_summary.append(f'removed {upload_docs_count} uploaded document record(s)')

        summary_text = f' ({", ".join(cleanup_summary)})' if cleanup_summary else ''

        return jsonify({
            'success': True,
            'message': f'Requirement "{requirement_name}" deleted successfully{summary_text}'
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
                {'step_name': 'Assessment / SCSR', 'step_description': 'Admin schedules interview or home visit and uploads Social Case Study Report', 'step_type': 'assessment', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'min_items': 1, 'allowed_file_types': ''}
            ]
        },
        'AICS': {
            'name': 'Assistance to Individuals in Crisis Situations',
            'description': 'Standard workflow for AICS programs',
            'steps': [
                {'step_name': 'Application Review', 'step_description': 'Admin reviews and approves your application', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Assessment / SCSR', 'step_description': 'Admin schedules interview or home visit and uploads Social Case Study Report', 'step_type': 'assessment', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Schedule Release', 'step_description': 'Schedule your assistance release date', 'step_type': 'scheduling', 'is_pre_approval': False, 'requires_verification': False, 'min_items': 1, 'allowed_file_types': ''}
            ]
        },
        'default': {
            'name': 'Standard Workflow',
            'description': 'Default workflow for general programs',
            'steps': [
                {'step_name': 'Application Review', 'step_description': 'Admin reviews and approves your application', 'step_type': 'approval', 'is_pre_approval': True, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Submit Required Documents', 'step_description': 'Submit all required documents at MSWD Office or online if enabled', 'step_type': 'document_submission', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
                {'step_name': 'Assessment / SCSR', 'step_description': 'Admin schedules interview or home visit and uploads Social Case Study Report', 'step_type': 'assessment', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
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
                {'step_name': 'Assessment / SCSR', 'step_description': 'Admin schedules interview or home visit and uploads Social Case Study Report', 'step_type': 'assessment', 'is_pre_approval': False, 'requires_verification': True, 'min_items': 1, 'allowed_file_types': ''},
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
    """Schedule a subsidy payout, persist beneficiary list, and redirect to details page."""
    try:
        is_ajax_request = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        category_names = {
            'pwd': 'PWD',
            'senior': 'Senior Citizens',
            'solo_parent': 'Solo Parents'
        }

        def subsidy_error(message, status_code=400):
            if is_ajax_request:
                return jsonify({'success': False, 'message': message}), status_code
            flash(message, 'danger')
            return redirect(url_for('admin.adm_subsidy'))

        # Get form data
        payout_date = request.form.get('payout_date')
        payout_time = request.form.get('payout_time')
        categories = request.form.getlist('categories')
        payout_location = request.form.get('payout_location')
        payout_notes = request.form.get('payout_notes', '')
        
        # Validate inputs
        if not all([payout_date, payout_time, categories, payout_location]):
            return subsidy_error('Please fill in all required fields', 400)

        selected_categories = [cat for cat in categories if cat in category_names]
        if len(selected_categories) != 1:
            return subsidy_error('Please choose exactly one beneficiary category.', 400)

        selected_category = selected_categories[0]
        category_label = category_names[selected_category]
            
        # Combine date and time
        payout_datetime = datetime.strptime(f"{payout_date} {payout_time}", '%Y-%m-%d %H:%M')
        
        # Check if date is in the future
        if payout_datetime <= datetime.now():
            return subsidy_error('Payout date must be in the future', 400)
            
        # Get beneficiaries for selected category from active subsidy list membership.
        member_user_ids = _get_subsidy_member_user_ids(selected_category)
        if not member_user_ids:
            return subsidy_error(f'No beneficiaries found for selected category: {category_label}', 400)

        query = CommunityUsers.query.join(User, CommunityUsers.user_id == User.id).filter(User.role == 'community')
        query = query.filter(CommunityUsers.user_id.in_(list(member_user_ids)))
            
        query = query.order_by(User.last_name, User.first_name)
            
        beneficiaries = query.all()
        
        if not beneficiaries:
            return subsidy_error(f'No beneficiaries found for selected category: {category_label}', 400)
            
        # Create payout id and beneficiary snapshots for storage.
        payout_id = f"PAYOUT-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
        
        beneficiary_snapshot = []
        beneficiary_text_parts = [f"{category_label}:"]
        beneficiary_html_parts = [f'<strong class="text-primary">{category_label}:</strong><br>']

        for index, beneficiary in enumerate(beneficiaries, 1):
            full_name = f"{beneficiary.user.first_name} {beneficiary.user.last_name}".strip()
            barangay = beneficiary.barangay or "Not specified"

            beneficiary_snapshot.append({
                'rank': index,
                'community_user_id': beneficiary.id,
                'user_id': beneficiary.user_id,
                'name': full_name,
                'barangay': barangay,
                'category': category_label
            })

            beneficiary_text_parts.append(f"{index}. {full_name} - {barangay}")
            beneficiary_html_parts.append(f"{index}. {full_name} - <small class='text-muted'>{barangay}</small><br>")
        
        beneficiary_list_text = "\\n".join(beneficiary_text_parts)
        beneficiary_list_html = "".join(beneficiary_html_parts)
        
        # Generate suggested announcement content
        total_beneficiaries = len(beneficiaries)
        category_text = category_label
        
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

        payout_record = SubsidyPayout(
            payout_id=payout_id,
            payout_datetime=payout_datetime,
            payout_location=payout_location,
            payout_notes=payout_notes,
            category_key=selected_category,
            category_label=category_label,
            beneficiary_count=total_beneficiaries,
            beneficiary_snapshot=json.dumps(beneficiary_snapshot),
            beneficiary_list_text=beneficiary_list_text,
            beneficiary_list_html=beneficiary_list_html,
            suggested_title=suggested_title,
            suggested_content=suggested_content,
            status='draft',
            saved_in_system=False,
            scheduled_by=current_user.id
        )

        db.session.add(payout_record)
        db.session.commit()

        redirect_url = url_for('admin.scheduled_beneficiaries', payout_id=payout_id)

        if is_ajax_request:
            return jsonify({
                'success': True,
                'message': 'Payout scheduled successfully!',
                'payout_id': payout_id,
                'suggested_title': suggested_title,
                'suggested_content': suggested_content,
                'beneficiary_list_html': beneficiary_list_html,
                'total_beneficiaries': total_beneficiaries,
                'redirect_url': redirect_url
            }), 200

        flash('Payout scheduled successfully.', 'success')
        return redirect(redirect_url)

    except ValueError as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Invalid date/time format or amount'}), 400
        flash('Invalid date/time format or amount', 'danger')
        return redirect(url_for('admin.adm_subsidy'))
    except Exception as e:
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': f'Error scheduling payout: {str(e)}'}), 500
        flash(f'Error scheduling payout: {str(e)}', 'danger')
        return redirect(url_for('admin.adm_subsidy'))

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

        payout_record = SubsidyPayout.query.filter_by(payout_id=payout_id).first()
        if not payout_record:
            flash('Scheduled payout record not found.', 'error')
            return redirect(url_for('admin.adm_subsidy'))

        if payout_record.beneficiary_list_text and 'LIST OF BENEFICIARIES:' not in announcement_content:
            announcement_content = f"{announcement_content}\n\nLIST OF BENEFICIARIES:\n{payout_record.beneficiary_list_text}"
            
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
        db.session.flush()

        payout_record.announcement_id = announcement.id
        payout_record.saved_in_system = True
        if not payout_record.saved_at:
            payout_record.saved_at = datetime.utcnow()
        payout_record.status = 'announced'

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
    category = _normalize_subsidy_category_key(request.args.get('category'))
    
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
        
        existing_user_ids = _get_subsidy_member_user_ids(category)
        
        if category == 'pwd':
            # For PWD: search verified users not already in subsidy list
            eligible_query = base_query.filter(
                CommunityUsers.pwd_verification == 'approved'
            )
            verification_field = 'pwd_verification'
            
        elif category == 'senior':
            # For Senior Citizens: search age-qualified or verified users not already in list
            eligible_query = base_query.filter(
                or_(
                    CommunityUsers.age >= 60,
                    CommunityUsers.senior_citizen_verification == 'approved'
                )
            )
            verification_field = 'senior_citizen_verification'
            
        elif category == 'solo_parent':
            # For Solo Parents: search verified users not already in subsidy list
            eligible_query = base_query.filter(
                CommunityUsers.solo_parent_verification == 'approved'
            )
            verification_field = 'solo_parent_verification'
            
        else:
            return jsonify({'users': []})

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
    """Notify a user about subsidy eligibility without auto-adding to subsidy list."""
    user_id = request.form.get('user_id')
    category = _normalize_subsidy_category_key(request.form.get('category'))
    category_name = request.form.get('category_name')
    
    if not all([user_id, category, category_name]):
        return jsonify({'success': False, 'message': 'Missing required parameters'})
    
    try:
        # Get the user and their community profile
        user = User.query.get(user_id)
        if not user or not user.community_profile:
            return jsonify({'success': False, 'message': 'User not found or no community profile'})
        
        community_user = user.community_profile
        
        if not _is_user_verified_for_subsidy_category(community_user, category):
            return jsonify({'success': False, 'message': 'User is not verified for this subsidy category yet.'})

        if user.id in _get_subsidy_member_user_ids(category):
            return jsonify({'success': False, 'message': 'User is already included in this subsidy list.'})

        notification = Notifications(
            user_id=user.id,
            notif_title=f'Subsidy Eligibility Notice - {category_name}',
            notif_message=(
                f'You are verified and eligible to apply for {category_name}. '
                f'Please submit your subsidy application in Other Services. '
                f'You will be added to the subsidy list only after your application is reviewed and marked completed by the admin.'
            ),
            related_type='subsidy',
            created_at=datetime.utcnow()
        )
        
        db.session.add(notification)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'{user.first_name} {user.last_name} was notified about subsidy eligibility. They still need to complete the subsidy application workflow.'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error notifying subsidy eligibility: {str(e)}")
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

