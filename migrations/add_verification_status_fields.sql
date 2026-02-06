-- Migration: Add verification status fields to community_users table
-- For tracking Senior Citizen, PWD, and Solo Parent verification requests

-- Senior Citizen verification fields
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS senior_citizen_verification VARCHAR(20) DEFAULT 'none';
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS senior_citizen_id_number VARCHAR(50);
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS senior_citizen_verified_at TIMESTAMP;
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS senior_citizen_verified_by INTEGER REFERENCES users(id);
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS senior_citizen_document_path VARCHAR(255);
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS senior_citizen_rejection_reason TEXT;

-- PWD verification fields
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS pwd_verification VARCHAR(20) DEFAULT 'none';
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS pwd_id_number VARCHAR(50);
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS pwd_verified_at TIMESTAMP;
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS pwd_verified_by INTEGER REFERENCES users(id);
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS pwd_document_path VARCHAR(255);
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS pwd_rejection_reason TEXT;

-- Solo Parent verification fields
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS solo_parent_verification VARCHAR(20) DEFAULT 'none';
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS solo_parent_id_number VARCHAR(50);
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS solo_parent_verified_at TIMESTAMP;
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS solo_parent_verified_by INTEGER REFERENCES users(id);
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS solo_parent_document_path VARCHAR(255);
ALTER TABLE community_users ADD COLUMN IF NOT EXISTS solo_parent_rejection_reason TEXT;

-- Create indexes for faster filtering
CREATE INDEX IF NOT EXISTS idx_community_users_senior_verification ON community_users(senior_citizen_verification);
CREATE INDEX IF NOT EXISTS idx_community_users_pwd_verification ON community_users(pwd_verification);
CREATE INDEX IF NOT EXISTS idx_community_users_solo_parent_verification ON community_users(solo_parent_verification);
