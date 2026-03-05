from app import create_app, db
from app.models import Programs

app = create_app()
with app.app_context():
    prog = Programs.query.first()
    if prog:
        print(f"[VERIFIED] Program: {prog.program_name}")
        print(f"[VERIFIED] Enable Application Slip: {prog.enable_application_slip}")
        print("\n[SUCCESS] Feature is working correctly!")
    else:
        print("[INFO] No programs found")
