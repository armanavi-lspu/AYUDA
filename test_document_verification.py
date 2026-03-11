#!/usr/bin/env python
"""Test document verification endpoint"""

from app import create_app, db
from app.models import Applications, ApplicationDocumentUploads, Requirements
from datetime import datetime

app = create_app()

with app.app_context():
    # Find a test application with documents
    app_with_docs = db.session.query(Applications).join(
        ApplicationDocumentUploads,
        Applications.id == ApplicationDocumentUploads.application_id
    ).first()
    
    if app_with_docs:
        print(f"✅ Found test application #{app_with_docs.id}")
        
        # Get its uploaded documents
        uploads = ApplicationDocumentUploads.query.filter_by(
            application_id=app_with_docs.id
        ).all()
        
        print(f"✅ Found {len(uploads)} uploaded documents")
        
        if uploads:
            upload = uploads[0]
            print(f"\nDocument Upload #{upload.id}:")
            print(f"  Current Status: {upload.verification_status}")
            print(f"  Requirement: {upload.requirement_id}")
            print(f"  Application: {upload.application_id}")
            
            # Test the valid statuses
            valid_statuses = ['pending', 'approved', 'rejected']
            print(f"\n✅ Valid statuses for ApplicationDocumentUploads: {valid_statuses}")
            
            # Try updating to each status
            for status in valid_statuses:
                upload.verification_status = status
                db.session.commit()
                print(f"✅ Successfully set status to '{status}'")
            
            # Reset to pending
            upload.verification_status = 'pending'
            db.session.commit()
            print(f"\n✅ Final status reset to 'pending'")
    else:
        print("❌ No applications with documents found")
        # Let's create dummy data to test
        print("\nNote: Run fast_populate_data.py first to generate test data")
