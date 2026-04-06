#!/usr/bin/env python
from app import create_app
app = create_app()
print(f"Manila filter registered: {'manila' in app.jinja_env.filters}")
print(f"Filter object: {app.jinja_env.filters.get('manila')}")

# Test it works within app context
from datetime import datetime
import pytz

with app.app_context():
    test_dt = pytz.utc.localize(datetime(2026, 4, 5, 10, 30, 0))
    result = app.jinja_env.filters['manila'](test_dt, '%b %d, %Y %I:%M %p')
    print(f"Test filter output: {result}")
    print("SUCCESS: Filter works correctly!")
