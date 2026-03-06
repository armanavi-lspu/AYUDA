"""
Add default workflow steps to programs that don't have any.
This fixes the workflow progression issue for community users.
"""
from app import create_app, db
from app.models import Programs, ProgramWorkflowSteps

app = create_app()

with app.app_context():
    programs = Programs.query.all()
    
    for prog in programs:
        workflow_count = len(prog.workflow_steps) if prog.workflow_steps else 0
        
        if workflow_count == 0:
            print(f"\n🔧 Adding default workflow steps to: {prog.program_name} ({prog.program_type})")
            
            if prog.program_type == 'ESA':
                default_steps = [
                    {
                        'step_order': 1,
                        'step_name': 'Upload Shelter Photos',
                        'step_description': 'Upload at least 3 photos of your current shelter/housing situation',
                        'step_type': 'photo_upload',
                        'is_pre_approval': True,
                        'requires_verification': True,
                        'allowed_file_types': 'jpg,jpeg,png,gif'
                    },
                    {
                        'step_order': 2,
                        'step_name': 'Submit Required Documents',
                        'step_description': 'Submit all required documents at MSWD Office',
                        'step_type': 'document_submission',
                        'is_pre_approval': False,
                        'requires_verification': True,
                        'allowed_file_types': None
                    },
                    {
                        'step_order': 3,
                        'step_name': 'Schedule Release',
                        'step_description': 'Schedule your assistance release date',
                        'step_type': 'scheduling',
                        'is_pre_approval': False,
                        'requires_verification': False,
                        'allowed_file_types': None
                    }
                ]
            else:
                # Default for AICS, CA, and others
                default_steps = [
                    {
                        'step_order': 1,
                        'step_name': 'Application Review',
                        'step_description': 'Wait for admin to review and approve your application',
                        'step_type': 'approval',
                        'is_pre_approval': True,
                        'requires_verification': False,
                        'allowed_file_types': None
                    },
                    {
                        'step_order': 2,
                        'step_name': 'Submit Required Documents',
                        'step_description': 'Submit all required documents at MSWD Office',
                        'step_type': 'document_submission',
                        'is_pre_approval': False,
                        'requires_verification': True,
                        'allowed_file_types': None
                    },
                    {
                        'step_order': 3,
                        'step_name': 'Schedule Release',
                        'step_description': 'Schedule your assistance release date',
                        'step_type': 'scheduling',
                        'is_pre_approval': False,
                        'requires_verification': False,
                        'allowed_file_types': None
                    }
                ]
            
            # Add all default steps
            for step_data in default_steps:
                step = ProgramWorkflowSteps(
                    program_id=prog.id,
                    step_order=step_data['step_order'],
                    step_name=step_data['step_name'],
                    step_description=step_data['step_description'],
                    step_type=step_data['step_type'],
                    is_pre_approval=step_data['is_pre_approval'],
                    requires_verification=step_data['requires_verification'],
                    allowed_file_types=step_data['allowed_file_types']
                )
                db.session.add(step)
                print(f"   ✓ Added: {step.step_name}")
            
            db.session.commit()
            print(f"   ✅ Workflow steps created successfully")
        else:
            print(f"✅ {prog.program_name} ({prog.program_type}): Already has {workflow_count} steps")
    
    print("\n🎉 All programs now have workflow steps configured!")
    print("\nVerifying...")
    programs = Programs.query.all()
    for prog in programs:
        workflow_count = len(prog.workflow_steps) if prog.workflow_steps else 0
        print(f"   {prog.program_name}: {workflow_count} steps")
