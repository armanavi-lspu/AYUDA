from flask import render_template, request, flash, redirect, url_for, jsonify, abort
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import and_, desc, or_, func
from sqlalchemy.orm import joinedload
from app.admin import admin_bp
from app.models import Programs, Requirements, ProgramRequirements, Applications, FileAttachment, CommunityUsers, User, Announcements, Notifications, Assessment, ApplicationDocuments, ApplicationDocumentUploads, SubsidyPayout, UserActivityLog, ProgramWorkflowSteps, ApplicationWorkflowStatus, AdminUsers
from app.extensions import db
from app.utils import role_required, manila_strftime
from app.activity_logger import log_activity
from app.recommender import get_recommendations, SENIOR_CITIZEN_AGE, NEED_FOCUSED_WEIGHTS
from app.community.routes.profile import get_income_range_display
from app.location_options import MUNICIPALITY_BARANGAYS, get_municipalities, is_valid_municipality
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


def _current_admin_municipality():
    """Return the authenticated admin's municipality scope."""
    profile = getattr(current_user, 'admin_profile', None)
    municipality = (profile.municipality or '').strip() if profile else ''
    return municipality or None


def _scoped_programs_query():
    """Programs owned by admins in the current municipality."""
    municipality = _current_admin_municipality()
    if not municipality:
        return Programs.query.filter(False)

    return Programs.query.join(
        User, Programs.user_id == User.id
    ).join(
        AdminUsers, AdminUsers.user_id == User.id
    ).filter(
        User.role == 'admin',
        func.lower(func.trim(AdminUsers.municipality)) == municipality.lower()
    )


def _scoped_program_or_404(program_id):
    """Return one municipality-scoped program or 404."""
    program = _scoped_programs_query().filter(Programs.id == program_id).first()
    if not program:
        abort(404)
    return program


def _scoped_applications_query():
    """Applications tied to municipality-scoped programs."""
    return Applications.query.filter(
        Applications.program_id.in_(_scoped_programs_query().with_entities(Programs.id))
    )


def _scoped_community_users_query():
    """Community users in the current admin municipality."""
    municipality = _current_admin_municipality()
    if not municipality:
        return CommunityUsers.query.filter(False)

    return CommunityUsers.query.filter(
        func.lower(func.trim(CommunityUsers.municipality)) == municipality.lower()
    )


def _scoped_subsidy_logs_query():
    """Subsidy request logs from community users in the current municipality."""
    municipality = _current_admin_municipality()
    if not municipality:
        return UserActivityLog.query.filter(False)

    return UserActivityLog.query.join(
        User, UserActivityLog.user_id == User.id
    ).join(
        CommunityUsers, CommunityUsers.user_id == User.id
    ).filter(
        User.role == 'community',
        func.lower(func.trim(CommunityUsers.municipality)) == municipality.lower()
    )


def _scoped_subsidy_payouts_query():
    """Saved/scheduled subsidy payout lists created by admins in scope municipality."""
    municipality = _current_admin_municipality()
    if not municipality:
        return SubsidyPayout.query.filter(False)

    return SubsidyPayout.query.join(
        User, SubsidyPayout.scheduled_by == User.id
    ).join(
        AdminUsers, AdminUsers.user_id == User.id
    ).filter(
        User.role == 'admin',
        func.lower(func.trim(AdminUsers.municipality)) == municipality.lower()
    )


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
    if not _current_admin_municipality():
        flash('Your admin account has no municipality assigned. Please update your profile.', 'danger')
        return redirect(url_for('admin.admin_profile'))

    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # Get filter parameters
    search = request.args.get('search', '').strip()
    type_filter = request.args.get('type', '').strip()
    category_filter = request.args.get('category', '').strip()
    period_filter = request.args.get('period', '').strip()
    date_range = request.args.get('date_range', '').strip()
    
    # Base query
    query = _scoped_programs_query().options(
        joinedload(Programs.creator),
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
    program_types = _scoped_programs_query().with_entities(Programs.program_type).distinct().all()
    program_periods = _scoped_programs_query().with_entities(Programs.program_period).distinct().all()
    
    # Calculate statistics
    total_programs = _scoped_programs_query().count()
    
    # Programs with applications
    programs_with_apps = db.session.query(func.count(func.distinct(Applications.program_id))).filter(
        Applications.program_id.in_(_scoped_programs_query().with_entities(Programs.id))
    ).scalar()

    # Active applications across all programs
    active_applications = _scoped_applications_query().filter_by(application_status='active').count()
    
    # Recent programs count (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_programs = _scoped_programs_query().filter(Programs.date >= thirty_days_ago).count()
    
    # Add application count to each program
    for program in pagination.items:
        program.application_count = _scoped_applications_query().filter(Applications.program_id == program.id).count()
        program.active_application_count = _scoped_applications_query().filter(
            Applications.program_id == program.id,
            Applications.application_status == 'active'
        ).count()
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
    return _scoped_subsidy_logs_query().options(joinedload(UserActivityLog.user)).filter(
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

    logs = _scoped_subsidy_logs_query().filter(
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

    recent_subsidy_logs = _scoped_subsidy_logs_query().options(
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

    community_user = _scoped_community_users_query().filter_by(user_id=request_log.user_id).first()
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
    query = _scoped_community_users_query().join(User, CommunityUsers.user_id == User.id)

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
    barangays = _scoped_community_users_query().with_entities(CommunityUsers.barangay)\
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

    community_user = _scoped_community_users_query().filter(CommunityUsers.id == community_user_id).first()
    if not community_user or not community_user.user:
        flash('Beneficiary record not found.', 'danger')
        return redirect(url_for('admin.subsidy_list', category=category))

    subsidy_logs = _scoped_subsidy_logs_query().filter(
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
    ranked_program_id = request.args.get('ranked_program_id', type=int)

    query = _scoped_subsidy_payouts_query()

    if ranked_program_id:
        query = query.filter(SubsidyPayout.category_key == f'program_ranked_{ranked_program_id}')

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

    status_base_query = _scoped_subsidy_payouts_query()
    if ranked_program_id:
        status_base_query = status_base_query.filter(
            SubsidyPayout.category_key == f'program_ranked_{ranked_program_id}'
        )

    status_counts = {
        'draft': status_base_query.filter(SubsidyPayout.status == 'draft').count(),
        'saved': status_base_query.filter(SubsidyPayout.status == 'saved').count(),
        'announced': status_base_query.filter(SubsidyPayout.status == 'announced').count()
    }

    return render_template(
        'admin/scheduled_beneficiaries_list.html',
        payout_lists=pagination.items,
        pagination=pagination,
        search=search,
        status_filter=status_filter,
        ranked_program_id=ranked_program_id,
        status_counts=status_counts,
        user=current_user
    )


@admin_bp.route('/subsidy/scheduled/<string:payout_id>', endpoint='scheduled_beneficiaries')
@login_required
@role_required('admin')
def scheduled_beneficiaries(payout_id):
    """Display a scheduled payout with its beneficiary list and actions."""
    payout = _scoped_subsidy_payouts_query().filter_by(payout_id=payout_id).first_or_404()
    beneficiaries = payout.snapshot_data

    ranked_application_ids = [
        int(row.get('application_id'))
        for row in beneficiaries
        if isinstance(row, dict) and str(row.get('application_id') or '').isdigit()
    ]
    can_schedule_viewed_list = bool(ranked_application_ids)

    pending_ranked_schedule_count = 0
    if ranked_application_ids:
        pending_ranked_schedule_count = _scoped_applications_query().filter(
            Applications.id.in_(ranked_application_ids),
            Applications.claim_status == 'not_scheduled'
        ).count()

    return render_template(
        'admin/scheduled_beneficiaries.html',
        payout=payout,
        beneficiaries=beneficiaries,
        can_schedule_viewed_list=can_schedule_viewed_list,
        pending_ranked_schedule_count=pending_ranked_schedule_count,
        user=current_user
    )


@admin_bp.route('/subsidy/scheduled/<string:payout_id>/save', methods=['POST'], endpoint='save_scheduled_beneficiaries')
@login_required
@role_required('admin')
def save_scheduled_beneficiaries(payout_id):
    """Mark a scheduled payout list as saved in the system."""
    payout = _scoped_subsidy_payouts_query().filter_by(payout_id=payout_id).first_or_404()

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


def _parse_ranked_program_id(category_key):
    """Extract a program id from category keys like 'program_ranked_12'."""
    if not category_key:
        return None

    prefix = 'program_ranked_'
    value = str(category_key).strip().lower()
    if not value.startswith(prefix):
        return None

    suffix = value[len(prefix):]
    if not suffix.isdigit():
        return None

    return int(suffix)


def _normalize_ranked_claim_schedule(claim_date_str, claim_time_raw):
    """Validate and normalize claim date/time into storage-friendly values."""
    claim_date = datetime.strptime(claim_date_str, '%Y-%m-%d')
    raw_time = (claim_time_raw or '').strip()
    if not raw_time:
        raise ValueError('Claim time is required')

    parsed_time = None
    upper_time = raw_time.upper()
    for fmt, value in (('%I:%M %p', upper_time), ('%H:%M', raw_time)):
        try:
            parsed_time = datetime.strptime(value, fmt)
            break
        except ValueError:
            continue

    if parsed_time is None:
        raise ValueError('Invalid claim time format')

    payout_datetime = claim_date.replace(hour=parsed_time.hour, minute=parsed_time.minute)
    normalized_claim_time = parsed_time.strftime('%I:%M %p').lstrip('0')
    return claim_date, normalized_claim_time, payout_datetime


def _build_ranked_snapshot_rows(program, ordered_application_ids):
    """Build snapshot payload rows for a ranked beneficiary list."""
    app_rows = _scoped_applications_query().filter(
        Applications.program_id == program.id,
        Applications.id.in_(ordered_application_ids)
    ).all()
    applications_by_id = {app.id: app for app in app_rows}

    snapshot_rows = []
    beneficiary_text_parts = [f'Program Ranked List: {program.program_name}']
    beneficiary_html_parts = [f'<strong class="text-primary">Program Ranked List: {program.program_name}</strong><br>']

    rank_counter = 0
    for app_id in ordered_application_ids:
        application = applications_by_id.get(app_id)
        if not application:
            continue

        rank_counter += 1
        applicant = application.applicant
        profile = applicant.community_profile if applicant else None
        full_name = f"{(applicant.first_name if applicant else '').strip()} {(applicant.last_name if applicant else '').strip()}".strip() or f'Applicant #{application.user_id}'
        municipality = (profile.municipality if profile and profile.municipality else 'Not specified')
        barangay = (profile.barangay if profile and profile.barangay else 'Not specified')

        snapshot_rows.append({
            'rank': rank_counter,
            'application_id': application.id,
            'user_id': application.user_id,
            'name': full_name,
            'municipality': municipality,
            'barangay': barangay,
            'category': f'Ranked List - {program.program_name}',
        })

        beneficiary_text_parts.append(f'{rank_counter}. {full_name} - {barangay}, {municipality}')
        beneficiary_html_parts.append(
            f"{rank_counter}. {full_name} - <small class='text-muted'>{barangay}, {municipality}</small><br>"
        )

    return snapshot_rows, '\n'.join(beneficiary_text_parts), ''.join(beneficiary_html_parts)


def _schedule_ranked_applications(program, ordered_application_ids, claim_date, claim_time, claim_location, claim_instructions):
    """Apply payout scheduling to ranked applications and update workflow scheduling step."""
    app_rows = _scoped_applications_query().filter(
        Applications.program_id == program.id,
        Applications.id.in_(ordered_application_ids)
    ).all()
    applications_by_id = {app.id: app for app in app_rows}

    scheduling_step = ProgramWorkflowSteps.query.filter_by(
        program_id=program.id,
        step_type='scheduling'
    ).order_by(ProgramWorkflowSteps.step_order.asc()).first()

    now = datetime.utcnow()
    scheduled_count = 0
    skipped = []

    for app_id in ordered_application_ids:
        application = applications_by_id.get(app_id)
        if not application:
            skipped.append({'application_id': app_id, 'reason': 'Application not found for this program.'})
            continue

        if application.application_status not in ['active', 'approved', 'completed']:
            skipped.append({'application_id': app_id, 'reason': 'Application is not eligible for scheduling.'})
            continue

        if application.claim_status in ['scheduled', 'claimed']:
            skipped.append({'application_id': app_id, 'reason': 'Application already has a claim schedule or is already claimed.'})
            continue

        if not application.documents_complete:
            skipped.append({'application_id': app_id, 'reason': 'Required documents are not yet complete.'})
            continue

        was_already_completed = (application.application_status == 'completed')

        application.claim_date = claim_date
        application.claim_time = claim_time
        application.claim_location = claim_location
        application.claim_instructions = claim_instructions
        application.claim_status = 'scheduled'
        application.claim_scheduled_by = current_user.id
        application.claim_scheduled_at = now
        application.application_status = 'completed'
        application.updated_at = now

        if scheduling_step:
            workflow_status = ApplicationWorkflowStatus.query.filter_by(
                application_id=application.id,
                workflow_step_id=scheduling_step.id
            ).first()
            if not workflow_status:
                workflow_status = ApplicationWorkflowStatus(
                    application_id=application.id,
                    workflow_step_id=scheduling_step.id,
                )
                db.session.add(workflow_status)

            workflow_status.step_status = 'approved'
            workflow_status.started_at = workflow_status.started_at or now
            workflow_status.completed_at = now
            workflow_status.reviewed_at = now
            workflow_status.reviewed_by = current_user.id
            workflow_status.admin_feedback = 'Release scheduled from Ranked Beneficiary List.'
            workflow_status.updated_at = now

        if was_already_completed:
            notif_title = 'Release Date Scheduled'
            notif_message = (
                f'📅 Release Date Scheduled!\n\n'
                f'Your financial assistance for {program.program_name} has been scheduled for release:\n\n'
                f'📅 Date: {manila_strftime(claim_date, "%A, %B %d, %Y", "N/A")}\n'
                f'🕐 Time: {claim_time}\n'
                f'📍 Location: {claim_location}\n'
            )
        else:
            notif_title = 'Application Completed - Release Scheduled'
            notif_message = (
                f'🎉 Great news! Your application for {program.program_name} is now COMPLETED!\n\n'
                f'Your financial assistance release has been scheduled:\n\n'
                f'📅 Date: {manila_strftime(claim_date, "%A, %B %d, %Y", "N/A")}\n'
                f'🕐 Time: {claim_time}\n'
                f'📍 Location: {claim_location}\n'
            )

        if claim_instructions:
            notif_message += f'📝 Instructions: {claim_instructions}\n'

        notif_message += '\nPlease be present on the scheduled date and time to claim your assistance. Bring your valid ID and application slip.'

        db.session.add(Notifications(
            user_id=application.user_id,
            notif_title=notif_title,
            notif_message=notif_message,
            is_read=False,
            created_at=now,
        ))

        scheduled_count += 1

    return scheduled_count, skipped


@admin_bp.route('/subsidy/scheduled/<string:payout_id>/schedule', methods=['POST'], endpoint='schedule_saved_ranked_list')
@login_required
@role_required('admin')
def schedule_saved_ranked_list(payout_id):
    """Schedule beneficiaries from a saved ranked list snapshot."""
    payout = _scoped_subsidy_payouts_query().filter_by(payout_id=payout_id).first_or_404()

    program_id = _parse_ranked_program_id(payout.category_key)
    if not program_id:
        flash('This saved list does not support ranked scheduling.', 'warning')
        return redirect(url_for('admin.scheduled_beneficiaries', payout_id=payout_id))

    program = _scoped_programs_query().filter(Programs.id == program_id).first()
    if not program:
        flash('Linked program for this saved list could not be found.', 'danger')
        return redirect(url_for('admin.scheduled_beneficiaries', payout_id=payout_id))

    snapshot_rows = payout.snapshot_data
    application_ids = [
        int(row.get('application_id'))
        for row in snapshot_rows
        if isinstance(row, dict) and str(row.get('application_id') or '').isdigit()
    ]

    if not application_ids:
        flash('No application IDs were found in this saved list snapshot.', 'warning')
        return redirect(url_for('admin.scheduled_beneficiaries', payout_id=payout_id))

    ordered_application_ids = list(dict.fromkeys(application_ids))
    claim_date = payout.payout_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
    claim_time = payout.payout_datetime.strftime('%I:%M %p').lstrip('0')
    claim_location = (payout.payout_location or 'MSWD Office, Municipal Building, Mabitac, Laguna').strip()
    claim_instructions = (payout.payout_notes or '').strip()

    try:
        scheduled_count, skipped = _schedule_ranked_applications(
            program=program,
            ordered_application_ids=ordered_application_ids,
            claim_date=claim_date,
            claim_time=claim_time,
            claim_location=claim_location,
            claim_instructions=claim_instructions,
        )

        if scheduled_count <= 0:
            db.session.rollback()
            flash('No beneficiaries were scheduled from this saved list. They may already be scheduled or currently ineligible.', 'warning')
            return redirect(url_for('admin.scheduled_beneficiaries', payout_id=payout_id))

        if payout.status == 'draft':
            payout.status = 'saved'
        if not payout.saved_in_system:
            payout.saved_in_system = True
        payout.saved_at = payout.saved_at or datetime.utcnow()

        db.session.commit()

        message = f'Successfully scheduled {scheduled_count} beneficiary(ies) from this saved list.'
        if skipped:
            message += f' Skipped {len(skipped)} ineligible record(s).'
        flash(message, 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Error scheduling saved ranked list: {str(exc)}', 'danger')

    return redirect(url_for('admin.scheduled_beneficiaries', payout_id=payout_id))


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
    program = _scoped_programs_query().options(
        db.joinedload(Programs.program_requirements)
        .joinedload(ProgramRequirements.requirement),
        db.joinedload(Programs.applications),  # Load applications for counting
        db.joinedload(Programs.workflow_steps)  # Load workflow steps
    ).filter(Programs.id == id).first_or_404()
    
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
            row[0] for row in _scoped_community_users_query().with_entities(CommunityUsers.barangay)
            .filter(CommunityUsers.barangay.isnot(None))
            .distinct()
            .order_by(CommunityUsers.barangay)
            .all()
        ]
        
        # Get count of eligible unscheduled applications
        eligible_unscheduled_count = _scoped_applications_query().filter(
            Applications.program_id == program.id,
            Applications.application_status == 'completed',
            Applications.claim_status == 'not_scheduled'
        ).count()
        
        # Add application and requirement counts
        program.application_count = _scoped_applications_query().filter(Applications.program_id == program.id).count()
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
            program.updated_at = datetime.utcnow()
            
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
                    program.updated_at = datetime.utcnow()
            
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
    program = _scoped_program_or_404(id)
    program_name = program.program_name
    
    # Check if program has applications
    app_count = _scoped_applications_query().filter(Applications.program_id == id).count()
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
    program = _scoped_program_or_404(id)
    
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
    total_applications = _scoped_applications_query().filter(Applications.program_id == id).count()
    pending_apps = _scoped_applications_query().filter(
        Applications.program_id == id,
        Applications.application_status == 'pending'
    ).count()
    approved_apps = _scoped_applications_query().filter(
        Applications.program_id == id,
        Applications.application_status.in_(['approved', 'active', 'completed'])
    ).count()
    
    # Get recent applications
    recent_applications = _scoped_applications_query().filter(
        Applications.program_id == id
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
    program = _scoped_program_or_404(program_id)

    # Start from the canonical municipality-barangay reference list,
    # then merge additional values seen in existing community records.
    municipality_barangays = {
        municipality: set(barangays)
        for municipality, barangays in MUNICIPALITY_BARANGAYS.items()
    }

    location_rows = db.session.query(
        CommunityUsers.municipality,
        CommunityUsers.barangay
    ).filter(
        CommunityUsers.municipality.isnot(None)
    ).distinct().all()

    for raw_municipality, raw_barangay in location_rows:
        municipality = (raw_municipality or '').strip()
        barangay = (raw_barangay or '').strip()
        if not municipality:
            continue
        municipality_barangays.setdefault(municipality, set())
        if barangay:
            municipality_barangays[municipality].add(barangay)

    canonical_order = list(get_municipalities())
    extra_municipalities = sorted(
        municipality for municipality in municipality_barangays.keys()
        if municipality not in canonical_order
    )
    municipalities = canonical_order + extra_municipalities

    municipality_barangays = {
        municipality: sorted(set(municipality_barangays.get(municipality, [])))
        for municipality in municipalities
    }

    eligible_unscheduled_count = _scoped_applications_query().filter(
        Applications.program_id == program_id,
        Applications.application_status == 'completed',
        Applications.claim_status == 'not_scheduled'
    ).count()

    return render_template(
        'admin/program_ranked_list.html',
        program=program,
        municipalities=municipalities,
        municipality_barangays_json=json.dumps(municipality_barangays),
        eligible_unscheduled_count=eligible_unscheduled_count,
        user=current_user
    )


@admin_bp.route('/programs/<int:program_id>/generate-ranked-list', methods=['POST'], endpoint='generate_program_ranked_list')
@login_required
@role_required('admin')
def generate_program_ranked_list(program_id):
    """Generate ranked beneficiaries for a specific program from completed/unscheduled applications only."""
    program = _scoped_program_or_404(program_id)
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

    completion_date_order = str(data.get('completion_date_order', 'asc') or 'asc').strip().lower()
    if completion_date_order not in {'asc', 'desc'}:
        return jsonify({'success': False, 'message': 'Invalid completion date order. Use asc or desc.'}), 400

    priority_barangays = data.get('priority_barangays', []) or []
    priority_municipality = (data.get('priority_municipality') or '').strip()
    priority_groups = ''
    case_severity = ''
    solo_parent_priority = bool(data.get('solo_parent_priority', False))
    student_priority = bool(data.get('student_priority', False))
    pwd_priority = bool(data.get('pwd_priority', False))
    senior_citizen_priority = bool(data.get('senior_citizen_priority', False))

    def _to_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        return str(value or '').strip().lower() in {'1', 'true', 'yes', 'y', 'on'}

    raw_scoring_parameters = data.get('scoring_parameters') or {}
    if not isinstance(raw_scoring_parameters, dict):
        return jsonify({'success': False, 'message': 'Invalid scoring parameters payload.'}), 400

    scoring_parameters = {
        'case_severity': _to_bool(raw_scoring_parameters.get('case_severity', True)),
        'income_vulnerability': _to_bool(raw_scoring_parameters.get('income_vulnerability', True)),
        'household_vulnerability': _to_bool(raw_scoring_parameters.get('household_vulnerability', True)),
        'repeat_beneficiary_penalty': _to_bool(raw_scoring_parameters.get('repeat_beneficiary_penalty', True)),
    }

    if not any(scoring_parameters.values()):
        return jsonify({'success': False, 'message': 'Select at least one scoring parameter.'}), 400

    raw_scoring_weights = data.get('scoring_weights') or {}
    if not isinstance(raw_scoring_weights, dict):
        return jsonify({'success': False, 'message': 'Invalid scoring weights payload.'}), 400

    default_scoring_weights = {
        key: NEED_FOCUSED_WEIGHTS[key] * 100
        for key in NEED_FOCUSED_WEIGHTS.keys()
    }
    scoring_weights = {}
    for factor_key in NEED_FOCUSED_WEIGHTS.keys():
        try:
            raw_weight = float(raw_scoring_weights.get(factor_key, default_scoring_weights[factor_key]))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': f'Invalid weight for {factor_key}.'}), 400
        if raw_weight < 0:
            return jsonify({'success': False, 'message': 'Scoring weights cannot be negative.'}), 400
        scoring_weights[factor_key] = raw_weight / 100.0

    enabled_total_weight = sum(
        scoring_weights[factor_key]
        for factor_key in NEED_FOCUSED_WEIGHTS.keys()
        if scoring_parameters.get(factor_key)
    )
    if enabled_total_weight <= 0:
        return jsonify({'success': False, 'message': 'Enabled scoring factors must have a positive total weight.'}), 400

    if priority_municipality:
        valid_municipalities = {m for m in get_municipalities() if m}
        valid_municipalities.update(
            (row[0] or '').strip()
            for row in db.session.query(CommunityUsers.municipality)
            .filter(CommunityUsers.municipality.isnot(None)).distinct().all()
            if (row[0] or '').strip()
        )
        if priority_municipality not in valid_municipalities and not is_valid_municipality(priority_municipality):
            return jsonify({'success': False, 'message': 'Invalid municipality filter selected.'}), 400

    # Restrict candidate pool to completed applications that are not yet scheduled for claiming.
    query = db.session.query(
        Applications.id.label('application_id'),
        Applications.application_date,
        User.id.label('user_id'),
        User.first_name,
        User.last_name,
        User.email,
        CommunityUsers.age,
        CommunityUsers.municipality,
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
    app_history_count_map = {}
    for user_id, program_name, program_type in app_history_rows:
        token = ' '.join(filter(None, [program_name, program_type]))
        if user_id in app_history_map:
            app_history_map[user_id] += ' ' + token
        else:
            app_history_map[user_id] = token
        app_history_count_map[user_id] = app_history_count_map.get(user_id, 0) + 1

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
            'municipality': row.municipality,
            'barangay': row.barangay,
            'family_annual_income': float(row.family_annual_income) if row.family_annual_income and 0 <= row.family_annual_income <= 10000000 else 0,
            'is_solo_parent': row.is_solo_parent,
            'is_student': row.is_student,
            'is_pwd': row.is_pwd,
            'is_currently_employed': row.is_currently_employed,
            'occupation': row.occupation,
            'past_applications': app_history_map.get(row.user_id, ''),
            'past_applications_count': app_history_count_map.get(row.user_id, 0),
            'case_severity': severity_map.get(row.user_id, 'unrated'),
        }
        for row in eligible_rows
    ]

    ranked = get_recommendations(
        beneficiaries_data=beneficiaries_data,
        target_profile=None,
        max_beneficiaries=max_beneficiaries,
        solo_parent_priority=solo_parent_priority,
        student_priority=student_priority,
        pwd_priority=pwd_priority,
        senior_citizen_priority=senior_citizen_priority,
        priority_barangays=priority_barangays if priority_barangays else None,
        priority_municipality=priority_municipality or None,
        priority_groups=priority_groups,
        min_income=min_income,
        max_income=max_income,
        case_severity_prioritization=bool(case_severity),
        scoring_parameters=scoring_parameters,
        scoring_weights=scoring_weights,
    )

    # Stable two-pass sorting: completion date order is used only as tie-breaker for equal scores.
    if completion_date_order == 'desc':
        ranked.sort(
            key=lambda row: application_date_map.get(row.get('user_id')) or datetime.min,
            reverse=True,
        )
    else:
        ranked.sort(
            key=lambda row: application_date_map.get(row.get('user_id')) or datetime.max,
        )

    ranked.sort(
        key=lambda row: float(row.get('score', 0.0) or 0.0),
        reverse=True,
    )

    recommendations = []
    for row in ranked:
        user_id = row.get('user_id')

        score_value = float(row.get('score', 0.0) or 0.0)
        
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
            'municipality': row.get('municipality', 'N/A'),
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
        'completion_date_order': completion_date_order,
        'message': 'Ranked list generated from completed and unscheduled applications only.'
    })


@admin_bp.route('/programs/<int:program_id>/save-ranked-list-schedule', methods=['POST'], endpoint='save_ranked_list_schedule_payout')
@login_required
@role_required('admin')
def save_ranked_list_schedule_payout(program_id):
    """Save ranked selection by scheduling payout for all included application IDs."""
    program = _scoped_program_or_404(program_id)
    data = request.get_json() or {}

    application_ids_raw = data.get('application_ids') or []
    if not isinstance(application_ids_raw, list) or not application_ids_raw:
        return jsonify({'success': False, 'message': 'No ranked applications were provided for scheduling.'}), 400

    application_ids = []
    for raw_id in application_ids_raw:
        try:
            parsed_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if parsed_id > 0:
            application_ids.append(parsed_id)

    if not application_ids:
        return jsonify({'success': False, 'message': 'No valid application IDs were provided.'}), 400

    # Preserve order from ranked results while removing duplicates.
    ordered_application_ids = list(dict.fromkeys(application_ids))

    claim_date_str = (data.get('claim_date') or '').strip()
    claim_time_raw = (data.get('claim_time') or '').strip()
    claim_location = (data.get('claim_location') or 'MSWD Office, Municipal Building, Mabitac, Laguna').strip()
    claim_instructions = (data.get('claim_instructions') or '').strip()

    if not claim_date_str or not claim_time_raw:
        return jsonify({'success': False, 'message': 'Claim date and time are required.'}), 400

    try:
        claim_date, claim_time, payout_datetime = _normalize_ranked_claim_schedule(
            claim_date_str=claim_date_str,
            claim_time_raw=claim_time_raw,
        )
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400

    if claim_date.date() <= datetime.now().date():
        return jsonify({'success': False, 'message': 'Claim date must be in the future.'}), 400

    snapshot_rows, beneficiary_list_text, beneficiary_list_html = _build_ranked_snapshot_rows(
        program=program,
        ordered_application_ids=ordered_application_ids,
    )
    if not snapshot_rows:
        return jsonify({'success': False, 'message': 'No valid ranked applications were found for this program.'}), 400

    payout_id = f'RANKED-{program.id}-{datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")}'
    suggested_title = f'Ranked Beneficiary List - {program.program_name}'
    suggested_content = (
        f'Ranked beneficiary list generated for {program.program_name}.\n\n'
        f'Payout Date: {manila_strftime(claim_date, "%B %d, %Y", "N/A")}\n'
        f'Payout Time: {claim_time}\n'
        f'Location: {claim_location}\n\n'
        f'Total Beneficiaries: {len(snapshot_rows)}\n\n'
        f'{beneficiary_list_text}'
    )

    try:
        payout_record = SubsidyPayout(
            payout_id=payout_id,
            payout_datetime=payout_datetime,
            payout_location=claim_location,
            payout_notes=claim_instructions,
            category_key=f'program_ranked_{program.id}',
            category_label=f'Ranked List - {program.program_name}',
            beneficiary_count=len(snapshot_rows),
            beneficiary_snapshot=json.dumps(snapshot_rows),
            beneficiary_list_text=beneficiary_list_text,
            beneficiary_list_html=beneficiary_list_html,
            suggested_title=suggested_title,
            suggested_content=suggested_content,
            status='saved',
            saved_in_system=True,
            saved_at=datetime.utcnow(),
            scheduled_by=current_user.id,
        )
        db.session.add(payout_record)

        scheduled_count, skipped = _schedule_ranked_applications(
            program=program,
            ordered_application_ids=ordered_application_ids,
            claim_date=claim_date,
            claim_time=claim_time,
            claim_location=claim_location,
            claim_instructions=claim_instructions,
        )

        if scheduled_count <= 0:
            db.session.rollback()
            return jsonify({
                'success': False,
                'message': 'No ranked beneficiaries were scheduled. Please review eligibility and claim status.',
                'scheduled_count': 0,
                'skipped_count': len(skipped),
                'skipped': skipped,
            }), 400

        db.session.commit()

        message = f'Successfully scheduled payout for {scheduled_count} ranked beneficiaries.'
        if skipped:
            message += f' Skipped {len(skipped)} application(s) that were no longer eligible.'

        return jsonify({
            'success': True,
            'message': message,
            'scheduled_count': scheduled_count,
            'skipped_count': len(skipped),
            'skipped': skipped,
            'saved_payout_id': payout_id,
            'saved_list_url': url_for('admin.scheduled_beneficiaries', payout_id=payout_id),
        })

    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error scheduling ranked payout: {str(exc)}'}), 500

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
    
    program = _scoped_program_or_404(program_id)
    
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
    
    _scoped_program_or_404(program_id)
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
    
    _scoped_program_or_404(program_id)
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
    
    program = _scoped_program_or_404(program_id)
    
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
    
    program = _scoped_program_or_404(program_id)
    
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
    
    program = _scoped_program_or_404(program_id)
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
    
    program = _scoped_program_or_404(program_id)
    
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

        query = _scoped_community_users_query().join(User, CommunityUsers.user_id == User.id).filter(User.role == 'community')
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

        payout_record = _scoped_subsidy_payouts_query().filter_by(payout_id=payout_id).first()
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
        base_query = _scoped_community_users_query().join(User, CommunityUsers.user_id == User.id)
        
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
        try:
            target_user_id = int(user_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Invalid user ID'}), 400

        # Get the user and their community profile
        community_user = _scoped_community_users_query().filter(
            CommunityUsers.user_id == target_user_id
        ).first()
        if not community_user:
            return jsonify({'success': False, 'message': 'User not found or no community profile'})

        user = community_user.user
        if not user:
            return jsonify({'success': False, 'message': 'User not found or no community profile'})
        
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


