
from flask import render_template, jsonify, request, redirect, url_for, Response, flash
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.utils import role_required, manila_strftime
from app.models import (
    Applications,
    Programs,
    AdminUsers,
    CommunityUsers,
    User,
    Notifications,
    Requirements,
    ProgramRequirements,
    AdminActivityLog,
    UserActivityLog,
)
from app.extensions import db
from app.forecasting import arima_forecast, forecast_program_growth, forecast_program_timeseries
from app.recommender import get_recommendations, SENIOR_CITIZEN_AGE, BeneficiaryRecommender
from app.config.recommender_configs import ConfigFactory, ConfigManager
from app.ml.explainer import BeneficiaryExplainer
from app.ml.fairness_auditor import FairnessAuditor
from app.ml.program_compatibility import ProgramCompatibilityScorer
from app.ml.weight_optimizer import WeightOptimizer
from app.activity_logger import log_recommendation_saved, log_activity
from app.location_options import get_barangays_by_municipality, MUNICIPALITY_BARANGAYS
from sqlalchemy import func, extract, or_, case
from sqlalchemy.orm import aliased
from datetime import datetime, timedelta
import os
from dateutil.relativedelta import relativedelta
import csv
import io
import json
import textwrap

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# Default age for target profile when program priority group is not senior citizens;
# 30 represents a typical working-age beneficiary demographic
DEFAULT_TARGET_AGE = 30

REPORT_TYPE_OPTIONS = (
    {'value': 'applications', 'label': 'Applications'},
    {'value': 'activity_logs', 'label': 'Activity Logs'},
    {'value': 'summary', 'label': 'Summary Report'},
)

DATE_PRESET_OPTIONS = (
    {'value': 'last_7_days', 'label': 'Last 7 Days'},
    {'value': 'last_30_days', 'label': 'Last 30 Days'},
    {'value': 'this_month', 'label': 'This Month'},
    {'value': 'this_year', 'label': 'This Year'},
    {'value': 'custom', 'label': 'Custom Date Range'},
)

EXPORT_FORMAT_OPTIONS = (
    {
        'value': 'pdf',
        'label': 'PDF',
        'description': 'Recommended for better accessibility',
        'recommended': True,
    },
    {
        'value': 'excel',
        'label': 'Excel Spreadsheet',
        'description': 'Table-ready format for spreadsheet workflows',
        'recommended': False,
    },
    {
        'value': 'csv',
        'label': 'CSV File',
        'description': 'Lightweight flat-file export for integrations',
        'recommended': False,
    },
)

QUICK_REPORT_PRESETS = (
    {
        'slug': 'weekly_sessions',
        'name': 'Weekly Sessions',
        'description': 'Community session and authentication activities for the last 7 days.',
        'params': {
            'report_type': 'activity_logs',
            'date_preset': 'last_7_days',
            'log_scope': 'community',
            'activity_focus': 'sessions',
            'export_format': 'pdf',
        },
    },
    {
        'slug': 'weekly_applications',
        'name': 'Weekly Applications',
        'description': 'Applications submitted in the last 7 days across all program types.',
        'params': {
            'report_type': 'applications',
            'date_preset': 'last_7_days',
            'export_format': 'pdf',
        },
    },
    {
        'slug': 'monthly_summary',
        'name': 'Monthly Summary',
        'description': 'Monthly roll-up of applications and activity trends.',
        'params': {
            'report_type': 'summary',
            'date_preset': 'this_month',
            'export_format': 'pdf',
        },
    },
)

DEFAULT_ANALYTICS_APPLICANTS_LABELS = [
    'January 2025', 'February 2025', 'March 2025', 'April 2025',
    'May 2025', 'June 2025', 'July 2025', 'August 2025',
    'September 2025', 'October 2025', 'November 2025', 'December 2025',
]
DEFAULT_ANALYTICS_APPLICANTS_VALUES = [38, 62, 92, 65, 40, 50, 53, 59, 43, 45, 30, 11]

ANALYTICS_FORCE_SEED_DATA = os.environ.get('ANALYTICS_FORCE_SEED_DATA', 'false').lower() == 'true'


def _default_applicants_series():
    return list(DEFAULT_ANALYTICS_APPLICANTS_LABELS), list(DEFAULT_ANALYTICS_APPLICANTS_VALUES)


def _parse_bool_flag(value):
    if value is None:
        return None
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _should_force_seed(request_args):
    flag = _parse_bool_flag(request_args.get('force_seed'))
    if flag is None:
        return ANALYTICS_FORCE_SEED_DATA
    return flag


def _build_seeded_applicants_series(rows, end_month=None):
    start_month = datetime(2025, 1, 1)
    anchor = end_month or datetime.utcnow()
    end_month = datetime(anchor.year, anchor.month, 1)

    month_counts = {}
    for row in rows:
        if not row.month:
            continue
        month_key = datetime(row.month.year, row.month.month, 1)
        month_counts[month_key] = int(row.count or 0)

    labels = []
    values = []
    cursor = start_month
    while cursor <= end_month:
        idx = (cursor.year - 2025) * 12 + (cursor.month - 1)
        if 0 <= idx < len(DEFAULT_ANALYTICS_APPLICANTS_VALUES):
            value = DEFAULT_ANALYTICS_APPLICANTS_VALUES[idx]
        else:
            value = month_counts.get(cursor, 0)
        labels.append(cursor.strftime('%B %Y'))
        values.append(value)
        cursor = cursor + relativedelta(months=1)

    return labels, values

VALID_REPORT_TYPES = {option['value'] for option in REPORT_TYPE_OPTIONS}
VALID_DATE_PRESETS = {option['value'] for option in DATE_PRESET_OPTIONS}
VALID_EXPORT_FORMATS = {option['value'] for option in EXPORT_FORMAT_OPTIONS}
VALID_LOG_SCOPES = {'all', 'admin', 'community'}
VALID_ACTIVITY_FOCUS = {'all', 'sessions', 'applications'}
AREA_OF_CONCERN_OPTIONS = ('Business', 'Education', 'Medical', 'Emergency')
AREA_OF_CONCERN_OPTION_MAP = {
    option.lower(): option
    for option in AREA_OF_CONCERN_OPTIONS
}
AREA_OF_CONCERN_KEYWORDS = {
    'Business': ('business', 'livelihood', 'entrepreneur', 'enterprise', 'capital', 'employment', 'job'),
    'Education': ('education', 'student', 'scholar', 'school', 'tuition', 'training', 'learning'),
    'Medical': ('medical', 'health', 'hospital', 'medicine', 'illness', 'surgery', 'treatment'),
    'Emergency': ('emergency', 'disaster', 'calamity', 'crisis', 'relief', 'urgent'),
}
FAMILY_MONTHLY_INCOME_RANGES = (
    {'min': 0, 'max': 9999, 'display': 'Below ₱10,000'},
    {'min': 10000, 'max': 20000, 'display': '₱10,000 - ₱20,000'},
    {'min': 20001, 'max': 30000, 'display': '₱20,001 - ₱30,000'},
    {'min': 30001, 'max': 40000, 'display': '₱30,001 - ₱40,000'},
    {'min': 40001, 'max': 50000, 'display': '₱40,001 - ₱50,000'},
    {'min': 50001, 'max': 75000, 'display': '₱50,001 - ₱75,000'},
    {'min': 75001, 'max': 100000, 'display': '₱75,001 - ₱100,000'},
    {'min': 100001, 'max': 150000, 'display': '₱100,001 - ₱150,000'},
    {'min': 150001, 'max': 200000, 'display': '₱150,001 - ₱200,000'},
    {'min': 200001, 'max': 300000, 'display': '₱200,001 - ₱300,000'},
    {'min': 300001, 'max': 400000, 'display': '₱300,001 - ₱400,000'},
    {'min': 400001, 'max': 500000, 'display': '₱400,001 - ₱500,000'},
    {'min': 500001, 'max': None, 'display': '₱500,001 and above'},
)


def _parse_community_areas_of_concern(raw_value):
    """Parse a stored community profile areas_of_concern JSON payload."""
    if raw_value in (None, ''):
        return []

    if isinstance(raw_value, list):
        values = raw_value
    else:
        try:
            values = json.loads(raw_value)
        except (TypeError, ValueError):
            return []

    if not isinstance(values, list):
        return []

    parsed = []
    for raw_entry in values:
        normalized = str(raw_entry or '').strip().lower()
        canonical = AREA_OF_CONCERN_OPTION_MAP.get(normalized)
        if canonical and canonical not in parsed:
            parsed.append(canonical)
    return parsed


def _infer_program_area_of_concerns(program):
    """Infer area-of-concern signals from program metadata."""
    if not program:
        return []

    haystack = ' '.join([
        str(getattr(program, 'program_name', '') or ''),
        str(getattr(program, 'description', '') or ''),
        str(getattr(program, 'priority_group', '') or ''),
        str(getattr(program, 'program_type', '') or ''),
    ]).lower()

    inferred = []
    for area_name in AREA_OF_CONCERN_OPTIONS:
        area_token = area_name.lower()
        keyword_tokens = AREA_OF_CONCERN_KEYWORDS.get(area_name, ())
        if area_token in haystack or any(keyword in haystack for keyword in keyword_tokens):
            inferred.append(area_name)

    return inferred


def _normalize_status_expr(column):
    """Return lower-trimmed SQL expression for status comparisons."""
    return func.lower(func.trim(func.coalesce(column, '')))


def _format_family_monthly_income_range(income_value):
    """Map stored family monthly income base value to its configured display range."""
    try:
        numeric = float(income_value)
    except (TypeError, ValueError):
        return 'Not specified'

    for income_range in FAMILY_MONTHLY_INCOME_RANGES:
        lower = income_range['min']
        upper = income_range['max']
        if upper is None and numeric >= lower:
            return income_range['display']
        if upper is not None and lower <= numeric <= upper:
            return income_range['display']

    return f'₱{numeric:,.0f}'


def _current_admin_municipality_key():
    """Return normalized municipality key for the current admin, or None."""
    admin_profile = getattr(current_user, 'admin_profile', None)
    municipality = (getattr(admin_profile, 'municipality', None) or '').strip().lower()
    return municipality or None


def _current_admin_municipality_display():
    """Return display municipality for the current admin, if available."""
    admin_profile = getattr(current_user, 'admin_profile', None)
    municipality = (getattr(admin_profile, 'municipality', None) or '').strip()
    return municipality or None


def _scoped_programs_query():
    municipality_key = _current_admin_municipality_key()
    if not municipality_key:
        return Programs.query.filter(False)

    owner_user = aliased(User)
    owner_admin = aliased(AdminUsers)
    return Programs.query.join(
        owner_user, Programs.user_id == owner_user.id
    ).join(
        owner_admin, owner_admin.user_id == owner_user.id
    ).filter(
        func.lower(func.trim(owner_admin.municipality)) == municipality_key
    )


def _scoped_applications_query():
    municipality_key = _current_admin_municipality_key()
    if not municipality_key:
        return Applications.query.filter(False)

    owner_user = aliased(User)
    owner_admin = aliased(AdminUsers)
    return Applications.query.join(
        Programs, Applications.program_id == Programs.id
    ).join(
        owner_user, Programs.user_id == owner_user.id
    ).join(
        owner_admin, owner_admin.user_id == owner_user.id
    ).filter(
        func.lower(func.trim(owner_admin.municipality)) == municipality_key
    )


def _scoped_community_users_query():
    municipality_key = _current_admin_municipality_key()
    if not municipality_key:
        return CommunityUsers.query.filter(False)

    return CommunityUsers.query.filter(
        func.lower(func.trim(CommunityUsers.municipality)) == municipality_key
    )


def _scoped_admin_activity_logs_query():
    municipality_key = _current_admin_municipality_key()
    if not municipality_key:
        return AdminActivityLog.query.filter(False)

    actor_user = aliased(User)
    actor_admin = aliased(AdminUsers)
    return AdminActivityLog.query.join(
        actor_user, AdminActivityLog.admin_id == actor_user.id
    ).join(
        actor_admin, actor_admin.user_id == actor_user.id
    ).filter(
        func.lower(func.trim(actor_admin.municipality)) == municipality_key
    )


def _scoped_user_activity_logs_query():
    municipality_key = _current_admin_municipality_key()
    if not municipality_key:
        return UserActivityLog.query.filter(False)

    return UserActivityLog.query.join(
        CommunityUsers, UserActivityLog.user_id == CommunityUsers.user_id
    ).filter(
        func.lower(func.trim(CommunityUsers.municipality)) == municipality_key
    )


def _is_emergency_program_snapshot(program_type=None, program_name=None, description=None, priority_group=None, program_period=None):
    """Return True when a program snapshot should be treated as emergency/crisis-response."""
    type_text = str(program_type or '').strip().lower()
    name_text = str(program_name or '').strip().lower()
    desc_text = str(description or '').strip().lower()
    priority_text = str(priority_group or '').strip().lower()
    period_text = str(program_period or '').strip().lower()
    haystack = ' '.join([type_text, name_text, desc_text, priority_text, period_text])
    return (
        type_text == 'esa'
        or period_text == 'emergency'
        or 'emergency' in haystack
        or 'burial assistance' in haystack
        or 'funeral assistance' in haystack
        or 'burial' in name_text
        or 'funeral' in name_text
    )


def _default_report_form_values(preset_slug=None):
    """Build default form values for the analytics report configuration page."""
    defaults = {
        'report_type': 'applications',
        'date_preset': 'last_30_days',
        'start_date': '',
        'end_date': '',
        'application_status': '',
        'program_type': '',
        'log_scope': 'all',
        'activity_focus': 'all',
        'export_format': 'pdf',
    }

    if preset_slug:
        preset = next((item for item in QUICK_REPORT_PRESETS if item['slug'] == preset_slug), None)
        if preset:
            defaults.update(preset.get('params', {}))

    return defaults


def _resolve_report_date_range(date_preset, start_date_raw, end_date_raw):
    """Resolve report date range inputs into start/end datetimes and a display label."""
    if date_preset not in VALID_DATE_PRESETS:
        raise ValueError('Please select a valid date range preset.')

    now = datetime.now()
    today = now.date()

    if date_preset == 'last_7_days':
        start_date = today - timedelta(days=6)
        end_date = today
        label = 'Last 7 Days'
    elif date_preset == 'last_30_days':
        start_date = today - timedelta(days=29)
        end_date = today
        label = 'Last 30 Days'
    elif date_preset == 'this_month':
        start_date = today.replace(day=1)
        end_date = today
        label = 'This Month'
    elif date_preset == 'this_year':
        start_date = today.replace(month=1, day=1)
        end_date = today
        label = 'This Year'
    else:
        if not start_date_raw or not end_date_raw:
            raise ValueError('Custom date range requires both start and end dates.')

        try:
            start_date = datetime.strptime(start_date_raw, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_raw, '%Y-%m-%d').date()
        except ValueError as exc:
            raise ValueError('Custom date range must follow YYYY-MM-DD format.') from exc

        if start_date > end_date:
            raise ValueError('Start date cannot be later than end date.')

        label = f'Custom ({start_date.isoformat()} to {end_date.isoformat()})'

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    return start_dt, end_dt, label


def _build_applications_report(start_dt, end_dt, filters):
    """Build tabular data for applications report exports."""
    status_filter = (filters.get('application_status') or '').strip().lower()
    program_type_filter = (filters.get('program_type') or '').strip()

    applicant_user = aliased(User)
    query = _scoped_applications_query().join(
        applicant_user, Applications.user_id == applicant_user.id
    ).with_entities(
        Applications.id,
        Applications.application_status,
        Applications.application_date,
        applicant_user.first_name,
        applicant_user.last_name,
        applicant_user.email,
        Programs.program_name,
        Programs.program_type,
    ).filter(
        Applications.application_date >= start_dt,
        Applications.application_date <= end_dt,
    )

    if status_filter:
        query = query.filter(Applications.application_status == status_filter)

    if program_type_filter:
        query = query.filter(Programs.program_type == program_type_filter)

    records = query.order_by(Applications.application_date.desc()).all()
    rows = []
    for record in records:
        full_name = f'{record.first_name} {record.last_name}'.strip()
        rows.append([
            record.id,
            full_name,
            record.email,
            record.program_name,
            record.program_type,
            record.application_status,
            manila_strftime(record.application_date, '%Y-%m-%d %H:%M:%S', ''),
        ])

    summary_lines = [f'Total matching applications: {len(rows)}']
    if status_filter:
        summary_lines.append(f'Application status filter: {status_filter}')
    if program_type_filter:
        summary_lines.append(f'Program type filter: {program_type_filter}')

    return {
        'title': 'Applications Report',
        'columns': [
            'Application ID',
            'Applicant Name',
            'Email',
            'Program',
            'Program Type',
            'Status',
            'Application Date',
        ],
        'rows': rows,
        'summary_lines': summary_lines,
    }


def _build_activity_logs_report(start_dt, end_dt, filters):
    """Build tabular data for activity log exports."""
    log_scope = (filters.get('log_scope') or 'all').strip().lower()
    activity_focus = (filters.get('activity_focus') or 'all').strip().lower()

    if log_scope not in VALID_LOG_SCOPES:
        log_scope = 'all'
    if activity_focus not in VALID_ACTIVITY_FOCUS:
        activity_focus = 'all'

    entries = []

    if log_scope in {'all', 'admin'}:
        admin_query = _scoped_admin_activity_logs_query().filter(
            AdminActivityLog.created_at >= start_dt,
            AdminActivityLog.created_at <= end_dt,
        )

        if activity_focus == 'applications':
            admin_query = admin_query.filter(AdminActivityLog.entity_type == 'application')
        elif activity_focus == 'sessions':
            admin_query = admin_query.filter(AdminActivityLog.entity_type == 'session')

        for log in admin_query.all():
            actor_name = (log.admin_name or '').strip()
            if not actor_name:
                actor_name = f'Admin #{log.admin_id}' if log.admin_id else 'Admin'

            entries.append({
                'created_at': log.created_at or datetime.min,
                'role': 'Admin',
                'row': [
                    manila_strftime(log.created_at, '%Y-%m-%d %H:%M:%S', ''),
                    actor_name,
                    'Admin',
                    log.action,
                    log.action_type,
                    log.entity_type,
                    log.description,
                    log.ip_address or '',
                ],
            })

    if log_scope in {'all', 'community'}:
        community_query = _scoped_user_activity_logs_query().filter(
            UserActivityLog.created_at >= start_dt,
            UserActivityLog.created_at <= end_dt,
        )

        if activity_focus == 'applications':
            community_query = community_query.filter(UserActivityLog.entity_type == 'application')
        elif activity_focus == 'sessions':
            community_query = community_query.filter(
                or_(
                    UserActivityLog.entity_type == 'session',
                    UserActivityLog.action_type == 'auth',
                )
            )

        community_logs = community_query.all()
        community_user_ids = sorted({log.user_id for log in community_logs if log.user_id})
        community_names = {}
        if community_user_ids:
            for user_id, first_name, last_name in db.session.query(
                User.id, User.first_name, User.last_name
            ).filter(
                User.id.in_(community_user_ids)
            ).all():
                community_names[user_id] = f'{(first_name or "").strip()} {(last_name or "").strip()}'.strip()

        for log in community_logs:
            actor_name = community_names.get(log.user_id)
            if not actor_name:
                actor_name = f'User #{log.user_id}' if log.user_id else 'Community User'

            entries.append({
                'created_at': log.created_at or datetime.min,
                'role': 'Community',
                'row': [
                    manila_strftime(log.created_at, '%Y-%m-%d %H:%M:%S', ''),
                    actor_name,
                    'Community',
                    log.action,
                    log.action_type,
                    log.entity_type,
                    log.description,
                    log.ip_address or '',
                ],
            })

    entries.sort(key=lambda item: item['created_at'], reverse=True)
    rows = [entry['row'] for entry in entries]

    admin_count = sum(1 for entry in entries if entry['role'] == 'Admin')
    community_count = sum(1 for entry in entries if entry['role'] == 'Community')

    focus_label = 'All Activities'
    if activity_focus == 'sessions':
        focus_label = 'Session Activities'
    elif activity_focus == 'applications':
        focus_label = 'Application Activities'

    summary_lines = [
        f'Total log entries: {len(rows)}',
        f'Admin entries: {admin_count}',
        f'Community entries: {community_count}',
        f'Focus: {focus_label}',
    ]

    return {
        'title': 'Activity Logs Report',
        'columns': [
            'Date & Time',
            'Actor',
            'Role',
            'Action',
            'Action Type',
            'Entity Type',
            'Description',
            'IP Address',
        ],
        'rows': rows,
        'summary_lines': summary_lines,
    }


def _build_summary_report(start_dt, end_dt, filters):
    """Build tabular data for a high-level summary report export."""
    status_filter = (filters.get('application_status') or '').strip().lower()
    program_type_filter = (filters.get('program_type') or '').strip()

    application_query = _scoped_applications_query().filter(
        Applications.application_date >= start_dt,
        Applications.application_date <= end_dt,
    )

    if status_filter:
        application_query = application_query.filter(Applications.application_status == status_filter)

    if program_type_filter:
        application_query = application_query.filter(Programs.program_type == program_type_filter)

    total_applications = application_query.count()

    unique_applicants = application_query.with_entities(
        func.count(func.distinct(Applications.user_id))
    ).scalar() or 0

    status_breakdown = application_query.with_entities(
        Applications.application_status,
        func.count(Applications.id),
    ).group_by(Applications.application_status).all()

    top_programs = _scoped_applications_query().with_entities(
        Programs.program_name,
        func.count(Applications.id).label('application_count'),
    ).filter(
        Applications.application_date >= start_dt,
        Applications.application_date <= end_dt,
    )

    if status_filter:
        top_programs = top_programs.filter(Applications.application_status == status_filter)
    if program_type_filter:
        top_programs = top_programs.filter(Programs.program_type == program_type_filter)

    top_programs = top_programs.group_by(Programs.program_name).order_by(
        func.count(Applications.id).desc()
    ).limit(5).all()

    admin_activity_count = _scoped_admin_activity_logs_query().filter(
        AdminActivityLog.created_at >= start_dt,
        AdminActivityLog.created_at <= end_dt,
    ).count()
    community_activity_count = _scoped_user_activity_logs_query().filter(
        UserActivityLog.created_at >= start_dt,
        UserActivityLog.created_at <= end_dt,
    ).count()

    rows = [
        ['Applications Submitted', total_applications],
        ['Unique Applicants', unique_applicants],
        ['Admin Activity Entries', admin_activity_count],
        ['Community Activity Entries', community_activity_count],
    ]

    for status, count in sorted(status_breakdown, key=lambda item: item[0] or ''):
        label = (status or 'unknown').replace('_', ' ').title()
        rows.append([f'Applications ({label})', count])

    if top_programs:
        rows.append(['Top Programs by Applications', ''])
        for index, (program_name, count) in enumerate(top_programs, start=1):
            rows.append([f'{index}. {program_name}', count])

    summary_lines = [
        'Summary report combines application and activity-level indicators.',
        f'Total summary metrics: {len(rows)}',
    ]
    if status_filter:
        summary_lines.append(f'Application status filter: {status_filter}')
    if program_type_filter:
        summary_lines.append(f'Program type filter: {program_type_filter}')

    return {
        'title': 'Summary Report',
        'columns': ['Metric', 'Value'],
        'rows': rows,
        'summary_lines': summary_lines,
    }


def _build_report_payload(report_type, start_dt, end_dt, filters):
    """Dispatch report payload builder based on report type."""
    if report_type == 'applications':
        return _build_applications_report(start_dt, end_dt, filters)
    if report_type == 'activity_logs':
        return _build_activity_logs_report(start_dt, end_dt, filters)
    return _build_summary_report(start_dt, end_dt, filters)


def _build_delimited_response(report_payload, filename, date_label, delimiter, mimetype, extension):
    """Serialize report payload to CSV/TSV-like formats for download."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter=delimiter)

    writer.writerow([report_payload['title']])
    writer.writerow([f'Date Range: {date_label}'])
    for line in report_payload.get('summary_lines', []):
        writer.writerow([line])
    writer.writerow([])
    writer.writerow(report_payload['columns'])

    for row in report_payload['rows']:
        writer.writerow(row)

    return Response(
        output.getvalue(),
        mimetype=mimetype,
        headers={
            'Content-Disposition': f'attachment; filename={filename}.{extension}'
        },
    )


def _pdf_escape(value):
    """Escape a string value for direct PDF text object rendering."""
    text = str(value).replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    return text.encode('latin-1', 'replace').decode('latin-1')


def _build_simple_pdf(lines):
    """Build a simple, dependency-free PDF document from text lines."""
    safe_lines = [_pdf_escape(line) for line in lines]
    if not safe_lines:
        safe_lines = ['No data available.']

    lines_per_page = 42
    pages = [
        safe_lines[index:index + lines_per_page]
        for index in range(0, len(safe_lines), lines_per_page)
    ]

    if not pages:
        pages = [['No data available.']]

    object_count = 3 + (len(pages) * 2)
    objects = {}

    page_object_ids = []
    for page_index, page_lines in enumerate(pages):
        page_id = 4 + (page_index * 2)
        content_id = page_id + 1
        page_object_ids.append(page_id)

        stream_lines = ['BT', '/F1 10 Tf', '40 780 Td']
        for line_index, line in enumerate(page_lines):
            if line_index > 0:
                stream_lines.append('0 -17 Td')
            stream_lines.append(f'({line}) Tj')
        stream_lines.append('ET')
        stream = '\n'.join(stream_lines)
        stream_bytes = stream.encode('latin-1', 'replace')

        objects[content_id] = (
            f'<< /Length {len(stream_bytes)} >>\n'
            'stream\n'
            f'{stream}\n'
            'endstream'
        )
        objects[page_id] = (
            '<< /Type /Page '
            '/Parent 2 0 R '
            '/MediaBox [0 0 612 792] '
            '/Resources << /Font << /F1 3 0 R >> >> '
            f'/Contents {content_id} 0 R >>'
        )

    kids = ' '.join([f'{page_id} 0 R' for page_id in page_object_ids])
    objects[1] = '<< /Type /Catalog /Pages 2 0 R >>'
    objects[2] = f'<< /Type /Pages /Kids [ {kids} ] /Count {len(page_object_ids)} >>'
    objects[3] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'

    pdf_bytes = bytearray()
    pdf_bytes.extend(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')

    offsets = {}
    for object_id in range(1, object_count + 1):
        offsets[object_id] = len(pdf_bytes)
        pdf_bytes.extend(f'{object_id} 0 obj\n'.encode('ascii'))
        pdf_bytes.extend(objects[object_id].encode('latin-1', 'replace'))
        pdf_bytes.extend(b'\nendobj\n')

    xref_position = len(pdf_bytes)
    pdf_bytes.extend(f'xref\n0 {object_count + 1}\n'.encode('ascii'))
    pdf_bytes.extend(b'0000000000 65535 f \n')
    for object_id in range(1, object_count + 1):
        pdf_bytes.extend(f'{offsets[object_id]:010d} 00000 n \n'.encode('ascii'))

    pdf_bytes.extend(
        (
            f'trailer\n<< /Size {object_count + 1} /Root 1 0 R >>\n'
            f'startxref\n{xref_position}\n%%EOF'
        ).encode('ascii')
    )

    return bytes(pdf_bytes)


def _normalize_table_value(value, max_chars=220):
    """Normalize payload values for safer table rendering in PDF cells."""
    text = str(value if value is not None else '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        return '-'
    if len(text) > max_chars:
        return text[: max_chars - 3] + '...'
    return text


def _estimate_pdf_col_widths(columns, available_width):
    """Estimate balanced table column widths from semantic header hints."""
    if not columns:
        return []

    weights = []
    for column in columns:
        key = str(column or '').lower()
        weight = 1.0

        if 'description' in key or 'message' in key:
            weight = 2.6
        elif 'name' in key:
            weight = 1.8
        elif 'program' in key:
            weight = 1.7
        elif 'email' in key:
            weight = 2.0
        elif 'date' in key or 'time' in key:
            weight = 1.4
        elif 'ip' in key:
            weight = 1.2
        elif 'income' in key:
            weight = 1.3
        elif key.endswith('id') or key == 'id' or ' id' in key:
            weight = 0.8

        weights.append(weight)

    total_weight = sum(weights) if sum(weights) > 0 else len(columns)
    return [available_width * (weight / total_weight) for weight in weights]


def _build_reportlab_pdf(report_payload, date_label):
    """Build a styled table-based PDF document using ReportLab."""
    generated_at = manila_strftime(datetime.now(), '%B %d, %Y %I:%M %p', '')
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=0.45 * inch,
        rightMargin=0.45 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
        title=_normalize_table_value(report_payload.get('title', 'Analytics Report'), max_chars=120),
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'AnalyticsReportTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        textColor=colors.HexColor('#1f2a44'),
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        'AnalyticsReportMeta',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#3f4f63'),
    )
    section_style = ParagraphStyle(
        'AnalyticsReportSection',
        parent=styles['Heading4'],
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=13,
        textColor=colors.HexColor('#1f2a44'),
        spaceBefore=4,
        spaceAfter=4,
    )
    summary_style = ParagraphStyle(
        'AnalyticsReportSummary',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=8.7,
        leading=11,
        textColor=colors.HexColor('#364456'),
        leftIndent=8,
    )
    header_cell_style = ParagraphStyle(
        'AnalyticsReportHeaderCell',
        parent=styles['BodyText'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.white,
        alignment=1,
    )
    body_cell_style = ParagraphStyle(
        'AnalyticsReportBodyCell',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#1f2a44'),
    )

    elements = []
    elements.append(Paragraph(_normalize_table_value(report_payload.get('title', 'Analytics Report'), max_chars=140), title_style))
    elements.append(
        Paragraph(
            f'<b>Generated On:</b> {_normalize_table_value(generated_at, 60)}&nbsp;&nbsp;&nbsp;&nbsp;'
            f'<b>Date Range:</b> {_normalize_table_value(date_label, 100)}',
            meta_style,
        )
    )

    summary_lines = report_payload.get('summary_lines', [])
    if summary_lines:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph('Summary', section_style))
        for line in summary_lines:
            elements.append(Paragraph(f'&#8226; {_normalize_table_value(line, max_chars=180)}', summary_style))

    rows = report_payload.get('rows', [])
    columns = report_payload.get('columns', [])

    elements.append(Spacer(1, 8))
    elements.append(Paragraph('Data Table', section_style))

    if not rows:
        elements.append(Paragraph('No records found for the selected configuration.', meta_style))
        doc.build(elements)
        return buffer.getvalue()

    max_rows = 420
    truncated_count = max(0, len(rows) - max_rows)
    table_rows = rows[:max_rows]

    table_data = [
        [Paragraph(_normalize_table_value(column, max_chars=80), header_cell_style) for column in columns]
    ]

    for row in table_rows:
        padded_row = list(row[: len(columns)]) + [''] * max(0, len(columns) - len(row))
        table_data.append([
            Paragraph(_normalize_table_value(value), body_cell_style)
            for value in padded_row[: len(columns)]
        ])

    col_widths = _estimate_pdf_col_widths(columns, doc.width)
    table = Table(table_data, repeatRows=1, colWidths=col_widths, hAlign='LEFT')
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f6feb')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d7dfeb')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ])

    for row_index in range(1, len(table_data)):
        if row_index % 2 == 0:
            table_style.add('BACKGROUND', (0, row_index), (-1, row_index), colors.HexColor('#f7faff'))

    for col_index, column in enumerate(columns):
        key = str(column or '').lower()
        if 'income' in key or 'count' in key or 'value' in key or 'score' in key:
            table_style.add('ALIGN', (col_index, 1), (col_index, -1), 'RIGHT')
        elif key.endswith('id') or key == 'id' or ' id' in key:
            table_style.add('ALIGN', (col_index, 1), (col_index, -1), 'CENTER')

    table.setStyle(table_style)
    elements.append(table)

    if truncated_count > 0:
        elements.append(Spacer(1, 6))
        elements.append(
            Paragraph(
                f'Note: {truncated_count} row(s) were omitted to keep PDF output readable. '
                'Use CSV/Excel export for full raw datasets.',
                meta_style,
            )
        )

    doc.build(elements)
    return buffer.getvalue()


def _build_pdf_response(report_payload, filename, date_label):
    """Serialize report payload into a downloadable PDF file."""
    if REPORTLAB_AVAILABLE:
        try:
            pdf_content = _build_reportlab_pdf(report_payload, date_label)
            return Response(
                pdf_content,
                mimetype='application/pdf',
                headers={
                    'Content-Disposition': f'attachment; filename={filename}.pdf'
                },
            )
        except Exception:
            # Fall back to the simple generator if table rendering fails.
            pass

    generated_at = manila_strftime(datetime.now(), '%B %d, %Y %I:%M %p', '')

    lines = [
        report_payload['title'],
        f'Generated On: {generated_at}',
        f'Date Range: {date_label}',
        '',
        'Summary',
    ]

    for line in report_payload.get('summary_lines', []):
        lines.extend(textwrap.wrap(str(line), width=95) or [''])

    lines.extend(['', 'Data'])

    headers = ' | '.join([str(column) for column in report_payload['columns']])
    lines.append(headers)
    lines.append('-' * min(len(headers), 110))

    rows = report_payload['rows']
    max_rows = 220
    for row in rows[:max_rows]:
        row_text = ' | '.join([str(value) for value in row])
        lines.extend(textwrap.wrap(row_text, width=110) or [''])

    if len(rows) > max_rows:
        lines.append('')
        lines.append(f'Output truncated: {len(rows) - max_rows} row(s) were omitted in this PDF export.')

    if not rows:
        lines.append('No records found for the selected configuration.')

    pdf_content = _build_simple_pdf(lines)
    return Response(
        pdf_content,
        mimetype='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename={filename}.pdf'
        },
    )

@admin_bp.route('/adm_analytics')
@login_required
@role_required('admin')
def analytics():
    """Main analytics dashboard - redirect to analysis page"""
    return redirect(url_for('admin.analytics_analysis'))

@admin_bp.route('/adm_analytics/analysis')
@login_required
@role_required('admin')
def analytics_analysis():
    """Analysis page with graphs and statistics"""
    # Get date range for filtering (default: last 12 months)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=365)
    admin_municipality_key = _current_admin_municipality_key()
    
    # 1. Applicants count over time (monthly aggregation)
    applicants_over_time_raw = _scoped_applications_query().with_entities(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()

    force_seed = _should_force_seed(request.args)

    # Convert to JSON-friendly format
    if force_seed:
        seeded_labels, seeded_values = _build_seeded_applicants_series(applicants_over_time_raw, end_date)
        applicants_over_time = {
            'labels': seeded_labels,
            'data': seeded_values,
        }
    else:
        applicants_over_time = {
            'labels': [row.month.strftime('%B %Y') if row.month else '' for row in applicants_over_time_raw],
            'data': [row.count for row in applicants_over_time_raw]
        }

    if not force_seed and (not applicants_over_time['labels'] or not applicants_over_time['data']):
        default_labels, default_values = _default_applicants_series()
        applicants_over_time = {
            'labels': default_labels,
            'data': default_values,
        }
    
    # 2. Applications per program type
    applications_by_type_raw = _scoped_applications_query().with_entities(
        Programs.program_type,
        func.count(Applications.id).label('count')
    ).group_by(Programs.program_type).all()
    
    applications_by_type = {
        'labels': [row.program_type for row in applications_by_type_raw],
        'data': [row.count for row in applications_by_type_raw]
    }
    
    # 3. Applicants per barangay (include all barangays, even with zero applicants)
    admin_municipality_display = _current_admin_municipality_display() or ''

    canonical_barangays = list(get_barangays_by_municipality(admin_municipality_display) or [])
    if not canonical_barangays and admin_municipality_display:
        normalized_admin_municipality = admin_municipality_display.strip().lower().replace('.', '')
        for municipality_name, barangays in MUNICIPALITY_BARANGAYS.items():
            normalized_reference = municipality_name.strip().lower().replace('.', '')
            if normalized_reference == normalized_admin_municipality:
                canonical_barangays = list(barangays or [])
                break

    barangays_from_profiles = sorted({
        (row.barangay or '').strip()
        for row in _scoped_community_users_query().with_entities(CommunityUsers.barangay).filter(
            CommunityUsers.barangay.isnot(None),
            func.trim(CommunityUsers.barangay) != ''
        ).distinct().all()
        if (row.barangay or '').strip()
    })

    canonical_set = set(canonical_barangays)
    extra_barangays = [barangay for barangay in barangays_from_profiles if barangay not in canonical_set]
    ordered_barangays = canonical_barangays + extra_barangays if canonical_barangays else barangays_from_profiles

    applicant_user = aliased(User)
    applicant_profile = aliased(CommunityUsers)
    applicants_by_barangay_raw = _scoped_applications_query().join(
        applicant_user, Applications.user_id == applicant_user.id
    ).join(
        applicant_profile, applicant_profile.user_id == applicant_user.id
    ).with_entities(
        applicant_profile.barangay,
        func.count(Applications.id).label('count')
    ).filter(
        applicant_profile.barangay.isnot(None)
    ).group_by(applicant_profile.barangay).all()

    applicants_by_barangay_counts = {barangay: 0 for barangay in ordered_barangays}
    for row in applicants_by_barangay_raw:
        barangay_name = (row.barangay or '').strip()
        if not barangay_name:
            continue
        if barangay_name not in applicants_by_barangay_counts:
            ordered_barangays.append(barangay_name)
            applicants_by_barangay_counts[barangay_name] = 0
        applicants_by_barangay_counts[barangay_name] += int(row.count or 0)

    sorted_applicants_by_barangay = sorted(
        applicants_by_barangay_counts.items(),
        key=lambda item: (-item[1], item[0].lower())
    )
    
    applicants_by_barangay = {
        'labels': [item[0] for item in sorted_applicants_by_barangay],
        'data': [item[1] for item in sorted_applicants_by_barangay]
    }

    # 4. Application completion rate per barangay (top 10 by total applications)
    completion_rate_by_barangay_raw = _scoped_applications_query().join(
        applicant_user, Applications.user_id == applicant_user.id
    ).join(
        applicant_profile, applicant_profile.user_id == applicant_user.id
    ).with_entities(
        applicant_profile.barangay.label('barangay'),
        func.count(Applications.id).label('total_count'),
        func.sum(
            case((Applications.application_status == 'completed', 1), else_=0)
        ).label('completed_count')
    ).filter(
        applicant_profile.barangay.isnot(None),
        func.trim(applicant_profile.barangay) != ''
    ).group_by(
        applicant_profile.barangay
    ).order_by(
        func.count(Applications.id).desc(),
        applicant_profile.barangay.asc()
    ).limit(10).all()

    completion_rate_by_barangay_rows = []
    for row in completion_rate_by_barangay_raw:
        total_count = int(row.total_count or 0)
        completed_count = int(row.completed_count or 0)
        completion_rate = round((completed_count / total_count) * 100, 2) if total_count > 0 else 0.0

        completion_rate_by_barangay_rows.append({
            'barangay': (row.barangay or '').strip(),
            'rate': completion_rate,
            'completed_count': completed_count,
            'total_count': total_count,
        })

    # Keep the selected top-10 barangays, but display them highest-to-lowest by completion rate.
    completion_rate_by_barangay_rows.sort(
        key=lambda item: (-item['rate'], -item['total_count'], item['barangay'].lower())
    )

    completion_rate_by_barangay = {
        'labels': [item['barangay'] for item in completion_rate_by_barangay_rows],
        'rates': [item['rate'] for item in completion_rate_by_barangay_rows],
        'completed_counts': [item['completed_count'] for item in completion_rate_by_barangay_rows],
        'total_counts': [item['total_count'] for item in completion_rate_by_barangay_rows],
    }

    # 5. Community users by municipality (always include all registered municipalities)
    registered_municipalities = [
        'Mabitac',
        'Siniloan',
        'Pakil',
        'Pangil',
        'Famy',
        'Paete',
        'Sta Maria',
        'Kalayaan',
    ]

    municipality_aliases = {
        'mabitac': 'Mabitac',
        'siniloan': 'Siniloan',
        'pakil': 'Pakil',
        'pangil': 'Pangil',
        'famy': 'Famy',
        'paete': 'Paete',
        'sta maria': 'Sta Maria',
        'sta. maria': 'Sta Maria',
        'santa maria': 'Sta Maria',
        'kalayaan': 'Kalayaan',
    }

    def _normalize_municipality_name(raw_name):
        normalized_key = str(raw_name or '').strip().lower()
        return municipality_aliases.get(normalized_key)

    municipality_expr = func.coalesce(
        func.nullif(func.trim(CommunityUsers.municipality), ''),
        'Not Specified'
    )
    users_by_municipality_raw = _scoped_community_users_query().with_entities(
        municipality_expr.label('municipality'),
        func.count(CommunityUsers.id).label('count')
    ).group_by(municipality_expr).all()

    users_by_municipality_counts = {name: 0 for name in registered_municipalities}
    for row in users_by_municipality_raw:
        normalized_name = _normalize_municipality_name(row.municipality)
        if normalized_name:
            users_by_municipality_counts[normalized_name] += int(row.count or 0)

    if admin_municipality_key:
        scoped_counts = {name: count for name, count in users_by_municipality_counts.items() if name.lower() == admin_municipality_key}
        users_by_municipality_counts = {name: 0 for name in registered_municipalities}
        users_by_municipality_counts.update(scoped_counts)

    users_by_municipality = {
        'labels': registered_municipalities,
        'data': [users_by_municipality_counts[name] for name in registered_municipalities]
    }
    
    # Summary statistics
    total_applications = _scoped_applications_query().count()
    total_applicants = _scoped_applications_query().with_entities(func.count(func.distinct(Applications.user_id))).scalar() or 0
    total_programs = _scoped_programs_query().count()
    total_community_users = _scoped_community_users_query().count()
    municipalities_represented = sum(1 for count in users_by_municipality_counts.values() if count > 0)

    top_municipality_name = 'No registered users yet'
    top_municipality_user_count = 0
    if users_by_municipality_counts:
        top_municipality_name, top_municipality_user_count = max(
            users_by_municipality_counts.items(),
            key=lambda item: item[1]
        )
    
    # Application status breakdown
    status_breakdown = _scoped_applications_query().with_entities(
        Applications.application_status,
        func.count(Applications.id).label('count')
    ).group_by(Applications.application_status).all()
    
    return render_template(
        'admin/analytics_analysis.html',
        user=current_user,
        applicants_over_time_json=json.dumps(applicants_over_time),
        applications_by_type_json=json.dumps(applications_by_type),
        applicants_by_barangay_json=json.dumps(applicants_by_barangay),
        completion_rate_by_barangay_json=json.dumps(completion_rate_by_barangay),
        users_by_municipality_json=json.dumps(users_by_municipality),
        total_applications=total_applications,
        total_applicants=total_applicants,
        total_programs=total_programs,
        total_community_users=total_community_users,
        municipalities_represented=municipalities_represented,
        top_municipality_name=top_municipality_name,
        top_municipality_user_count=top_municipality_user_count,
        status_breakdown=status_breakdown
    )


@admin_bp.route('/adm_analytics/reports')
@login_required
@role_required('admin')
def analytics_reports():
    """Render report configuration page for admin analytics exports."""
    selected_preset = (request.args.get('preset') or '').strip().lower()
    form_values = _default_report_form_values(selected_preset)

    for field in form_values.keys():
        value = request.args.get(field)
        if value is not None and value != '':
            form_values[field] = value.strip()

    if form_values.get('date_preset') == 'custom':
        today = datetime.now().date()
        if not form_values.get('start_date'):
            form_values['start_date'] = (today - timedelta(days=6)).isoformat()
        if not form_values.get('end_date'):
            form_values['end_date'] = today.isoformat()

    application_status_options = [
        row[0]
        for row in _scoped_applications_query().with_entities(Applications.application_status)
        .filter(Applications.application_status.isnot(None))
        .distinct()
        .order_by(Applications.application_status)
        .all()
    ]

    program_type_options = [
        row[0]
        for row in _scoped_programs_query().with_entities(Programs.program_type)
        .filter(Programs.program_type.isnot(None))
        .distinct()
        .order_by(Programs.program_type)
        .all()
    ]

    quick_report_presets = []
    for preset in QUICK_REPORT_PRESETS:
        quick_report_presets.append({
            'slug': preset['slug'],
            'name': preset['name'],
            'description': preset['description'],
            'configure_url': url_for('admin.analytics_reports', preset=preset['slug']),
            'generate_url': url_for('admin.analytics_generate_report', **preset['params']),
        })

    return render_template(
        'admin/analytics_reports.html',
        user=current_user,
        report_type_options=REPORT_TYPE_OPTIONS,
        date_preset_options=DATE_PRESET_OPTIONS,
        export_format_options=EXPORT_FORMAT_OPTIONS,
        quick_report_presets=quick_report_presets,
        application_status_options=application_status_options,
        program_type_options=program_type_options,
        form_values=form_values,
    )


@admin_bp.route('/adm_analytics/reports/generate', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def analytics_generate_report():
    """Generate and export reports based on analytics report configuration."""
    source = request.form if request.method == 'POST' else request.args

    report_type = (source.get('report_type') or '').strip().lower()
    date_preset = (source.get('date_preset') or 'last_30_days').strip().lower()
    export_format = (source.get('export_format') or 'pdf').strip().lower()
    start_date = (source.get('start_date') or '').strip()
    end_date = (source.get('end_date') or '').strip()

    if report_type not in VALID_REPORT_TYPES:
        flash('Please choose a valid report type.', 'danger')
        return redirect(url_for('admin.analytics_reports'))

    if export_format not in VALID_EXPORT_FORMATS:
        flash('Please choose a valid export format.', 'danger')
        return redirect(url_for('admin.analytics_reports'))

    filters = {
        'application_status': (source.get('application_status') or '').strip().lower(),
        'program_type': (source.get('program_type') or '').strip(),
        'log_scope': (source.get('log_scope') or 'all').strip().lower(),
        'activity_focus': (source.get('activity_focus') or 'all').strip().lower(),
    }

    try:
        start_dt, end_dt, date_label = _resolve_report_date_range(date_preset, start_date, end_date)
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('admin.analytics_reports'))

    report_payload = _build_report_payload(report_type, start_dt, end_dt, filters)
    timestamp = manila_strftime(datetime.now(), '%Y%m%d_%H%M%S', '')
    filename = f'{report_type}_report_{timestamp}'

    if export_format == 'csv':
        return _build_delimited_response(
            report_payload,
            filename,
            date_label,
            delimiter=',',
            mimetype='text/csv',
            extension='csv',
        )

    if export_format == 'excel':
        return _build_delimited_response(
            report_payload,
            filename,
            date_label,
            delimiter='\t',
            mimetype='application/vnd.ms-excel',
            extension='xls',
        )

    return _build_pdf_response(report_payload, filename, date_label)

@admin_bp.route('/adm_analytics/recommend')
@login_required
@role_required('admin')
def analytics_recommend():
    """Recommendation page for beneficiary selection"""
    requested_program_id = request.args.get('program_id', type=int)

    # Exclude ESA and Emergency-period programs — they are crisis-response programs
    # that do not benefit from predictive beneficiary selection.
    programs = _scoped_programs_query().filter(
        Programs.program_type != 'ESA',
        Programs.program_period != 'Emergency'
    ).all()

    available_program_ids = {program.id for program in programs}
    preselected_program_id = (
        requested_program_id
        if requested_program_id in available_program_ids
        else None
    )

    admin_municipality = _current_admin_municipality_display()
    municipalities = [admin_municipality] if admin_municipality else []
    municipality_barangays = (
        {
            admin_municipality: get_barangays_by_municipality(admin_municipality)
        }
        if admin_municipality
        else {}
    )
    
    return render_template(
        'admin/analytics_recommend.html',
        user=current_user,
        programs=programs,
        preselected_program_id=preselected_program_id,
        municipalities=municipalities,
        admin_municipality=admin_municipality,
        municipality_barangays_json=json.dumps(municipality_barangays),
    )

@admin_bp.route('/api/program/<int:program_id>/parameters')
@login_required
@role_required('admin')
def api_get_program_parameters(program_id):
    """API endpoint to fetch program parameters for auto-fill"""
    program = _scoped_programs_query().filter(Programs.id == program_id).first_or_404()
    
    return jsonify({
        'success': True,
        'priority_group': program.priority_group,
        'income_range': program.income_range,
        'beneficiary_limit': program.beneficiary_limit
    })

@admin_bp.route('/api/analytics/applicants-timeseries')
@login_required
@role_required('admin')
def api_applicants_timeseries():
    """API endpoint for applicants time series data"""
    months = request.args.get('months', 18, type=int)  # Changed from 12 to 18 for better ARIMA accuracy
    # Only allow seed data to be used for the Mabitac MSWDO admin page.
    admin_municipality_key = _current_admin_municipality_key()
    allow_seed = bool(admin_municipality_key and 'mabitac' in admin_municipality_key)

    # If the admin is scoped to Mabitac and the caller did not explicitly pass
    # a force_seed flag, default to showing the seeded 12-month series. If the
    # caller provided an explicit flag, respect it (but only for Mabitac).
    requested_flag = _parse_bool_flag(request.args.get('force_seed'))
    if allow_seed:
        force_seed = True if requested_flag is None else requested_flag
    else:
        force_seed = False
    end_date = datetime.utcnow()
    # Use relativedelta for accurate calendar-month arithmetic; timedelta(days=months*30)
    # undershoots by ~5 days/year and can exclude the earliest data point.
    start_date = end_date - relativedelta(months=months)
    
    data = _scoped_applications_query().with_entities(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()

    if force_seed:
        labels, values = _build_seeded_applicants_series(data, end_date)
        return jsonify({
            'labels': labels,
            'values': values,
        })

    if not data:
        default_labels, default_values = _default_applicants_series()
        return jsonify({
            'labels': default_labels,
            'values': default_values,
        })
    
    return jsonify({
        'labels': [d.month.strftime('%B %Y') for d in data],
        'values': [d.count for d in data]
    })

@admin_bp.route('/api/analytics/generate-recommendations', methods=['POST'])
@login_required
@role_required('admin')
def api_generate_recommendations():
    """
    API endpoint to generate beneficiary recommendations using content-based filtering.
    
    Request Body (JSON):
        program_id: Target program ID for recommendations
        max_beneficiaries: Maximum number of recommendations to return (default: 50)
        priority_barangays: List of barangay names to filter by. If empty list or not 
                           provided, all barangays are included in recommendations.
        priority_municipality: Municipality name to strictly filter recommendations.
        priority_groups: Comma-separated string of priority groups (e.g., "Solo Parent, Student, PWD, Senior Citizen")
                        Takes precedence over individual priority flags if provided.
        area_of_concerns: Applied automatically from selected program context and
                  matched against beneficiary profile selections.
        min_income: Minimum Family Monthly Income filter (default: 0)
        max_income: Maximum Family Monthly Income filter (default: 999999999)
        senior_citizen_priority: Boolean to prioritize senior citizens in scoring (default: False)
    
    Returns:
        JSON with success status, count, recommendations list, and message
    """
    data = request.get_json() or {}
    admin_municipality_key = _current_admin_municipality_key()
    admin_municipality_display = _current_admin_municipality_display()

    if not admin_municipality_key:
        return jsonify({
            'success': False,
            'message': 'Admin municipality is not configured for this account.'
        }), 403

    # Extract parameters with validation
    scoped_program = None
    raw_program_id = data.get('program_id')
    program_id = None
    if raw_program_id not in (None, ''):
        try:
            program_id = int(raw_program_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Invalid program ID supplied.'}), 400

        scoped_program = _scoped_programs_query().filter(Programs.id == program_id).first()
        if not scoped_program:
            return jsonify({
                'success': False,
                'message': 'Selected program was not found for your municipality.'
            }), 404

        # Reject requests for ESA or Emergency-period programs
        if scoped_program.program_type == 'ESA' or scoped_program.program_period == 'Emergency':
            return jsonify({
                'success': False,
                'message': 'Recommendations are not available for ESA or Emergency-type programs.'
            }), 400
    
    try:
        max_beneficiaries = int(data.get('max_beneficiaries', 50))
        if max_beneficiaries < 1:
            return jsonify({'success': False, 'message': 'Max beneficiaries must be at least 1'}), 400
        if max_beneficiaries > 1000:
            return jsonify({'success': False, 'message': 'Max beneficiaries cannot exceed 1000'}), 400
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid max_beneficiaries value'}), 400
    
    # priority_barangays is a list of barangay names; empty list means include all barangays
    priority_barangays = data.get('priority_barangays', [])
    if not isinstance(priority_barangays, list):
        priority_barangays = []

    area_of_concerns = _infer_program_area_of_concerns(scoped_program)

    requested_priority_municipality = (data.get('priority_municipality') or '').strip()
    if requested_priority_municipality and requested_priority_municipality.lower() != admin_municipality_key:
        return jsonify({'success': False, 'message': 'Municipality filter must match your assigned municipality.'}), 403

    priority_municipality = admin_municipality_display or requested_priority_municipality
    
    # Validate income range with comprehensive error handling
    try:
        min_income = float(data.get('min_income', 0) or 0)
        max_income = float(data.get('max_income', 10000000) or 10000000)
        
        # Validate min_income
        if min_income < 0:
            return jsonify({'success': False, 'message': 'Minimum income cannot be negative'}), 400
        if min_income > 10000000:
            return jsonify({'success': False, 'message': 'Minimum income exceeds maximum allowed value (₱10,000,000)'}), 400
        
        # Validate max_income
        if max_income < 0:
            return jsonify({'success': False, 'message': 'Maximum income cannot be negative'}), 400
        if max_income > 10000000:
            return jsonify({'success': False, 'message': 'Maximum income exceeds maximum allowed value (₱10,000,000)'}), 400
        
        # Validate range logic
        if min_income > max_income:
            return jsonify({'success': False, 'message': 'Minimum income cannot be greater than maximum income'}), 400
            
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': f'Invalid income range format: {str(e)}'}), 400
    
    # If a config_type is supplied, load defaults from the config framework
    # and let explicit request parameters override them.
    config_type = data.get('config_type')
    preset = None
    if config_type:
        try:
            preset = ConfigFactory.get_config(config_type)
        except KeyError:
            return jsonify({'success': False, 'message': f'Unknown config_type: {config_type}'}), 400
        # Apply preset defaults for values not explicitly provided
        if 'max_beneficiaries' not in data:
            max_beneficiaries = preset.max_beneficiaries
        if 'min_income' not in data:
            min_income = preset.min_income
        if 'max_income' not in data:
            max_income = preset.max_income
        if 'priority_barangays' not in data and preset.priority_barangays:
            priority_barangays = preset.priority_barangays

    # These three manual filters are intentionally disabled from the analytics UI.
    solo_parent_priority = False
    student_priority = False
    pwd_priority = False
    senior_citizen_priority = data.get('senior_citizen_priority', preset.senior_citizen_priority if preset else False)
    target_is_emergency = _is_emergency_program_snapshot(
        scoped_program.program_type if scoped_program else None,
        scoped_program.program_name if scoped_program else None,
        scoped_program.description if scoped_program else None,
        scoped_program.priority_group if scoped_program else None,
        scoped_program.program_period if scoped_program else None,
    )
    
    # Query all community users with their profiles
    query = db.session.query(
        User.id,
        User.first_name,
        User.last_name,
        User.email,
        CommunityUsers.age,
        CommunityUsers.barangay,
        CommunityUsers.municipality,
        CommunityUsers.family_annual_income,
        CommunityUsers.is_solo_parent,
        CommunityUsers.is_student,
        CommunityUsers.is_pwd,
        CommunityUsers.is_currently_employed,
        CommunityUsers.occupation,
        CommunityUsers.areas_of_concern,
    ).join(
        CommunityUsers, User.id == CommunityUsers.user_id
    ).filter(
        func.lower(func.trim(CommunityUsers.municipality)) == admin_municipality_key,
        CommunityUsers.age.isnot(None),
        CommunityUsers.birth_year.isnot(None),
        CommunityUsers.birth_month.isnot(None),
        CommunityUsers.birth_day.isnot(None),
        CommunityUsers.is_currently_employed.isnot(None),
        CommunityUsers.is_student.isnot(None),
        CommunityUsers.family_annual_income.isnot(None),
        func.length(func.trim(func.coalesce(User.first_name, ''))) > 0,
        func.length(func.trim(func.coalesce(User.last_name, ''))) > 0,
        func.length(func.trim(func.coalesce(User.email, ''))) > 0,
        func.length(func.trim(func.coalesce(CommunityUsers.gender, ''))) > 0,
        func.length(func.trim(func.coalesce(CommunityUsers.mobile_no, ''))) > 0,
        func.length(func.trim(func.coalesce(CommunityUsers.barangay, ''))) > 0,
        func.length(func.trim(func.coalesce(CommunityUsers.address, ''))) > 0,
        func.length(func.trim(func.coalesce(CommunityUsers.municipality, ''))) > 0,
        func.length(func.trim(func.coalesce(CommunityUsers.civil_status, ''))) > 0,
        func.length(func.trim(func.coalesce(CommunityUsers.highest_education_attainment, ''))) > 0,
        func.length(func.trim(func.coalesce(CommunityUsers.occupation, ''))) > 0,
    )
    
    all_users = query.all()
    all_user_ids = [u.id for u in all_users]

    # Build per-user application history text map for semantic similarity features.
    # Use a delimiter so downstream parsing can derive stable counts.
    application_status_key = _normalize_status_expr(Applications.application_status)

    app_history_rows = (
        _scoped_applications_query().with_entities(Applications.user_id, Programs.program_name, Programs.program_type)
        .filter(application_status_key.in_(['approved', 'active', 'completed']))
        .all()
    )
    app_history_map: dict = {}
    for user_id, prog_name, prog_type in app_history_rows:
        tokens = ' '.join(filter(None, [prog_name, prog_type])).strip()
        if not tokens:
            continue
        if user_id in app_history_map:
            app_history_map[user_id] += '|' + tokens
        else:
            app_history_map[user_id] = tokens

    # Enforce cooldown as a hard filter for recommendations:
    # users with recent completed/claimed applications are excluded.
    cooldown_reference = datetime.utcnow() - relativedelta(months=3)
    cooldown_blocked_user_ids = set()
    recent_completion_count_map = {}

    if all_user_ids and not target_is_emergency:
        cooldown_candidate_rows = _scoped_applications_query().with_entities(
            Applications.user_id,
            Applications.application_status,
            Applications.claim_date,
            Applications.updated_at,
            Applications.review_date,
            Applications.application_date,
            Programs.program_name,
            Programs.program_type,
            Programs.program_period,
            Programs.priority_group,
            Programs.description,
        ).filter(
            Applications.user_id.in_(all_user_ids),
            or_(
                application_status_key == 'completed',
                Applications.claim_date.isnot(None),
            )
        ).order_by(
            Applications.user_id.asc(),
            Applications.updated_at.desc(),
            Applications.application_date.desc(),
        ).all()

        for row in cooldown_candidate_rows:
            reference_date = row.claim_date or row.updated_at or row.review_date or row.application_date
            if not reference_date or reference_date < cooldown_reference:
                continue

            if _is_emergency_program_snapshot(
                row.program_type,
                row.program_name,
                row.description,
                row.priority_group,
                row.program_period,
            ):
                continue

            user_id = row.user_id
            cooldown_blocked_user_ids.add(user_id)

            status_key = str(row.application_status or '').strip().lower()
            if status_key == 'completed' or row.claim_date is not None:
                recent_completion_count_map[user_id] = int(recent_completion_count_map.get(user_id, 0)) + 1

    # Build repeat-beneficiary pressure metrics.
    repeat_stats_rows = (
        _scoped_applications_query().with_entities(
            Applications.user_id,
            func.count(Applications.id).label('total_applications_count'),
            func.sum(
                case(
                    (application_status_key.in_(['approved', 'active', 'completed']), 1),
                    else_=0,
                )
            ).label('received_program_count'),
            func.sum(
                case(
                    (application_status_key == 'completed', 1),
                    else_=0,
                )
            ).label('completed_program_count'),
        ).group_by(Applications.user_id).all()
    )

    repeat_stats_map = {}
    for row in repeat_stats_rows:
        repeat_stats_map[row.user_id] = {
            'total_applications_count': int(row.total_applications_count or 0),
            'received_program_count': int(row.received_program_count or 0),
            'completed_program_count': int(row.completed_program_count or 0),
            'recent_completed_within_cooldown_count': int(recent_completion_count_map.get(row.user_id, 0)),
        }

    # Convert to list of dictionaries for the recommender with income validation
    beneficiaries_data = []
    for u in all_users:
        if u.id in cooldown_blocked_user_ids:
            continue

        repeat_stats = repeat_stats_map.get(u.id, {})
        beneficiaries_data.append({
            'user_id': u.id,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'email': u.email,
            'age': u.age,
            'barangay': u.barangay,
            'municipality': u.municipality,
            'family_annual_income': float(u.family_annual_income) if u.family_annual_income and 0 <= u.family_annual_income <= 10000000 else 0,
            'is_solo_parent': u.is_solo_parent,
            'is_student': u.is_student,
            'is_pwd': u.is_pwd,
            'is_currently_employed': u.is_currently_employed,
            'occupation': u.occupation,
            'areas_of_concern': _parse_community_areas_of_concern(u.areas_of_concern),
            'past_applications': app_history_map.get(u.id, ''),
            'past_applications_count': int(repeat_stats.get('total_applications_count', 0)),
            'total_applications_count': int(repeat_stats.get('total_applications_count', 0)),
            'received_program_count': int(repeat_stats.get('received_program_count', 0)),
            'completed_program_count': int(repeat_stats.get('completed_program_count', 0)),
            'recent_completed_within_cooldown_count': int(repeat_stats.get('recent_completed_within_cooldown_count', 0)),
        })

    # Keep all scoped beneficiaries in the recommendation pool. Eligibility constraints
    # such as active applications and cooldowns are surfaced as non-blocking flags
    # in the response so admins can still review these users.

    # Build a target_profile from the program's priority group and requirements so
    # that the CBF (content-based filtering) KNN pipeline can be used instead of
    # plain rule-based scoring.
    target_profile = None
    effective_priority_groups = data.get('priority_groups')
    if scoped_program:
        program = scoped_program
        if not effective_priority_groups and program.priority_group:
            effective_priority_groups = program.priority_group

        # Gather qualification requirements to build a rich text feature.
        requirements = db.session.query(Requirements).join(
            ProgramRequirements, Requirements.id == ProgramRequirements.requirement_id
        ).filter(
            ProgramRequirements.program_id == program_id,
            Requirements.requirement_type == 'qualification'
        ).all()

        req_text = ' '.join([
            r.requirement_name + ' ' + (r.description or '')
            for r in requirements
        ])
        priority_group = (program.priority_group or '').lower()
        priority_tokens = [token.strip() for token in priority_group.split(',') if token.strip()]
        senior_targeted = any(
            token in {'senior', 'senior citizen', 'senior citizens', 'seniors', 'elderly'} or
            'senior' in token
            for token in priority_tokens
        )

        # Use the selected Beneficiary Recommendation income dropdown as the
        # target income signal for CBF income proximity and similarity.
        # For "Below X" selections (min=0), use X directly as target.
        # For explicit ranges, use the midpoint.
        selected_target_income = max_income if min_income <= 0 else ((min_income + max_income) / 2)
        selected_target_income = max(0.0, min(float(selected_target_income), 10000000.0))

        target_profile = {
            # Use a representative age aligned with recommender configuration.
            'age': SENIOR_CITIZEN_AGE if senior_targeted else DEFAULT_TARGET_AGE,
            'family_annual_income': selected_target_income,
            'barangay': 'Unknown',
            'is_solo_parent': 'solo parent' in priority_group or 'solo_parent' in priority_group,
            'is_student': 'student' in priority_group,
            'is_pwd': 'pwd' in priority_group or 'disability' in priority_group,
            'is_currently_employed': False,
            'occupation': req_text or program.description or '',
            # Represent the program itself as a past-application signal so that
            # beneficiaries who have applied to similar programs score higher.
            'past_applications': ' '.join(filter(None, [
                program.program_name,
                program.program_type,
                program.priority_group or '',
            ])),
        }
    
    # Use content-based filtering (CBF) when a target_profile is available;
    # otherwise fall back to rule-based priority scoring.
    recommendations = get_recommendations(
        beneficiaries_data=beneficiaries_data,
        target_profile=target_profile,
        max_beneficiaries=max_beneficiaries,
        solo_parent_priority=solo_parent_priority,
        student_priority=student_priority,
        pwd_priority=pwd_priority,
        senior_citizen_priority=senior_citizen_priority,
        priority_barangays=priority_barangays if priority_barangays else None,
        priority_municipality=priority_municipality or None,
        priority_groups=effective_priority_groups,
        area_of_concerns=area_of_concerns,
        min_income=min_income,
        max_income=max_income
    )
    
    recommendation_user_ids = []
    for recommendation in recommendations:
        try:
            parsed_user_id = int(recommendation.get('user_id'))
        except (TypeError, ValueError):
            continue
        if parsed_user_id > 0:
            recommendation_user_ids.append(parsed_user_id)

    active_application_flags = {}
    if program_id and recommendation_user_ids:
        active_status_key = _normalize_status_expr(Applications.application_status)
        active_rows = _scoped_applications_query().with_entities(
            Applications.user_id,
            Applications.id,
            Applications.application_status,
            Applications.application_date,
        ).filter(
            Applications.program_id == program_id,
            Applications.user_id.in_(recommendation_user_ids),
            active_status_key.in_(['pending', 'approved', 'active'])
        ).order_by(
            Applications.user_id.asc(),
            Applications.application_date.desc()
        ).all()

        for user_id, application_id, application_status, application_date in active_rows:
            if user_id in active_application_flags:
                continue
            active_application_flags[user_id] = {
                'application_id': application_id,
                'status': application_status,
                'application_date': application_date.isoformat() if application_date else None,
            }

    cooldown_flags = {}

    if recommendation_user_ids and not target_is_emergency:
        cooldown_reference = datetime.utcnow() - relativedelta(months=3)
        cooldown_status_key = _normalize_status_expr(Applications.application_status)
        cooldown_rows = _scoped_applications_query().with_entities(
            Applications.user_id,
            Applications.id,
            Applications.application_status,
            Applications.claim_date,
            Applications.updated_at,
            Applications.review_date,
            Applications.application_date,
            Programs.program_name,
            Programs.program_type,
            Programs.program_period,
            Programs.priority_group,
            Programs.description,
        ).filter(
            Applications.user_id.in_(recommendation_user_ids),
            or_(
                cooldown_status_key == 'completed',
                Applications.claim_date.isnot(None)
            )
        ).order_by(
            Applications.user_id.asc(),
            Applications.updated_at.desc(),
            Applications.application_date.desc()
        ).all()

        for row in cooldown_rows:
            user_id = row.user_id
            if user_id in cooldown_flags:
                continue

            reference_date = row.claim_date or row.updated_at or row.review_date or row.application_date
            if not reference_date or reference_date < cooldown_reference:
                continue

            if _is_emergency_program_snapshot(
                row.program_type,
                row.program_name,
                row.description,
                row.priority_group,
                row.program_period,
            ):
                continue

            lock_until_date = (reference_date + relativedelta(months=3)).date()
            cooldown_flags[user_id] = {
                'application_id': row.id,
                'status': row.application_status,
                'program_name': row.program_name or 'previous program',
                'reference_date': reference_date.isoformat(),
                'lock_until': lock_until_date.isoformat(),
            }

    active_application_flags_by_user = {str(user_id): payload for user_id, payload in active_application_flags.items()}
    cooldown_flags_by_user = {str(user_id): payload for user_id, payload in cooldown_flags.items()}

    generated_at = datetime.utcnow().isoformat()
    recommendation_payload = [
        {
            'user_id': r.get('user_id'),
            'name': f"{r.get('first_name', '')} {r.get('last_name', '')}",
            'email': r.get('email', ''),
            'barangay': r.get('barangay', 'N/A'),
            'municipality': r.get('municipality', 'N/A'),
            'income': r.get('family_annual_income', 0),
            'income_range_label': _format_family_monthly_income_range(r.get('family_annual_income', None)),
            'age': r.get('age', None),
            'is_solo_parent': r.get('is_solo_parent', False),
            'is_student': r.get('is_student', False),
            'is_pwd': r.get('is_pwd', False),
            'is_senior': (r.get('age') or 0) >= 60,
            # CBF path produces similarity_score; rule-based path produces score.
            # Use whichever is non-zero so the UI always shows a meaningful value.
            'score': r.get('score') or r.get('similarity_score', 0.0) or 0.0,
            'adjusted_similarity_score': r.get('adjusted_similarity_score', None),
            'repeat_beneficiary_penalty': r.get('repeat_beneficiary_penalty', 0.0),
            'score_breakdown': r.get('score_breakdown', {}),
            'similarity_score': r.get('similarity_score', None),
            'past_applications': r.get('past_applications', ''),
            'past_applications_count': r.get('past_applications_count', 0),
            'received_program_count': r.get('received_program_count', 0),
            'completed_program_count': r.get('completed_program_count', 0),
            'recent_completed_within_cooldown_count': r.get('recent_completed_within_cooldown_count', 0),
            'has_active_application': bool(active_application_flags_by_user.get(str(r.get('user_id')))),
            'active_application': active_application_flags_by_user.get(str(r.get('user_id'))),
            'has_active_cooldown': bool(cooldown_flags_by_user.get(str(r.get('user_id')))),
            'active_cooldown': cooldown_flags_by_user.get(str(r.get('user_id'))),
        }
        for r in recommendations
    ]

    history_program_name = scoped_program.program_name if scoped_program else 'Unknown Program'
    history_filters = {
        'max_beneficiaries': max_beneficiaries,
        'priority_groups': effective_priority_groups or '',
        'priority_municipality': priority_municipality or '',
        'priority_barangays': priority_barangays,
        'area_of_concerns': area_of_concerns,
        'min_income': min_income,
        'max_income': max_income,
        'algorithm': 'content-based-knn' if target_profile else 'rule-based-scoring',
    }

    max_snapshot_items = 500
    stored_user_ids = recommendation_user_ids[:max_snapshot_items]
    stored_snapshot = recommendation_payload[:max_snapshot_items]

    try:
        log_recommendation_saved(
            program_name=history_program_name,
            recommendation_count=len(recommendation_payload),
            details_extra={
                'history_type': 'generated_recommendation',
                'program_id': program_id,
                'generated_at': generated_at,
                'filters': history_filters,
                'recommended_user_ids': stored_user_ids,
                'recommended_user_count': len(recommendation_user_ids),
                'recommended_user_ids_truncated': len(recommendation_user_ids) > len(stored_user_ids),
                'recommendation_snapshot': stored_snapshot,
                'recommendation_snapshot_count': len(recommendation_payload),
                'recommendation_snapshot_truncated': len(recommendation_payload) > len(stored_snapshot),
            }
        )
        db.session.commit()
    except Exception:
        # History logging should not block recommendation generation.
        db.session.rollback()

    return jsonify({
        'success': True,
        'count': len(recommendations),
        'recommendations': recommendation_payload,
        'algorithm': 'content-based-knn' if target_profile else 'rule-based-scoring',
        'program_matched': program_id is not None,
        'priority_groups': effective_priority_groups or '',
        'area_of_concerns': area_of_concerns,
        'generated_at': generated_at,
        'message': 'Recommendations generated using content-based filtering algorithm'
    })


@admin_bp.route('/api/analytics/recommender-configs')
@login_required
@role_required('admin')
def api_recommender_configs():
    """List available pre-defined recommender configurations."""
    return jsonify({
        'success': True,
        'configs': ConfigFactory.list_available_detailed(),
    })


@admin_bp.route('/api/analytics/recommender-config/<config_type>')
@login_required
@role_required('admin')
def api_recommender_config_detail(config_type):
    """Return the full parameter set for a specific config type."""
    try:
        config = ConfigFactory.get_config(config_type)
    except KeyError:
        return jsonify({'success': False, 'message': f'Unknown config type: {config_type}'}), 404
    return jsonify({'success': True, 'config': config.to_dict()})


def _parse_positive_int_list(raw_values):
    """Return unique positive integer IDs from a raw list payload."""
    values = []
    if isinstance(raw_values, list):
        for raw_id in raw_values:
            try:
                parsed_id = int(raw_id)
                if parsed_id > 0:
                    values.append(parsed_id)
            except (TypeError, ValueError):
                continue
    return sorted(set(values))


def _sanitize_export_token(value, fallback='program'):
    """Return a filesystem-safe token for exported filenames."""
    raw = str(value or '').strip().lower()
    cleaned = ''.join(ch if ch.isalnum() else '_' for ch in raw).strip('_')
    return cleaned or fallback


def _coerce_export_rows(raw_rows):
    """Normalize recommendation rows payload from API request JSON."""
    if not isinstance(raw_rows, list):
        return []
    return [row for row in raw_rows if isinstance(row, dict)]


def _build_recommendation_export_payload(data):
    """Build report-payload structure for recommendation list exports."""
    recommendations = _coerce_export_rows(data.get('recommendations'))

    generated_raw = str(data.get('generated_at') or '').strip()
    generated_date = None
    if generated_raw:
        normalized = generated_raw.replace('Z', '+00:00')
        try:
            generated_date = datetime.fromisoformat(normalized)
        except ValueError:
            generated_date = None

    date_label = (
        manila_strftime(generated_date, '%B %d, %Y %I:%M %p', 'N/A')
        if generated_date
        else 'N/A'
    )

    program_name = str(data.get('program_name') or 'Unknown Program').strip() or 'Unknown Program'
    algorithm = str(data.get('algorithm') or 'N/A').strip() or 'N/A'
    priority_groups = str(data.get('priority_groups') or 'N/A').strip() or 'N/A'

    filters = data.get('filters', {})
    if not isinstance(filters, dict):
        filters = {}

    municipality_filter = str(filters.get('priority_municipality') or 'All').strip() or 'All'
    min_income = filters.get('min_income', 0)
    max_income = filters.get('max_income', 0)
    try:
        min_income = float(min_income or 0)
    except (TypeError, ValueError):
        min_income = 0.0
    try:
        max_income = float(max_income or 0)
    except (TypeError, ValueError):
        max_income = 0.0

    rows = []
    for index, rec in enumerate(recommendations, start=1):
        try:
            income_value = float(rec.get('income', 0) or 0)
        except (TypeError, ValueError):
            income_value = 0.0

        score_type = 'Similarity' if rec.get('similarity_score') is not None else 'Priority Score'
        try:
            score_value = float(rec.get('score', 0) or 0)
        except (TypeError, ValueError):
            score_value = 0.0

        rows.append([
            index,
            rec.get('user_id') or '',
            rec.get('name') or '',
            rec.get('email') or '',
            rec.get('municipality') or '',
            rec.get('barangay') or '',
            rec.get('age') if rec.get('age') is not None else '',
            round(income_value, 2),
            'Yes' if rec.get('is_student') else 'No',
            'Yes' if rec.get('is_solo_parent') else 'No',
            'Yes' if rec.get('is_pwd') else 'No',
            'Yes' if rec.get('is_senior') else 'No',
            'Yes' if rec.get('has_active_application') else 'No',
            'Yes' if rec.get('has_active_cooldown') else 'No',
            score_type,
            round(score_value, 4),
        ])

    report_payload = {
        'title': 'Beneficiary Recommendation Export',
        'columns': [
            'Rank', 'User ID', 'Name', 'Email', 'Municipality', 'Barangay', 'Age',
            'Family Monthly Income', 'Student', 'Solo Parent', 'PWD', 'Senior Citizen',
            'Active Application', 'Cooldown Active', 'Score Type', 'Score'
        ],
        'rows': rows,
        'summary_lines': [
            f'Program: {program_name}',
            f'Generated At: {date_label}',
            f'Algorithm: {algorithm}',
            f'Priority Groups: {priority_groups}',
            f'Municipality Filter: {municipality_filter}',
            f'Income Range: PHP {min_income:,.0f} - PHP {max_income:,.0f}',
            f'Recommended Beneficiaries: {len(rows)}',
        ],
    }

    timestamp_token = datetime.utcnow().strftime('%Y%m%dT%H%M%S')
    filename = f"recommendations_{_sanitize_export_token(program_name)}_{timestamp_token}"
    return report_payload, filename, date_label


@admin_bp.route('/api/analytics/save-recommendations', methods=['POST'])
@login_required
@role_required('admin')
def api_save_recommendations():
    """Save/log a recommendation history entry for backward compatibility."""
    data = request.get_json() or {}

    program_id_raw = data.get('program_id')
    try:
        program_id = int(program_id_raw) if program_id_raw not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Invalid program ID supplied.'}), 400

    raw_user_ids = data.get('recommendation_user_ids', [])
    recommendation_user_ids = _parse_positive_int_list(raw_user_ids)

    if recommendation_user_ids:
        scoped_user_ids = {
            row[0]
            for row in _scoped_community_users_query().with_entities(CommunityUsers.user_id).filter(
                CommunityUsers.user_id.in_(recommendation_user_ids)
            ).all()
        }
        recommendation_user_ids = [user_id for user_id in recommendation_user_ids if user_id in scoped_user_ids]

    recommendation_count_raw = data.get('count', len(recommendation_user_ids))
    try:
        recommendation_count = max(0, int(recommendation_count_raw))
    except (TypeError, ValueError):
        recommendation_count = len(recommendation_user_ids)

    recommendation_count = max(recommendation_count, len(recommendation_user_ids))

    program = _scoped_programs_query().filter(Programs.id == program_id).first() if program_id else None
    if program_id and not program:
        return jsonify({'success': False, 'message': 'Selected program was not found for your municipality.'}), 404

    program_name = program.program_name if program else 'Unknown Program'

    filters_payload = data.get('filters', {})
    if not isinstance(filters_payload, dict):
        filters_payload = {}

    generated_at = str(data.get('generated_at') or '').strip() or datetime.utcnow().isoformat()

    max_ids_to_store = 300
    stored_user_ids = recommendation_user_ids[:max_ids_to_store]

    try:
        log_recommendation_saved(
            program_name=program_name,
            recommendation_count=recommendation_count,
            details_extra={
                'program_id': program_id,
                'generated_at': generated_at,
                'filters': filters_payload,
                'recommended_user_ids': stored_user_ids,
                'recommended_user_count': len(recommendation_user_ids),
                'recommended_user_ids_truncated': len(recommendation_user_ids) > len(stored_user_ids),
            }
        )
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Recommendation history entry recorded successfully.',
            'saved_count': len(recommendation_user_ids),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/analytics/saved-recommendations')
@login_required
@role_required('admin')
def api_saved_recommendations():
    """Return recent recommendation history records with summary details."""
    limit = request.args.get('limit', 30, type=int)
    limit = max(1, min(limit, 100))

    logs = _scoped_admin_activity_logs_query().filter(
        AdminActivityLog.action == 'save_recommendation',
        AdminActivityLog.entity_type == 'recommendation'
    ).order_by(
        AdminActivityLog.created_at.desc()
    ).limit(limit).all()

    program_ids = set()
    for log in logs:
        details = log.details_dict if hasattr(log, 'details_dict') else {}
        if not isinstance(details, dict):
            continue
        raw_program_id = details.get('program_id')
        try:
            parsed_program_id = int(raw_program_id) if raw_program_id not in (None, '') else None
        except (TypeError, ValueError):
            parsed_program_id = None
        if parsed_program_id:
            program_ids.add(parsed_program_id)

    programs_map = {}
    if program_ids:
        programs = _scoped_programs_query().filter(Programs.id.in_(program_ids)).all()
        programs_map = {program.id: program.program_name for program in programs}

    saved_lists = []
    for log in logs:
        details = log.details_dict if hasattr(log, 'details_dict') else {}
        if not isinstance(details, dict):
            details = {}

        raw_program_id = details.get('program_id')
        try:
            program_id = int(raw_program_id) if raw_program_id not in (None, '') else None
        except (TypeError, ValueError):
            program_id = None

        filters_payload = details.get('filters', {})
        if not isinstance(filters_payload, dict):
            filters_payload = {}

        recommended_user_ids = _parse_positive_int_list(details.get('recommended_user_ids', []))

        recommended_user_count = details.get('recommended_user_count', len(recommended_user_ids))
        try:
            recommended_user_count = max(int(recommended_user_count), len(recommended_user_ids))
        except (TypeError, ValueError):
            recommended_user_count = len(recommended_user_ids)

        recommendation_count = details.get('recommendation_count', recommended_user_count)
        try:
            recommendation_count = max(int(recommendation_count), recommended_user_count)
        except (TypeError, ValueError):
            recommendation_count = recommended_user_count

        snapshot_count = details.get('recommendation_snapshot_count', recommendation_count)
        try:
            snapshot_count = max(int(snapshot_count), 0)
        except (TypeError, ValueError):
            snapshot_count = recommendation_count

        generated_at = str(details.get('generated_at') or '').strip() or (log.created_at.isoformat() if log.created_at else None)

        saved_lists.append({
            'id': log.id,
            'created_at': log.created_at.isoformat() if log.created_at else None,
            'generated_at': generated_at,
            'admin_id': log.admin_id,
            'admin_name': log.admin_name,
            'program_id': program_id,
            'program_name': programs_map.get(program_id) or details.get('program_name') or 'Unknown Program',
            'recommendation_count': recommendation_count,
            'recommended_user_count': recommended_user_count,
            'recommended_user_ids': recommended_user_ids,
            'recommended_user_ids_truncated': bool(details.get('recommended_user_ids_truncated', False)),
            'has_recommendation_snapshot': bool(isinstance(details.get('recommendation_snapshot', []), list) and details.get('recommendation_snapshot')),
            'recommendation_snapshot_count': snapshot_count,
            'recommendation_snapshot_truncated': bool(details.get('recommendation_snapshot_truncated', False)),
            'history_type': details.get('history_type') or 'saved_recommendation',
            'filters': filters_payload,
        })

    return jsonify({
        'success': True,
        'count': len(saved_lists),
        'saved_lists': saved_lists,
    })


@admin_bp.route('/api/analytics/saved-recommendations/<int:saved_list_id>')
@login_required
@role_required('admin')
def api_saved_recommendation_detail(saved_list_id):
    """Return one recommendation history record with beneficiary details."""
    log = _scoped_admin_activity_logs_query().filter(
        AdminActivityLog.id == saved_list_id,
        AdminActivityLog.action == 'save_recommendation',
        AdminActivityLog.entity_type == 'recommendation'
    ).first()

    if not log:
        return jsonify({'success': False, 'message': 'Recommendation history record not found.'}), 404

    details = log.details_dict if hasattr(log, 'details_dict') else {}
    if not isinstance(details, dict):
        details = {}

    raw_program_id = details.get('program_id')
    try:
        program_id = int(raw_program_id) if raw_program_id not in (None, '') else None
    except (TypeError, ValueError):
        program_id = None

    program = _scoped_programs_query().filter(Programs.id == program_id).first() if program_id else None
    program_name = program.program_name if program else (details.get('program_name') or 'Unknown Program')

    filters_payload = details.get('filters', {})
    if not isinstance(filters_payload, dict):
        filters_payload = {}

    recommended_user_ids = _parse_positive_int_list(details.get('recommended_user_ids', []))

    recommended_user_count = details.get('recommended_user_count', len(recommended_user_ids))
    try:
        recommended_user_count = max(int(recommended_user_count), len(recommended_user_ids))
    except (TypeError, ValueError):
        recommended_user_count = len(recommended_user_ids)

    recommendation_count = details.get('recommendation_count', recommended_user_count)
    try:
        recommendation_count = max(int(recommendation_count), recommended_user_count)
    except (TypeError, ValueError):
        recommendation_count = recommended_user_count

    generated_at = str(details.get('generated_at') or '').strip() or (log.created_at.isoformat() if log.created_at else None)

    beneficiary_rows = []
    if recommended_user_ids:
        admin_municipality_key = _current_admin_municipality_key()
        beneficiary_rows = db.session.query(
            User.id,
            User.first_name,
            User.last_name,
            User.email,
            CommunityUsers.municipality,
            CommunityUsers.barangay,
            CommunityUsers.age,
            CommunityUsers.is_solo_parent,
            CommunityUsers.is_student,
            CommunityUsers.is_pwd,
        ).join(
            CommunityUsers, CommunityUsers.user_id == User.id
        ).filter(
            User.id.in_(recommended_user_ids),
            User.role == 'community',
            func.lower(func.trim(CommunityUsers.municipality)) == admin_municipality_key
        ).all()

    row_map = {row.id: row for row in beneficiary_rows}
    beneficiaries = []
    for user_id in recommended_user_ids:
        row = row_map.get(user_id)
        if not row:
            continue
        age_value = row.age if row.age is not None else None
        beneficiaries.append({
            'user_id': row.id,
            'name': f'{(row.first_name or "").strip()} {(row.last_name or "").strip()}'.strip() or f'User #{row.id}',
            'email': row.email or '',
            'municipality': row.municipality or 'N/A',
            'barangay': row.barangay or 'N/A',
            'age': age_value,
            'is_solo_parent': bool(row.is_solo_parent),
            'is_student': bool(row.is_student),
            'is_pwd': bool(row.is_pwd),
            'is_senior': bool(age_value is not None and age_value >= SENIOR_CITIZEN_AGE),
        })

    raw_snapshot = details.get('recommendation_snapshot', [])
    recommendation_snapshot = []
    if isinstance(raw_snapshot, list):
        recommendation_snapshot = [row for row in raw_snapshot if isinstance(row, dict)]

    if not recommendation_snapshot and beneficiaries:
        recommendation_snapshot = [
            {
                'user_id': row.get('user_id'),
                'name': row.get('name', ''),
                'email': row.get('email', ''),
                'barangay': row.get('barangay', 'N/A'),
                'municipality': row.get('municipality', 'N/A'),
                'income': 0,
                'income_range_label': '',
                'age': row.get('age'),
                'is_solo_parent': row.get('is_solo_parent', False),
                'is_student': row.get('is_student', False),
                'is_pwd': row.get('is_pwd', False),
                'is_senior': row.get('is_senior', False),
                'score': 0.0,
                'adjusted_similarity_score': None,
                'repeat_beneficiary_penalty': 0.0,
                'score_breakdown': {},
                'similarity_score': None,
                'past_applications': '',
                'past_applications_count': 0,
                'received_program_count': 0,
                'completed_program_count': 0,
                'recent_completed_within_cooldown_count': 0,
                'has_active_application': False,
                'active_application': None,
                'has_active_cooldown': False,
                'active_cooldown': None,
            }
            for row in beneficiaries
        ]

    snapshot_count = details.get('recommendation_snapshot_count', recommendation_count)
    try:
        snapshot_count = max(int(snapshot_count), len(recommendation_snapshot))
    except (TypeError, ValueError):
        snapshot_count = max(recommendation_count, len(recommendation_snapshot))

    saved_list_payload = {
        'id': log.id,
        'created_at': log.created_at.isoformat() if log.created_at else None,
        'generated_at': generated_at,
        'admin_id': log.admin_id,
        'admin_name': log.admin_name,
        'program_id': program_id,
        'program_name': program_name,
        'recommendation_count': recommendation_count,
        'recommended_user_count': recommended_user_count,
        'recommended_user_ids': recommended_user_ids,
        'recommended_user_ids_truncated': bool(details.get('recommended_user_ids_truncated', False)),
        'has_recommendation_snapshot': bool(recommendation_snapshot),
        'recommendation_snapshot_count': snapshot_count,
        'recommendation_snapshot_truncated': bool(details.get('recommendation_snapshot_truncated', False)),
        'history_type': details.get('history_type') or 'saved_recommendation',
        'filters': filters_payload,
    }

    return jsonify({
        'success': True,
        'saved_list': saved_list_payload,
        'recommendations': recommendation_snapshot,
        'beneficiaries': beneficiaries,
        'beneficiary_count': len(beneficiaries),
    })


@admin_bp.route('/api/analytics/saved-recommendations/<int:saved_list_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def api_delete_saved_recommendation(saved_list_id):
    """Retained for backward compatibility; recommendation history records are immutable."""
    return jsonify({
        'success': False,
        'message': 'Recommendation history records cannot be deleted.'
    }), 403


@admin_bp.route('/api/analytics/export-recommendations', methods=['POST'])
@login_required
@role_required('admin')
def api_export_recommendations():
    """Export generated recommendation list as CSV, Excel, or PDF."""
    data = request.get_json() or {}
    export_format = str(data.get('export_format') or 'csv').strip().lower()

    if export_format not in {'csv', 'excel', 'pdf'}:
        return jsonify({'success': False, 'message': 'Invalid export format.'}), 400

    report_payload, filename, date_label = _build_recommendation_export_payload(data)

    if export_format == 'csv':
        return _build_delimited_response(
            report_payload,
            filename,
            date_label,
            delimiter=',',
            mimetype='text/csv',
            extension='csv',
        )

    if export_format == 'excel':
        return _build_delimited_response(
            report_payload,
            filename,
            date_label,
            delimiter='\t',
            mimetype='application/vnd.ms-excel',
            extension='xls',
        )

    return _build_pdf_response(report_payload, filename, date_label)


@admin_bp.route('/api/analytics/notify-recommendations', methods=['POST'])
@login_required
@role_required('admin')
def api_notify_recommendations():
    """Send recommendation notifications to selected users."""
    data = request.get_json() or {}

    program_id_raw = data.get('program_id')
    try:
        program_id = int(program_id_raw)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'A valid program ID is required.'}), 400

    program = _scoped_programs_query().filter(Programs.id == program_id).first()
    if not program:
        return jsonify({'success': False, 'message': 'Selected program was not found for your municipality.'}), 404

    raw_user_ids = data.get('user_ids') or data.get('recommendation_user_ids') or []
    user_ids = _parse_positive_int_list(raw_user_ids)
    if not user_ids:
        return jsonify({'success': False, 'message': 'No valid beneficiaries were provided for notification.'}), 400

    admin_municipality_key = _current_admin_municipality_key()
    target_rows = db.session.query(User.id).join(
        CommunityUsers, CommunityUsers.user_id == User.id
    ).filter(
        User.id.in_(user_ids),
        User.role == 'community',
        func.lower(func.trim(CommunityUsers.municipality)) == admin_municipality_key
    ).all()

    target_user_ids = [row[0] for row in target_rows]
    if not target_user_ids:
        return jsonify({'success': False, 'message': 'No eligible community users found to notify.'}), 400

    notifications = []
    for user_id in target_user_ids:
        notifications.append(Notifications(
            user_id=user_id,
            notif_title=f'Program Recommendation: {program.program_name}',
            notif_message=(
                f'You are included in the recommended beneficiary list for {program.program_name}. '
                f'Click this notification to open the Programs page and review the recommendation.'
            ),
            related_type='program',
            related_id=None,
            created_at=datetime.utcnow(),
        ))

    try:
        db.session.add_all(notifications)

        log_activity(
            action='notify_recommended_beneficiaries',
            action_type='create',
            entity_type='recommendation',
            description=(
                f'Sent recommendation notifications for "{program.program_name}" '
                f'to {len(target_user_ids)} community user(s).'
            ),
            entity_id=program.id,
            details={
                'program_id': program.id,
                'program_name': program.program_name,
                'target_user_ids': target_user_ids,
                'target_count': len(target_user_ids),
            }
        )

        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Notifications sent to {len(target_user_ids)} user(s).',
            'notified_count': len(target_user_ids),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/analytics/arima-forecast')
@login_required
@role_required('admin')
def api_arima_forecast():
    """API endpoint for ARIMA-based applicants forecast"""
    # Get parameters
    months = request.args.get('months', 18, type=int)  # Changed from 12 to 18 for better ARIMA accuracy
    forecast_periods = request.args.get('forecast_periods', 6, type=int)
    force_arima = request.args.get('force_arima', 'false').lower() == 'true'

    # Only allow seed data to be used for the Mabitac MSWDO admin page.
    admin_municipality_key = _current_admin_municipality_key()
    allow_seed = bool(admin_municipality_key and 'mabitac' in admin_municipality_key)

    # If the admin is scoped to Mabitac and the caller did not explicitly pass
    # a force_seed flag, default to using the seeded 12-month series. Respect an
    # explicit flag when provided (but only for Mabitac).
    requested_flag = _parse_bool_flag(request.args.get('force_seed'))
    if allow_seed:
        force_seed = True if requested_flag is None else requested_flag
    else:
        force_seed = False
    
    # Limit forecast periods for stability
    forecast_periods = min(forecast_periods, 12)
    
    end_date = datetime.utcnow()
    # Use relativedelta for accurate calendar-month arithmetic; timedelta(days=months*30)
    # undershoots by ~5 days/year and can exclude the earliest data point.
    start_date = datetime(2025, 1, 1) if force_seed else end_date - relativedelta(months=months)
    
    # Query historical data
    historical_data = _scoped_applications_query().with_entities(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()
    
    # Prepare data for ARIMA
    labels = [d.month.strftime('%B %Y') for d in historical_data if d.month]
    values = [d.count for d in historical_data]

    if force_seed:
        labels, values = _build_seeded_applicants_series(historical_data, end_date)
    elif not labels or not values:
        labels, values = _default_applicants_series()
    
    # Generate ARIMA forecast with force mode
    forecast_result = arima_forecast(values, labels, periods=forecast_periods, force_arima=force_arima, digits=0)
    fallback_reason = forecast_result.get('fallback_reason')
    forecast_note = forecast_result.get('forecast_note')
    forecast_supported = forecast_result.get('forecast_supported', forecast_result.get('model') != 'none')
    forecast_message = forecast_note or forecast_result.get('message')
    if forecast_supported is False and not forecast_message:
        forecast_message = 'Forecasting is not supported because there is not enough data.'
    
    return jsonify({
        'historical': {
            'labels': labels,
            'values': values
        },
        'forecast': forecast_result,
        'model': forecast_result.get('model', 'unknown'),
        'forecast_supported': forecast_supported,
        'data_points': len(values),
        'force_arima_mode': force_arima,
        'arima_error': forecast_result.get('arima_error', None),
        'required_data_points': forecast_result.get('required_data_points'),
        'available_data_points': forecast_result.get('available_data_points', len(values)),
        'fallback_reason': fallback_reason,
        'forecast_note': forecast_note,
        'forecast_message': forecast_message
    })

@admin_bp.route('/api/analytics/program-forecast')
@login_required
@role_required('admin')
def api_program_forecast():
    """API endpoint for ARIMA-based monthly program-category forecast."""
    months = request.args.get('months', 18, type=int)
    forecast_periods = request.args.get('forecast_periods', 6, type=int)

    months = min(max(months or 18, 6), 60)
    forecast_periods = min(max(forecast_periods or 6, 1), 12)

    now = datetime.utcnow()
    end_month = datetime(now.year, now.month, 1)
    start_month = end_month - relativedelta(months=months - 1)
    end_exclusive = end_month + relativedelta(months=1)

    historical_months = []
    cursor = start_month
    while cursor <= end_month:
        historical_months.append(cursor)
        cursor = cursor + relativedelta(months=1)

    historical_labels = [month.strftime('%b %Y') for month in historical_months]

    rows = _scoped_applications_query().with_entities(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.coalesce(Programs.program_type, 'Unspecified').label('program_type'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_month,
        Applications.application_date < end_exclusive,
    ).group_by(
        'month', 'program_type'
    ).order_by(
        'month', 'program_type'
    ).all()

    program_types = sorted({(row.program_type or 'Unspecified') for row in rows})
    if not program_types:
        return jsonify({
            'success': False,
            'message': 'No program-category history available for forecasting.',
            'historical_labels': historical_labels,
            'forecast_labels': [],
            'categories': [],
            'historical_months': months,
            'forecast_periods': forecast_periods,
        })

    month_category_counts = {}
    for row in rows:
        if not row.month:
            continue
        month_label = row.month.strftime('%b %Y')
        program_type = row.program_type or 'Unspecified'
        month_category_counts[(program_type, month_label)] = int(row.count or 0)

    program_histories = {
        program_type: {
            'labels': historical_labels,
            'values': [month_category_counts.get((program_type, label), 0) for label in historical_labels],
        }
        for program_type in program_types
    }

    forecast_by_program = forecast_program_timeseries(program_histories, periods=forecast_periods, digits=0)

    forecast_labels = []
    for program_type in program_types:
        labels = (forecast_by_program.get(program_type) or {}).get('forecast_labels', [])
        if labels:
            forecast_labels = labels
            break

    if not forecast_labels:
        forecast_labels = [
            (end_month + relativedelta(months=i)).strftime('%b %Y')
            for i in range(1, forecast_periods + 1)
        ]

    categories = []
    for program_type in program_types:
        forecast_result = forecast_by_program.get(program_type, {})
        categories.append({
            'program_type': program_type,
            'historical_values': program_histories[program_type]['values'],
            'forecast_values': forecast_result.get('forecast_values', []),
            'model': forecast_result.get('model', 'unknown'),
            'forecast_supported': forecast_result.get('forecast_supported', forecast_result.get('success', False)),
            'fallback_reason': forecast_result.get('fallback_reason'),
            'forecast_note': forecast_result.get('forecast_note'),
        })

    return jsonify({
        'success': True,
        'historical_labels': historical_labels,
        'forecast_labels': forecast_labels,
        'categories': categories,
        'historical_months': months,
        'forecast_periods': forecast_periods,
    })

@admin_bp.route('/api/analytics/test-arima')
@login_required
@role_required('admin')
def api_test_arima():
    """Test endpoint to validate ARIMA model performance"""
    # Get all historical data
    all_data = _scoped_applications_query().with_entities(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).group_by('month').order_by('month').all()
    
    labels = [d.month.strftime('%B %Y') for d in all_data if d.month]
    values = [d.count for d in all_data]
    
    # Test with different configurations
    results = {}
    
    # Test 1: Standard ARIMA (12 months minimum)
    forecast_12 = arima_forecast(values, labels, periods=6, force_arima=False)
    results['standard_12mo'] = {
        'model': forecast_12.get('model'),
        'success': forecast_12.get('success'),
        'data_points': len(values),
        'error': forecast_12.get('arima_error')
    }
    
    # Test 2: Forced ARIMA mode
    forecast_forced = arima_forecast(values, labels, periods=6, force_arima=True)
    results['forced_mode'] = {
        'model': forecast_forced.get('model'),
        'success': forecast_forced.get('success'),
        'data_points': len(values),
        'error': forecast_forced.get('arima_error')
    }
    
    # Test 3: Last 6 months only
    if len(values) >= 6:
        forecast_6 = arima_forecast(values[-6:], labels[-6:], periods=3, force_arima=False)
        results['last_6mo'] = {
            'model': forecast_6.get('model'),
            'success': forecast_6.get('success'),
            'data_points': 6,
            'error': forecast_6.get('arima_error')
        }
    
    return jsonify({
        'total_data_points': len(values),
        'date_range': f"{labels[0]} to {labels[-1]}" if labels else "No data",
        'tests': results,
        'recommendations': {
            'min_points_for_arima': 4,
            'min_points_for_seasonality': 36,
            'current_status': 'ARIMA ready' if len(values) >= 4 else 'Need more data'
        }
    })

@admin_bp.route('/api/analytics/program-timeseries-forecast')
@login_required
@role_required('admin')
def api_program_timeseries_forecast():
    """API endpoint for per-program-type ARIMA time series forecast"""
    periods = request.args.get('forecast_periods', 6, type=int)
    months = request.args.get('months', 24, type=int)

    end_date = datetime.utcnow()
    # Use relativedelta for accurate calendar-month arithmetic
    start_date = end_date - relativedelta(months=months)

    # Query per-program-type monthly counts
    raw = _scoped_applications_query().with_entities(
        Programs.program_type,
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by(Programs.program_type, 'month').order_by(Programs.program_type, 'month').all()

    # Group into per-program-type histories
    histories = {}
    for row in raw:
        pt = row.program_type
        if pt not in histories:
            histories[pt] = {'labels': [], 'values': []}
        if row.month:
            histories[pt]['labels'].append(row.month.strftime('%B %Y'))
            histories[pt]['values'].append(row.count)

    forecasts = forecast_program_timeseries(histories, periods=periods)
    return jsonify({'success': True, 'forecasts': forecasts})


# ---------------------------------------------------------------------------
# Explainability endpoints
# ---------------------------------------------------------------------------

@admin_bp.route('/api/recommender/explain/<int:user_id>')
@login_required
@role_required('admin')
def api_explain_recommendation(user_id):
    """Explain recommendation score for a specific beneficiary."""
    cu = _scoped_community_users_query().filter_by(user_id=user_id).first()
    if not cu:
        return jsonify({'success': False, 'message': 'Beneficiary not found'}), 404

    user = cu.user
    beneficiary = {
        'user_id': cu.user_id,
        'first_name': user.first_name if user else '',
        'last_name': user.last_name if user else '',
        'age': cu.age,
        'barangay': cu.barangay,
        'family_annual_income': float(cu.family_annual_income) if cu.family_annual_income else 0,
        'is_solo_parent': cu.is_solo_parent,
        'is_student': cu.is_student,
        'is_pwd': cu.is_pwd,
        'is_currently_employed': cu.is_currently_employed,
        'occupation': cu.occupation,
    }

    # Load population for comparison
    all_cu = _scoped_community_users_query().all()
    population = [
        {
            'family_annual_income': float(c.family_annual_income) if c.family_annual_income else 0,
            'is_solo_parent': c.is_solo_parent,
            'is_student': c.is_student,
            'is_pwd': c.is_pwd,
        }
        for c in all_cu
    ]

    explainer = BeneficiaryExplainer(population=population)
    # Use a quick rule-based score for the explanation
    recommender = BeneficiaryRecommender()
    scored = recommender.score_beneficiaries([beneficiary])
    score = scored[0]['score'] if scored else 0

    explanation = explainer.explain_score(beneficiary, score)
    return jsonify({'success': True, 'explanation': explanation, 'beneficiary': beneficiary})


@admin_bp.route('/api/recommender/recommendations/with-explanations', methods=['POST'])
@login_required
@role_required('admin')
def api_recommendations_with_explanations():
    """Generate recommendations with explanations attached."""
    data = request.get_json() or {}

    program_id = data.get('program_id')
    max_beneficiaries = int(data.get('max_beneficiaries', 50))
    admin_municipality_key = _current_admin_municipality_key()

    if not admin_municipality_key:
        return jsonify({'success': False, 'message': 'Admin municipality is not configured for this account.'}), 403

    # Reuse the main recommendation logic
    all_users = db.session.query(
        User.id, User.first_name, User.last_name, User.email,
        CommunityUsers.age, CommunityUsers.barangay,
        CommunityUsers.family_annual_income,
        CommunityUsers.is_solo_parent, CommunityUsers.is_student,
        CommunityUsers.is_pwd, CommunityUsers.is_currently_employed,
        CommunityUsers.occupation,
    ).join(
        CommunityUsers, User.id == CommunityUsers.user_id
    ).filter(
        func.lower(func.trim(CommunityUsers.municipality)) == admin_municipality_key
    ).all()

    beneficiaries_data = [
        {
            'user_id': u.id,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'email': u.email,
            'age': u.age,
            'barangay': u.barangay,
            'family_annual_income': float(u.family_annual_income) if u.family_annual_income and 0 <= u.family_annual_income <= 10_000_000 else 0,
            'is_solo_parent': u.is_solo_parent,
            'is_student': u.is_student,
            'is_pwd': u.is_pwd,
            'is_currently_employed': u.is_currently_employed,
            'occupation': u.occupation,
        }
        for u in all_users
    ]

    recommendations = get_recommendations(
        beneficiaries_data=beneficiaries_data,
        max_beneficiaries=max_beneficiaries,
        solo_parent_priority=data.get('solo_parent_priority', False),
        student_priority=data.get('student_priority', False),
        pwd_priority=data.get('pwd_priority', False),
        senior_citizen_priority=data.get('senior_citizen_priority', False),
    )

    explainer = BeneficiaryExplainer(population=beneficiaries_data)
    explained = explainer.explain_batch(recommendations)

    return jsonify({
        'success': True,
        'count': len(explained),
        'recommendations': [
            {
                'user_id': r.get('user_id'),
                'name': f"{r.get('first_name', '')} {r.get('last_name', '')}",
                'score': r.get('score', 0),
                'explanation': r.get('explanation', {}),
            }
            for r in explained
        ],
    })


# ---------------------------------------------------------------------------
# Fairness audit endpoint
# ---------------------------------------------------------------------------

@admin_bp.route('/api/recommender/fairness-audit', methods=['POST'])
@login_required
@role_required('admin')
def api_fairness_audit():
    """Run a fairness audit on generated recommendations.

    Expects a JSON body with ``recommendations`` (list of scored dicts)
    or ``program_id`` to generate recommendations first.
    """
    data = request.get_json() or {}
    admin_municipality_key = _current_admin_municipality_key()

    if not admin_municipality_key:
        return jsonify({'success': False, 'message': 'Admin municipality is not configured for this account.'}), 403

    # Either use provided recommendations or generate them
    recommendations = data.get('recommendations')
    if not recommendations:
        program_id = data.get('program_id')
        max_beneficiaries = int(data.get('max_beneficiaries', 75))

        all_users = db.session.query(
            User.id, CommunityUsers.age, CommunityUsers.barangay,
            CommunityUsers.family_annual_income,
            CommunityUsers.is_solo_parent, CommunityUsers.is_student,
            CommunityUsers.is_pwd, CommunityUsers.is_currently_employed,
            CommunityUsers.occupation,
        ).join(
            CommunityUsers, User.id == CommunityUsers.user_id
        ).filter(
            func.lower(func.trim(CommunityUsers.municipality)) == admin_municipality_key
        ).all()

        beneficiaries_data = [
            {
                'user_id': u.id,
                'age': u.age,
                'barangay': u.barangay,
                'family_annual_income': float(u.family_annual_income) if u.family_annual_income else 0,
                'is_solo_parent': u.is_solo_parent,
                'is_student': u.is_student,
                'is_pwd': u.is_pwd,
                'is_currently_employed': u.is_currently_employed,
                'occupation': u.occupation,
            }
            for u in all_users
        ]

        recommendations = get_recommendations(
            beneficiaries_data=beneficiaries_data,
            max_beneficiaries=max_beneficiaries,
            solo_parent_priority=data.get('solo_parent_priority', True),
            student_priority=data.get('student_priority', True),
            pwd_priority=data.get('pwd_priority', True),
            senior_citizen_priority=data.get('senior_citizen_priority', True),
        )

        auditor = FairnessAuditor(beneficiaries_data, recommendations)
    else:
        # Use all community users as the population baseline
        all_cu = _scoped_community_users_query().all()
        population = [
            {
                'barangay': c.barangay,
                'is_solo_parent': c.is_solo_parent,
                'is_student': c.is_student,
                'is_pwd': c.is_pwd,
            }
            for c in all_cu
        ]
        auditor = FairnessAuditor(population, recommendations)

    audit_result = auditor.audit()
    return jsonify({'success': True, 'audit': audit_result})


# ---------------------------------------------------------------------------
# Program compatibility endpoint
# ---------------------------------------------------------------------------

@admin_bp.route('/api/recommender/program/<int:program_id>/compatibility')
@login_required
@role_required('admin')
def api_program_compatibility(program_id):
    """Score beneficiary compatibility for a specific program."""
    program = _scoped_programs_query().filter(Programs.id == program_id).first_or_404()
    user_id = request.args.get('user_id', type=int)

    program_dict = {
        'id': program.id,
        'priority_group': program.priority_group,
        'income_range': program.income_range,
        'beneficiary_limit': program.beneficiary_limit,
        'requirements': [],
    }

    # Load program requirements
    prog_reqs = ProgramRequirements.query.filter_by(program_id=program_id).all()
    for pr in prog_reqs:
        req = Requirements.query.get(pr.requirement_id)
        if req:
            program_dict['requirements'].append({
                'field': req.requirement_name.lower().replace(' ', '_'),
                'name': req.requirement_name,
                'mandatory': pr.is_mandatory,
            })

    # Load historical data for approval rate calculation
    historical_raw = _scoped_applications_query().join(
        CommunityUsers, Applications.user_id == CommunityUsers.user_id
    ).with_entities(
        Applications.user_id, Applications.program_id,
        Applications.application_status, CommunityUsers.age,
    ).filter(
        Applications.program_id == program_id
    ).all()

    historical_data = [
        {
            'user_id': h.user_id,
            'program_id': h.program_id,
            'application_status': h.application_status,
            'age': h.age,
        }
        for h in historical_raw
    ]

    scorer = ProgramCompatibilityScorer(historical_data=historical_data)

    if user_id:
        cu = _scoped_community_users_query().filter_by(user_id=user_id).first()
        if not cu:
            return jsonify({'success': False, 'message': 'Beneficiary not found'}), 404

        beneficiary = {
            'user_id': cu.user_id,
            'age': cu.age,
            'family_annual_income': float(cu.family_annual_income) if cu.family_annual_income else 0,
            'is_solo_parent': cu.is_solo_parent,
            'is_student': cu.is_student,
            'is_pwd': cu.is_pwd,
            'is_currently_employed': cu.is_currently_employed,
            'occupation': cu.occupation,
        }
        result = scorer.calculate_fit(beneficiary, program_dict)
        return jsonify({'success': True, 'compatibility': result})

    # Score all community users
    all_cu = _scoped_community_users_query().limit(200).all()
    beneficiaries = [
        {
            'user_id': c.user_id,
            'age': c.age,
            'barangay': c.barangay,
            'family_annual_income': float(c.family_annual_income) if c.family_annual_income else 0,
            'is_solo_parent': c.is_solo_parent,
            'is_student': c.is_student,
            'is_pwd': c.is_pwd,
            'is_currently_employed': c.is_currently_employed,
            'occupation': c.occupation,
        }
        for c in all_cu
    ]

    results = scorer.score_batch(beneficiaries, program_dict)
    return jsonify({
        'success': True,
        'count': len(results),
        'top_matches': [
            {
                'user_id': r['user_id'],
                'compatibility': r['compatibility'],
            }
            for r in results[:50]
        ],
    })


# ---------------------------------------------------------------------------
# Weight optimization endpoint
# ---------------------------------------------------------------------------

@admin_bp.route('/api/recommender/optimize-weights', methods=['POST'])
@login_required
@role_required('admin')
def api_optimize_weights():
    """Run weight optimization to find the best configuration."""
    data = request.get_json() or {}
    objectives = data.get('objectives', ['coverage', 'equity', 'efficiency'])
    admin_municipality_key = _current_admin_municipality_key()

    if not admin_municipality_key:
        return jsonify({'success': False, 'message': 'Admin municipality is not configured for this account.'}), 403

    # Load all beneficiaries
    all_cu = _scoped_community_users_query().all()
    beneficiaries = [
        {
            'user_id': c.user_id,
            'age': c.age,
            'barangay': c.barangay,
            'family_annual_income': float(c.family_annual_income) if c.family_annual_income else 0,
            'is_solo_parent': c.is_solo_parent,
            'is_student': c.is_student,
            'is_pwd': c.is_pwd,
            'is_currently_employed': c.is_currently_employed,
        }
        for c in all_cu
    ]

    # Gather ground truth from approved applications
    ground_truth = None
    program_id = data.get('program_id')
    if program_id:
        scoped_program = _scoped_programs_query().filter(Programs.id == program_id).first()
        if not scoped_program:
            return jsonify({'success': False, 'message': 'Selected program was not found for your municipality.'}), 404

        approved = _scoped_applications_query().with_entities(Applications.user_id).filter(
            Applications.program_id == program_id,
            Applications.application_status.in_(['approved', 'completed']),
        ).all()
        ground_truth = [a.user_id for a in approved] if approved else None

    optimizer = WeightOptimizer(beneficiaries, ground_truth_approvals=ground_truth)
    result = optimizer.optimize_weights(objectives=objectives)

    return jsonify({'success': True, 'optimization': result})
