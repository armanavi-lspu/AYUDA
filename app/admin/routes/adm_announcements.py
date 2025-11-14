from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.models import Announcements, User
from app.extensions import db
from app.utils import role_required
from sqlalchemy import or_, func
from datetime import datetime, timedelta

@admin_bp.route('/announcements', endpoint='adm_announcements')
@login_required
@role_required('admin')
def announcements():
    return render_template('admin/adm_announcements.html', user=current_user)

@admin_bp.route('/announcements/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_announcement():
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        category = request.form.get('category', 'General')
        status = request.form.get('status', 'draft')
        
        if not title or not content:
            flash('Title and content are required.', 'error')
            return redirect(url_for('admin.adm_announcements'))
        
        new_announcement = Announcements(
            title=title,
            content=content,
            category=category,
            status=status,
            author_id=current_user.id,
            created_at=datetime.utcnow(),
            views=0
        )
        
        db.session.add(new_announcement)
        db.session.commit()
        
        flash(f'Announcement "{title}" has been created successfully!', 'success')
        return redirect(url_for('admin.adm_announcements'))
    
    return render_template('admin/add_announcement.html', user=current_user)

@admin_bp.route('/announcements/edit/<int:id>', methods=['POST'])
@login_required
@role_required('admin')
def edit_announcement(id):
    announcement = Announcements.query.get_or_404(id)
    
    announcement.title = request.form.get('title')
    announcement.content = request.form.get('content')
    announcement.category = request.form.get('category', 'General')
    announcement.status = request.form.get('status', 'draft')
    announcement.updated_at = datetime.utcnow()
    
    db.session.commit()
    flash(f'Announcement "{announcement.title}" has been updated!', 'success')
    return redirect(url_for('admin.adm_announcements'))

@admin_bp.route('/announcements/delete/<int:id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_announcement(id):
    announcement = Announcements.query.get_or_404(id)
    title = announcement.title
    
    db.session.delete(announcement)
    db.session.commit()
    
    flash(f'Announcement "{title}" has been deleted.', 'warning')
    return redirect(url_for('admin.adm_announcements'))
