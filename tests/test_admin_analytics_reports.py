import pytest

from app import create_app
from app.admin.routes import analytics as analytics_routes


def test_report_routes_registered():
    app = create_app()

    rules = {rule.endpoint: rule for rule in app.url_map.iter_rules()}

    assert 'admin.analytics_reports' in rules
    assert 'admin.analytics_generate_report' in rules

    reports_rule = rules['admin.analytics_reports']
    generate_rule = rules['admin.analytics_generate_report']

    assert str(reports_rule) == '/admin/adm_analytics/reports'
    assert str(generate_rule) == '/admin/adm_analytics/reports/generate'
    assert 'GET' in reports_rule.methods
    assert 'GET' in generate_rule.methods
    assert 'POST' in generate_rule.methods


def test_default_report_values_for_weekly_sessions_preset():
    values = analytics_routes._default_report_form_values('weekly_sessions')

    assert values['report_type'] == 'activity_logs'
    assert values['date_preset'] == 'last_7_days'
    assert values['log_scope'] == 'community'
    assert values['activity_focus'] == 'sessions'
    assert values['export_format'] == 'pdf'


def test_resolve_custom_date_range():
    start_dt, end_dt, label = analytics_routes._resolve_report_date_range(
        'custom',
        '2026-04-01',
        '2026-04-06',
    )

    assert start_dt <= end_dt
    assert 'Custom' in label


@pytest.mark.parametrize(
    'start_date,end_date',
    [
        ('2026-04-10', '2026-04-01'),
        ('invalid-date', '2026-04-01'),
    ],
)
def test_resolve_custom_date_range_invalid_inputs(start_date, end_date):
    with pytest.raises(ValueError):
        analytics_routes._resolve_report_date_range('custom', start_date, end_date)


def test_pdf_builder_returns_valid_pdf_bytes():
    pdf_bytes = analytics_routes._build_simple_pdf([
        'Report Configuration Test',
        'Line 1',
        'Line 2',
    ])

    assert pdf_bytes.startswith(b'%PDF-1.4')
    assert b'startxref' in pdf_bytes
    assert b'%%EOF' in pdf_bytes
