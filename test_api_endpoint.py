#!/usr/bin/env python
"""Test the actual API endpoint for ARIMA forecast"""

from app import create_app
import json

app = create_app()

with app.test_client() as client:
    # Need to log in first as admin
    # First, find an admin user
    from app.models import User
    from app import db
    
    with app.app_context():
        admin = db.session.query(User).filter(User.role == 'admin').first()
        if not admin:
            print("❌ No admin user found")
            exit(1)
        
        admin_email = admin.email
        print(f"Using admin: {admin_email}\n")
    
    # Test login (assuming you know the password)
    print("Testing /api/analytics/arima-forecast endpoint...\n")
    
    # Make request with test credentials
    response = client.get('/admin/api/analytics/arima-forecast?months=18&forecast_periods=6')
    
    if response.status_code == 401:
        print("❌ Not authenticated. Need to login first.")
        print("Response:", response.json)
    elif response.status_code == 200:
        data = response.json
        print("✅ Get request successful!")
        print(f"\n📊 API Response:")
        print(f"  Model: {data.get('model', 'unknown')}")
        print(f"  Data Points: {data.get('data_points', 0)}")
        print(f"  Force ARIMA: {data.get('force_arima_mode', False)}")
        print(f"  ARIMA Error: {data.get('arima_error', 'None')}")
        
        print(f"\n📈 Historical Data (last 5):")
        labels = data.get('historical', {}).get('labels', [])
        values = data.get('historical', {}).get('values', [])
        for label, value in zip(labels[-5:], values[-5:]):
            print(f"  {label}: {value}")
        
        print(f"\n🔮 Forecast (first 3 periods):")
        forecast = data.get('forecast', {})
        forecast_data = forecast.get('forecast', [])
        for i, pred in enumerate(forecast_data[:3]):
            print(f"  Period {i+1}: {pred}")
    else:
        print(f"❌ Request failed with status {response.status_code}")
        print("Response:", response.json)
