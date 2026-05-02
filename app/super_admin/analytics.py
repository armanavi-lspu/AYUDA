from datetime import datetime, timedelta
import json

from dateutil.relativedelta import relativedelta
from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from app.admin.routes import analytics as admin_analytics
from app.extensions import db
from app.forecasting import arima_forecast, forecast_program_timeseries
from app.location_options import get_municipalities
from app.models import AdminActivityLog, Applications, CommunityUsers, Programs, User, UserActivityLog
from app.super_admin import super_admin_bp
from app.utils import manila_strftime, role_required


@super_admin_bp.route('/analytics')
@login_required
@role_required('super_admin')
def analytics():
    """Super-admin analytics landing page redirects to analysis."""
    return redirect(url_for('super_admin.analytics_analysis'))


@super_admin_bp.route('/analytics/analysis')
@login_required
@role_required('super_admin')
def analytics_analysis():
    """Unfiltered analytics analysis dashboard for super admins."""
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=365)

    users_over_time_raw = db.session.query(
        func.date_trunc('month', User.created_at).label('month'),
        func.count(User.id).label('count')
    ).filter(
        User.created_at >= start_date
    ).group_by('month').order_by('month').all()

    users_over_time = {
        'labels': [row.month.strftime('%B %Y') if row.month else '' for row in users_over_time_raw],
        'data': [row.count for row in users_over_time_raw],
    }

    registered_municipalities = get_municipalities()

    municipality_aliases = {
        'sta maria': 'Santa Maria',
        'sta. maria': 'Santa Maria',
        'santa maria': 'Santa Maria',
    }

    def _normalize_municipality_name(raw_name):
        normalized_key = str(raw_name or '').strip().lower()
        if normalized_key in municipality_aliases:
            return municipality_aliases[normalized_key]
        return str(raw_name or '').strip()

    municipality_expr = func.coalesce(
        func.nullif(func.trim(CommunityUsers.municipality), ''),
        'Not Specified'
    )

    users_by_municipality_raw = db.session.query(
        municipality_expr.label('municipality'),
        func.count(CommunityUsers.id).label('count')
    ).group_by(municipality_expr).all()

    users_by_municipality_counts = {name: 0 for name in registered_municipalities}
    for row in users_by_municipality_raw:
        normalized_name = _normalize_municipality_name(row.municipality)
        if normalized_name and normalized_name in users_by_municipality_counts:
            users_by_municipality_counts[normalized_name] += int(row.count or 0)

    users_by_municipality = {
        'labels': registered_municipalities,
        'data': [users_by_municipality_counts[name] for name in registered_municipalities],
    }

    total_super_admins = User.query.filter_by(role='super_admin').count()
    total_admins = User.query.filter_by(role='admin').count()
    total_community_users = User.query.filter_by(role='community').count()
    total_users = total_super_admins + total_admins + total_community_users

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    active_admins = db.session.query(func.count(func.distinct(User.id))).outerjoin(
        AdminActivityLog, AdminActivityLog.admin_id == User.id
    ).filter(
        User.role == 'admin'
    ).filter(
        or_(
            User.last_activity >= seven_days_ago,
            AdminActivityLog.created_at >= seven_days_ago,
        )
    ).scalar() or 0
    inactive_admins = max(total_admins - active_admins, 0)

    active_community_users = db.session.query(func.count(func.distinct(User.id))).outerjoin(
        UserActivityLog, UserActivityLog.user_id == User.id
    ).filter(
        User.role == 'community'
    ).filter(
        or_(
            User.last_activity >= seven_days_ago,
            UserActivityLog.created_at >= seven_days_ago,
        )
    ).scalar() or 0
    inactive_community_users = max(total_community_users - active_community_users, 0)

    account_status_chart = {
        'labels': ['Admins', 'Community Users'],
        'active': [active_admins, active_community_users],
        'inactive': [inactive_admins, inactive_community_users],
    }
    user_role_chart = {
        'labels': ['Super Admins', 'Admins', 'Community Users'],
        'data': [total_super_admins, total_admins, total_community_users],
    }

    return render_template(
        'super_admin/analytics_analysis.html',
        user=current_user,
        users_over_time_json=json.dumps(users_over_time),
        users_by_municipality_json=json.dumps(users_by_municipality),
        account_status_chart=account_status_chart,
        user_role_chart=user_role_chart,
        total_users=total_users,
        total_admins=total_admins,
        total_super_admins=total_super_admins,
        total_community_users=total_community_users,
    )


@super_admin_bp.route('/analytics/reports')
@login_required
@role_required('super_admin')
def analytics_reports():
    """Render report configuration for super-admin analytics exports."""
    selected_preset = (request.args.get('preset') or '').strip().lower()
    form_values = admin_analytics._default_report_form_values(selected_preset)

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
    for preset in admin_analytics.QUICK_REPORT_PRESETS:
        quick_report_presets.append({
            'slug': preset['slug'],
            'name': preset['name'],
            'description': preset['description'],
            'configure_url': url_for('super_admin.analytics_reports', preset=preset['slug']),
            'generate_url': url_for('super_admin.analytics_generate_report', **preset['params']),
        })

    return render_template(
        'super_admin/analytics_reports.html',
        user=current_user,
        report_type_options=admin_analytics.REPORT_TYPE_OPTIONS,
        date_preset_options=admin_analytics.DATE_PRESET_OPTIONS,
        export_format_options=admin_analytics.EXPORT_FORMAT_OPTIONS,
        quick_report_presets=quick_report_presets,
        application_status_options=application_status_options,
        program_type_options=program_type_options,
        form_values=form_values,
    )


@super_admin_bp.route('/analytics/reports/generate', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def analytics_generate_report():
    """Generate and export super-admin analytics reports."""
    source = request.form if request.method == 'POST' else request.args

    report_type = (source.get('report_type') or '').strip().lower()
    date_preset = (source.get('date_preset') or 'last_30_days').strip().lower()
    export_format = (source.get('export_format') or 'pdf').strip().lower()
    start_date = (source.get('start_date') or '').strip()
    end_date = (source.get('end_date') or '').strip()

    if report_type not in admin_analytics.VALID_REPORT_TYPES:
        flash('Please choose a valid report type.', 'danger')
        return redirect(url_for('super_admin.analytics_reports'))

    if export_format not in admin_analytics.VALID_EXPORT_FORMATS:
        flash('Please choose a valid export format.', 'danger')
        return redirect(url_for('super_admin.analytics_reports'))

    filters = {
        'application_status': (source.get('application_status') or '').strip().lower(),
        'program_type': (source.get('program_type') or '').strip(),
        'log_scope': (source.get('log_scope') or 'all').strip().lower(),
        'activity_focus': (source.get('activity_focus') or 'all').strip().lower(),
    }

    try:
        start_dt, end_dt, date_label = admin_analytics._resolve_report_date_range(date_preset, start_date, end_date)
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('super_admin.analytics_reports'))

    report_payload = admin_analytics._build_report_payload(report_type, start_dt, end_dt, filters)
    timestamp = manila_strftime(datetime.now(), '%Y%m%d_%H%M%S', '')
    filename = f'super_admin_{report_type}_report_{timestamp}'

    if export_format == 'csv':
        return admin_analytics._build_delimited_response(
            report_payload,
            filename,
            date_label,
            delimiter=',',
            mimetype='text/csv',
            extension='csv',
        )

    if export_format == 'excel':
        return admin_analytics._build_delimited_response(
            report_payload,
            filename,
            date_label,
            delimiter='\t',
            mimetype='application/vnd.ms-excel',
            extension='xls',
        )

    return admin_analytics._build_pdf_response(report_payload, filename, date_label)


@super_admin_bp.route('/api/analytics/users-timeseries')
@super_admin_bp.route('/api/analytics/applicants-timeseries')
@login_required
@role_required('super_admin')
def api_users_timeseries():
    """API endpoint for user registration time series data."""
    months = request.args.get('months', 18, type=int)
    end_date = datetime.utcnow()
    start_date = end_date - relativedelta(months=months)

    data = db.session.query(
        func.date_trunc('month', User.created_at).label('month'),
        func.count(User.id).label('count')
    ).filter(
        User.created_at >= start_date
    ).group_by('month').order_by('month').all()

    return jsonify({
        'labels': [d.month.strftime('%B %Y') for d in data if d.month],
        'values': [d.count for d in data],
        'months': months,
    })


@super_admin_bp.route('/api/analytics/arima-forecast')
@login_required
@role_required('super_admin')
def api_arima_forecast():
    """API endpoint for ARIMA-based applicants forecast."""
    months = request.args.get('months', 18, type=int)
    forecast_periods = request.args.get('forecast_periods', 6, type=int)
    force_arima = request.args.get('force_arima', 'false').lower() == 'true'

    forecast_periods = min(forecast_periods, 12)

    end_date = datetime.utcnow()
    start_date = end_date - relativedelta(months=months)

    historical_data = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()

    labels = [d.month.strftime('%B %Y') for d in historical_data if d.month]
    values = [d.count for d in historical_data]

    forecast_result = arima_forecast(values, labels, periods=forecast_periods, force_arima=force_arima)
    fallback_reason = forecast_result.get('fallback_reason')
    forecast_note = forecast_result.get('forecast_note')
    forecast_supported = forecast_result.get('forecast_supported', forecast_result.get('model') != 'none')
    forecast_message = forecast_note or forecast_result.get('message')
    if forecast_supported is False and not forecast_message:
        forecast_message = 'Forecasting is not supported because there is not enough data.'

    return jsonify({
        'historical': {
            'labels': labels,
            'values': values,
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
        'forecast_message': forecast_message,
    })


@super_admin_bp.route('/api/analytics/program-forecast')
@login_required
@role_required('super_admin')
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

    rows = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.coalesce(Programs.program_type, 'Unspecified').label('program_type'),
        func.count(Applications.id).label('count')
    ).join(
        Programs, Programs.id == Applications.program_id
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

    forecast_by_program = forecast_program_timeseries(program_histories, periods=forecast_periods)

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
