# Document Upload Workflow for Educational Assistance Programs

## Overview
This document describes the new application process that includes an online document upload step for initial verification before physical submission at the MSWD office.

## New Application Workflow

### Previous Workflow
1. User submits application
2. User physically submits documents at MSWD office
3. Admin reviews and verifies documents
4. Application approved/rejected

### New Improved Workflow
1. **User submits application** → Application status: `pending`, Upload status: `pending`
2. **User uploads documents online** → Upload status: `uploaded` (when all mandatory documents uploaded)
3. **Admin reviews uploaded documents** → Verifies or rejects each document
   - If approved: Upload status: `verified`
   - If rejected: Upload status: `rejected` (user must resubmit)
4. **User proceeds to physical submission** → Only after documents are verified online
5. **Final approval** → Application approved for claiming

## Benefits
- **Reduces unnecessary visits**: Users know if their documents are acceptable before going to the office
- **Saves time**: Admin can pre-screen documents and provide feedback remotely
- **Better preparation**: Users receive feedback and can correct documents before physical submission
- **Improved efficiency**: Only users with verified documents proceed to physical submission
- **Audit trail**: All document versions and feedback are tracked

## Database Changes

### 1. Applications Table
**New Column:**
- `document_upload_status` VARCHAR(20) - Tracks online document upload status
  - Values: `pending`, `uploaded`, `verified`, `rejected`

### 2. New Table: application_document_uploads
Stores online document uploads for pre-verification.

**Columns:**
- `id` - Primary key
- `application_id` - FK to applications
- `requirement_id` - FK to requirements
- `file_path` - Path to uploaded file
- `original_filename` - Original file name
- `file_size` - File size in bytes
- `file_type` - MIME type
- `verification_status` - Status: `pending`, `approved`, `rejected`
- `admin_feedback` - Feedback from admin
- `verified_by` - FK to users (admin who verified)
- `verified_at` - Timestamp of verification
- `uploaded_at` - Timestamp of upload
- `updated_at` - Timestamp of last update

## New Routes

### Community Routes (app/community/routes/applications.py)

1. **GET /applications/<id>/upload-documents**
   - Displays document upload page
   - Shows all document requirements
   - Shows existing uploads with verification status
   - Allows reupload if rejected

2. **POST /applications/<id>/submit-documents**
   - Handles document file uploads
   - Validates file types (PDF, JPG, JPEG, PNG)
   - Validates file sizes (max 10MB)
   - Updates application.document_upload_status
   - Creates notifications for admin and user

3. **GET /document-uploads/<id>/view**
   - View uploaded document
   - Security check: user owns application or is admin

### Admin Routes (app/admin/routes/applications.py)

1. **POST /admin/applications/<id>/verify-upload/<upload_id>**
   - Approve or reject uploaded documents
   - Add admin feedback
   - Update verification status
   - Auto-update application.document_upload_status
   - Send notifications to user

## Templates

### 1. templates/community/upload_documents.html
**Features:**
- Step indicator showing application progress
- File upload interface with drag-and-drop support
- Progress tracker showing upload completion
- Mandatory vs optional document indicators
- Preview of uploaded files
- Admin feedback display
- Validation (file type, size)

### 2. templates/community/application_details.html (Updated)
**New Features:**
- Document upload status badge
- Action alerts based on upload status:
  - Pending: "Upload Documents" button
  - Rejected: "Resubmit Documents" button
  - Uploaded: "Under Review" status
  - Verified: "Proceed to Physical Submission" message

### 3. templates/admin/view_application.html (Updated)
**New Features:**
- Online uploads section showing all uploaded documents
- Verification status for each upload
- Quick approve/reject buttons
- View document button (opens in new tab)
- Admin feedback display
- Upload timestamp and file information

## User Experience Flow

### For Applicants

1. **Submit Application**
   - Fill out application form
   - Click "Apply for Program"
   - Redirected to document upload page

2. **Upload Documents**
   - See list of required documents
   - Upload clear photos/scans of each document
   - Submit for review
   - Wait for admin verification (receive notification)

3. **Receive Feedback**
   - If approved: Proceed to MSWD office with verified documents
   - If rejected: Review feedback, correct issues, reupload

4. **Physical Submission**
   - Bring verified documents to MSWD office
   - Final verification and approval

### For Admins

1. **Review Application**
   - Navigate to application details
   - See "Online Document Uploads" section
   - View each uploaded document

2. **Verify Documents**
   - Click to view document
   - Click "Approve" if document is acceptable
   - Click "Reject" and provide feedback if issues found
   - System auto-updates application upload status

3. **Track Status**
   - Dashboard shows applications with pending uploads
   - Easy filtering by upload status
   - Notifications for new uploads

## File Storage

**Location:** `static/uploads/application_documents/<application_id>/`

**Naming Convention:** `<requirement_id>_<timestamp>_<original_filename>`

**Security:**
- Files stored outside web root (if configured)
- Access controlled through Flask routes
- Only applicant and admins can view files

## Validation Rules

### File Upload
- **Allowed types:** PDF, JPG, JPEG, PNG
- **Max size:** 10MB per file
- **Required:** All mandatory documents must be uploaded before status changes to "uploaded"

### Status Transitions

**document_upload_status:**
- `pending` → `uploaded`: When all mandatory documents uploaded
- `uploaded` → `verified`: When all mandatory documents approved by admin
- `uploaded` → `rejected`: When any mandatory document rejected by admin
- `rejected` → `uploaded`: When user reuploads rejected documents

**verification_status (per document):**
- `pending` → `approved`: Admin verifies document
- `pending` → `rejected`: Admin rejects document
- `rejected` → `pending`: User reuploads new document

## Notifications

### User Notifications
1. **Application Created:** "Please upload your documents for initial verification"
2. **Documents Under Review:** "Your documents are being reviewed by our team"
3. **Documents Verified:** "Your documents have been verified. You may proceed to physical submission"
4. **Documents Rejected:** "Some documents need revision. Please check feedback and resubmit"

### Admin Notifications
1. **New Upload:** "User has uploaded documents for application #123"
2. **Reupload:** "User has resubmitted rejected documents for application #123"

## Migration Instructions

1. **Backup Database:**
   ```bash
   sqlite3 instance/ayuda.db ".backup instance/ayuda_backup.db"
   ```

2. **Run Migration:**
   ```bash
   sqlite3 instance/ayuda.db < migrations/add_document_upload_workflow.sql
   ```

3. **Verify Migration:**
   ```sql
   -- Check if column exists
   PRAGMA table_info(applications);
   
   -- Check if table exists
   SELECT name FROM sqlite_master WHERE type='table' AND name='application_document_uploads';
   ```

4. **Update Existing Applications:**
   ```sql
   -- Set default upload status for existing applications
   UPDATE applications SET document_upload_status = 'pending' WHERE document_upload_status IS NULL;
   ```

## Testing Checklist

### User Flow
- [ ] Submit new application - redirects to upload page
- [ ] Upload mandatory documents - upload status updates
- [ ] Upload optional documents
- [ ] View uploaded documents
- [ ] Receive notification when documents reviewed
- [ ] Reupload rejected documents
- [ ] View application details with upload status

### Admin Flow
- [ ] View uploaded documents in application details
- [ ] Approve uploaded document
- [ ] Reject uploaded document with feedback
- [ ] View document file
- [ ] Receive notification for new uploads
- [ ] See upload status in application list

### Edge Cases
- [ ] Upload file too large (>10MB)
- [ ] Upload invalid file type
- [ ] Upload without mandatory documents
- [ ] Cancel application with uploads
- [ ] Multiple reuploads of same document

## Future Enhancements

1. **Email Notifications**: Send email when documents are verified/rejected
2. **Document Templates**: Provide downloadable templates for common documents
3. **OCR Integration**: Auto-extract data from uploaded documents
4. **Batch Upload**: Upload multiple files at once
5. **Mobile Upload**: Optimize for mobile camera capture
6. **Document Expiry Tracking**: Track document expiration dates
7. **Version History**: Keep all uploaded versions for audit trail

## Support

For issues or questions about the document upload workflow:
- Check application logs: `logs/flask_app.log`
- Review uploaded files: `static/uploads/application_documents/`
- Database queries: Check `application_document_uploads` table

---

**Last Updated:** January 20, 2026
**Version:** 1.0
