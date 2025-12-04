# Announcement Program Link Feature

## Overview
This feature allows administrators to link announcements to specific programs, enabling community users to quickly navigate from an announcement to the program application page. Administrators can also add external links or attachment URLs to announcements.

## Features Added

### 1. **Database Changes**
- Added `program_id` field to link announcements to programs (foreign key to `programs` table)
- Added `attachment_url` field for external links or resource URLs (up to 500 characters)

### 2. **Admin Interface Enhancements**
When creating or editing announcements, admins can now:
- **Select a Program**: Choose from a dropdown list of active programs to link to the announcement
- **Add Attachment URL**: Provide an external link or resource URL (e.g., Google Drive link, external document)
- View linked program information in the announcement view modal

### 3. **Community User Experience**
Community users viewing announcements will see:
- **Linked Program Alert**: Prominent call-to-action box showing the linked program with "Apply Now" button
- **Attachment Link**: Button to open external attachments or resources in a new tab
- **Apply to Program Button**: Direct link from announcement list to program application page
- **Program Badge**: Visual indicator on announcement cards showing linked programs

## How to Use

### For Administrators

#### Creating an Announcement with Program Link:
1. Navigate to **Admin → Announcements**
2. Click **"Create Announcement"**
3. Fill in the announcement details (title, content, category)
4. In the **"Link to Program (Optional)"** section:
   - Select a program from the dropdown (or leave as "No Program Link")
   - OR add an external link/attachment URL
5. Click **"Create Announcement"**

#### Editing an Announcement:
1. Click the **Edit** button on any announcement
2. Update the program link or attachment URL as needed
3. Save changes

### For Community Users

#### Viewing Announcements:
1. Navigate to **Community → Announcements**
2. Announcements with linked programs will show:
   - A blue badge saying "Linked Program: [Program Name]"
   - An **"Apply to Program"** button for quick access
3. Click **"View Full Details"** to see the complete announcement
4. In the detail view:
   - See a prominent program card with **"Apply Now"** button
   - Click to be redirected to the program application page
   - If an attachment URL is provided, click **"Open Link"** to view it

## Database Migration

To apply the database changes, run the migration script:

```bash
# Navigate to project directory
cd c:\Users\abule\Documents\GitHub\FLASK

# Run the migration
python migrations/add_announcement_program_link.py
```

### Rollback (if needed):
```bash
python migrations/add_announcement_program_link.py downgrade
```

## Technical Details

### Model Changes (`app/models.py`)
```python
class Announcements(db.Model):
    # ... existing fields ...
    program_id = db.Column(db.Integer, db.ForeignKey('programs.id'), nullable=True)
    attachment_url = db.Column(db.String(500), nullable=True)
    
    # Relationship
    linked_program = db.relationship('Programs', backref='announcements', foreign_keys=[program_id])
```

### Route Changes
- **`adm_announcements.py`**: Updated to handle program_id and attachment_url in create/edit operations
- **`announcements.py`**: No changes needed (templates handle the display)

### Template Changes
1. **`admin/adm_announcements.html`**: Added program selection and attachment URL inputs
2. **`community/announcements.html`**: Added program link badge and apply button
3. **`community/view_announcement.html`**: Added prominent program card with call-to-action

## Benefits

1. **Seamless Navigation**: Users can easily move from reading about a program to applying for it
2. **Better Engagement**: Prominent call-to-action buttons increase program application rates
3. **Flexibility**: Support for both internal program links and external resources
4. **Admin Convenience**: Simple dropdown selection to link programs
5. **Visual Indicators**: Clear badges and buttons show which announcements have linked programs

## Example Use Cases

1. **Program Launch Announcement**: 
   - Link announcement about a new scholarship program directly to the application page
   
2. **Deadline Reminder**: 
   - Announcement about upcoming deadline with quick link to the program
   
3. **Document Requirements Update**: 
   - Link to external document (Google Drive, Dropbox) with updated forms
   
4. **Event Registration**: 
   - Link to external registration form or event page

## Notes

- Both program link and attachment URL are optional
- Only active programs appear in the dropdown
- External links open in new tabs for better user experience
- Program links are displayed prominently with gradient backgrounds
- The feature is backward compatible - existing announcements without links still work normally
