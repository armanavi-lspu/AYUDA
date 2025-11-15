from flask import render_template, jsonify, redirect, url_for, request, flash, send_file
from flask_login import login_required, current_user
from datetime import datetime
from app.admin import admin_bp
from app.utils import role_required
from app.models import Programs, Requirements, ProgramRequirements, Applications, ApplicationDocuments, Notifications
from app.extensions import db


@admin_bp.route('/applications')
@login_required
@role_required('admin')
def applications():
    return render_template('admin/applications.html', user=current_user)


@admin_bp.route('/applications/<int:application_id>/documents/<int:doc_id>/update', methods=['POST'])
@login_required
@role_required('admin')
def admin_update_document(application_id, doc_id):
    data = request.json or {}
    new_status = data.get('status')  # 'submitted', 'approved', 'rejected'
    notes = data.get('notes')

    app_doc = ApplicationDocuments.query.filter_by(id=doc_id, application_id=application_id).first_or_404()
    app_doc.submission_status = new_status
    app_doc.admin_feedback = notes
    app_doc.verified_by = current_user.id
    app_doc.verified_at = datetime.utcnow()
    db.session.commit()

    # update overall application status if all mandatory docs submitted/approved (example)
    # ...business logic...

    # notify applicant
    notif = Notifications(
        user_id=app_doc.application.user_id,
        notif_title='Document Status Updated',
        notif_message=f'Document {app_doc.requirement.document_name} marked {new_status} for application {application_id}.',
        is_read=False,
        created_at=datetime.utcnow()
    )
    db.session.add(notif)
    db.session.commit()

    return jsonify(success=True, status=new_status)