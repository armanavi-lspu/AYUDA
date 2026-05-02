from flask import Blueprint, abort, send_file, request
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import os

from app.models import (
    User,
    CommunityUsers,
    ShelterPhotos,
    CALDocuments,
    AnnouncementImages,
    FileAttachment,
    AssessmentDocument,
    Applications,
)
from app.utils import resolve_upload_path

files_bp = Blueprint('files', __name__, url_prefix='/files')


def _is_admin(user):
    return user.is_authenticated and user.role in {'admin', 'super_admin'}


def _send_upload(path, download_name=None, as_attachment=False):
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(
        path,
        as_attachment=as_attachment,
        download_name=download_name or os.path.basename(path),
    )


@files_bp.route('/profile-pic/<int:user_id>')
@login_required
def profile_pic(user_id):
    user = User.query.get_or_404(user_id)
    if not _is_admin(current_user) and current_user.id != user_id:
        abort(403)

    if not user.profile_pic:
        abort(404)

    path = resolve_upload_path(user.profile_pic)
    return _send_upload(path)


@files_bp.route('/verification/<verification_type>/<int:user_id>')
@login_required
def verification_document(verification_type, user_id):
    allowed_types = {
        'senior_citizen': 'senior_citizen_document_path',
        'pwd': 'pwd_document_path',
        'solo_parent': 'solo_parent_document_path',
    }
    field_name = allowed_types.get(verification_type)
    if not field_name:
        abort(404)

    if not _is_admin(current_user) and current_user.id != user_id:
        abort(403)

    profile = CommunityUsers.query.filter_by(user_id=user_id).first_or_404()
    raw_path = getattr(profile, field_name)
    if not raw_path:
        abort(404)

    path = resolve_upload_path(raw_path)
    return _send_upload(path)


@files_bp.route('/shelter-photo/<int:photo_id>')
@login_required
def shelter_photo(photo_id):
    photo = ShelterPhotos.query.get_or_404(photo_id)
    if not _is_admin(current_user) and photo.application.user_id != current_user.id:
        abort(403)

    path = resolve_upload_path(photo.photo_path)
    return _send_upload(path)


@files_bp.route('/ca-document/<int:doc_id>')
@login_required
def ca_document(doc_id):
    doc = CALDocuments.query.get_or_404(doc_id)
    application = Applications.query.get(doc.application_id)
    if not application:
        abort(404)
    if not _is_admin(current_user) and application.user_id != current_user.id:
        abort(403)

    path = resolve_upload_path(doc.file_path)
    return _send_upload(path)


@files_bp.route('/announcement-image/<int:image_id>')
@login_required
def announcement_image(image_id):
    image = AnnouncementImages.query.get_or_404(image_id)
    path = resolve_upload_path(image.image_path)
    return _send_upload(path)


@files_bp.route('/program-attachment/<int:attachment_id>')
@login_required
def program_attachment(attachment_id):
    attachment = FileAttachment.query.get_or_404(attachment_id)
    path = resolve_upload_path(attachment.file_path)
    as_attachment = request.args.get('download') == '1'
    return _send_upload(path, download_name=attachment.filename, as_attachment=as_attachment)


@files_bp.route('/assessment-document/<int:document_id>')
@login_required
def assessment_document(document_id):
    if not _is_admin(current_user):
        abort(403)

    doc = AssessmentDocument.query.get_or_404(document_id)
    path = resolve_upload_path(doc.file_path)
    as_attachment = request.args.get('download') == '1'
    return _send_upload(path, download_name=doc.original_filename, as_attachment=as_attachment)


@files_bp.route('/beneficiaries-list/<path:filename>')
@login_required
def beneficiaries_list(filename):
    if not _is_admin(current_user):
        abort(403)

    safe_name = secure_filename(os.path.basename(filename))
    if not safe_name:
        abort(404)

    path = resolve_upload_path(os.path.join('beneficiaries_lists', safe_name))
    return _send_upload(path)
