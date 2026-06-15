from app import create_app
from app.extensions import db
from app.models import ApplicationDocumentUploads
import os

app = create_app()

with app.app_context():
    uploads = ApplicationDocumentUploads.query.filter_by(application_id=35).all()
    
    if uploads:
        for upload in uploads:
            print(f"Upload ID: {upload.id}")
            print(f"Stored path: {upload.file_path}")
            print(f"File exists: {os.path.exists(upload.file_path)}")
            print(f"Is absolute: {os.path.isabs(upload.file_path)}")
            print("-" * 50)
    else:
        print("No uploads found for application 35")
