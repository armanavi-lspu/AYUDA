from flask import render_template, redirect, url_for
from flask_login import login_required, current_user
from app.community import community_bp
from app.models import Announcements, User, AdminUsers
from app.extensions import db
from app.utils import role_required
from sqlalchemy import desc, func


def _get_current_user_municipality():
    """Return the logged-in community user's municipality."""
    profile = getattr(current_user, 'community_profile', None)
    if not profile or not profile.municipality:
        return None
    return profile.municipality.strip()


def _municipality_announcements_query():
    """Published announcements authored by admins in the user's municipality."""
    municipality = _get_current_user_municipality()
    if not municipality:
        return Announcements.query.filter(False)

    return Announcements.query.join(
        User, Announcements.author_id == User.id
    ).join(
        AdminUsers, AdminUsers.user_id == User.id
    ).filter(
        User.role == 'admin',
        func.lower(func.trim(AdminUsers.municipality)) == municipality.lower()
    )

@community_bp.route('/announcements')
@login_required
@role_required('community')
def announcements():
    """Display announcements - filtering handled client-side"""
    # Fetch all municipality-scoped published announcements.
    announcements = _municipality_announcements_query().filter(
        Announcements.status == 'published'
    ).order_by(desc(Announcements.created_at)).all()
    
    # Get unique categories within municipality scope.
    categories = _municipality_announcements_query().with_entities(
        Announcements.category
    ).filter(
        Announcements.status == 'published'
    ).distinct().all()
    categories = [cat[0] for cat in categories if cat[0]]
    
    return render_template('community/announcements.html', 
                         announcements=announcements,
                         categories=categories)

@community_bp.route('/announcement/<int:announcement_id>')
@login_required
def view_announcement_detail(announcement_id):
    """View full announcement details"""
    announcement = _municipality_announcements_query().filter(
        Announcements.id == announcement_id
    ).first()
    if not announcement:
        return redirect(url_for('community.announcements'))
    
    # Only allow viewing published announcements
    if announcement.status != 'published':
        return redirect(url_for('community.announcements'))
    
    return render_template('community/view_announcement.html', 
                         announcement=announcement)