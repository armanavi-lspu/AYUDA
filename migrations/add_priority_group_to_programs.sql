-- Add priority_group, beneficiary_limit, and income_range columns to programs table
-- This allows programs to specify target beneficiary groups, set acceptance limits, and target income levels

ALTER TABLE programs 
ADD COLUMN priority_group VARCHAR(255),
ADD COLUMN beneficiary_limit INTEGER,
ADD COLUMN income_range VARCHAR(100);

-- Add comments to explain the columns
COMMENT ON COLUMN programs.priority_group IS 'Target beneficiary groups (comma-separated, e.g., "Low Income Families, Students, PWDs")';
COMMENT ON COLUMN programs.beneficiary_limit IS 'Maximum number of beneficiaries that can be accepted (NULL = unlimited)';
COMMENT ON COLUMN programs.income_range IS 'Target monthly household income range (e.g., "Below 10,000", "10,000 - 15,000")';

-- Optional: Add index if you plan to search by priority groups
CREATE INDEX idx_programs_priority_group ON programs(priority_group);

-- Optional: Add check constraint to ensure beneficiary_limit is positive
ALTER TABLE programs 
ADD CONSTRAINT chk_beneficiary_limit_positive 
CHECK (beneficiary_limit IS NULL OR beneficiary_limit > 0);
