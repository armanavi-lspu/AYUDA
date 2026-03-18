from app import create_app, db
from app.models import Applications
from sqlalchemy import func
from datetime import datetime

app = create_app()
with app.app_context():
    # Check ALL applications, not filtered by date
    all_apps = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).group_by('month').order_by('month').all()
    
    print("📊 ALL Applications by Month (Unfiltered):")
    print("=" * 60)
    
    for month_data in all_apps:
        month = month_data.month
        count = month_data.count
        if month:
            print(f"{month.strftime('%B %Y')}: {count}")
    
    print("=" * 60)
    print(f"Total data points: {len(all_apps)}")
    print(f"Total applications: {sum(d.count for d in all_apps if d.month)}")
    
    # Check the earliest and latest
    if all_apps:
        earliest = all_apps[0].month
        latest = all_apps[-1].month
        print(f"\nDate range: {earliest.strftime('%B %Y')} to {latest.strftime('%B %Y')}")
        
        # Count months between
        months_between = (latest.year - earliest.year) * 12 + (latest.month - earliest.month) + 1
        print(f"Expected months: {months_between}")
        print(f"Actual months: {len(all_apps)}")
        if months_between != len(all_apps):
            print(f"⚠️  Gap detected: {months_between - len(all_apps)} months missing!")
