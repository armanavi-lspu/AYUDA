from flask import render_template, redirect, url_for
from flask_login import login_required, current_user
from app.community import community_bp
from app.models import Announcements
from app.extensions import db
from app.utils import role_required
from sqlalchemy import desc

@community_bp.route('/announcements')
@login_required
@role_required('community')
def announcements():
    """Display announcements - filtering handled client-side"""
    # Fetch all published announcements
    announcements = Announcements.query.filter_by(status='published').order_by(desc(Announcements.created_at)).all()
    
    # Get unique categories
    categories = db.session.query(Announcements.category).filter_by(status='published').distinct().all()
    categories = [cat[0] for cat in categories if cat[0]]
    
    return render_template('community/announcements.html', 
                         announcements=announcements,
                         categories=categories)

@community_bp.route('/announcement/<int:announcement_id>')
@login_required
def view_announcement_detail(announcement_id):
    """View full announcement details"""
    announcement = Announcements.query.get_or_404(announcement_id)
    
    # Only allow viewing published announcements
    if announcement.status != 'published':
        return redirect(url_for('community.announcements'))
    
    return render_template('community/view_announcement.html', 
                         announcement=announcement)