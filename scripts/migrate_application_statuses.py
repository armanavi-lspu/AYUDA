"""
Migration script to update application_status values in the database.

New status types:
  - 'pending'    : Application submitted, not yet approved by admin (approval step type)
  - 'approved'   : Approved by admin, but not yet opened/recognized by the user
  - 'rejected'   : Not approved by admin or system
  - 'active'     : Approved and opened/recognized by the user (auto-transitions when user views the application)
  - 'completed'  : A schedule/claim has been given to the user (ready for release/claiming)

Old statuses being migrated:
  - 'on-hold' / 'on_hold' → 'rejected' (with remark added)
  - 'under_review'         → 'pending'
  - 'submitted'            → 'pending'

Run this script from the project root:
    python scripts/migrate_application_statuses.py
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.extensions import db
from app.models import Applications
from datetime import datetime


def migrate_statuses():
    """Migrate old application statuses to new status types."""
    with app.app_context():
        print("=" * 60)
        print("APPLICATION STATUS MIGRATION")
        print("=" * 60)

        # 1. Show current status distribution
        print("\n📊 Current status distribution:")
        statuses = db.session.query(
            Applications.application_status,
            db.func.count(Applications.id)
        ).group_by(Applications.application_status).all()

        for status, count in statuses:
            print(f"   {status}: {count}")

        # 2. Migrate 'on-hold' → 'rejected'
        on_hold_hyphen = Applications.query.filter_by(application_status='on-hold').all()
        on_hold_underscore = Applications.query.filter_by(application_status='on_hold').all()
        on_hold_apps = on_hold_hyphen + on_hold_underscore

        if on_hold_apps:
            print(f"\n🔄 Migrating {len(on_hold_apps)} 'on-hold'/'on_hold' → 'rejected'...")
            for app_obj in on_hold_apps:
                app_obj.application_status = 'rejected'
                if not app_obj.remarks:
                    app_obj.remarks = 'Status migrated from on-hold to rejected.'
                else:
                    app_obj.remarks += ' [Status migrated from on-hold to rejected]'
                app_obj.updated_at = datetime.utcnow()
            print(f"   ✅ Done")
        else:
            print("\n✅ No 'on-hold'/'on_hold' applications to migrate")

        # 3. Migrate 'under_review' → 'pending'
        under_review_apps = Applications.query.filter_by(application_status='under_review').all()
        if under_review_apps:
            print(f"\n🔄 Migrating {len(under_review_apps)} 'under_review' → 'pending'...")
            for app_obj in under_review_apps:
                app_obj.application_status = 'pending'
                app_obj.updated_at = datetime.utcnow()
            print(f"   ✅ Done")
        else:
            print("\n✅ No 'under_review' applications to migrate")

        # 4. Migrate 'submitted' → 'pending'
        submitted_apps = Applications.query.filter_by(application_status='submitted').all()
        if submitted_apps:
            print(f"\n🔄 Migrating {len(submitted_apps)} 'submitted' → 'pending'...")
            for app_obj in submitted_apps:
                app_obj.application_status = 'pending'
                app_obj.updated_at = datetime.utcnow()
            print(f"   ✅ Done")
        else:
            print("\n✅ No 'submitted' applications to migrate")

        # 5. Migrate approved applications that have document processing in progress → 'active'
        approved_apps = Applications.query.filter_by(application_status='approved').all()
        migrated_to_active = 0
        if approved_apps:
            print(f"\n🔄 Checking {len(approved_apps)} 'approved' applications for active processing...")
            for app_obj in approved_apps:
                # If the application has documents being processed (uploaded but not all verified)
                # or has a submission deadline set, it should be 'active'
                has_uploads = app_obj.document_upload_status in ['uploaded', 'pending']
                has_deadline = app_obj.submission_deadline is not None
                completion = app_obj.completion_percentage if hasattr(app_obj, 'completion_percentage') else 0

                if (has_uploads and has_deadline) or (has_deadline and completion > 0 and completion < 100):
                    app_obj.application_status = 'active'
                    app_obj.updated_at = datetime.utcnow()
                    migrated_to_active += 1

            if migrated_to_active:
                print(f"   ✅ Migrated {migrated_to_active} approved applications to 'active' (had document processing in progress)")
            else:
                print(f"   ✅ No approved applications needed migration to 'active'")

        # Commit all changes
        db.session.commit()

        # 6. Show new status distribution
        print("\n📊 New status distribution:")
        statuses = db.session.query(
            Applications.application_status,
            db.func.count(Applications.id)
        ).group_by(Applications.application_status).all()

        for status, count in statuses:
            print(f"   {status}: {count}")

        print("\n✅ Migration complete!")
        print("=" * 60)


if __name__ == '__main__':
    migrate_statuses()
