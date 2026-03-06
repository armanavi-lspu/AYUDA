from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, or_
from werkzeug.utils import secure_filename
import os
from app.admin import admin_bp
from app.models import Announcements, User, AnnouncementImages, Programs
from app.extensions import db
from app.utils import role_required
from app.activity_logger import log_announcement

# Configuration
UPLOAD_FOLDER = 'static/uploads/announcements'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@admin_bp.route('/announcements', endpoint='adm_announcements')
@login_required
@role_required('admin')
def announcements():
    """Display all announcements with search and filter"""
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # Get filter parameters
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '').strip()
    category_filter = request.args.get('category', '').strip()
    date_range = request.args.get('date_range', '').strip()
    
    # Base query
    query = Announcements.query
    
    # Apply search filter
    if search:
        search_filter = or_(
            Announcements.announcement_title.contains(search),
            Announcements.announcement_content.contains(search)
        )
        query = query.filter(search_filter)
    
    # Apply status filter
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    # Apply category filter
    if category_filter:
        query = query.filter_by(category=category_filter)
    
    # Apply date range filter
    if date_range:
        today = datetime.utcnow()
        if date_range == 'today':
            start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.filter(Announcements.created_at >= start_date)
        elif date_range == 'week':
            start_date = today - timedelta(days=7)
            query = query.filter(Announcements.created_at >= start_date)
        elif date_range == 'month':
            start_date = today - timedelta(days=30)
            query = query.filter(Announcements.created_at >= start_date)
        elif date_range == 'year':
            start_date = today - timedelta(days=365)
            query = query.filter(Announcements.created_at >= start_date)
    
    # Order by creation date (newest first)
    query = query.order_by(desc(Announcements.created_at))
    
    # Paginate results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Calculate statistics
    today = datetime.utcnow()
    start_of_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    total_announcements = Announcements.query.count()
    published_count = Announcements.query.filter_by(status='published').count()
    draft_count = Announcements.query.filter_by(status='draft').count()
    this_month_count = Announcements.query.filter(
        Announcements.created_at >= start_of_month
    ).count()
    
    # Get all active programs for linking
    programs = Programs.query.filter_by(is_active=True).order_by(Programs.program_name).all()
    
    return render_template(
        'admin/adm_announcements.html',
        announcements=pagination.items,
        pagination=pagination,
        total_announcements=total_announcements,
        published_count=published_count,
        draft_count=draft_count,
        this_month_count=this_month_count,
        programs=programs,
        user=current_user
    )

@admin_bp.route('/announcements/add', endpoint='add_announcement', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_announcement():
    """Add a new announcement with images"""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        category = request.form.get('category', 'General').strip()
        status = request.form.get('status', 'draft').strip()
        program_id = request.form.get('program_id', '').strip()
        attachment_url = request.form.get('attachment_url', '').strip()
        
        # Validation
        if not title or not content:
            flash('Title and content are required.', 'danger')
            return redirect(url_for('admin.adm_announcements'))
        
        # Convert program_id to integer or None
        program_id = int(program_id) if program_id and program_id != '' else None
        
        # Create new announcement
        new_announcement = Announcements(
            announcement_title=title,
            announcement_content=content,
            category=category,
            status=status,
            author_id=current_user.id,
            program_id=program_id,
            attachment_url=attachment_url if attachment_url else None,
            created_at=datetime.utcnow()
        )
        
        try:
            db.session.add(new_announcement)
            db.session.flush()  # Get the announcement ID
            
            # Handle image uploads
            uploaded_files = request.files.getlist('images')
            image_captions = request.form.getlist('image_captions')
            
            for idx, file in enumerate(uploaded_files):
                if file and file.filename and allowed_file(file.filename):
                    # Create upload directory if it doesn't exist
                    upload_path = os.path.join('static', 'uploads', 'announcements', str(new_announcement.id))
                    os.makedirs(upload_path, exist_ok=True)
                    
                    # Secure filename and save
                    filename = secure_filename(file.filename)
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    unique_filename = f"{timestamp}_{filename}"
                    file_path = os.path.join(upload_path, unique_filename)
                    
                    file.save(file_path)
                    
                    # Get caption if provided
                    caption = image_captions[idx] if idx < len(image_captions) else ''
                    
                    # Save image record
                    announcement_image = AnnouncementImages(
                        announcement_id=new_announcement.id,
                        image_path=file_path.replace('\\', '/'),
                        caption=caption,
                        display_order=idx
                    )
                    db.session.add(announcement_image)
            
            db.session.commit()
            
            # Log activity
            log_announcement(new_announcement, 'create' if status == 'draft' else 'publish')
            db.session.commit()
            
            flash(f'Announcement "{title}" created successfully!', 'success')
            return redirect(url_for('admin.adm_announcements'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating announcement: {str(e)}', 'danger')
            return redirect(url_for('admin.adm_announcements'))
    
    return render_template('admin/add_announcement.html', user=current_user)

@admin_bp.route('/announcements/edit/<int:id>', endpoint='edit_announcement', methods=['POST'])
@login_required
@role_required('admin')
def edit_announcement(id):
    """Edit an existing announcement and manage images"""
    announcement = Announcements.query.get_or_404(id)
    
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    category = request.form.get('category', 'General').strip()
    status = request.form.get('status', 'draft').strip()
    program_id = request.form.get('program_id', '').strip()
    attachment_url = request.form.get('attachment_url', '').strip()
    
    # Validation
    if not title or not content:
        flash('Title and content are required.', 'danger')
        return redirect(url_for('admin.adm_announcements'))
    
    # Convert program_id to integer or None
    program_id = int(program_id) if program_id and program_id != '' else None
    
    # Update announcement
    announcement.announcement_title = title
    announcement.announcement_content = content
    announcement.category = category
    announcement.status = status
    announcement.program_id = program_id
    announcement.attachment_url = attachment_url if attachment_url else None
    announcement.updated_at = datetime.utcnow()
    
    try:
        # Handle new image uploads
        uploaded_files = request.files.getlist('new_images')
        image_captions = request.form.getlist('new_image_captions')
        
        # Get current max display order
        max_order = db.session.query(db.func.max(AnnouncementImages.display_order))\
            .filter_by(announcement_id=id).scalar() or -1
        
        for idx, file in enumerate(uploaded_files):
            if file and file.filename and allowed_file(file.filename):
                # Create upload directory if it doesn't exist
                upload_path = os.path.join('static', 'uploads', 'announcements', str(id))
                os.makedirs(upload_path, exist_ok=True)
                
                # Secure filename and save
                filename = secure_filename(file.filename)
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                unique_filename = f"{timestamp}_{filename}"
                file_path = os.path.join(upload_path, unique_filename)
                
                file.save(file_path)
                
                # Get caption if provided
                caption = image_captions[idx] if idx < len(image_captions) else ''
                
                # Save image record
                announcement_image = AnnouncementImages(
                    announcement_id=id,
                    image_path=file_path.replace('\\', '/'),
                    caption=caption,
                    display_order=max_order + idx + 1
                )
                db.session.add(announcement_image)
        
        # Handle image deletions
        images_to_delete = request.form.getlist('delete_images')
        for image_id in images_to_delete:
            image = AnnouncementImages.query.get(int(image_id))
            if image and image.announcement_id == id:
                # Delete file from filesystem
                if os.path.exists(image.image_path):
                    os.remove(image.image_path)
                db.session.delete(image)
        
        db.session.commit()
        
        # Log activity
        log_announcement(announcement, 'update')
        db.session.commit()
        
        flash(f'Announcement "{title}" updated successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating announcement: {str(e)}', 'danger')
    
    return redirect(url_for('admin.adm_announcements'))

@admin_bp.route('/announcements/delete/<int:id>', endpoint='delete_announcement', methods=['POST'])
@login_required
@role_required('admin')
def delete_announcement(id):
    """Delete an announcement and its images"""
    announcement = Announcements.query.get_or_404(id)
    title = announcement.announcement_title
    
    try:
        # Delete all associated images from filesystem
        for image in announcement.images:
            if os.path.exists(image.image_path):
                os.remove(image.image_path)
        
        # Delete announcement directory if empty
        upload_path = os.path.join('static', 'uploads', 'announcements', str(id))
        if os.path.exists(upload_path):
            try:
                os.rmdir(upload_path)
            except OSError:
                pass  # Directory not empty or doesn't exist
        
        db.session.delete(announcement)
        
        # Log activity before commit
        log_announcement(type('Announcement', (), {'announcement_title': title, 'status': 'deleted', 'category': '', 'id': id})(), 'delete')
        
        db.session.commit()
        flash(f'Announcement "{title}" deleted successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting announcement: {str(e)}', 'danger')
    
    return redirect(url_for('admin.adm_announcements'))

@admin_bp.route('/announcements/delete-image/<int:image_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_announcement_image(image_id):
    """Delete a single announcement image"""
    image = AnnouncementImages.query.get_or_404(image_id)
    announcement_id = image.announcement_id
    
    try:
        # Delete file from filesystem
        if os.path.exists(image.image_path):
            os.remove(image.image_path)
        
        db.session.delete(image)
        db.session.commit()
        
        return {'success': True, 'message': 'Image deleted successfully'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'message': str(e)}, 500

@admin_bp.route('/announcements/publish/<int:id>', endpoint='publish_announcement', methods=['POST'])
@login_required
@role_required('admin')
def publish_announcement(id):
    """Publish a draft announcement"""
    announcement = Announcements.query.get_or_404(id)
    
    if announcement.status == 'draft':
        announcement.status = 'published'
        announcement.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash(f'Announcement "{announcement.announcement_title}" published successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error publishing announcement: {str(e)}', 'danger')
    else:
        flash('Announcement is already published.', 'info')
    
    return redirect(url_for('admin.adm_announcements'))

@admin_bp.route('/announcements/unpublish/<int:id>', endpoint='unpublish_announcement', methods=['POST'])
@login_required
@role_required('admin')
def unpublish_announcement(id):
    """Unpublish an announcement (set to draft)"""
    announcement = Announcements.query.get_or_404(id)
    
    if announcement.status == 'published':
        announcement.status = 'draft'
        announcement.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash(f'Announcement "{announcement.announcement_title}" unpublished successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error unpublishing announcement: {str(e)}', 'danger')
    else:
        flash('Announcement is already a draft.', 'info')
    
    return redirect(url_for('admin.adm_announcements'))
