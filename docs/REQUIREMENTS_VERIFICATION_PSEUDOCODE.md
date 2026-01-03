# REQUIREMENTS VERIFICATION PROCESS - PSEUDOCODE

## OVERVIEW
Two-tier verification system: (1) Automatic qualification checking based on user profile, (2) Manual document verification by admin.

---

## 1. AUTOMATIC QUALIFICATION VERIFICATION

```
FUNCTION CheckQualification(requirement, user_profile)
    INPUT: requirement {name, description, type}, user_profile {demographics}
    
    IF user_profile IS NULL THEN RETURN false
    
    combined_text = LOWERCASE(requirement.name + " " + requirement.description)
    
    // Age-based checking
    IF combined_text CONTAINS ["age", "years old", "senior"] THEN
        IF "senior" OR "60" IN combined_text THEN
            RETURN user_profile.age >= 60
        ELSE IF "18" IN combined_text THEN
            RETURN user_profile.age >= 18
        ELSE IF PATTERN "X to Y years" EXISTS THEN
            [min_age, max_age] = EXTRACT_AGE_RANGE(combined_text)
            RETURN min_age <= user_profile.age <= max_age
        END IF
    END IF
    
    // Employment status
    IF combined_text CONTAINS ["employed", "employment"] THEN
        IF "unemployed" OR "not employed" IN combined_text THEN
            RETURN NOT user_profile.is_currently_employed
        ELSE
            RETURN user_profile.is_currently_employed
        END IF
    END IF
    
    // Student status
    IF combined_text CONTAINS "student" THEN
        RETURN user_profile.is_student
    END IF
    
    // Solo parent status
    IF combined_text CONTAINS ["solo parent", "single parent"] THEN
        RETURN user_profile.is_solo_parent
    END IF
    
    // PWD status
    IF combined_text CONTAINS ["pwd", "disability", "disabled"] THEN
        RETURN user_profile.is_pwd
    END IF
    
    // Residency
    IF combined_text CONTAINS ["resident", "barangay", "mabitac"] THEN
        RETURN user_profile.barangay IS NOT NULL
    END IF
    
    // Income-based
    IF combined_text CONTAINS ["income", "indigent", "poverty"] THEN
        IF "low income" OR "indigent" IN combined_text THEN
            RETURN user_profile.family_annual_income <= 20000
        END IF
    END IF
    
    // Unable to auto-verify
    RETURN null
END FUNCTION
```

---

## 2. MANUAL DOCUMENT VERIFICATION (ADMIN)

```
FUNCTION VerifyDocument(application_id, document_id, verification_data)
    INPUT: application_id, document_id, 
           is_complete (boolean), admin_feedback (text), notes (text)
    
    // Fetch document record
    document = FETCH ApplicationDocuments WHERE 
               id = document_id AND application_id = application_id
    
    IF document NOT EXISTS THEN RETURN error("Document not found")
    
    BEGIN TRANSACTION
        // Update document status
        IF is_complete = true THEN
            document.submission_status = "approved"
        ELSE
            document.submission_status = "submitted"  // Needs revision
        END IF
        
        // Add admin feedback
        IF admin_feedback IS NOT NULL THEN
            document.admin_feedback = admin_feedback
        END IF
        
        IF notes IS NOT NULL THEN
            document.notes = notes
        END IF
        
        document.verified_by = currentAdmin.id
        document.verified_at = NOW()
        document.updated_at = NOW()
        
        SAVE document
        
        // Check if all mandatory documents are complete
        application = document.application
        mandatoryDocs = FETCH ApplicationDocuments WHERE 
                        application_id = application_id AND
                        requirement.is_mandatory = true
        
        allComplete = ALL(mandatoryDocs.submission_status = "approved")
        
        // Auto-approve application if all mandatory docs verified
        IF allComplete AND application.status = "pending" THEN
            application.application_status = "approved"
            application.reviewed_by = currentAdmin.id
            application.review_date = NOW()
            SAVE application
        END IF
        
        // Send notification if feedback provided
        IF admin_feedback OR notes THEN
            CREATE Notifications {
                user_id: application.user_id,
                title: "Document Feedback",
                message: "Admin feedback on '" + document.requirement_name + 
                        "': " + (admin_feedback OR notes),
                is_read: false
            }
        END IF
        
    COMMIT TRANSACTION
    
    completionPercentage = (approvedDocs / totalDocs) * 100
    
    RETURN {
        success: true,
        is_complete: is_complete,
        completion_percentage: completionPercentage
    }
    
    ON ERROR: ROLLBACK, return error
END FUNCTION
```

---

## 3. BATCH PHOTO VERIFICATION

```
FUNCTION VerifyAllShelterPhotos(application_id, action, remarks)
    INPUT: application_id, action ["verify"|"reject"], remarks (optional)
    
    photos = FETCH ShelterPhotos WHERE application_id = application_id
    
    IF photos.length = 0 THEN RETURN error("No photos found")
    
    BEGIN TRANSACTION
        FOR EACH photo IN photos DO
            IF action = "verify" THEN
                photo.is_verified = true
                photo.verification_status = "approved"
            ELSE IF action = "reject" THEN
                photo.is_verified = false
                photo.verification_status = "rejected"
            END IF
            
            photo.verified_by = currentAdmin.id
            photo.verified_at = NOW()
            photo.admin_remarks = remarks
            SAVE photo
        END FOR
        
        // Create notification
        statusText = (action = "verify") ? "verified" : "rejected"
        CREATE Notifications {
            user_id: application.user_id,
            title: "Shelter Photos " + CAPITALIZE(statusText),
            message: "Your shelter photos have been " + statusText + 
                    (remarks ? ". Remarks: " + remarks : ""),
            is_read: false
        }
        
    COMMIT TRANSACTION
    
    RETURN success("All photos " + statusText)
    
    ON ERROR: ROLLBACK
END FUNCTION
```

---

## 4. VERIFICATION WORKFLOW

```
APPLICATION SUBMISSION:
    ↓
    CREATE ApplicationDocuments (all with status: "pending")
    ↓
    AUTOMATIC QUALIFICATION CHECK
    ├─ qualification_type requirements → Auto-check against user profile
    │  └─ Status: "met", "not_met", or "needs_verification"
    └─ document_type requirements → Awaits manual verification
    
USER SUBMITS DOCUMENTS (offline at MSWD office):
    ↓
    ADMIN REVIEWS PHYSICAL DOCUMENTS
    ↓
    ADMIN VERIFIES EACH DOCUMENT:
    ├─ Mark as "approved" (complete & valid)
    ├─ Mark as "submitted" (incomplete/needs revision)
    └─ Add feedback/notes
    
COMPLETION CHECK:
    IF all_mandatory_documents.status = "approved" THEN
        Auto-update application.status = "approved"
        SEND notification to user
        Generate application slip
    ELSE
        Application remains "pending"
        User notified of missing/incomplete documents
    END IF
```

---

## 5. VERIFICATION STATUS FLOW

```
Document Lifecycle:
    "pending"        → Initial state after application submission
         ↓
    "submitted"      → User submitted physical document (marked by admin)
         ↓
    "approved"       → Admin verified document is complete & valid
    OR
    "rejected"       → Document rejected (needs resubmission)

Qualification Lifecycle:
    "pending"        → Initial state
         ↓
    AUTO-CHECK       → System checks against user profile
         ↓
    "met"            → User qualifies (auto-verified)
    "not_met"        → User doesn't qualify
    "needs_verification" → Cannot auto-verify, admin review needed
```

---

## KEY FEATURES

1. **Dual Verification System**
   - Qualifications: Automatic via profile matching
   - Documents: Manual admin verification

2. **Progress Tracking**
   - Completion % = (approved_docs / total_docs) × 100
   - Real-time updates on verification status

3. **Auto-Approval Logic**
   - When all mandatory documents verified → Auto-approve application

4. **Feedback Mechanism**
   - Admin can add notes/feedback per document
   - User receives notification for each feedback

5. **Batch Operations**
   - Verify/reject multiple photos simultaneously
   - Bulk status updates with remarks

---

**END OF DOCUMENT**
