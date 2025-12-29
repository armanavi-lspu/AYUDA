-- Add program duration fields to programs table
-- This allows tracking of program start and end dates, especially useful for one-time/time-bound programs

ALTER TABLE programs 
ADD COLUMN start_date DATE COMMENT 'Program start date (when it begins accepting applications)',
ADD COLUMN end_date DATE COMMENT 'Program end date / deadline for document submission';

-- Add index for end_date to quickly find expiring/expired programs
CREATE INDEX idx_programs_end_date ON programs(end_date);

-- Add check constraint to ensure end_date is after start_date (if both are set)
ALTER TABLE programs 
ADD CONSTRAINT chk_program_date_range 
CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date);

-- Update existing programs with NULL values (no changes to existing data)
-- Admins can update these values through the edit program interface
