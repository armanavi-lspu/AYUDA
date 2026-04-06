from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, or_, func, case
from sqlalchemy.orm import joinedload
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
import secrets
import string
import os
from app.admin import admin_bp
from app.models import User, Applications, Notifications, CommunityUsers, UserActivityLog
from app.extensions import db
from app.utils import role_required, manila_strftime
from app.activity_logger import log_verification_request, log_user_modification
from app.community.routes.profile import get_income_range_display

@admin_bp.route('/community')
@login_required
@role_required('admin')
def community():
    """Display all community users with search and filter"""
    page = request.args.get('page', 1, type=int)
    per_page = 15
    
    # Get filter parameters
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '').strip()
    barangay_filter = request.args.get('barangay', '').strip()
    municipality_filter = request.args.get('municipality', '').strip()
    date_range = request.args.get('date_range', '').strip()
    
    # Get sort parameters
    sort_by = request.args.get('sort_by', 'date').strip()  # 'date' or 'name'
    sort_order = request.args.get('sort_order', 'desc').strip()  # 'asc' or 'desc'
    
    # Base query - only community users
    query = User.query.filter_by(role='community')
    
    # Apply search filter
    if search:
        query = query.outerjoin(CommunityUsers, CommunityUsers.user_id == User.id)
        search_filter = or_(
            User.first_name.ilike(f'%{search}%'),
            User.last_name.ilike(f'%{search}%'),
            User.email.ilike(f'%{search}%'),
            CommunityUsers.mobile_no.ilike(f'%{search}%'),
            CommunityUsers.barangay.ilike(f'%{search}%'),
            CommunityUsers.municipality.ilike(f'%{search}%')
        )
        query = query.filter(search_filter)
    
    # Apply status filter (verification status)
    if status_filter:
        if status_filter == 'pwd_verified':
            query = query.filter(User.community_profile.has(pwd_verification='approved'))
        elif status_filter == 'senior_citizen_verified':
            query = query.filter(User.community_profile.has(senior_citizen_verification='approved'))
        elif status_filter == 'solo_parent_verified':
            query = query.filter(User.community_profile.has(solo_parent_verification='approved'))
        elif status_filter == 'student':
            query = query.filter(User.community_profile.has(is_student=True))
    
    # Apply barangay filter
    if barangay_filter:
        query = query.filter(User.community_profile.has(barangay=barangay_filter))

    # Apply municipality filter
    if municipality_filter:
        query = query.filter(User.community_profile.has(municipality=municipality_filter))
    
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
    
    # Apply sorting
    if sort_by == 'name':
        # Sort by user name
        if sort_order == 'asc':
            query = query.order_by(User.first_name.asc(), User.last_name.asc())
        else:
            query = query.order_by(User.first_name.desc(), User.last_name.desc())
    else:  # Default to date sorting
        if sort_order == 'asc':
            query = query.order_by(User.created_at.asc())
        else:
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

    municipalities = db.session.query(CommunityUsers.municipality)\
        .filter(CommunityUsers.municipality.isnot(None))\
        .distinct().order_by(CommunityUsers.municipality).all()
    municipalities = [m[0] for m in municipalities if m[0]]
    
    # Add application counts to each user
    for user in pagination.items:
        # FIX: Specify the join condition explicitly
        user.app_count = Applications.query.filter_by(user_id=user.id).count()
        user.approved_apps = Applications.query.filter_by(
            user_id=user.id, 
            application_status='approved'
        ).count()
        user.active_apps = Applications.query.filter_by(user_id=user.id).filter(
            Applications.application_status.notin_(['approved', 'rejected', 'completed'])
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
        municipalities=municipalities,
        sort_by=sort_by,
        sort_order=sort_order,
        user=current_user
    )

@admin_bp.route('/community/view/<int:user_id>')
@login_required
@role_required('admin')
def view_community_user(user_id):
    """View detailed information about a community user"""
    community_user = User.query.options(joinedload(User.community_profile)).filter_by(id=user_id, role='community').first_or_404()
    
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
    
    # Get user activity logs (last 10)
    user_activities = UserActivityLog.query.filter_by(user_id=user_id)\
        .order_by(desc(UserActivityLog.created_at)).limit(10).all()
    
    return render_template(
        'admin/view_community_user.html',
        community_user=community_user,
        total_apps=total_apps,
        pending_apps=pending_apps,
        approved_apps=approved_apps,
        rejected_apps=rejected_apps,
        applications=applications,
        user_activities=user_activities,
        user=current_user,
        get_income_range_display=get_income_range_display
    )

@admin_bp.route('/community/reset-password/<int:user_id>', methods=['POST'])
@login_required
@role_required('admin')
def reset_user_password(user_id):
    """Reset a community user's password"""
    community_user = User.query.filter_by(id=user_id, role='community').first_or_404()
    
    # Generate temporary reset code
    reset_code = ''.join(secrets.choice(string.digits) for _ in range(8))
    community_user.password_hash = generate_password_hash(reset_code, method='pbkdf2:sha256')
    
    try:
        # Send reset code to the target user via in-app notification.
        notification = Notifications(
            user_id=user_id,
            notif_title='Password Reset',
            notif_message=(
                f'Your password has been reset by an administrator. '
                f'Your temporary password/reset code is: {reset_code}. '
                f'Use this code to log in. It is strongly recommended that you change your password immediately.'
            ),
            related_type='profile',
            related_id=user_id,
            created_at=datetime.utcnow()
        )
        db.session.add(notification)

        # Log reset activity as part of the same transaction.
        log_user_modification(community_user, 'reset_password', {
            'reset_code_delivery': 'notification_and_flash',
            'reset_code_length': len(reset_code)
        })

        db.session.commit()
        
        flash(
            f'Password reset successfully for {community_user.first_name} {community_user.last_name}. '
            f'New temporary password/reset code: {reset_code}',
            'success'
        )
        
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
                notif_title='Account Restricted',
                notif_message='Your account has been restricted by an administrator. Please contact support for more information.',
                related_type='profile',
                created_at=datetime.utcnow()
            )
            db.session.add(notification)
            db.session.commit()
            
            flash(f'Account disabled for {community_user.first_name} {community_user.last_name}.', 'warning')
            
            # Log activity
            log_user_modification(community_user, 'suspend')
            db.session.commit()
        else:
            notification = Notifications(
                user_id=user_id,
                notif_title='Account Restored',
                notif_message='Your account has been restored by an administrator. You can now access all features.',
                related_type='profile',
                created_at=datetime.utcnow()
            )
            db.session.add(notification)
            db.session.commit()
            
            flash(f'Account enabled for {community_user.first_name} {community_user.last_name}.', 'success')
            
            # Log activity
            log_user_modification(community_user, 'unsuspend')
            db.session.commit()
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
        
        # Delete activity logs
        from app.models import UserActivityLog
        UserActivityLog.query.filter_by(user_id=user_id).delete()
        
        # Log activity before deleting user
        from app.activity_logger import log_activity
        log_activity(
            action='delete_user',
            action_type='delete',
            entity_type='user',
            description=f'Deleted community user: {user_name} ({community_user.email})',
            entity_id=user_id,
            details={'user_name': user_name, 'user_email': community_user.email}
        )
        
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
            manila_strftime(user.created_at, '%Y-%m-%d %H:%M:%S', ''),
            manila_strftime(user.last_activity, '%Y-%m-%d %H:%M:%S', '')
        ])
    
    # Create response
    output = si.getvalue()
    si.close()
    
    return Response(
        output,
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename=community_users_{manila_strftime(datetime.utcnow(), "%Y%m%d_%H%M%S", "")}.csv'
        }
    )


# ============== VERIFICATION ROUTES ==============

@admin_bp.route('/community/verify')
@login_required
@role_required('admin')
def community_verify():
    """Display verification requests for Senior Citizen, PWD, and Solo Parent"""
    page = request.args.get('page', 1, type=int)
    per_page = 15
    
    # Get filter parameters
    search = request.args.get('search', '').strip()
    verification_type = request.args.get('type', '').strip()
    status_filter = request.args.get('status', '').strip()
    barangay_filter = request.args.get('barangay', '').strip()
    municipality_filter = request.args.get('municipality', '').strip()
    
    # Base query - users with verification requests
    query = CommunityUsers.query.join(User, CommunityUsers.user_id == User.id)
    
    # Filter by verification type and status
    if verification_type == 'senior_citizen':
        if status_filter:
            query = query.filter(CommunityUsers.senior_citizen_verification == status_filter)
        else:
            query = query.filter(CommunityUsers.senior_citizen_verification != 'none')
    elif verification_type == 'pwd':
        if status_filter:
            query = query.filter(CommunityUsers.pwd_verification == status_filter)
        else:
            query = query.filter(CommunityUsers.pwd_verification != 'none')
    elif verification_type == 'solo_parent':
        if status_filter:
            query = query.filter(CommunityUsers.solo_parent_verification == status_filter)
        else:
            query = query.filter(CommunityUsers.solo_parent_verification != 'none')
    else:
        # Show all pending verification requests by default
        if status_filter == 'pending':
            query = query.filter(
                or_(
                    CommunityUsers.senior_citizen_verification == 'pending',
                    CommunityUsers.pwd_verification == 'pending',
                    CommunityUsers.solo_parent_verification == 'pending'
                )
            )
        elif status_filter == 'approved':
            query = query.filter(
                or_(
                    CommunityUsers.senior_citizen_verification == 'approved',
                    CommunityUsers.pwd_verification == 'approved',
                    CommunityUsers.solo_parent_verification == 'approved'
                )
            )
        elif status_filter == 'rejected':
            query = query.filter(
                or_(
                    CommunityUsers.senior_citizen_verification == 'rejected',
                    CommunityUsers.pwd_verification == 'rejected',
                    CommunityUsers.solo_parent_verification == 'rejected'
                )
            )
        else:
            query = query.filter(
                or_(
                    CommunityUsers.senior_citizen_verification != 'none',
                    CommunityUsers.pwd_verification != 'none',
                    CommunityUsers.solo_parent_verification != 'none'
                )
            )
    
    # Apply search filter
    if search:
        search_filter = or_(
            User.first_name.ilike(f'%{search}%'),
            User.last_name.ilike(f'%{search}%'),
            User.email.ilike(f'%{search}%'),
            CommunityUsers.barangay.ilike(f'%{search}%'),
            CommunityUsers.municipality.ilike(f'%{search}%')
        )
        query = query.filter(search_filter)
    
    # Apply barangay filter
    if barangay_filter:
        query = query.filter(CommunityUsers.barangay == barangay_filter)

    if municipality_filter:
        query = query.filter(CommunityUsers.municipality == municipality_filter)
    
    # Order: Pending requests first, then by creation date (newest first)
    query = query.order_by(
        case(
            (or_(
                CommunityUsers.senior_citizen_verification == 'pending',
                CommunityUsers.pwd_verification == 'pending',
                CommunityUsers.solo_parent_verification == 'pending'
            ), 0),
            else_=1
        ),
        desc(CommunityUsers.created_at)
    )
    
    # Paginate results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Get statistics
    pending_senior = CommunityUsers.query.filter_by(senior_citizen_verification='pending').count()
    pending_pwd = CommunityUsers.query.filter_by(pwd_verification='pending').count()
    pending_solo_parent = CommunityUsers.query.filter_by(solo_parent_verification='pending').count()
    total_pending = pending_senior + pending_pwd + pending_solo_parent
    
    approved_senior = CommunityUsers.query.filter_by(senior_citizen_verification='approved').count()
    approved_pwd = CommunityUsers.query.filter_by(pwd_verification='approved').count()
    approved_solo_parent = CommunityUsers.query.filter_by(solo_parent_verification='approved').count()
    total_approved = approved_senior + approved_pwd + approved_solo_parent
    
    rejected_senior = CommunityUsers.query.filter_by(senior_citizen_verification='rejected').count()
    rejected_pwd = CommunityUsers.query.filter_by(pwd_verification='rejected').count()
    rejected_solo_parent = CommunityUsers.query.filter_by(solo_parent_verification='rejected').count()
    total_rejected = rejected_senior + rejected_pwd + rejected_solo_parent
    
    # Get unique barangays
    barangays = db.session.query(CommunityUsers.barangay)\
        .filter(CommunityUsers.barangay.isnot(None))\
        .distinct().order_by(CommunityUsers.barangay).all()
    barangays = [b[0] for b in barangays if b[0]]

    municipalities = db.session.query(CommunityUsers.municipality)\
        .filter(CommunityUsers.municipality.isnot(None))\
        .distinct().order_by(CommunityUsers.municipality).all()
    municipalities = [m[0] for m in municipalities if m[0]]
    
    return render_template(
        'admin/community_verify.html',
        verifications=pagination.items,
        pagination=pagination,
        pending_senior=pending_senior,
        pending_pwd=pending_pwd,
        pending_solo_parent=pending_solo_parent,
        total_pending=total_pending,
        approved_senior=approved_senior,
        approved_pwd=approved_pwd,
        approved_solo_parent=approved_solo_parent,
        total_approved=total_approved,
        rejected_senior=rejected_senior,
        rejected_pwd=rejected_pwd,
        rejected_solo_parent=rejected_solo_parent,
        total_rejected=total_rejected,
        barangays=barangays,
        municipalities=municipalities,
        user=current_user
    )


@admin_bp.route('/community/verify/<int:user_id>/<verification_type>', methods=['POST'])
@login_required
@role_required('admin')
def process_verification(user_id, verification_type):
    """Process a verification request (approve or reject)"""
    community_user = CommunityUsers.query.filter_by(user_id=user_id).first_or_404()
    user = User.query.get(user_id)
    
    action = request.form.get('action')  # 'approve' or 'reject'
    rejection_reason = request.form.get('rejection_reason', '').strip()
    id_number = request.form.get('id_number', '').strip()
    
    try:
        if verification_type == 'senior_citizen':
            if action == 'approve':
                community_user.senior_citizen_verification = 'approved'
                community_user.senior_citizen_verified_at = datetime.utcnow()
                community_user.senior_citizen_verified_by = current_user.id
                if id_number:
                    community_user.senior_citizen_id_number = id_number
                # Also set the is_pwd equivalent for senior (age >= 60 is already tracked)
                
                # Send notification
                notification = Notifications(
                    user_id=user_id,
                    notif_title='Senior Citizen Verification Approved',
                    notif_message='Your Senior Citizen verification has been approved. You can now access Senior Citizen benefits.',
                    is_read=False,
                    related_type='profile',
                    created_at=datetime.utcnow()
                )
                db.session.add(notification)
                flash(f'Senior Citizen verification approved for {user.first_name} {user.last_name}.', 'success')
            else:
                community_user.senior_citizen_verification = 'rejected'
                community_user.senior_citizen_rejection_reason = rejection_reason
                
                notification = Notifications(
                    user_id=user_id,
                    notif_title='Senior Citizen Verification Rejected',
                    notif_message=f'Your Senior Citizen verification was rejected. Reason: {rejection_reason}',
                    is_read=False,
                    related_type='profile',
                    created_at=datetime.utcnow()
                )
                db.session.add(notification)
                flash(f'Senior Citizen verification rejected for {user.first_name} {user.last_name}.', 'warning')
                
        elif verification_type == 'pwd':
            if action == 'approve':
                community_user.pwd_verification = 'approved'
                community_user.pwd_verified_at = datetime.utcnow()
                community_user.pwd_verified_by = current_user.id
                community_user.is_pwd = True  # Set the is_pwd flag
                if id_number:
                    community_user.pwd_id_number = id_number
                
                notification = Notifications(
                    user_id=user_id,
                    notif_title='PWD Verification Approved',
                    notif_message='Your PWD (Person with Disability) verification has been approved. You can now access PWD benefits.',
                    is_read=False,
                    related_type='profile',
                    created_at=datetime.utcnow()
                )
                db.session.add(notification)
                flash(f'PWD verification approved for {user.first_name} {user.last_name}.', 'success')
            else:
                community_user.pwd_verification = 'rejected'
                community_user.pwd_rejection_reason = rejection_reason
                
                notification = Notifications(
                    user_id=user_id,
                    notif_title='PWD Verification Rejected',
                    notif_message=f'Your PWD verification was rejected. Reason: {rejection_reason}',
                    is_read=False,
                    related_type='profile',
                    created_at=datetime.utcnow()
                )
                db.session.add(notification)
                flash(f'PWD verification rejected for {user.first_name} {user.last_name}.', 'warning')
                
        elif verification_type == 'solo_parent':
            if action == 'approve':
                community_user.solo_parent_verification = 'approved'
                community_user.solo_parent_verified_at = datetime.utcnow()
                community_user.solo_parent_verified_by = current_user.id
                community_user.is_solo_parent = True  # Set the is_solo_parent flag
                if id_number:
                    community_user.solo_parent_id_number = id_number
                
                notification = Notifications(
                    user_id=user_id,
                    notif_title='Solo Parent Verification Approved',
                    notif_message='Your Solo Parent verification has been approved. You can now access Solo Parent benefits.',
                    is_read=False,
                    related_type='profile',
                    created_at=datetime.utcnow()
                )
                db.session.add(notification)
                flash(f'Solo Parent verification approved for {user.first_name} {user.last_name}.', 'success')
            else:
                community_user.solo_parent_verification = 'rejected'
                community_user.solo_parent_rejection_reason = rejection_reason
                
                notification = Notifications(
                    user_id=user_id,
                    notif_title='Solo Parent Verification Rejected',
                    notif_message=f'Your Solo Parent verification was rejected. Reason: {rejection_reason}',
                    is_read=False,
                    related_type='profile',
                    created_at=datetime.utcnow()
                )
                db.session.add(notification)
                flash(f'Solo Parent verification rejected for {user.first_name} {user.last_name}.', 'warning')
        else:
            flash('Invalid verification type.', 'error')
            return redirect(url_for('admin.community_verify'))
        
        # Log verification request activity
        log_verification_request(user, verification_type, action, rejection_reason if action == 'reject' else None)
        
        db.session.commit()
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error processing verification: {str(e)}', 'error')
    
    return redirect(url_for('admin.community_verify'))


@admin_bp.route('/community/verify/view/<int:user_id>')
@login_required
@role_required('admin')
def view_verification_details(user_id):
    """View detailed verification information for a user"""
    community_user = CommunityUsers.query.filter_by(user_id=user_id).first_or_404()
    user = User.query.get(user_id)
    
    return render_template(
        'admin/view_verification.html',
        community_user=community_user,
        user_info=user,
        user=current_user
    )
