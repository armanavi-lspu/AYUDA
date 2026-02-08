-- Add gender field to community_users table
ALTER TABLE community_users
ADD COLUMN gender VARCHAR(20);

-- Create index for gender filtering
CREATE INDEX idx_community_users_gender ON community_users(gender);
