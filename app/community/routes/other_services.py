import json
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from sqlalchemy import desc
from flask_login import login_required, current_user
from app.community import community_bp
from app.extensions import db
from app.models import Applications, Assessment, User, UserActivityLog
from app.user_activity_logger import log_user_activity
from app.utils import role_required


def _safe_details(details_text):
    if not details_text:
        return {}
    try:
        if isinstance(details_text, dict):
            return details_text
        return json.loads(details_text)
    except (TypeError, ValueError):
        return {}


def _build_subsidy_cards(profile):
    cards = [
        {
            'key': 'pwd',
            'name': 'Persons with Disability (PWD)',
            'icon': 'fa-wheelchair',
            'description': 'Support for verified PWD beneficiaries including aid and special assistance.',
            'eligible': bool(profile and (profile.is_pwd or profile.pwd_verification == 'approved')),
            'eligibility_note': 'Requires approved PWD verification.'
        },
        {
            'key': 'senior',
            'name': 'Senior Citizens',
            'icon': 'fa-user-clock',
            'description': 'Programs and subsidies for qualified senior citizen community members.',
            'eligible': bool(profile and (profile.age >= 60 or profile.senior_citizen_verification == 'approved')),
            'eligibility_note': 'Available for users aged 60 and above or approved as senior citizen.'
        },
        {
            'key': 'solo_parent',
            'name': 'Solo Parents',
            'icon': 'fa-user-friends',
            'description': 'Assistance and subsidy support intended for verified solo parents.',
            'eligible': bool(profile and (profile.is_solo_parent or profile.solo_parent_verification == 'approved')),
            'eligibility_note': 'Requires approved solo parent verification.'
        }
    ]
    return cards


def _load_user_requests(user_id):
    logs = UserActivityLog.query.filter(
        UserActivityLog.user_id == user_id,
        UserActivityLog.action.in_(['request_subsidy', 'request_assessment'])
    ).order_by(UserActivityLog.created_at.desc()).all()

    subsidy_requests = []
    assessment_requests = []

    for log in logs:
        details = _safe_details(log.details)
        payload = {
            'id': log.id,
            'description': log.description,
            'created_at': log.created_at,
            'status': details.get('status', 'pending'),
            'details': details
        }
        if log.action == 'request_subsidy':
            subsidy_requests.append(payload)
        elif log.action == 'request_assessment':
            assessment_requests.append(payload)

    return subsidy_requests, assessment_requests


def _notify_admins(title, message, related_id=None, related_type='profile'):
    # Local import avoids circular import issues.
    from app.community.routes.notifications import create_notification

    admins = User.query.filter_by(role='admin').all()
    for admin in admins:
        create_notification(
            user_id=admin.id,
            title=title,
            message=message,
            related_id=related_id if related_id is not None else current_user.id,
            related_type=related_type
        )


def _has_open_subsidy_request(subsidy_requests, category):
    open_statuses = {'pending', 'submitted', 'under_review'}
    for req in subsidy_requests:
        req_category = req['details'].get('category')
        req_status = str(req.get('status', '')).lower()
        if req_category == category and req_status in open_statuses:
            return True
    return False

@community_bp.route('/other_services')
@login_required
@role_required('community')
def other_services():
    profile = current_user.community_profile
    subsidy_cards = _build_subsidy_cards(profile)
    subsidy_requests, assessment_requests = _load_user_requests(current_user.id)
    user_applications = Applications.query.filter(
        Applications.user_id == current_user.id,
        Applications.application_status != 'rejected'
    ).order_by(desc(Applications.application_date)).all()

    for card in subsidy_cards:
        card['has_open_request'] = _has_open_subsidy_request(subsidy_requests, card['key'])

    return render_template(
        'community/other_services.html',
        user=current_user,
        subsidy_cards=subsidy_cards,
        subsidy_requests=subsidy_requests,
        assessment_requests=assessment_requests,
        user_applications=user_applications
    )


@community_bp.route('/other_services/subsidy/apply', methods=['POST'])
@login_required
@role_required('community')
def apply_subsidy():
    category = request.form.get('category', '').strip()

    profile = current_user.community_profile
    if not profile:
        flash('Please complete your community profile first.', 'warning')
        return redirect(url_for('community.other_services'))

    subsidy_cards = {card['key']: card for card in _build_subsidy_cards(profile)}
    selected = subsidy_cards.get(category)
    if not selected:
        flash('Invalid subsidy category selected.', 'danger')
        return redirect(url_for('community.other_services'))

    if not selected['eligible']:
        flash(f'You are not yet eligible for {selected["name"]}. Please complete verification requirements first.', 'warning')
        return redirect(url_for('community.other_services'))

    subsidy_requests, _ = _load_user_requests(current_user.id)
    if _has_open_subsidy_request(subsidy_requests, category):
        flash(f'You already have an active request for {selected["name"]}.', 'info')
        return redirect(url_for('community.other_services'))

    details = {
        'category': category,
        'category_name': selected['name'],
        'status': 'pending'
    }

    log_user_activity(
        action='request_subsidy',
        action_type='create',
        entity_type='subsidy',
        description=f'Submitted subsidy request for {selected["name"]}',
        details=details
    )

    _notify_admins(
        title='New Subsidy Request',
        message=f'{current_user.first_name} {current_user.last_name} requested subsidy support for {selected["name"]}.'
    )

    db.session.commit()
    flash(f'Your subsidy request for {selected["name"]} has been submitted.', 'success')
    return redirect(url_for('community.other_services'))


@community_bp.route('/other_services/assessment/request', methods=['POST'])
@login_required
@role_required('community')
def request_assessment_service():
    application_id = request.form.get('application_id', type=int)
    purpose = request.form.get('purpose', '').strip()
    preferred_date = request.form.get('preferred_date', '').strip()
    notes = request.form.get('notes', '').strip()

    if not application_id:
        flash('Please select an application for this assessment request.', 'warning')
        return redirect(url_for('community.other_services'))

    if not purpose:
        flash('Please specify the purpose of your assessment/SCSR request.', 'warning')
        return redirect(url_for('community.other_services'))

    application = Applications.query.filter_by(id=application_id, user_id=current_user.id).first()
    if not application:
        flash('Invalid application selected.', 'danger')
        return redirect(url_for('community.other_services'))

    assigned_admin = User.query.filter_by(role='admin').order_by(User.id.asc()).first()

    preferred_datetime = None
    if preferred_date:
        try:
            preferred_datetime = datetime.strptime(preferred_date, '%Y-%m-%d')
        except ValueError:
            preferred_datetime = None

    assessment_title = f'Requested SCSR: {purpose[:120]}'
    assessment_description = (
        f'Community request for assessment/SCSR.\n'
        f'Purpose: {purpose}\n'
        f'Notes: {notes or "N/A"}'
    )

    assessment = Assessment(
        application_id=application.id,
        assessment_type='interview',
        title=assessment_title,
        description=assessment_description,
        scheduled_date=preferred_datetime,
        status='requested',
        conducted_by=assigned_admin.id if assigned_admin else current_user.id,
    )
    db.session.add(assessment)
    db.session.flush()

    details = {
        'application_id': application.id,
        'assessment_id': assessment.id,
        'purpose': purpose,
        'preferred_date': preferred_date or None,
        'notes': notes or None,
        'status': 'requested'
    }

    log_user_activity(
        action='request_assessment',
        action_type='create',
        entity_type='assessment_request',
        description=f'Submitted assessment/SCSR request for application #{application.id}',
        entity_id=assessment.id,
        details=details
    )

    preferred_text = preferred_date if preferred_date else 'no preferred date'
    _notify_admins(
        title='New Assessment/SCSR Request',
        message=(
            f'{current_user.first_name} {current_user.last_name} requested an assessment/SCSR. '
            f'Application #{application.id} ({application.program.program_name}). '
            f'Purpose: {purpose}. Preferred date: {preferred_text}.'
        ),
        related_id=assessment.id,
        related_type='assessment'
    )

    db.session.commit()
    flash('Your assessment/SCSR request has been submitted.', 'success')
    return redirect(url_for('community.other_services'))