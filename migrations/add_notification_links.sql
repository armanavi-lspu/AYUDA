-- Add related_id and related_type columns to notifications table
ALTER TABLE notifications
ADD COLUMN related_id INTEGER,
ADD COLUMN related_type VARCHAR(50);

-- Create index for faster lookups
CREATE INDEX idx_notifications_related ON notifications(related_type, related_id);
