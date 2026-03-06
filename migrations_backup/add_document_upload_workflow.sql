-- Migration: Add document upload workflow to applications
-- Date: 2026-01-20
-- Description: Adds document_upload_status to applications table and creates application_document_uploads table for pre-verification of documents

-- Step 1: Add document_upload_status column to applications table
ALTER TABLE applications 
ADD COLUMN document_upload_status VARCHAR(20) DEFAULT 'pending';

-- Add index for faster querying
CREATE INDEX idx_applications_doc_upload_status ON applications(document_upload_status);

-- Update existing applications to have default status
UPDATE applications 
SET document_upload_status = 'pending' 
WHERE document_upload_status IS NULL;

-- Step 2: Create application_document_uploads table for storing uploaded documents
CREATE TABLE IF NOT EXISTS application_document_uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    requirement_id INTEGER NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    file_size INTEGER,
    file_type VARCHAR(100),
    verification_status VARCHAR(20) DEFAULT 'pending',
    admin_feedback TEXT,
    verified_by INTEGER,
    verified_at DATETIME,
    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
    FOREIGN KEY (requirement_id) REFERENCES requirements(id),
    FOREIGN KEY (verified_by) REFERENCES users(id)
);

-- Add indexes for better query performance
CREATE INDEX idx_doc_uploads_application ON application_document_uploads(application_id);
CREATE INDEX idx_doc_uploads_status ON application_document_uploads(verification_status);
CREATE INDEX idx_doc_uploads_requirement ON application_document_uploads(requirement_id);

-- Step 3: Create trigger to update updated_at timestamp
CREATE TRIGGER IF NOT EXISTS update_doc_upload_timestamp 
AFTER UPDATE ON application_document_uploads
FOR EACH ROW
BEGIN
    UPDATE application_document_uploads 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE id = NEW.id;
END;

-- Notes:
-- 1. document_upload_status values: 'pending', 'uploaded', 'verified', 'rejected'
--    - pending: User has not uploaded documents yet
--    - uploaded: User uploaded documents, awaiting admin review
--    - verified: Admin has verified and approved all uploaded documents
--    - rejected: One or more documents were rejected by admin
--
-- 2. verification_status values in application_document_uploads: 'pending', 'approved', 'rejected'
--    - pending: Document uploaded but not yet reviewed
--    - approved: Document reviewed and approved by admin
--    - rejected: Document rejected by admin, needs reupload
--
-- 3. Workflow:
--    a. User submits application (document_upload_status = 'pending')
--    b. User uploads documents online (creates records in application_document_uploads)
--    c. When all mandatory documents uploaded, document_upload_status = 'uploaded'
--    d. Admin reviews uploaded documents, updates verification_status
--    e. When all mandatory documents approved, document_upload_status = 'verified'
--    f. User can then proceed to physical submission with verified documents

-- Rollback SQL (if needed):
-- DROP TRIGGER IF EXISTS update_doc_upload_timestamp;
-- DROP INDEX IF EXISTS idx_doc_uploads_requirement;
-- DROP INDEX IF EXISTS idx_doc_uploads_status;
-- DROP INDEX IF EXISTS idx_doc_uploads_application;
-- DROP TABLE IF EXISTS application_document_uploads;
-- DROP INDEX IF EXISTS idx_applications_doc_upload_status;
-- ALTER TABLE applications DROP COLUMN document_upload_status;
