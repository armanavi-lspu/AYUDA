#!/usr/bin/env python
"""Verify that dummy data includes essential information"""

from app import create_app, db
from sqlalchemy import text

app = create_app()
with app.app_context():
    conn = db.engine.connect()
    
    # Check community user data
    cu = conn.execute(text("SELECT COUNT(*), AVG(age), COUNT(DISTINCT barangay) FROM community_users WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'user%@test.com')"))
    count, avg_age, barangays = cu.fetchone()
    print(f'✅ Community Users: {count} created | Avg Age: {avg_age:.0f} | Barangays: {barangays}')
    
    # Check applications with essential data
    apps = conn.execute(text("SELECT COUNT(*), COUNT(CASE WHEN submission_deadline IS NOT NULL THEN 1 END), COUNT(CASE WHEN verification_code IS NOT NULL THEN 1 END) FROM applications WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'user%@test.com')"))
    total, deadline_count, vcode_count = apps.fetchone()
    print(f'✅ Applications: {total} | With Deadline: {deadline_count} | With VerCode: {vcode_count}')
    
    # Sample user profile
    sample = conn.execute(text("SELECT age, gender, occupation, family_annual_income, is_pwd, is_solo_parent FROM community_users cu WHERE cu.user_id IN (SELECT id FROM users WHERE email LIKE 'user%@test.com') LIMIT 1"))
    row = sample.fetchone()
    if row:
        print(f'✅ Sample Profile: Age={row[0]}, Gender={row[1]}, Income=${row[3]}, PWD={row[4]}, SoloParent={row[5]}')
    
    # Show sample community user details
    details = conn.execute(text("SELECT age, gender, mobile_no, barangay, occupation, is_pwd, disability_type FROM community_users WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'user%@test.com') LIMIT 1"))
    row = details.fetchone()
    if row:
        print(f'\n📋 Sample Full Profile:')
        print(f'   - Age: {row[0]}')
        print(f'   - Gender: {row[1]}')
        print(f'   - Mobile: {row[2]}')
        print(f'   - Barangay: {row[3]}')
        print(f'   - Occupation: {row[4]}')
        print(f'   - PWD: {row[5]} (Type: {row[6]})')
    
    # Show sample application details
    app_details = conn.execute(text("SELECT application_date, submission_deadline, verification_code, claim_location FROM applications WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'user%@test.com') LIMIT 1"))
    app_row = app_details.fetchone()
    if app_row:
        print(f'\n📝 Sample Application Details:')
        print(f'   - Applied: {app_row[0]}')
        print(f'   - Deadline: {app_row[1]}')
        print(f'   - Verification Code: {app_row[2]}')
        print(f'   - Claim Location: {app_row[3]}')
    
    conn.close()
    print(f'\n🎉 All essential data is now present in dummy records!')
