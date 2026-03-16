## Document Verification Counter & Unverify Fix - Summary

### Issues Fixed

**Issue 1: Verified Counter Not Updating**
- **Root Cause**: The counter was reading from the old `ApplicationDocuments` model with `submission_status` field instead of the new `ApplicationDocumentUploads` model with `verification_status` field
- **File Fixed**: `templates/admin/view_application.html` (Line ~1445)
- **Change**: Updated counter badge to iterate through `document_requirements` and check actual verified documents in `uploads_by_requirement` dictionary

**Issue 2: "Error: Invalid verification status" When Unverifying**
- **Root Cause**: The backend endpoint only accepted 'approved' or 'rejected', but the unverify button sends 'pending' status
- **File Fixed**: `app/admin/routes/applications.py` (Line 1923)
- **Changes Made**:
  1. Updated validation to accept `['approved', 'rejected', 'pending']` (was: `['approved', 'rejected']`)
  2. Added handling for pending status to set `document_upload_status = 'uploaded'` (Line 2004)

**Issue 3: "Complete Step & Proceed" Button Not Clickable Despite All Documents Verified**
- **Root Cause**: The button disable condition had flawed logic - it was disabled when `mandatory_docs == 0`, even when all documents were verified
- **File Fixed**: `templates/admin/view_application.html` (Line 1608)
- **Change**: 
  - **Before**: `{% if approved_docs != mandatory_docs or mandatory_docs == 0 %}disabled{% endif %}`
  - **After**: `{% if mandatory_docs > 0 and approved_docs != mandatory_docs %}disabled{% endif %}`
  - **Why**: The button should only be disabled if there ARE mandatory documents AND not all are approved. When `mandatory_docs == 0` (no mandatory docs required), the button should be enabled.

### Files Modified

1. **templates/admin/view_application.html**
   - Line ~1445: Updated verified document counter logic
   - Line 1608: Fixed button disable condition logic

2. **app/admin/routes/applications.py**  
   - Line 1923: Added 'pending' to valid verification statuses
   - Line 2004: Added handling for documents set back to pending

### What to Do Next

**IMPORTANT: Restart the Flask Development Server**

If you're running the Flask app in development mode, you need to restart it for the template changes to take effect:

```bash
# Kill any running Flask processes
# Then restart with:
.\.venv\Scripts\Activate.ps1
python main.py
```

Or if you're using `flask run`:
```bash
.\.venv\Scripts\Activate.ps1  
flask run --host=0.0.0.0 --port=5000
```

### Testing the Fix

After restarting Flask:

1. **Test Approving a Document**:
   - Go to any application
   - Click "Approve" on a pending document
   - The counter should update from "0 / 4 Verified" to "1 / 4 Verified" after page reload

2. **Test Unverifying a Document**:
   - Click "Unverify" on an approved document
   - Should see message: "Document verification removed. Status reset to pending review"
   - Counter should decrease accordingly

3. **Test Button Clickability**:
   - When all mandatory documents are verified, the "Complete Step & Proceed" button should be clickable
   - When some documents are still pending, the button should remain disabled with a grayed-out appearance

### Verification Steps

Run this command to verify the code is correct:

```bash
.\.venv\Scripts\python.exe -c "
from app import create_app
import inspect

app = create_app()
with app.app_context():
    from app.admin.routes.applications import verify_uploaded_document
    source = inspect.getsource(verify_uploaded_document)
    if 'pending' in source:
        print('✅ Backend fix is loaded')
        for line in source.split('\n'):
            if 'verification_status not in' in line:
                print(f'   {line.strip()}')
    else:
        print('❌ Backend fix NOT loaded')
"
```

Expected Output:
```
✅ Backend fix is loaded
   if verification_status not in ['approved', 'rejected', 'pending']:
```

### How It Works Now

**Approve Document Flow**:
1. Admin clicks "Approve" button
2. Frontend calls `/admin/applications/{id}/verify-upload/{upload_id}` with status='approved'
3. Backend updates ApplicationDocumentUploads record
4. Page reloads
5. Template re-renders with updated counter showing confirmed approved documents
6. If all mandatory documents are approved, "Complete Step & Proceed" button becomes clickable

**Unverify Document Flow**:
1. Admin clicks "Unverify" button  
2. Frontend calls `/admin/applications/{id}/verify-upload/{upload_id}` with status='pending'
3. Backend now accepts 'pending' status (previously rejected this)
4. Document status returns to 'pending' for re-review
5. Page reloads
6. Counter decreases to reflect the change

### Notes

- The verified counter dynamically counts documents with `verification_status == 'approved'` from the `ApplicationDocumentUploads` table
- Setting a document to 'pending' removes its "approved" status and allows for re-review
- Both the header badge and footer status section track the same uploaded documents
