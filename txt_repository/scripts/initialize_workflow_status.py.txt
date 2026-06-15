"""
Initialize workflow status for existing applications that don't have it.
"""
from app import create_app, db
from app.models import Applications, ProgramWorkflowSteps, ApplicationWorkflowStatus

app = create_app()

with app.app_context():
    applications = Applications.query.all()
    initialized_count = 0
    skipped_count = 0
    
    for app_obj in applications:
        if not app_obj.program.workflow_steps:
            continue
        
        existing_statuses = ApplicationWorkflowStatus.query.filter_by(
            application_id=app_obj.id
        ).count()
        
        if existing_statuses == 0:
            print(f"\n[*] Initializing workflow for Application #{app_obj.id} ({app_obj.program.program_name})")
            
            workflow_steps = sorted(app_obj.program.workflow_steps, key=lambda x: x.step_order)
            
            for step in workflow_steps:
                # Determine initial status based on application status and step type
                if app_obj.application_status == 'pending':
                    initial_status = 'not_started'
                elif app_obj.application_status == 'approved':
                    # Approval steps should be marked as approved
                    if step.step_type == 'approval' and step.is_pre_approval:
                        initial_status = 'approved'
                    else:
                        initial_status = 'not_started'
                elif app_obj.application_status == 'active':
                    # Only the first document step should be in progress
                    if step.step_type == 'document_upload':
                        initial_status = 'in_progress'
                    elif step.step_type in ['document_submission', 'physical_submission']:
                        # These come after document_upload, so leave them as not_started
                        initial_status = 'not_started'
                    elif step.step_type in ['approval', 'photo_upload'] and step.is_pre_approval:
                        initial_status = 'approved'
                    else:
                        initial_status = 'not_started'
                else:  # completed or rejected
                    initial_status = 'not_started'
                
                status = ApplicationWorkflowStatus(
                    application_id=app_obj.id,
                    workflow_step_id=step.id,
                    step_status=initial_status
                )
                db.session.add(status)
                print(f"   [+] {step.step_name}: {initial_status}")
            
            db.session.commit()
            initialized_count += 1
        else:
            skipped_count += 1
    
    print(f"\n[SUCCESS] Summary:")
    print(f"   Initialized: {initialized_count} applications")
    print(f"   Skipped (already have status): {skipped_count} applications")
    print(f"   Total applications processed: {len(applications)}")
