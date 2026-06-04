from flask import Blueprint, jsonify, render_template, request

from app.forecasting import arima_forecast
from app.extensions import csrf


home_bp = Blueprint('main', __name__)


def _parse_seasonal_order(value):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = [part.strip() for part in raw.replace(';', ',').split(',') if part.strip()]
    if len(parts) != 4:
        return None
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None

@home_bp.route('/')
def about():
    return render_template('about.html')

@home_bp.route('/programs')
def programs():
    return render_template('programs.html')

@home_bp.route('/privacy')
def privacy():
    return render_template('securitynprivacy.html')


@home_bp.route('/data-privacy-consent')
def data_privacy_consent():
    return render_template('data_privacy_consent.html')


@home_bp.route('/arima-test')
def arima_test():
    """Render a standalone ARIMA test page using a fixed dataset."""
    return render_template('arima_test.html')


@home_bp.route('/api/arima-test', methods=['GET', 'POST'])
@csrf.exempt
def api_arima_test():
    """Return ARIMA results for the fixed test dataset (no system data)."""
    forecast_periods = request.args.get('forecast_periods', 6, type=int)
    force_arima = request.args.get('force_arima', 'false').lower() == 'true'

    forecast_digits = request.args.get('forecast_digits', 2, type=int)
    forecast_digits = min(max(forecast_digits or 0, 0), 4)
    seasonal_min_points = request.args.get('seasonal_min_points', 12, type=int)
    seasonal_min_points = max(seasonal_min_points or 0, 0)
    seasonal_order = _parse_seasonal_order(request.args.get('seasonal_order'))

    forecast_periods = min(max(forecast_periods or 6, 1), 12)

    default_labels = [
        'Jan 2025', 'Feb 2025', 'Mar 2025', 'Apr 2025',
        'May 2025', 'Jun 2025', 'Jul 2025', 'Aug 2025',
        'Sep 2025', 'Oct 2025', 'Nov 2025', 'Dec 2025',
    ]
    default_values = [38, 62, 92, 65, 40, 50, 53, 59, 43, 45, 30, 11]

    labels = default_labels
    values = default_values
    source = 'static_test_dataset'
    input_warning = None

    payload = request.get_json(silent=True) or {}
    custom_labels = payload.get('historical_labels') if isinstance(payload, dict) else None
    custom_values = payload.get('historical_values') if isinstance(payload, dict) else None

    if isinstance(custom_labels, list) and isinstance(custom_values, list) and custom_labels and custom_values:
        if len(custom_labels) != len(custom_values):
            input_warning = 'Custom labels and values had different lengths; extra items were ignored.'

        cleaned_labels = []
        cleaned_values = []
        for label, value in zip(custom_labels, custom_values):
            label_text = str(label).strip()
            if not label_text:
                continue
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                numeric_value = 0
                if input_warning is None:
                    input_warning = 'Some values were invalid and were set to 0.'
            cleaned_labels.append(label_text)
            cleaned_values.append(numeric_value)

        if cleaned_labels:
            labels = cleaned_labels[:36]
            values = cleaned_values[:36]
            source = 'custom_payload'
        else:
            input_warning = 'Custom data was empty or invalid; using the default dataset.'

    program_category_seed = [
        {'program_type': 'Education', 'values': [12, 18, 24, 20, 14, 16, 19, 23, 17, 15, 11, 7]},
        {'program_type': 'Health', 'values': [8, 13, 15, 12, 10, 9, 11, 12, 10, 9, 7, 5]},
        {'program_type': 'Livelihood', 'values': [18, 24, 32, 22, 16, 19, 21, 24, 20, 18, 14, 9]},
    ]

    def normalize_series(series_values, target_length):
        if not target_length:
            return []
        if not series_values:
            return [0] * target_length
        if len(series_values) >= target_length:
            return series_values[:target_length]
        last_value = series_values[-1]
        return series_values + [last_value] * (target_length - len(series_values))

    program_categories = []
    program_forecast_labels = []
    for category in program_category_seed:
        historical_values = normalize_series(category['values'], len(labels))
        forecast_result = arima_forecast(
            historical_values,
            labels,
            periods=forecast_periods,
            force_arima=force_arima,
            digits=forecast_digits,
            seasonal_order=seasonal_order,
            seasonal_min_points=seasonal_min_points
        )
        forecast_labels = forecast_result.get('forecast_labels') or []
        if not program_forecast_labels and forecast_labels:
            program_forecast_labels = forecast_labels

        program_categories.append({
            'program_type': category['program_type'],
            'historical_values': historical_values,
            'forecast_values': forecast_result.get('forecast_values', []),
            'forecast_supported': forecast_result.get('forecast_supported', True),
            'model': forecast_result.get('model'),
            'fallback_reason': forecast_result.get('fallback_reason'),
            'forecast_note': forecast_result.get('forecast_note') or forecast_result.get('message'),
            'arima_error': forecast_result.get('arima_error'),
        })

    forecast_result = arima_forecast(
        values,
        labels,
        periods=forecast_periods,
        force_arima=force_arima,
        digits=forecast_digits,
        seasonal_order=seasonal_order,
        seasonal_min_points=seasonal_min_points
    )
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
        'program_category_forecast': {
            'historical_labels': labels,
            'forecast_labels': program_forecast_labels,
            'categories': program_categories,
        },
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
        'input_warning': input_warning,
        'source': source,
    })
