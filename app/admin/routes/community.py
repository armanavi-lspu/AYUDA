from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, or_, func
from werkzeug.security import generate_password_hash
import secrets
import string
from app.admin import admin_bp
from app.models import User, Applications, Notifications
from app.extensions import db
from app.utils import role_required

@admin_bp.route('/community')
@login_required
@role_required('admin')
def community():
    """Display all community users with search and filter"""
    page = request.args.get('page', 1, type=int)
    per_page = 15
    
    # Get filter parameters
    search = request.args.get('search', '').strip()
    employment_filter = request.args.get('employment', '').strip()
    barangay_filter = request.args.get('barangay', '').strip()
    date_range = request.args.get('date_range', '').strip()
    
    # Base query - only community users
    query = User.query.filter_by(role='community')
    
    # Apply search filter
    if search:
        search_filter = or_(
            User.first_name.contains(search),
            User.last_name.contains(search),
            User.email.contains(search)
        )
        query = query.filter(search_filter)
    
    # Apply employment filter
    if employment_filter:
        query = query.join(User.community_profile).filter(
            or_(
                User.community_profile.has(is_currently_employed=(employment_filter == 'employed')),
                User.community_profile.has(is_student=(employment_filter == 'student')),
                User.community_profile.has(is_solo_parent=(employment_filter == 'solo_parent'))
            )
        )
    
    # Apply barangay filter
    if barangay_filter:
        query = query.join(User.community_profile).filter(
            User.community_profile.has(barangay=barangay_filter)
        )
    
    # Apply date range filter
    if date_range:
        today = datetime.utcnow()
        if date_range == 'today':
            start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.filter(User.created_at >= start_date)
        elif date_range == 'week':
            start_date = today - timedelta(days=7)
            query = query.filter(User.created_at >= start_date)
        elif date_range == 'month':
            start_date = today - timedelta(days=30)
            query = query.filter(User.created_at >= start_date)
        elif date_range == 'year':
            start_date = today - timedelta(days=365)
            query = query.filter(User.created_at >= start_date)
    
    # Order by creation date (newest first)
    query = query.order_by(desc(User.created_at))
    
    # Paginate results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Get statistics
    total_users = User.query.filter_by(role='community').count()
    
    # Active users (last 7 days)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    active_users = User.query.filter(
        User.role == 'community',
        User.last_activity >= seven_days_ago
    ).count()
    
    # Users with applications - FIX: Specify the join condition explicitly
    users_with_apps = db.session.query(func.count(func.distinct(Applications.user_id)))\
        .join(User, Applications.user_id == User.id)\
        .filter(User.role == 'community').scalar()
    
    # New users this month
    start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_this_month = User.query.filter(
        User.role == 'community',
        User.created_at >= start_of_month
    ).count()
    
    # Get unique barangays for filter dropdown
    from app.models import CommunityUsers
    barangays = db.session.query(CommunityUsers.barangay)\
        .filter(CommunityUsers.barangay.isnot(None))\
        .distinct().order_by(CommunityUsers.barangay).all()
    barangays = [b[0] for b in barangays if b[0]]
    
    # Add application counts to each user
    for user in pagination.items:
        # FIX: Specify the join condition explicitly
        user.app_count = Applications.query.filter_by(user_id=user.id).count()
        user.approved_apps = Applications.query.filter_by(
            user_id=user.id, 
            application_status='approved'
        ).count()
    
    return render_template(
        'admin/community.html',
        users=pagination.items,
        pagination=pagination,
        total_users=total_users,
        active_users=active_users,
        users_with_apps=users_with_apps,
        new_this_month=new_this_month,
        barangays=barangays,
        user=current_user
    )

@admin_bp.route('/community/view/<int:user_id>')
@login_required
@role_required('admin')
def view_community_user(user_id):
    """View detailed information about a community user"""
    community_user = User.query.filter_by(id=user_id, role='community').first_or_404()
    
    # Get application statistics
    total_apps = Applications.query.filter_by(user_id=user_id).count()
    pending_apps = Applications.query.filter_by(
        user_id=user_id, 
        application_status='pending'
    ).count()
    approved_apps = Applications.query.filter_by(
        user_id=user_id, 
        application_status='approved'
    ).count()
    rejected_apps = Applications.query.filter_by(
        user_id=user_id, 
        application_status='rejected'
    ).count()
    
    # Get all applications
    applications = Applications.query.filter_by(user_id=user_id)\
        .order_by(desc(Applications.application_date)).all()
    
    return render_template(
        'admin/view_community_user.html',
        community_user=community_user,
        total_apps=total_apps,
        pending_apps=pending_apps,
        approved_apps=approved_apps,
        rejected_apps=rejected_apps,
        applications=applications,
        user=current_user
    )

@admin_bp.route('/community/reset-password/<int:user_id>', methods=['POST'])
@login_required
@role_required('admin')
def reset_user_password(user_id):
    """Reset a community user's password"""
    community_user = User.query.filter_by(id=user_id, role='community').first_or_404()
    
    # Generate random password
    new_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    
    # Update password
    community_user.password = generate_password_hash(new_password)
    
    try:
        # Create notification for user
        notification = Notifications(
            user_id=user_id,
            title='Password Reset',
            message=f'Your password has been reset by an administrator. Your new temporary password is: {new_password}. Please change it after logging in.',
            notification_type='system',
            created_at=datetime.utcnow()
        )
        db.session.add(notification)
        db.session.commit()
        
        flash(f'Password reset successfully for {community_user.first_name} {community_user.last_name}. New password: {new_password}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error resetting password: {str(e)}', 'danger')
    
    return redirect(request.referrer or url_for('admin.community'))

@admin_bp.route('/community/toggle-status/<int:user_id>', methods=['POST'])
@login_required
@role_required('admin')
def toggle_user_status(user_id):
    """Enable or disable a community user's account"""
    community_user = User.query.filter_by(id=user_id, role='community').first_or_404()
    
    action = request.form.get('action', 'disable')
    
    try:
        if action == 'disable':
            # Add a field to track disabled status (you may need to add this to your User model)
            # For now, we'll just create a notification
            notification = Notifications(
                user_id=user_id,
                title='Account Restricted',
                message='Your account has been restricted by an administrator. Please contact support for more information.',
                notification_type='system',
                created_at=datetime.utcnow()
            )
            db.session.add(notification)
            db.session.commit()
            
            flash(f'Account disabled for {community_user.first_name} {community_user.last_name}.', 'warning')
        else:
            notification = Notifications(
                user_id=user_id,
                title='Account Restored',
                message='Your account has been restored by an administrator. You can now access all features.',
                notification_type='system',
                created_at=datetime.utcnow()
            )
            db.session.add(notification)
            db.session.commit()
            
            flash(f'Account enabled for {community_user.first_name} {community_user.last_name}.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating account status: {str(e)}', 'danger')
    
    return redirect(request.referrer or url_for('admin.community'))

@admin_bp.route('/community/delete/<int:user_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_community_user(user_id):
    """Delete a community user"""
    community_user = User.query.filter_by(id=user_id, role='community').first_or_404()
    
    # Check if user has applications
    app_count = Applications.query.filter_by(user_id=user_id).count()
    
    if app_count > 0:
        flash(f'Cannot delete user {community_user.first_name} {community_user.last_name} because they have {app_count} application(s). Please handle applications first.', 'danger')
        return redirect(url_for('admin.community'))
    
    try:
        user_name = f"{community_user.first_name} {community_user.last_name}"
        
        # Delete community profile if exists
        if community_user.community_profile:
            db.session.delete(community_user.community_profile)
        
        # Delete notifications
        Notifications.query.filter_by(user_id=user_id).delete()
        
        # Delete user
        db.session.delete(community_user)
        db.session.commit()
        
        flash(f'User {user_name} deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {str(e)}', 'danger')
    
    return redirect(url_for('admin.community'))

@admin_bp.route('/community/export', methods=['GET'])
@login_required
@role_required('admin')
def export_community_users():
    """Export community users to CSV"""
    import csv
    from io import StringIO
    from flask import Response
    
    # Get all community users
    users = User.query.filter_by(role='community').all()
    
    # Create CSV
    si = StringIO()
    writer = csv.writer(si)
    
    # Write header
    writer.writerow([
        'ID', 'First Name', 'Middle Name', 'Last Name', 'Email',
        'Mobile', 'Barangay', 'Municipality', 'Age',
        'Employed', 'Student', 'Solo Parent',
        'Applications Count', 'Registered Date', 'Last Activity'
    ])
    
    # Write data
    for user in users:
        profile = user.community_profile
        app_count = Applications.query.filter_by(user_id=user.id).count()
        
        writer.writerow([
            user.id,
            user.first_name,
            user.middle_name or '',
            user.last_name,
            user.email,
            profile.mobile_no if profile else '',
            profile.barangay if profile else '',
            profile.municipality if profile else '',
            profile.age if profile else '',
            'Yes' if profile and profile.is_currently_employed else 'No',
            'Yes' if profile and profile.is_student else 'No',
            'Yes' if profile and profile.is_solo_parent else 'No',
            app_count,
            user.created_at.strftime('%Y-%m-%d %H:%M:%S') if user.created_at else '',
            user.last_activity.strftime('%Y-%m-%d %H:%M:%S') if user.last_activity else ''
        ])
    
    # Create response
    output = si.getvalue()
    si.close()
    
    return Response(
        output,
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename=community_users_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
        }
    )
