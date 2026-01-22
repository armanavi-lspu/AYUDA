from flask import render_template, request, flash, redirect, url_for, send_file, current_app
from flask_login import login_required, current_user
from datetime import datetime
from app.community import community_bp
from app.utils import role_required
from app.models import Applications, Programs, ApplicationDocuments, ProgramRequirements, Requirements, ApplicationDocumentUploads, Notifications, User
from app.extensions import db
from sqlalchemy import desc, or_
from werkzeug.utils import secure_filename
from PIL import Image
import os

@community_bp.route('/applications')
@login_required
@role_required('community')
def applications():
    """Display all applications submitted by the current user"""
    page = request.args.get('page', 1, type=int)
    per_page = 10
    status_filter = request.args.get('status', 'all')
    
    # Base query for user's applications
    query = Applications.query.filter_by(user_id=current_user.id)
    
    # Apply status filter
    if status_filter != 'all':
        if status_filter == 'pending':
            query = query.filter(Applications.application_status.in_(['pending']))
        elif status_filter == 'returned':
            query = query.filter(or_(
                Applications.application_status == 'rejected',
                Applications.remarks.isnot(None)
            ))  
        elif status_filter == 'on-hold':
            query = query.filter(Applications.application_status.in_(['on-hold']))
        else:
            query = query.filter_by(application_status=status_filter)
    
    query = query.order_by(desc(Applications.application_date))
    
    applications_paginated = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    # Calculate simplified statistics
    total_applications = Applications.query.filter_by(user_id=current_user.id)
    
    stats = {
        'total': total_applications.count(),
        'pending': total_applications.filter(
            Applications.application_status.in_(['pending'])
        ).count(),
        'returned': total_applications.filter(or_(
            Applications.application_status == 'rejected',
            Applications.remarks.isnot(None)
        )).count(),
        'approved': total_applications.filter_by(application_status='approved').count()
    }
    
    return render_template(
        'community/applications.html',
        applications=applications_paginated.items,
        pagination=applications_paginated,
        stats=stats,
        current_filter=status_filter,
        user=current_user
    )

@community_bp.route('/applications/<int:application_id>')
@login_required
@role_required('community')
def application_detail(application_id):
    """Display detailed information about a specific application"""
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    # Get all requirements with their details
    all_requirements = db.session.query(
        ApplicationDocuments,
        ProgramRequirements.is_mandatory,
        Requirements.requirement_name,
        Requirements.description,
        Requirements.requirement_type
    ).join(
        Requirements,
        ApplicationDocuments.requirement_id == Requirements.id
    ).join(
        ProgramRequirements,
        (ApplicationDocuments.requirement_id == ProgramRequirements.requirement_id) &
        (ProgramRequirements.program_id == application.program_id)
    ).filter(
        ApplicationDocuments.application_id == application_id
    ).all()
    
    # Separate documents and qualifications
    document_requirements = []
    qualification_requirements = []
    
    for doc, is_mandatory, req_name, description, req_type in all_requirements:
        if req_type == 'document':
            document_requirements.append((doc, is_mandatory, req_name, description))
        elif req_type == 'qualification':
            qualification_requirements.append((doc, is_mandatory, req_name, description))
    
    return render_template(
        'community/application_details.html',
        application=application,
        document_requirements=document_requirements,
        qualification_requirements=qualification_requirements,
        datetime=datetime,
        user=current_user,
        today=datetime.utcnow().date()
    )


@community_bp.route('/documents/<int:doc_id>/download')
@login_required
def download_document(doc_id):
    """Download or view a document file"""
    # Get the document
    document = ApplicationDocuments.query.get_or_404(doc_id)
    
    # Security check: ensure user owns the application or is an admin
    if current_user.role != 'admin':
        if document.application.user_id != current_user.id:
            flash('You do not have permission to view this document.', 'danger')
            return redirect(url_for('community.applications'))
    
    # Check if file exists
    if not document.file_path or not os.path.exists(document.file_path):
        flash('Document file not found.', 'danger')
        return redirect(request.referrer or url_for('community.applications'))
    
    try:
        # Send file for download/view
        return send_file(
            document.file_path,
            as_attachment=False,  # False = view in browser, True = force download
            download_name=os.path.basename(document.file_path)
        )
    except Exception as e:
        flash(f'Error accessing document: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('community.applications'))

@community_bp.route('/applications/<int:application_id>/slip')
@login_required
@role_required('community')
def application_slip(application_id):
    """Application slip viewing is disabled for community users"""    
    flash('Application slips can only be obtained from the MSWD Office. Please submit your documents to receive your application slip with verification code.', 'info')
    return redirect(url_for('community.application_detail', application_id=application_id))


@community_bp.route('/verify-code', methods=['GET', 'POST'])
@login_required
@role_required('community')
def verify_code():
    """Verify application code from physical slip"""
    if request.method == 'POST':
        code = request.form.get('verification_code', '').strip().upper()
        
        if not code:
            flash('Please enter a verification code.', 'warning')
            return render_template('community/verify_code.html', user=current_user)
        
        # Find application by verification code
        application = Applications.query.filter_by(
            verification_code=code,
            user_id=current_user.id
        ).first()
        
        if not application:
            flash('Invalid verification code or the code does not belong to your account.', 'danger')
            return render_template('community/verify_code.html', user=current_user)
        
        # Check if code has already been used
        if application.code_used_at:
            flash(f'This verification code has already been used on {application.code_used_at.strftime("%B %d, %Y at %I:%M %p")}.', 'warning')
            return redirect(url_for('community.application_detail', application_id=application.id))
        
        # Mark code as used and update application status
        try:
            application.code_used_at = datetime.utcnow()
            application.documents_submitted_at = datetime.utcnow()
            
            # Update all document statuses to pending for review
            for doc in application.document_checklist:
                if doc.submission_status in ['not_submitted', 'returned']:
                    doc.submission_status = 'pending'
                    doc.submitted_at = datetime.utcnow()
            
            db.session.commit()
            
            flash(f'Verification successful! Your documents for {application.program.program_name} are now marked as submitted and pending review.', 'success')
            return redirect(url_for('community.application_detail', application_id=application.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error processing verification: {str(e)}', 'danger')
            return render_template('community/verify_code.html', user=current_user)
    
    return render_template('community/verify_code.html', user=current_user)

@community_bp.route('/applications/<int:application_id>/cancel', methods=['POST'])
@login_required
@role_required('community')
def cancel_application(application_id):
    """Cancel and completely delete an application with all associated data"""
    try:
        # Get the application and verify user owns it
        application = Applications.query.filter_by(
            id=application_id,
            user_id=current_user.id
        ).first_or_404()
        
        program_name = application.program.program_name
        
        # Delete all application documents and their files
        app_docs = ApplicationDocuments.query.filter_by(application_id=application_id).all()
        for doc in app_docs:
            if doc.file_path and os.path.exists(doc.file_path):
                try:
                    os.remove(doc.file_path)
                except:
                    pass
            db.session.delete(doc)
        
        # Delete all shelter photos and their files
        if application.shelter_photos:
            for photo in application.shelter_photos:
                if photo.photo_path and os.path.exists(photo.photo_path):
                    try:
                        os.remove(photo.photo_path)
                    except:
                        pass
                db.session.delete(photo)
        
        # Delete the application itself
        db.session.delete(application)
        db.session.commit()
        
        flash(f'Your application for {program_name} has been cancelled and permanently deleted.', 'success')
        return redirect(url_for('community.applications'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error cancelling application: {str(e)}', 'danger')
        return redirect(url_for('community.application_detail', application_id=application_id))


@community_bp.route('/applications/<int:application_id>/upload-documents')
@login_required
@role_required('community')
def upload_documents(application_id):
    """Display document upload page for an application"""
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    # Get document requirements for this program (exclude qualifications)
    program_requirements = db.session.query(
        Requirements,
        ProgramRequirements.is_mandatory
    ).join(
        ProgramRequirements,
        Requirements.id == ProgramRequirements.requirement_id
    ).filter(
        ProgramRequirements.program_id == application.program_id,
        Requirements.requirement_type == 'document'
    ).all()
    
    # Get existing uploads
    existing_uploads = {
        upload.requirement_id: upload 
        for upload in ApplicationDocumentUploads.query.filter_by(
            application_id=application_id
        ).all()
    }
    
    # Prepare document requirements data
    document_requirements = []
    mandatory_count = 0
    uploaded_count = 0
    
    for req, is_mandatory in program_requirements:
        has_upload = req.id in existing_uploads
        if has_upload:
            uploaded_count += 1
        if is_mandatory:
            mandatory_count += 1
            
        document_requirements.append({
            'id': req.id,
            'requirement_name': req.requirement_name,
            'description': req.description,
            'is_mandatory': is_mandatory,
            'has_upload': has_upload,
            'upload': existing_uploads.get(req.id)
        })
    
    total_documents = len(document_requirements)
    upload_progress = round((uploaded_count / total_documents * 100)) if total_documents > 0 else 0
    
    return render_template('community/upload_documents.html',
                         application=application,
                         document_requirements=document_requirements,
                         mandatory_count=mandatory_count,
                         uploaded_count=uploaded_count,
                         total_documents=total_documents,
                         upload_progress=upload_progress)


def validate_and_process_image(file_path, max_size_mb=5):
    """
    Validate and optimize image files using Pillow
    Returns: (success, message, image_info)
    """
    try:
        # Open and validate the image
        with Image.open(file_path) as img:
            # Get original dimensions and format
            original_format = img.format
            original_size = os.path.getsize(file_path) / (1024 * 1024)  # Size in MB
            width, height = img.size
            
            image_info = {
                'format': original_format,
                'width': width,
                'height': height,
                'original_size_mb': round(original_size, 2)
            }
            
            # Check if image is too large (dimensions)
            max_dimension = 4096
            if width > max_dimension or height > max_dimension:
                # Resize while maintaining aspect ratio
                img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
                width, height = img.size
                
            # Optimize and compress if file is too large
            if original_size > max_size_mb:
                # Convert RGBA to RGB if saving as JPEG
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create white background
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
                
                # Save with optimization
                save_format = 'JPEG' if original_format in ['JPEG', 'JPG'] else original_format
                quality = 85  # Good balance between quality and size
                
                img.save(file_path, format=save_format, quality=quality, optimize=True)
                
                new_size = os.path.getsize(file_path) / (1024 * 1024)
                image_info['compressed'] = True
                image_info['new_size_mb'] = round(new_size, 2)
                image_info['width'] = width
                image_info['height'] = height
            
            return True, "Image validated and optimized", image_info
            
    except Exception as e:
        return False, f"Invalid image file: {str(e)}", None


def create_thumbnail(file_path, thumbnail_size=(300, 300)):
    """
    Create a thumbnail for the uploaded image
    Returns: thumbnail_path or None
    """
    try:
        # Generate thumbnail filename
        base, ext = os.path.splitext(file_path)
        thumbnail_path = f"{base}_thumb{ext}"
        
        # Create thumbnail
        with Image.open(file_path) as img:
            # Convert RGBA to RGB if needed
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode == 'RGBA':
                    background.paste(img, mask=img.split()[-1])
                    img = background
            
            # Create thumbnail
            img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)
            img.save(thumbnail_path, format='JPEG', quality=85, optimize=True)
            
        return thumbnail_path
        
    except Exception as e:
        print(f"Error creating thumbnail: {e}")
        return None


@community_bp.route('/applications/<int:application_id>/submit-documents', methods=['POST'])
@login_required
@role_required('community')
def submit_documents(application_id):
    """Handle document upload submission"""
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    try:
        # Get document requirements for this program
        program_requirements = db.session.query(
            Requirements,
            ProgramRequirements.is_mandatory
        ).join(
            ProgramRequirements,
            Requirements.id == ProgramRequirements.requirement_id
        ).filter(
            ProgramRequirements.program_id == application.program_id,
            Requirements.requirement_type == 'document'
        ).all()
        
        upload_count = 0
        
        # Create upload directory if it doesn't exist
        # Store as relative path for portability
        upload_dir_relative = os.path.join('static', 'uploads', 'application_documents', str(application_id))
        
        # Get absolute path for file operations
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        upload_dir_absolute = os.path.join(project_root, upload_dir_relative)
        os.makedirs(upload_dir_absolute, exist_ok=True)
        
        # Process each document requirement
        for req, is_mandatory in program_requirements:
            file_key = f'document_{req.id}'
            
            if file_key in request.files:
                file = request.files[file_key]
                
                if file and file.filename:
                    # Secure the filename
                    filename = secure_filename(file.filename)
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    unique_filename = f'{req.id}_{timestamp}_{filename}'
                    
                    # Store relative path in database, use absolute for file operations
                    file_path_relative = os.path.join(upload_dir_relative, unique_filename)
                    file_path_absolute = os.path.join(upload_dir_absolute, unique_filename)
                    
                    # Save the file temporarily
                    file.save(file_path_absolute)
                    
                    # Validate and process images using Pillow
                    file_type = file.content_type
                    is_image = file_type.startswith('image/')
                    
                    if is_image:
                        # Validate and optimize the image
                        success, message, image_info = validate_and_process_image(file_path_absolute)
                        
                        if not success:
                            # Invalid image, delete and skip
                            os.remove(file_path_absolute)
                            flash(f'Error with {req.requirement_name}: {message}', 'warning')
                            continue
                        
                        # Create thumbnail for preview
                        thumbnail_path = create_thumbnail(file_path_absolute)
                        
                        # Log image optimization
                        if image_info.get('compressed'):
                            flash(f'{req.requirement_name}: Image optimized from {image_info["original_size_mb"]}MB to {image_info["new_size_mb"]}MB', 'info')
                    
                    # Get final file info after processing
                    file_size = os.path.getsize(file_path_absolute)
                    
                    # Check if upload already exists for this requirement
                    existing_upload = ApplicationDocumentUploads.query.filter_by(
                        application_id=application_id,
                        requirement_id=req.id
                    ).first()
                    
                    if existing_upload:
                        # Delete old file if it exists
                        if existing_upload.file_path:
                            old_file_path = existing_upload.file_path
                            if not os.path.isabs(old_file_path):
                                old_file_path = os.path.join(project_root, old_file_path)
                            if os.path.exists(old_file_path):
                                os.remove(old_file_path)
                        
                        # Update existing upload with relative path
                        existing_upload.file_path = file_path_relative
                        existing_upload.original_filename = filename
                        existing_upload.file_size = file_size
                        existing_upload.file_type = file_type
                        existing_upload.verification_status = 'pending'
                        existing_upload.uploaded_at = datetime.utcnow()
                    else:
                        # Create new upload record with relative path
                        new_upload = ApplicationDocumentUploads(
                            application_id=application_id,
                            requirement_id=req.id,
                            file_path=file_path_relative,
                            original_filename=filename,
                            file_size=file_size,
                            file_type=file_type,
                            verification_status='pending'
                        )
                        db.session.add(new_upload)
                    
                    upload_count += 1
        
        # Check if all mandatory documents are uploaded
        mandatory_reqs = [req for req, is_mandatory in program_requirements if is_mandatory]
        uploaded_mandatory = ApplicationDocumentUploads.query.filter(
            ApplicationDocumentUploads.application_id == application_id,
            ApplicationDocumentUploads.requirement_id.in_([req.id for req in mandatory_reqs])
        ).count()
        
        # Update application document upload status
        if uploaded_mandatory >= len(mandatory_reqs):
            application.document_upload_status = 'uploaded'
            
            # Create notifications for all admin users
            admin_users = User.query.filter_by(role='admin').all()
            for admin in admin_users:
                admin_notification = Notifications(
                    user_id=admin.id,
                    notif_title='New Documents Uploaded',
                    notif_message=f'{current_user.first_name} {current_user.last_name} has uploaded documents for application #{application_id}',
                    is_read=False,
                    related_id=application_id,
                    related_type='application'
                )
                db.session.add(admin_notification)
            
            # Notify user
            user_notification = Notifications(
                user_id=current_user.id,
                notif_title='Documents Submitted for Review',
                notif_message=f'Your documents for {application.program.program_name} have been submitted. Our team will review them shortly.',
                is_read=False,
                related_id=application_id,
                related_type='application'
            )
            db.session.add(user_notification)
        
        db.session.commit()
        
        if upload_count > 0:
            flash(f'{upload_count} document(s) uploaded successfully! Your documents will be reviewed by our team.', 'success')
        else:
            flash('No new documents were uploaded.', 'info')
        
        return redirect(url_for('community.application_detail', application_id=application_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error uploading documents: {str(e)}', 'danger')
        return redirect(url_for('community.upload_documents', application_id=application_id))


@community_bp.route('/document-uploads/<int:upload_id>/view')
@login_required
def view_uploaded_document(upload_id):
    """View an uploaded document"""
    upload = ApplicationDocumentUploads.query.get_or_404(upload_id)
    
    # Security check: ensure user owns the application or is an admin
    if current_user.role != 'admin':
        if upload.application.user_id != current_user.id:
            flash('You do not have permission to view this document.', 'danger')
            return redirect(url_for('community.applications'))
    
    # Handle file path - stored paths are relative from project root
    file_path = upload.file_path
    if not os.path.isabs(file_path):
        # Convert relative path to absolute from project root (FLASK directory)
        # Go up 3 levels from this file: routes -> community -> app -> FLASK
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        file_path = os.path.join(project_root, file_path)
    
    # Check if file exists
    if not os.path.exists(file_path):
        flash(f'Document file not found. Please contact support.', 'danger')
        return redirect(request.referrer or url_for('community.applications'))
    
    try:
        return send_file(
            file_path,
            as_attachment=False,
            download_name=upload.original_filename
        )
    except Exception as e:
        flash(f'Error accessing document: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('community.applications'))
