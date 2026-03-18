from app import create_app, db
from app.models import Applications
from app.forecasting import arima_forecast
from sqlalchemy import func
from datetime import datetime
from dateutil.relativedelta import relativedelta

app = create_app()
with app.app_context():
    print("🔍 Debugging ARIMA Forecast Issue")
    print("=" * 60)
    
    # Exactly replicate what the API does with 18 months
    end_date = datetime.utcnow()
    start_date = end_date - relativedelta(months=18)
    
    print(f"\nQuery Range: {start_date.date()} to {end_date.date()}")
    
    historical_data = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()
    
    labels = [d.month.strftime('%B %Y') for d in historical_data if d.month]
    values = [d.count for d in historical_data]
    
    print(f"\nData Summary:")
    print(f"  Data points: {len(values)}")
    print(f"  Total applications: {sum(values)}")
    print(f"  Min/Max: {min(values) if values else 0}/{max(values) if values else 0}")
    
    print(f"\nData points:")
    for label, value in zip(labels, values):
        print(f"  {label}: {value}")
    
    # Test ARIMA with exact parameters from API
    print(f"\n🔮 Running ARIMA forecast...")
    result = arima_forecast(values, labels, periods=6, force_arima=None)
    
    print(f"\nResult:")
    print(f"  Model: {result.get('model')}")
    print(f"  Success: {result.get('success')}")
    print(f"  Data Points Used: {result.get('data_points')}")
    
    if result.get('arima_error'):
        print(f"  Error: {result.get('arima_error')}")
    
    print(f"\nForecast:")
    for label, val in zip(result.get('forecast_labels', []), result.get('forecast_values', [])):
        print(f"  {label}: {val}")
    
    if 'linear' in result.get('model', '').lower():
        print(f"\n❌ STILL FALLING BACK TO LINEAR!")
        print(f"\nDebug Info:")
        print(f"  - Data point count: {len(values)} (min for ARIMA: 4)")
        print(f"  - Values list type: {type(values)}")
        print(f"  - Labels list type: {type(labels)}")
