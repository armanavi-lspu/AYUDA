"""
Fix workflow status for already-approved applications.
"""
from app import create_app, db
from app.models import Applications, ApplicationWorkflowStatus

app = create_app()

with app.app_context():
    fixed_count = 0
    
    for app_obj in Applications.query.all():
        if app_obj.application_status == 'approved' or app_obj.application_status == 'active':
            statuses = ApplicationWorkflowStatus.query.filter_by(
                application_id=app_obj.id
            ).all()
            
            for status in statuses:
                step = status.workflow_step
                
                # For approved/active applications, mark pre-approval steps as approved
                if step.is_pre_approval and step.step_type in ['approval', 'photo_upload']:
                    if status.step_status == 'not_started':
                        status.step_status = 'approved'
                        fixed_count += 1
                        print(f"[FIXED] App #{app_obj.id}: {step.step_name} -> approved")
                
                # For active applications, mark only document_upload as in_progress
                if app_obj.application_status == 'active' and step.step_type == 'document_upload':
                    if status.step_status == 'not_started':
                        status.step_status = 'in_progress'
                        fixed_count += 1
                        print(f"[FIXED] App #{app_obj.id}: {step.step_name} -> in_progress")
                
                # Physical submission steps stay not_started until document_upload is completed
                if app_obj.application_status == 'active' and step.step_type in ['document_submission', 'physical_submission']:
                    if status.step_status == 'not_started':
                        status.step_status = 'not_started'  # Keep waiting for document upload to complete
    
    db.session.commit()
    print(f"\n[SUCCESS] Fixed {fixed_count} workflow status records")
