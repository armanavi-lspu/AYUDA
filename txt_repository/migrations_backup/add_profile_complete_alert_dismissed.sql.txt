-- Migration: Add profile_complete_alert_dismissed column to users table
-- Purpose: Track if user has dismissed the profile completion success alert
-- Date: 2026-01-22

-- Add column to users table
ALTER TABLE users 
ADD COLUMN profile_complete_alert_dismissed BOOLEAN DEFAULT FALSE;

-- Add comment
COMMENT ON COLUMN users.profile_complete_alert_dismissed IS 'Tracks if user has dismissed the profile completion alert';

-- Update existing users (set to FALSE by default)
UPDATE users SET profile_complete_alert_dismissed = FALSE WHERE profile_complete_alert_dismissed IS NULL;

-- Verification query
-- SELECT id, email, profile_complete_alert_dismissed FROM users LIMIT 5;
