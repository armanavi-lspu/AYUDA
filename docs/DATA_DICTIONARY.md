# AYUDA Data Dictionary

Source: SQLAlchemy models in app/models.py.

## users

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| email | String(100) | NOT NULL, UNIQUE, INDEX |
| password_hash | String(255) | NOT NULL |
| first_name | String(50) | NOT NULL |
| middle_name | String(50) | NULL |
| last_name | String(50) | NOT NULL |
| role | String(20) | NOT NULL, INDEX; values like "super_admin", "admin", "community" |
| profile_pic | String(255) | NULL |
| last_activity | DateTime | NULL |
| profile_complete_alert_dismissed | Boolean | default False |
| created_at | DateTime | default UTC now |

## programs

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| program_name | String(200) | NOT NULL |
| program_type | String(50) | NOT NULL, INDEX |
| program_period | String(50) | NOT NULL |
| priority_group | String(255) | NULL |
| beneficiary_limit | Integer | NULL |
| income_range | String(100) | NULL |
| start_date | Date | NULL |
| end_date | Date | NULL |
| description | Text | NULL |
| date | DateTime | default UTC now |
| user_id | Integer | FK -> users.id |
| file_attachment_id | Integer | FK -> file_attachment.id |
| is_active | Boolean | default True, INDEX |
| allow_online_upload | Boolean | default True |
| enable_application_slip | Boolean | default True |

## program_workflow_steps

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| program_id | Integer | FK -> programs.id, NOT NULL |
| step_order | Integer | NOT NULL |
| step_name | String(100) | NOT NULL |
| step_description | Text | NULL |
| step_type | String(50) | NOT NULL, default "approval"; e.g. "photo_upload", "document_upload", "assessment", "document_submission", "scheduling" |
| is_pre_approval | Boolean | default False |
| requires_verification | Boolean | default True |
| allowed_file_types | String(255) | NULL |
| step_config | Text | JSON text |
| created_at | DateTime | default UTC now |
| updated_at | DateTime | default UTC now |

## requirements

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| requirement_name | String(255) | NOT NULL |
| requirement_type | String(50) | NOT NULL, default "document", INDEX; values "document" or "qualification" |
| description | Text | NULL |
| created_at | DateTime | default UTC now |

## program_requirements

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| program_id | Integer | FK -> programs.id, NOT NULL |
| requirement_id | Integer | FK -> requirements.id, NOT NULL |
| is_mandatory | Boolean | default True |
| is_completed | Boolean | default True |
| document_status | String(20) | NOT NULL, default "pending" |
| copy_type | Text | JSON text, default [{"type":"original","count":1}] |
| created_at | DateTime | default UTC now |

## announcements

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| announcement_title | String(200) | NOT NULL |
| announcement_content | Text | NOT NULL |
| category | String(100) | NOT NULL, default "General" |
| status | String(50) | NOT NULL, default "draft" |
| author_id | Integer | FK -> users.id |
| program_id | Integer | FK -> programs.id |
| attachment_url | String(500) | NULL |
| created_at | DateTime | default UTC now, INDEX |
| updated_at | DateTime | default UTC now |

## announcement_images

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| announcement_id | Integer | FK -> announcements.id, NOT NULL |
| image_path | String(255) | NOT NULL |
| caption | String(255) | NULL |
| display_order | Integer | default 0 |
| created_at | DateTime | default UTC now |

## subsidy_payouts

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| payout_id | String(50) | NOT NULL, UNIQUE, INDEX |
| payout_datetime | DateTime | NOT NULL, INDEX |
| payout_location | String(255) | NOT NULL |
| payout_notes | Text | NULL |
| category_key | String(50) | NOT NULL, INDEX |
| category_label | String(100) | NOT NULL |
| beneficiary_count | Integer | NOT NULL, default 0 |
| beneficiary_snapshot | Text | NOT NULL, JSON text |
| beneficiary_list_text | Text | NULL |
| beneficiary_list_html | Text | NULL |
| suggested_title | String(255) | NULL |
| suggested_content | Text | NULL |
| status | String(20) | NOT NULL, default "draft", INDEX; values like "draft", "saved", "announced" |
| saved_in_system | Boolean | NOT NULL, default False |
| saved_at | DateTime | NULL |
| announcement_id | Integer | FK -> announcements.id |
| scheduled_by | Integer | FK -> users.id, NOT NULL, INDEX |
| created_at | DateTime | default UTC now |
| updated_at | DateTime | default UTC now |

## applications

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| user_id | Integer | FK -> users.id, NOT NULL, INDEX |
| program_id | Integer | FK -> programs.id, NOT NULL, INDEX |
| application_status | String(20) | NOT NULL, default "pending", INDEX; values include "pending", "approved", "rejected", "active", "completed" |
| document_upload_status | String(20) | default "pending", INDEX; values include "pending", "uploaded", "verified", "rejected" |
| application_date | DateTime | default UTC now, INDEX |
| review_date | DateTime | INDEX |
| reviewed_by | Integer | FK -> users.id |
| submission_deadline | DateTime | INDEX |
| claim_date | DateTime | INDEX |
| claim_time | String(10) | NULL |
| claim_location | String(255) | NULL |
| claim_instructions | Text | NULL |
| claim_status | String(20) | default "not_scheduled", INDEX; values include "not_scheduled", "scheduled", "claimed", "missed" |
| claim_scheduled_by | Integer | FK -> users.id |
| claim_scheduled_at | DateTime | NULL |
| verification_code | String(20) | UNIQUE, INDEX |
| code_generated_at | DateTime | NULL |
| code_used_at | DateTime | NULL |
| documents_submitted_at | DateTime | NULL |
| cancellation_requested | Boolean | default False, INDEX |
| cancellation_reason | Text | NULL |
| cancellation_requested_at | DateTime | NULL |
| cancellation_status | String(20) | values include "pending", "approved", "rejected" |
| cancellation_reviewed_by | Integer | FK -> users.id |
| cancellation_reviewed_at | DateTime | NULL |
| cancellation_admin_notes | Text | NULL |
| remarks | Text | NULL |
| created_at | DateTime | default UTC now |
| updated_at | DateTime | default UTC now |

Indexes: idx_app_user_date (user_id, application_date), idx_app_program_status (program_id, application_status)

## application_documents

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| application_id | Integer | FK -> applications.id, NOT NULL |
| requirement_id | Integer | FK -> requirements.id, NOT NULL |
| submission_status | String(20) | default "pending"; values include "not_submitted", "submitted", "pending", "approved", "rejected", "returned" |
| qualification_met | Boolean | default False |
| verified_by | Integer | FK -> users.id |
| verified_at | DateTime | NULL |
| admin_feedback | Text | NULL |
| notes | Text | NULL |
| created_at | DateTime | default UTC now |
| updated_at | DateTime | default UTC now |

## application_document_uploads

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| application_id | Integer | FK -> applications.id, NOT NULL, INDEX |
| requirement_id | Integer | FK -> requirements.id, NOT NULL |
| file_path | String(255) | NOT NULL |
| original_filename | String(255) | NOT NULL |
| file_size | Integer | NULL |
| file_type | String(100) | NULL |
| verification_status | String(20) | default "pending", INDEX; values include "pending", "approved", "rejected" |
| admin_feedback | Text | NULL |
| verified_by | Integer | FK -> users.id |
| verified_at | DateTime | NULL |
| uploaded_at | DateTime | default UTC now |
| updated_at | DateTime | default UTC now |

## file_attachment

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| filename | String(255) | NOT NULL |
| file_path | String(255) | NOT NULL |
| file_size | Integer | NULL |
| file_type | String(100) | NULL |
| uploaded_by_id | Integer | FK -> users.id |
| uploaded_at | DateTime | default UTC now |
| attachment_type | String(50) | NULL |

## notifications

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| user_id | Integer | FK -> users.id, NOT NULL |
| notif_title | String(255) | NOT NULL |
| notif_message | Text | NOT NULL |
| is_read | Boolean | default False, INDEX |
| related_id | Integer | NULL |
| related_type | String(50) | NULL |
| created_at | DateTime | default UTC now |

## municipalities

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| name | String(100) | NOT NULL, UNIQUE, INDEX |
| created_at | DateTime | default UTC now |
| updated_at | DateTime | default UTC now |

## community_users

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| user_id | Integer | FK -> users.id, NOT NULL, INDEX |
| age | Integer | NOT NULL, INDEX |
| gender | String(20) | NULL |
| mobile_no | String(20) | NULL |
| birth_month | Integer | NULL |
| birth_day | Integer | NULL |
| birth_year | Integer | NULL |
| barangay | String(100) | INDEX |
| sitio | String(100) | NULL |
| address | Text | NULL |
| municipality | String(100) | default "Mabitac" |
| religion | String(100) | NULL |
| place_of_birth | String(200) | NULL |
| civil_status | String(50) | NULL |
| highest_education_attainment | String(100) | NULL |
| is_currently_employed | Boolean | default False, INDEX |
| occupation | String(100) | NULL |
| occupation_sector | String(100) | NULL |
| is_student | Boolean | default False, INDEX |
| is_solo_parent | Boolean | default False, INDEX |
| is_pwd | Boolean | default False, INDEX |
| disability_type | String(100) | NULL |
| family_annual_income | Numeric(12,2) | INDEX |
| income_category | String(50) | INDEX; e.g. "Indigent Families", "Low Income Families" |
| created_at | DateTime | default UTC now |
| senior_citizen_verification | String(20) | default "none", INDEX |
| senior_citizen_id_number | String(50) | NULL |
| senior_citizen_verified_at | DateTime | NULL |
| senior_citizen_verified_by | Integer | FK -> users.id |
| senior_citizen_document_path | String(255) | NULL |
| senior_citizen_rejection_reason | Text | NULL |
| pwd_verification | String(20) | default "none", INDEX |
| pwd_id_number | String(50) | NULL |
| pwd_verified_at | DateTime | NULL |
| pwd_verified_by | Integer | FK -> users.id |
| pwd_document_path | String(255) | NULL |
| pwd_rejection_reason | Text | NULL |
| solo_parent_verification | String(20) | default "none", INDEX |
| solo_parent_id_number | String(50) | NULL |
| solo_parent_verified_at | DateTime | NULL |
| solo_parent_verified_by | Integer | FK -> users.id |
| solo_parent_document_path | String(255) | NULL |
| solo_parent_rejection_reason | Text | NULL |
| areas_of_concern | Text | JSON text list |

## admin_users

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| user_id | Integer | FK -> users.id, NOT NULL |
| municipality | String(100) | INDEX |
| created_at | DateTime | default UTC now |

## shelter_photos

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| application_id | Integer | FK -> applications.id, NOT NULL |
| photo_path | String(255) | NOT NULL |
| caption | String(255) | NULL |
| uploaded_at | DateTime | default UTC now |
| verified_by | Integer | FK -> users.id |
| verified_at | DateTime | NULL |
| verification_status | String(20) | default "pending" |
| admin_notes | Text | NULL |

## cal_documents

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| application_id | Integer | FK -> applications.id, NOT NULL |
| document_type | String(50) | NOT NULL; values "certificate" or "proposal" |
| file_path | String(255) | NOT NULL |
| original_filename | String(255) | NULL |
| description | Text | NULL |
| uploaded_at | DateTime | default UTC now |
| verified_by | Integer | FK -> users.id |
| verified_at | DateTime | NULL |
| verification_status | String(20) | default "pending" |
| admin_notes | Text | NULL |

## admin_activity_logs

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| admin_id | Integer | FK -> users.id, NOT NULL, INDEX |
| action | String(50) | NOT NULL, INDEX |
| action_type | String(20) | NOT NULL, default "update", INDEX |
| entity_type | String(50) | NOT NULL, INDEX |
| entity_id | Integer | NULL |
| description | Text | NOT NULL |
| details | Text | JSON text |
| ip_address | String(45) | NULL |
| created_at | DateTime | default UTC now, INDEX |

Indexes: idx_activity_admin_date (admin_id, created_at), idx_activity_entity (entity_type, entity_id)

## user_activity_logs

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| user_id | Integer | FK -> users.id, NOT NULL, INDEX |
| action | String(50) | NOT NULL, INDEX |
| action_type | String(20) | NOT NULL, default "view", INDEX |
| entity_type | String(50) | NOT NULL, INDEX |
| entity_id | Integer | NULL |
| description | Text | NOT NULL |
| details | Text | JSON text |
| ip_address | String(45) | NULL |
| created_at | DateTime | default UTC now, INDEX |

Indexes: idx_user_activity_user_date (user_id, created_at), idx_user_activity_entity (entity_type, entity_id)

## saved_programs

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| user_id | Integer | FK -> users.id, NOT NULL |
| program_id | Integer | FK -> programs.id, NOT NULL |
| created_at | DateTime | default UTC now |

Constraint: UNIQUE (user_id, program_id)

## hidden_programs

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| user_id | Integer | FK -> users.id, NOT NULL |
| program_id | Integer | FK -> programs.id, NOT NULL |
| created_at | DateTime | default UTC now |

Constraint: UNIQUE (user_id, program_id)

## application_workflow_status

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| application_id | Integer | FK -> applications.id, NOT NULL |
| workflow_step_id | Integer | FK -> program_workflow_steps.id, NOT NULL |
| step_status | String(20) | NOT NULL, default "not_started"; values include "not_started", "in_progress", "pending_review", "approved", "rejected", "completed" |
| started_at | DateTime | NULL |
| completed_at | DateTime | NULL |
| reviewed_at | DateTime | NULL |
| reviewed_by | Integer | FK -> users.id |
| admin_feedback | Text | NULL |
| step_data | Text | JSON text |
| created_at | DateTime | default UTC now |
| updated_at | DateTime | default UTC now |

Constraints: UNIQUE (application_id, workflow_step_id)
Index: idx_workflow_status (application_id, step_status)

## assessments

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| application_id | Integer | FK -> applications.id, NOT NULL, INDEX |
| assessment_type | String(50) | NOT NULL, INDEX; values like "interview", "home_visit" |
| title | String(255) | NOT NULL |
| description | Text | NULL |
| scheduled_date | DateTime | INDEX |
| scheduled_time | String(10) | NULL |
| location | String(255) | NULL |
| status | String(20) | NOT NULL, default "scheduled", INDEX; values like "scheduled", "completed", "cancelled" |
| findings | Text | NULL |
| problems_identified | Text | NULL |
| recommendations | Text | NULL |
| case_severity | String(20) | NOT NULL, default "unrated", INDEX |
| severity_score | Integer | INDEX |
| severity_factors | Text | JSON text |
| severity_justification | Text | NULL |
| severity_updated_by | Integer | FK -> users.id |
| severity_updated_at | DateTime | NULL |
| conducted_by | Integer | FK -> users.id, NOT NULL |
| completed_at | DateTime | NULL |
| created_at | DateTime | default UTC now |
| updated_at | DateTime | default UTC now |

## assessment_documents

| Column | Type | Constraints / Notes |
| --- | --- | --- |
| id | Integer | PK |
| assessment_id | Integer | FK -> assessments.id, NOT NULL, INDEX |
| file_path | String(255) | NOT NULL |
| original_filename | String(255) | NOT NULL |
| file_size | Integer | NULL |
| file_type | String(100) | NULL |
| description | Text | NULL |
| uploaded_by | Integer | FK -> users.id, NOT NULL |
| uploaded_at | DateTime | default UTC now |
