# Verification Code Feature Documentation

## Overview
A two-factor verification system for application document submissions that ensures physical document delivery before marking submissions as complete in the system.

## Workflow

### 1. Admin Side (Print Application Slip)
**Route**: `/admin/applications/<application_id>/slip`

**Process**:
1. Admin reviews and approves an application
2. Admin clicks "Print Application Slip" button in `view_application.html`
3. System automatically generates a unique 8-character verification code (if not already generated)
4. Printable slip is displayed containing:
   - Applicant information (name, email, mobile, address, age)
   - Application details (program, dates, deadline)
   - **Verification code** (prominently displayed)
   - Requirements checklist
   - Step-by-step instructions for document submission

**Code Generation**:
- Uses Python's `secrets` module for secure random generation
- Format: 8 uppercase alphanumeric characters (e.g., "A7K9M2X5")
- Stored in `applications.verification_code` column
- Generation timestamp stored in `code_generated_at`

### 2. Physical Document Submission
**Process**:
1. Community user visits MSWD Office with required documents
2. Staff verifies physical documents
3. Staff prints and provides application slip with verification code
4. User receives hard copy slip

### 3. Community User Side (Online Verification)
**Route**: `/community/verify-code` (GET/POST)

**Process**:
1. User goes to "My Applications" or application details page
2. Clicks "Verify Submission Code" button
3. Enters the 8-character code from their slip
4. System validates:
   - Code exists and matches user's application
   - Code hasn't been used already
   - Application status is 'approved'
5. If valid:
   - Updates `code_used_at` timestamp
   - Updates `documents_submitted_at` timestamp
   - Changes all 'not_submitted' or 'returned' documents to 'pending' status
   - Displays success message
6. If invalid:
   - Shows error message (invalid code or already used)

## Database Schema Changes

### New Columns in `applications` table:
```sql
- verification_code VARCHAR(20) UNIQUE -- The 8-character code
- code_generated_at DATETIME         -- When admin printed slip
- code_used_at DATETIME              -- When user verified code online
- documents_submitted_at DATETIME     -- When documents were confirmed submitted
```

### Migration File:
`migrations/add_verification_code_fields.py`

## Files Modified/Created

### Backend Routes:
1. **`app/admin/routes/applications.py`**
   - Added `application_slip()` route for admin slip printing
   - Generates verification code on-demand
   - Renders printable slip template

2. **`app/community/routes/applications.py`**
   - Modified `application_slip()` to disable direct community access
   - Added `verify_code()` route (GET/POST) for code verification

### Models:
3. **`app/models.py`**
   - Added 4 new fields to `Applications` model
   - Added `generate_verification_code()` method
   - Imports: `secrets`, `string`

### Templates:
4. **`templates/admin/application_slip.html`** (NEW)
   - Full printable slip with verification code
   - Print-optimized CSS
   - Applicant info, requirements table, instructions

5. **`templates/community/verify_code.html`** (NEW)
   - Verification code input form
   - Instructions for obtaining code
   - Help section for common issues

6. **`templates/admin/view_application.html`**
   - Added "Print Application Slip" button for approved apps
   - Shows generated code badge if exists

7. **`templates/community/applications.html`**
   - Replaced "Download Slip" with "Verify Submission Code" button
   - Shows verification status (verified/not verified)
   - Added info text about code entry

8. **`templates/community/application_details.html`**
   - Updated Quick Actions section
   - Shows 4-step verification process
   - Displays verification timestamp when complete

## Security Features

1. **Secure Code Generation**: Uses `secrets` module (cryptographically strong random)
2. **Code Uniqueness**: Database constraint ensures no duplicate codes
3. **One-time Use**: System checks if code was already used (`code_used_at` field)
4. **Admin-only Printing**: Only admins can generate and print slips
5. **Physical + Digital**: Requires physical presence at office AND online verification
6. **Audit Trail**: Timestamps for code generation, usage, and document submission

## User Interface Elements

### Admin Interface:
- Print button appears only for approved applications
- Shows verification code badge if generated
- Info text explaining the slip's purpose

### Community Interface:
- "Verify Submission Code" button (yellow/warning style)
- Status indicators: "Code Pending" → "Verify Code" → "Documents Verified"
- Instructional alerts with step-by-step process
- Help section for troubleshooting

## Benefits

1. **Prevents Fraud**: Users can't falsely claim document submission
2. **Audit Trail**: Complete timestamp history of verification process
3. **Physical Verification**: Ensures documents are actually received at office
4. **Status Accuracy**: Document statuses only update after verification
5. **User Transparency**: Clear instructions and status updates
6. **Admin Control**: Only approved applications get verification codes

## Usage Example

```
Timeline:
Day 1, 10:00 AM  - User submits application online
Day 2, 2:00 PM   - Admin reviews and approves application
Day 2, 2:05 PM   - Admin prints slip (code: A7K9M2X5 generated)
Day 3, 11:00 AM  - User visits MSWD office with documents
Day 3, 11:30 AM  - Staff verifies docs, gives slip to user
Day 3, 12:00 PM  - User enters "A7K9M2X5" online
                 - System updates: code_used_at, documents_submitted_at
                 - All doc statuses → 'pending'
Day 4           - Admin reviews submitted documents
```

## Testing Checklist

- [ ] Admin can print slip for approved application
- [ ] Verification code is generated automatically
- [ ] Code is unique (no duplicates)
- [ ] Community user can access verify_code page
- [ ] Valid code updates document statuses to 'pending'
- [ ] Invalid code shows error message
- [ ] Used code cannot be reused
- [ ] Timestamps are recorded correctly
- [ ] UI buttons show correct states (pending/verify/verified)
- [ ] Help text and instructions are clear

## Future Enhancements

1. Email/SMS notification when slip is printed
2. QR code generation for faster scanning
3. Expiration time for verification codes
4. Code regeneration if lost
5. Integration with document upload system
6. Admin dashboard showing verification statistics
