
from flask import render_template, jsonify, request, redirect, url_for, Response, flash
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.utils import role_required, manila_strftime
from app.models import (
    Applications,
    Programs,
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
from app.location_options import get_municipalities, get_barangays_by_municipality
from sqlalchemy import func, extract, or_
from datetime import datetime, timedelta
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

VALID_REPORT_TYPES = {option['value'] for option in REPORT_TYPE_OPTIONS}
VALID_DATE_PRESETS = {option['value'] for option in DATE_PRESET_OPTIONS}
VALID_EXPORT_FORMATS = {option['value'] for option in EXPORT_FORMAT_OPTIONS}
VALID_LOG_SCOPES = {'all', 'admin', 'community'}
VALID_ACTIVITY_FOCUS = {'all', 'sessions', 'applications'}


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

    query = db.session.query(
        Applications.id,
        Applications.application_status,
        Applications.application_date,
        User.first_name,
        User.last_name,
        User.email,
        Programs.program_name,
        Programs.program_type,
    ).join(
        User, Applications.user_id == User.id
    ).join(
        Programs, Applications.program_id == Programs.id
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
        admin_query = db.session.query(
            AdminActivityLog,
            User.first_name,
            User.last_name,
        ).join(
            User, AdminActivityLog.admin_id == User.id
        ).filter(
            AdminActivityLog.created_at >= start_dt,
            AdminActivityLog.created_at <= end_dt,
        )

        if activity_focus == 'applications':
            admin_query = admin_query.filter(AdminActivityLog.entity_type == 'application')
        elif activity_focus == 'sessions':
            admin_query = admin_query.filter(AdminActivityLog.entity_type == 'session')

        for log, first_name, last_name in admin_query.all():
            entries.append({
                'created_at': log.created_at or datetime.min,
                'role': 'Admin',
                'row': [
                    manila_strftime(log.created_at, '%Y-%m-%d %H:%M:%S', ''),
                    f'{first_name} {last_name}'.strip(),
                    'Admin',
                    log.action,
                    log.action_type,
                    log.entity_type,
                    log.description,
                    log.ip_address or '',
                ],
            })

    if log_scope in {'all', 'community'}:
        community_query = db.session.query(
            UserActivityLog,
            User.first_name,
            User.last_name,
        ).join(
            User, UserActivityLog.user_id == User.id
        ).filter(
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

        for log, first_name, last_name in community_query.all():
            entries.append({
                'created_at': log.created_at or datetime.min,
                'role': 'Community',
                'row': [
                    manila_strftime(log.created_at, '%Y-%m-%d %H:%M:%S', ''),
                    f'{first_name} {last_name}'.strip(),
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

    application_query = db.session.query(Applications).join(
        Programs, Applications.program_id == Programs.id
    ).filter(
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

    top_programs = db.session.query(
        Programs.program_name,
        func.count(Applications.id).label('application_count'),
    ).join(
        Applications, Programs.id == Applications.program_id
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

    admin_activity_count = AdminActivityLog.query.filter(
        AdminActivityLog.created_at >= start_dt,
        AdminActivityLog.created_at <= end_dt,
    ).count()
    community_activity_count = UserActivityLog.query.filter(
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
    
    # 1. Applicants count over time (monthly aggregation)
    applicants_over_time_raw = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()
    
    # Convert to JSON-friendly format
    applicants_over_time = {
        'labels': [row.month.strftime('%B %Y') if row.month else '' for row in applicants_over_time_raw],
        'data': [row.count for row in applicants_over_time_raw]
    }
    
    # 2. Applications per program type
    applications_by_type_raw = db.session.query(
        Programs.program_type,
        func.count(Applications.id).label('count')
    ).join(
        Applications, Programs.id == Applications.program_id
    ).group_by(Programs.program_type).all()
    
    applications_by_type = {
        'labels': [row.program_type for row in applications_by_type_raw],
        'data': [row.count for row in applications_by_type_raw]
    }
    
    # 3. Applicants per barangay
    applicants_by_barangay_raw = db.session.query(
        CommunityUsers.barangay,
        func.count(Applications.id).label('count')
    ).join(
        User, CommunityUsers.user_id == User.id
    ).join(
        Applications, User.id == Applications.user_id
    ).filter(
        CommunityUsers.barangay.isnot(None)
    ).group_by(CommunityUsers.barangay).order_by(func.count(Applications.id).desc()).limit(10).all()
    
    applicants_by_barangay = {
        'labels': [row.barangay for row in applicants_by_barangay_raw],
        'data': [row.count for row in applicants_by_barangay_raw]
    }

    # 4. Community users by municipality
    municipality_expr = func.coalesce(
        func.nullif(func.trim(CommunityUsers.municipality), ''),
        'Not Specified'
    )
    users_by_municipality_raw = db.session.query(
        municipality_expr.label('municipality'),
        func.count(CommunityUsers.id).label('count')
    ).group_by(municipality_expr).order_by(func.count(CommunityUsers.id).desc()).all()

    users_by_municipality = {
        'labels': [row.municipality for row in users_by_municipality_raw],
        'data': [row.count for row in users_by_municipality_raw]
    }
    
    # Summary statistics
    total_applications = Applications.query.count()
    total_applicants = db.session.query(func.count(func.distinct(Applications.user_id))).scalar()
    total_programs = Programs.query.count()
    total_community_users = CommunityUsers.query.count()
    municipalities_represented = db.session.query(
        func.count(func.distinct(func.nullif(func.trim(CommunityUsers.municipality), '')))
    ).scalar() or 0

    top_municipality = users_by_municipality_raw[0] if users_by_municipality_raw else None
    top_municipality_name = top_municipality.municipality if top_municipality else 'No municipality data'
    top_municipality_user_count = top_municipality.count if top_municipality else 0
    
    # Application status breakdown
    status_breakdown = db.session.query(
        Applications.application_status,
        func.count(Applications.id).label('count')
    ).group_by(Applications.application_status).all()
    
    return render_template(
        'admin/analytics_analysis.html',
        user=current_user,
        applicants_over_time_json=json.dumps(applicants_over_time),
        applications_by_type_json=json.dumps(applications_by_type),
        applicants_by_barangay_json=json.dumps(applicants_by_barangay),
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
        for row in db.session.query(Applications.application_status)
        .filter(Applications.application_status.isnot(None))
        .distinct()
        .order_by(Applications.application_status)
        .all()
    ]

    program_type_options = [
        row[0]
        for row in db.session.query(Programs.program_type)
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
    # Exclude ESA and Emergency-period programs — they are crisis-response programs
    # that do not benefit from predictive beneficiary selection.
    programs = Programs.query.filter(
        Programs.program_type != 'ESA',
        Programs.program_period != 'Emergency'
    ).all()
    
    municipalities = get_municipalities()
    municipality_barangays = {
        municipality: get_barangays_by_municipality(municipality)
        for municipality in municipalities
    }
    
    return render_template(
        'admin/analytics_recommend.html',
        user=current_user,
        programs=programs,
        municipalities=municipalities,
        municipality_barangays_json=json.dumps(municipality_barangays)
    )

@admin_bp.route('/api/program/<int:program_id>/parameters')
@login_required
@role_required('admin')
def api_get_program_parameters(program_id):
    """API endpoint to fetch program parameters for auto-fill"""
    program = Programs.query.get_or_404(program_id)
    
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
    end_date = datetime.utcnow()
    # Use relativedelta for accurate calendar-month arithmetic; timedelta(days=months*30)
    # undershoots by ~5 days/year and can exclude the earliest data point.
    start_date = end_date - relativedelta(months=months)
    
    data = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()
    
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
        min_income: Minimum annual income filter (default: 0)
        max_income: Maximum annual income filter (default: 999999999)
        senior_citizen_priority: Boolean to prioritize senior citizens in scoring (default: False)
    
    Returns:
        JSON with success status, count, recommendations list, and message
    """
    data = request.get_json()
    
    # Extract parameters with validation
    program_id = data.get('program_id')

    # Reject requests for ESA or Emergency-period programs
    if program_id:
        _prog = Programs.query.get(program_id)
        if _prog and (_prog.program_type == 'ESA' or _prog.program_period == 'Emergency'):
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
    priority_municipality = (data.get('priority_municipality') or '').strip()

    valid_municipalities = set(get_municipalities())
    if priority_municipality and priority_municipality not in valid_municipalities:
        return jsonify({'success': False, 'message': 'Invalid municipality filter selected'}), 400
    
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
    senior_citizen_priority = data.get('senior_citizen_priority', preset.senior_citizen_priority if config_type else False)
    
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
        CommunityUsers.occupation
    ).join(
        CommunityUsers, User.id == CommunityUsers.user_id
    )
    
    all_users = query.all()

    # Build per-user application history map: user_id -> space-separated program names/types
    app_history_rows = (
        db.session.query(Applications.user_id, Programs.program_name, Programs.program_type)
        .join(Programs, Applications.program_id == Programs.id)
        .filter(Applications.application_status.in_(['approved', 'active', 'completed']))
        .all()
    )
    app_history_map: dict = {}
    for user_id, prog_name, prog_type in app_history_rows:
        tokens = ' '.join(filter(None, [prog_name, prog_type]))
        if user_id in app_history_map:
            app_history_map[user_id] += ' ' + tokens
        else:
            app_history_map[user_id] = tokens

    # Convert to list of dictionaries for the recommender with income validation
    beneficiaries_data = [
        {
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
            'past_applications': app_history_map.get(u.id, ''),
        }
        for u in all_users
    ]

    # Exclude beneficiaries already enrolled (approved/completed) in the selected program
    if program_id:
        enrolled_user_ids = set(
            row[0] for row in db.session.query(Applications.user_id).filter(
                Applications.program_id == program_id,
                Applications.application_status.in_(['approved', 'completed'])
            ).all()
        )
        beneficiaries_data = [b for b in beneficiaries_data if b['user_id'] not in enrolled_user_ids]

    # Build a target_profile from the program's priority group and requirements so
    # that the CBF (content-based filtering) KNN pipeline can be used instead of
    # plain rule-based scoring.
    target_profile = None
    effective_priority_groups = data.get('priority_groups')
    if program_id:
        program = Programs.query.get(program_id)
        if program:
            if not effective_priority_groups and program.priority_group:
                effective_priority_groups = program.priority_group

            # Gather qualification requirements to build a rich text feature
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

            # Parse income range if available (e.g., "0-250000" or "Below 250,000")
            # sensible default for low-income programs
            max_inc = 250000
            if program.income_range:
                try:
                    parts = str(program.income_range).replace(',', '').replace(' ', '').split('-')
                    if len(parts) == 2:
                        max_inc = float(parts[1])
                except (ValueError, IndexError):
                    pass

            target_profile = {
                # Use a representative age aligned with recommender configuration
                'age': SENIOR_CITIZEN_AGE if senior_targeted else DEFAULT_TARGET_AGE,
                'family_annual_income': max_inc / 2,  # midpoint of target income range
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
        min_income=min_income,
        max_income=max_income
    )
    
    return jsonify({
        'success': True,
        'count': len(recommendations),
        'recommendations': [
            {
                'user_id': r.get('user_id'),
                'name': f"{r.get('first_name', '')} {r.get('last_name', '')}",
                'email': r.get('email', ''),
                'barangay': r.get('barangay', 'N/A'),
                'municipality': r.get('municipality', 'N/A'),
                'income': r.get('family_annual_income', 0),
                'age': r.get('age', None),
                'is_solo_parent': r.get('is_solo_parent', False),
                'is_student': r.get('is_student', False),
                'is_pwd': r.get('is_pwd', False),
                'is_senior': (r.get('age') or 0) >= 60,
                # CBF path produces similarity_score; rule-based path produces score.
                # Use whichever is non-zero so the UI always shows a meaningful value.
                'score': r.get('score') or r.get('similarity_score', 0.0) or 0.0,
                'score_breakdown': r.get('score_breakdown', {}),
                'similarity_score': r.get('similarity_score', None),
                'past_applications': r.get('past_applications', ''),
            }
            for r in recommendations
        ],
        'algorithm': 'content-based-knn' if target_profile else 'rule-based-scoring',
        'program_matched': program_id is not None,
        'priority_groups': effective_priority_groups or '',
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


@admin_bp.route('/api/analytics/save-recommendations', methods=['POST'])
@login_required
@role_required('admin')
def api_save_recommendations():
    """Save/log a recommendation list generation for audit trail"""
    data = request.get_json() or {}

    program_id_raw = data.get('program_id')
    try:
        program_id = int(program_id_raw) if program_id_raw not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Invalid program ID supplied.'}), 400

    raw_user_ids = data.get('recommendation_user_ids', [])
    recommendation_user_ids = _parse_positive_int_list(raw_user_ids)

    recommendation_count_raw = data.get('count', len(recommendation_user_ids))
    try:
        recommendation_count = max(0, int(recommendation_count_raw))
    except (TypeError, ValueError):
        recommendation_count = len(recommendation_user_ids)

    recommendation_count = max(recommendation_count, len(recommendation_user_ids))

    program = Programs.query.get(program_id) if program_id else None
    if program_id and not program:
        return jsonify({'success': False, 'message': 'Selected program was not found.'}), 404

    program_name = program.program_name if program else 'Unknown Program'

    filters_payload = data.get('filters', {})
    if not isinstance(filters_payload, dict):
        filters_payload = {}

    max_ids_to_store = 300
    stored_user_ids = recommendation_user_ids[:max_ids_to_store]

    try:
        log_recommendation_saved(
            program_name=program_name,
            recommendation_count=recommendation_count,
            details_extra={
                'program_id': program_id,
                'filters': filters_payload,
                'recommended_user_ids': stored_user_ids,
                'recommended_user_count': len(recommendation_user_ids),
                'recommended_user_ids_truncated': len(recommendation_user_ids) > len(stored_user_ids),
            }
        )
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Recommendation list saved successfully.',
            'saved_count': len(recommendation_user_ids),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/analytics/saved-recommendations')
@login_required
@role_required('admin')
def api_saved_recommendations():
    """Return recent saved recommendation lists with summary details."""
    limit = request.args.get('limit', 30, type=int)
    limit = max(1, min(limit, 100))

    logs = AdminActivityLog.query.filter(
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
        programs = Programs.query.filter(Programs.id.in_(program_ids)).all()
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

        saved_lists.append({
            'id': log.id,
            'created_at': log.created_at.isoformat() if log.created_at else None,
            'admin_id': log.admin_id,
            'admin_name': log.admin_name,
            'program_id': program_id,
            'program_name': programs_map.get(program_id) or details.get('program_name') or 'Unknown Program',
            'recommendation_count': recommendation_count,
            'recommended_user_count': recommended_user_count,
            'recommended_user_ids': recommended_user_ids,
            'recommended_user_ids_truncated': bool(details.get('recommended_user_ids_truncated', False)),
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
    """Return one saved recommendation list with beneficiary details."""
    log = AdminActivityLog.query.filter(
        AdminActivityLog.id == saved_list_id,
        AdminActivityLog.action == 'save_recommendation',
        AdminActivityLog.entity_type == 'recommendation'
    ).first()

    if not log:
        return jsonify({'success': False, 'message': 'Saved recommendation list not found.'}), 404

    details = log.details_dict if hasattr(log, 'details_dict') else {}
    if not isinstance(details, dict):
        details = {}

    raw_program_id = details.get('program_id')
    try:
        program_id = int(raw_program_id) if raw_program_id not in (None, '') else None
    except (TypeError, ValueError):
        program_id = None

    program = Programs.query.get(program_id) if program_id else None
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

    beneficiary_rows = []
    if recommended_user_ids:
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
        ).outerjoin(
            CommunityUsers, CommunityUsers.user_id == User.id
        ).filter(
            User.id.in_(recommended_user_ids),
            User.role == 'community'
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

    saved_list_payload = {
        'id': log.id,
        'created_at': log.created_at.isoformat() if log.created_at else None,
        'admin_id': log.admin_id,
        'admin_name': log.admin_name,
        'program_id': program_id,
        'program_name': program_name,
        'recommendation_count': recommendation_count,
        'recommended_user_count': recommended_user_count,
        'recommended_user_ids': recommended_user_ids,
        'recommended_user_ids_truncated': bool(details.get('recommended_user_ids_truncated', False)),
        'filters': filters_payload,
    }

    return jsonify({
        'success': True,
        'saved_list': saved_list_payload,
        'beneficiaries': beneficiaries,
        'beneficiary_count': len(beneficiaries),
    })


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

    program = Programs.query.get(program_id)
    if not program:
        return jsonify({'success': False, 'message': 'Selected program was not found.'}), 404

    raw_user_ids = data.get('user_ids') or data.get('recommendation_user_ids') or []
    user_ids = _parse_positive_int_list(raw_user_ids)
    if not user_ids:
        return jsonify({'success': False, 'message': 'No valid beneficiaries were provided for notification.'}), 400

    target_rows = db.session.query(User.id).join(
        CommunityUsers, CommunityUsers.user_id == User.id
    ).filter(
        User.id.in_(user_ids),
        User.role == 'community'
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
    
    # Limit forecast periods for stability
    forecast_periods = min(forecast_periods, 12)
    
    end_date = datetime.utcnow()
    # Use relativedelta for accurate calendar-month arithmetic; timedelta(days=months*30)
    # undershoots by ~5 days/year and can exclude the earliest data point.
    start_date = end_date - relativedelta(months=months)
    
    # Query historical data
    historical_data = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()
    
    # Prepare data for ARIMA
    labels = [d.month.strftime('%B %Y') for d in historical_data if d.month]
    values = [d.count for d in historical_data]
    
    # Generate ARIMA forecast with force mode
    forecast_result = arima_forecast(values, labels, periods=forecast_periods, force_arima=force_arima)
    
    return jsonify({
        'historical': {
            'labels': labels,
            'values': values
        },
        'forecast': forecast_result,
        'model': forecast_result.get('model', 'unknown'),
        'data_points': len(values),
        'force_arima_mode': force_arima,
        'arima_error': forecast_result.get('arima_error', None)
    })

@admin_bp.route('/api/analytics/program-forecast')
@login_required
@role_required('admin')
def api_program_forecast():
    """API endpoint for program category growth forecast"""
    growth_rate = request.args.get('growth_rate', type=float)
    
    # Query current program applications
    applications_by_type = db.session.query(
        Programs.program_type,
        func.count(Applications.id).label('count')
    ).join(
        Applications, Programs.id == Applications.program_id
    ).group_by(Programs.program_type).all()
    
    program_data = {
        'labels': [row.program_type for row in applications_by_type],
        'data': [row.count for row in applications_by_type]
    }
    
    # Generate program growth forecast
    forecast_result = forecast_program_growth(program_data, growth_rate)
    
    return jsonify(forecast_result)

@admin_bp.route('/api/analytics/test-arima')
@login_required
@role_required('admin')
def api_test_arima():
    """Test endpoint to validate ARIMA model performance"""
    # Get all historical data
    all_data = db.session.query(
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
    raw = db.session.query(
        Programs.program_type,
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).join(
        Applications, Programs.id == Applications.program_id
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
    cu = CommunityUsers.query.filter_by(user_id=user_id).first()
    if not cu:
        return jsonify({'success': False, 'message': 'Beneficiary not found'}), 404

    user = User.query.get(user_id)
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
    all_cu = CommunityUsers.query.all()
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
    data = request.get_json()

    program_id = data.get('program_id')
    max_beneficiaries = int(data.get('max_beneficiaries', 50))

    # Reuse the main recommendation logic
    all_users = db.session.query(
        User.id, User.first_name, User.last_name, User.email,
        CommunityUsers.age, CommunityUsers.barangay,
        CommunityUsers.family_annual_income,
        CommunityUsers.is_solo_parent, CommunityUsers.is_student,
        CommunityUsers.is_pwd, CommunityUsers.is_currently_employed,
        CommunityUsers.occupation,
    ).join(CommunityUsers, User.id == CommunityUsers.user_id).all()

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
    data = request.get_json()

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
        ).join(CommunityUsers, User.id == CommunityUsers.user_id).all()

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
        all_cu = CommunityUsers.query.all()
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
    program = Programs.query.get_or_404(program_id)
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
    historical_raw = db.session.query(
        Applications.user_id, Applications.program_id,
        Applications.application_status, CommunityUsers.age,
    ).join(
        CommunityUsers, Applications.user_id == CommunityUsers.user_id
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
        cu = CommunityUsers.query.filter_by(user_id=user_id).first()
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
    all_cu = CommunityUsers.query.limit(200).all()
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

    # Load all beneficiaries
    all_cu = CommunityUsers.query.all()
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
        approved = db.session.query(Applications.user_id).filter(
            Applications.program_id == program_id,
            Applications.application_status.in_(['approved', 'completed']),
        ).all()
        ground_truth = [a.user_id for a in approved] if approved else None

    optimizer = WeightOptimizer(beneficiaries, ground_truth_approvals=ground_truth)
    result = optimizer.optimize_weights(objectives=objectives)

    return jsonify({'success': True, 'optimization': result})
