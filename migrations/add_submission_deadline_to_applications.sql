-- Migration: Add submission_deadline column to Applications table
-- This migration adds the submission_deadline column to track when applicants must submit documents

-- Add submission_deadline column to applications table
ALTER TABLE applications ADD COLUMN submission_deadline DATETIME;