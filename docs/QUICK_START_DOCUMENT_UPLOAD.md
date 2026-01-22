# Quick Start Guide: Document Upload Feature

## Overview
The new document upload feature allows users to upload their documents online for pre-verification before physical submission at the MSWD office. This reduces unnecessary follow-ups and improves efficiency.

## Installation Steps

### 1. Run Database Migration
```bash
# Navigate to project directory
cd C:\Users\abule\Documents\GitHub\FLASK

# Backup existing database (IMPORTANT!)
copy instance\ayuda.db instance\ayuda_backup_20260120.db

# Run migration
type migrations\add_document_upload_workflow.sql | sqlite3 instance\ayuda.db

# Verify migration
sqlite3 instance\ayuda.db "PRAGMA table_info(applications);"
sqlite3 instance\ayuda.db "SELECT name FROM sqlite_master WHERE type='table' AND name='application_document_uploads';"
```

### 2. Create Upload Directory
```bash
# Create directory for uploaded documents
mkdir static\uploads\application_documents
```

### 3. Restart Application
```bash
# Stop current Flask application (Ctrl+C if running)
# Then restart
python main.py
```

## How It Works

### For Users (Applicants)
1. **Apply for Program** → Redirected to upload page
2. **Upload Documents** → Take photos or upload scans of required documents
3. **Wait for Verification** → Admin reviews and provides feedback
4. **Get Approval** → Proceed to MSWD office once verified
5. **Physical Submission** → Bring verified documents to office

### For Admins
1. **View Application** → See "Online Document Uploads" section
2. **Review Documents** → Click to view each uploaded document
3. **Verify or Reject** → Approve good documents, reject with feedback if issues
4. **Track Progress** → System automatically updates upload status

## New URLs

### User Routes
- `/community/applications/<id>/upload-documents` - Upload documents page
- `/community/applications/<id>/submit-documents` - Handle upload submission
- `/community/document-uploads/<id>/view` - View uploaded document

### Admin Routes
- `/admin/applications/<id>/verify-upload/<upload_id>` - Verify uploaded document

## Key Features

### Upload Page Features
- ✅ Drag-and-drop file upload
- ✅ Progress tracking (X of Y documents uploaded)
- ✅ Mandatory vs optional document indicators
- ✅ File validation (PDF, JPG, JPEG, PNG only, max 10MB)
- ✅ Preview uploaded files
- ✅ View admin feedback on rejected documents
- ✅ Reupload capability for rejected documents

### Admin Review Features
- ✅ View all uploaded documents
- ✅ Quick approve/reject buttons
- ✅ Add feedback for rejected documents
- ✅ View document verification status
- ✅ Auto-update application upload status
- ✅ Send notifications to users

## Application Statuses

### document_upload_status
- **pending** - User has not uploaded documents yet (shows "Upload Documents" button)
- **uploaded** - User uploaded documents, awaiting admin review (shows "Under Review" badge)
- **verified** - Admin approved all mandatory documents (shows success message)
- **rejected** - One or more documents rejected by admin (shows "Resubmit" button)

### verification_status (per document)
- **pending** - Document uploaded but not yet reviewed
- **approved** - Document reviewed and approved by admin
- **rejected** - Document rejected by admin, needs reupload

## Workflow Example

### Scenario: Student Applying for Educational Assistance

1. **Day 1 - User Submits Application**
   - User fills out application for "Educational Assistance Program"
   - Clicks "Submit Application"
   - Automatically redirected to upload page
   - Status: `application_status = pending`, `document_upload_status = pending`

2. **Day 1 - User Uploads Documents**
   - User uploads:
     - ✓ Student ID (mandatory)
     - ✓ Certificate of Enrollment (mandatory)
     - ✓ Grade Report (mandatory)
     - ✓ Barangay Certificate (optional)
   - Clicks "Submit Documents for Verification"
   - Status: `document_upload_status = uploaded`
   - Admin receives notification

3. **Day 2 - Admin Reviews Documents**
   - Admin views uploaded documents
   - Student ID: ✓ Approved
   - Certificate of Enrollment: ✓ Approved
   - Grade Report: ✗ Rejected (blurry, can't read grades)
   - Admin adds feedback: "Image is too blurry. Please upload a clearer photo of your grade report."
   - Status: `document_upload_status = rejected`
   - User receives notification

4. **Day 2 - User Reuploads**
   - User receives notification about rejection
   - Views feedback on upload page
   - Takes new, clearer photo of grade report
   - Reuploads document
   - Status: `document_upload_status = uploaded`
   - Admin receives notification

5. **Day 3 - Admin Approves All**
   - Admin reviews new grade report upload
   - Grade Report: ✓ Approved
   - All mandatory documents now approved
   - Status: `document_upload_status = verified`
   - User receives notification: "Documents verified! You may proceed to physical submission."

6. **Day 4 - Physical Submission**
   - User visits MSWD office with verified documents
   - Admin does final check (documents already pre-verified)
   - Application approved
   - User receives application slip

## Testing the Feature

### Test Case 1: Complete Upload Flow
1. Login as community user
2. Navigate to Programs → Select a program → Apply
3. Should redirect to upload page
4. Upload at least one mandatory document
5. Submit documents
6. Check application details page - should show "Under Review" status

### Test Case 2: Admin Verification
1. Login as admin
2. Navigate to Applications → View application
3. See "Online Document Uploads" section
4. Click "View" to see uploaded document
5. Click "Approve" or "Reject"
6. Check that status updates

### Test Case 3: Reupload After Rejection
1. As admin, reject a document with feedback
2. Logout and login as community user
3. Navigate to application details
4. Should see "Documents Need Revision" alert
5. Click "Resubmit" button
6. Upload new document
7. Submit and verify status updates

## Troubleshooting

### Upload Not Working
- Check if `static/uploads/application_documents/` directory exists
- Check file permissions on upload directory
- Check file size (must be < 10MB)
- Check file type (must be PDF, JPG, JPEG, or PNG)

### Documents Not Showing for Admin
- Check if `uploads_by_requirement` is passed to template
- Check database query in `view_application` route
- Check if ApplicationDocumentUploads table exists

### Status Not Updating
- Check database for errors in console
- Verify all mandatory documents are uploaded/approved
- Check notification creation code

## Database Queries for Debugging

```sql
-- Check upload status of all applications
SELECT id, program_id, document_upload_status, application_status 
FROM applications 
ORDER BY id DESC LIMIT 10;

-- Check uploaded documents for application #123
SELECT * FROM application_document_uploads 
WHERE application_id = 123;

-- Check mandatory requirements for program #5
SELECT r.requirement_name, pr.is_mandatory 
FROM requirements r
JOIN program_requirements pr ON r.id = pr.requirement_id
WHERE pr.program_id = 5 AND r.requirement_type = 'document';

-- Count uploads by verification status
SELECT verification_status, COUNT(*) 
FROM application_document_uploads 
GROUP BY verification_status;
```

## Rollback (If Needed)

If you need to revert the changes:

```bash
# Restore backup
copy instance\ayuda_backup_20260120.db instance\ayuda.db

# Or run rollback SQL
sqlite3 instance\ayuda.db "DROP TRIGGER IF EXISTS update_doc_upload_timestamp;"
sqlite3 instance\ayuda.db "DROP TABLE IF EXISTS application_document_uploads;"
sqlite3 instance\ayuda.db "ALTER TABLE applications DROP COLUMN document_upload_status;"
```

## Support Contacts

For questions or issues:
- Check logs: `logs/flask_app.log`
- Review documentation: `DOCUMENT_UPLOAD_WORKFLOW.md`
- Database location: `instance/ayuda.db`

---

**Implementation Date:** January 20, 2026
**Status:** Ready for testing
