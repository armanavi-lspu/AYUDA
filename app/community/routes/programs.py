from flask import render_template, jsonify, redirect, url_for, request, flash, send_file
from flask_login import login_required, current_user
from app.community import community_bp
from datetime import datetime
from app.models import Programs, Requirements, ProgramRequirements, Applications, ApplicationDocuments, Notifications, ShelterPhotos
from app.extensions import db
from app.utils import role_required, calculate_profile_completion
from sqlalchemy import desc, func
from werkzeug.utils import secure_filename
import os

@community_bp.route('/programs')
@login_required
@role_required('community')
def programs():
    """Display financial assistance programs by category"""
    
    # Define program categories with their types
    categories = {
        'AICS': 'Assistance to Individuals in Crisis Situation (AICS)',
        'ESA': 'Emergency Shelter Assistance (ESA)', 
        '4Ps': 'Pantawid Pamilyang Pilipino Program (4Ps)',
        'CA': 'Capital Assistance (CA)'
    }
    
    # Get program counts by category
    program_stats = {}
    total_programs = 0
    
    for category_key, category_name in categories.items():
        count = Programs.query.filter_by(program_type=category_key).count()
        program_stats[category_key] = {
            'name': category_name,
            'count': count
        }
        total_programs += count
    
    # Total categories count
    total_categories = len(categories)
    
    return render_template('community/programs_category.html',
                         categories=program_stats,
                         total_categories=total_categories,
                         total_programs=total_programs)

@community_bp.route('/programs/category/<category>')
@login_required  
@role_required('community')
def programs_by_category(category):
    """Display programs for a specific category"""
    
    # Category mapping
    category_names = {
        'AICS': 'Assistance to Individuals in Crisis Situation (AICS)',
        'ESA': 'Emergency Shelter Assistance (ESA)', 
        '4Ps': 'Pantawid Pamilyang Pilipino Program (4Ps)',
        'CA': 'Capital Assistance (CA)'
    }
    
    print(f"DEBUG: Received category: '{category}'")
    print(f"DEBUG: Category in category_names: {category in category_names}")
    print(f"DEBUG: Available categories: {list(category_names.keys())}")
    
    if category not in category_names:
        print(f"DEBUG: Category '{category}' not found, redirecting to programs page")
        return redirect(url_for('community.programs'))
    
    # Get programs for this category
    programs = Programs.query.filter_by(program_type=category).order_by(desc(Programs.date)).all()
    
    return render_template('community/programs_list.html',
                         programs=programs,
                         category=category,
                         category_name=category_names[category],
                         total_programs=len(programs),
                         today=datetime.utcnow().date())

@community_bp.route('/program/<int:program_id>')
@login_required
@role_required('community')
def program_detail(program_id):
    """Display detailed information about a specific program"""
    program = Programs.query.get_or_404(program_id)
    
    # Get user's community profile
    user_profile = current_user.community_profile
    
    # Get program requirements with is_mandatory info from junction table
    program_requirements = db.session.query(
        Requirements, ProgramRequirements.is_mandatory
    ).join(
        ProgramRequirements, 
        Requirements.id == ProgramRequirements.requirement_id
    ).filter(
        ProgramRequirements.program_id == program_id
    ).all()
    
    # Helper function to check if user meets a qualification
    def check_qualification(requirement_name, description):
        """Check if user meets a qualification based on requirement name and description"""
        if not user_profile:
            return False
        
        req_lower = requirement_name.lower()
        desc_lower = description.lower() if description else ''
        combined = req_lower + ' ' + desc_lower
        
        # Age-based qualifications
        if 'age' in combined or 'years old' in combined or 'senior' in combined:
            if user_profile.age:
                if 'senior' in combined or '60' in combined:
                    return user_profile.age >= 60
                elif '18' in combined:
                    return user_profile.age >= 18
                # Check for age range patterns
                import re
                age_match = re.search(r'(\d+)[-\s](?:to|and)[-\s](\d+)', combined)
                if age_match:
                    min_age, max_age = int(age_match.group(1)), int(age_match.group(2))
                    return min_age <= user_profile.age <= max_age
        
        # Employment status
        if 'employed' in combined or 'employment' in combined:
            if 'unemployed' in combined or 'not employed' in combined:
                return not user_profile.is_currently_employed
            else:
                return user_profile.is_currently_employed
        
        # Student status
        if 'student' in combined:
            return user_profile.is_student
        
        # Solo parent
        if 'solo parent' in combined or 'single parent' in combined:
            return user_profile.is_solo_parent
        
        # PWD status
        if 'pwd' in combined or 'disability' in combined or 'disabled' in combined:
            return user_profile.is_pwd
        
        # Location-based
        if 'resident' in combined or 'barangay' in combined or 'mabitac' in combined:
            return user_profile.barangay is not None
        
        # Income-based
        if 'income' in combined or 'indigent' in combined or 'poverty' in combined:
            if user_profile.family_annual_income:
                # Assuming low income threshold is 250,000 PHP per year
                if 'low income' in combined or 'indigent' in combined:
                    return user_profile.family_annual_income <= 20000
        
        # Default: unable to determine
        return None  # None means we can't auto-determine
    
    # Separate requirements by type and check qualifications
    document_requirements = []
    qualification_requirements = []
    
    for req, is_mandatory in program_requirements:
        req_data = {
            'id': req.id,
            'requirement_name': req.requirement_name,
            'description': req.description,
            'is_mandatory': is_mandatory,
            'requirement_type': req.requirement_type
        }
        
        if req.requirement_type == 'document':
            document_requirements.append(req_data)
        elif req.requirement_type == 'qualification':
            # Check if user meets this qualification
            meets_qualification = check_qualification(req.requirement_name, req.description)
            req_data['is_qualified'] = meets_qualification
            qualification_requirements.append(req_data)
    
    # Check if program has reached beneficiary limit
    is_full = False
    approved_count = 0
    if program.beneficiary_limit:
        approved_count = Applications.query.filter_by(
            program_id=program_id,
            application_status='approved'
        ).count()
        is_full = approved_count >= program.beneficiary_limit
    
    # Get profile completion status
    completion_data = calculate_profile_completion(current_user)
    
    return render_template('community/program_detail.html',
                         program=program,
                         document_requirements=document_requirements,
                         qualification_requirements=qualification_requirements,
                         user_profile=user_profile,
                         is_full=is_full,
                         approved_count=approved_count,
                         completion=completion_data,
                         today=datetime.utcnow().date())
    
@community_bp.route('/program/<int:program_id>/apply', methods=['POST'])
@login_required
@role_required('community')
def submit_application(program_id):
    """Create an application for a program"""
    program = Programs.query.get_or_404(program_id)
    
    # Check if program application period has ended
    if program.end_date and program.end_date < datetime.utcnow().date():
        flash(f'The application period for this program ended on {program.end_date.strftime("%B %d, %Y")}. Applications are no longer being accepted.', 'danger')
        return redirect(url_for('community.program_detail', program_id=program_id))
    
    # Check if profile is complete before allowing application
    completion_data = calculate_profile_completion(current_user)
    if not completion_data['is_complete']:
        flash(f'Please complete your profile before applying for programs. You have {completion_data["missing_count"]} required fields missing.', 'warning')
        return redirect(url_for('community.edit_profile'))
    
    # Check if user already has a pending application
    existing_application = Applications.query.filter_by(
        user_id=current_user.id,
        program_id=program_id
    ).filter(Applications.application_status.in_(['pending', 'submitted', 'under_review'])).first()
    
    if existing_application:
        flash('You already have a pending application for this program.', 'warning')
        return redirect(url_for('community.program_detail', program_id=program_id))
    
    # Check if program has reached beneficiary limit
    if program.beneficiary_limit:
        approved_count = Applications.query.filter_by(
            program_id=program_id,
            application_status='approved'
        ).count()
        
        if approved_count >= program.beneficiary_limit:
            flash(f'This program has reached its maximum capacity of {program.beneficiary_limit} beneficiaries. Applications are no longer being accepted.', 'warning')
            return redirect(url_for('community.program_detail', program_id=program_id))
    
    # Create new application
    new_application = Applications(
        user_id=current_user.id,
        program_id=program_id,
        application_status='pending',
        document_upload_status='pending',  # Set initial upload status
        application_date=datetime.utcnow()
    )
    
    db.session.add(new_application)
    db.session.flush()  # Get the ID
    
    # Get requirements and create application documents checklist
    # Set status to 'pending' so admin can verify documents submitted at MSWD office
    program_requirements = ProgramRequirements.query.filter_by(program_id=program_id).all()
    for req_link in program_requirements:
        app_doc = ApplicationDocuments(
            application_id=new_application.id,
            requirement_id=req_link.requirement_id,
            submission_status='pending'
        )
        db.session.add(app_doc)
    
    # Create notification
    notification = Notifications(
        user_id=current_user.id,
        notif_title='Application Submitted',
        notif_message=f'Your application for {program.program_name} has been created. Please upload your documents for initial verification.',
        is_read=False,
        related_id=new_application.id,
        related_type='application'
    )
    db.session.add(notification)
    db.session.commit()
    
    flash('Application submitted! Please upload your documents for initial verification before proceeding to physical submission.', 'success')
    
    # Redirect to document upload page
    return redirect(url_for('community.upload_documents', application_id=new_application.id))

@community_bp.route('/application/<int:application_id>/upload-shelter-photos', methods=['POST'])
@login_required
@role_required('community')
def upload_shelter_photos(application_id):
    """Upload shelter photos for ESA program applications"""
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    # Verify this is an ESA program
    if application.program.program_type != 'ESA':
        flash('Shelter photos are only required for Emergency Shelter Assistance (ESA) programs.', 'warning')
        return redirect(url_for('community.application_detail', application_id=application_id))
    
    uploaded_files = request.files.getlist('shelter_photos')
    captions = request.form.getlist('photo_captions')
    
    # Check current photo count
    current_photos = len(application.shelter_photos)
    new_photos = len([f for f in uploaded_files if f.filename])
    total_after_upload = current_photos + new_photos
    
    if not uploaded_files or not any(f.filename for f in uploaded_files):
        flash('Please select at least one photo to upload.', 'warning')
        return redirect(url_for('community.application_detail', application_id=application_id))
    
    # Check if adding these photos will meet the minimum requirement
    if total_after_upload < 3:
        flash(f'ESA applications require a minimum of 3 shelter photos. You currently have {current_photos} and are uploading {new_photos}. Please upload {3 - total_after_upload} more photo(s).', 'warning')
        # Still allow upload but inform about requirement
    
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    
    uploaded_count = 0
    
    try:
        for idx, file in enumerate(uploaded_files):
            if file and file.filename:
                # Check file extension
                if '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS:
                    # Check file size
                    file.seek(0, os.SEEK_END)
                    file_size = file.tell()
                    file.seek(0)
                    
                    if file_size > MAX_FILE_SIZE:
                        flash(f'File {file.filename} is too large. Maximum size is 5MB.', 'warning')
                        continue
                    
                    # Create upload directory
                    upload_path = os.path.join('static', 'uploads', 'shelter_photos', str(application_id))
                    os.makedirs(upload_path, exist_ok=True)
                    
                    # Secure filename and save
                    filename = secure_filename(file.filename)
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    unique_filename = f"{timestamp}_{idx}_{filename}"
                    file_path = os.path.join(upload_path, unique_filename)
                    
                    file.save(file_path)
                    
                    # Get caption if provided
                    caption = captions[idx] if idx < len(captions) else ''
                    
                    # Save to database
                    shelter_photo = ShelterPhotos(
                        application_id=application_id,
                        photo_path=file_path.replace('\\', '/'),
                        caption=caption,
                        verification_status='pending'
                    )
                    db.session.add(shelter_photo)
                    uploaded_count += 1
        
        db.session.commit()
        
        if uploaded_count > 0:
            total_photos_now = len(application.shelter_photos)
            if total_photos_now >= 3:
                flash(f'Successfully uploaded {uploaded_count} shelter photo(s)! You now have {total_photos_now} photos meeting the minimum requirement.', 'success')
            else:
                remaining = 3 - total_photos_now
                flash(f'Successfully uploaded {uploaded_count} shelter photo(s)! You need {remaining} more photo(s) to meet the minimum requirement of 3 photos.', 'warning')
        else:
            flash('No valid photos were uploaded.', 'warning')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Error uploading photos: {str(e)}', 'danger')
    
    return redirect(url_for('community.application_detail', application_id=application_id))

@community_bp.route('/shelter-photo/<int:photo_id>/delete', methods=['POST'])
@login_required
@role_required('community')
def delete_shelter_photo(photo_id):
    """Delete a shelter photo"""
    photo = ShelterPhotos.query.get_or_404(photo_id)
    
    # Verify ownership
    if photo.application.user_id != current_user.id:
        flash('You do not have permission to delete this photo.', 'danger')
        return redirect(url_for('community.applications'))
    
    # Only allow deletion if not yet verified
    if photo.verification_status == 'approved':
        flash('Cannot delete an approved photo.', 'warning')
        return redirect(url_for('community.application_detail', application_id=photo.application_id))
    
    try:
        # Delete file from filesystem
        if os.path.exists(photo.photo_path):
            os.remove(photo.photo_path)
        
        application_id = photo.application_id
        db.session.delete(photo)
        db.session.commit()
        
        flash('Shelter photo deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting photo: {str(e)}', 'danger')
    
    return redirect(url_for('community.application_detail', application_id=application_id))


# ===================== CA (Capital Assistance) Routes =====================

from app.models import CALDocuments

@community_bp.route('/application/<int:application_id>/upload-ca-documents', methods=['POST'])
@login_required
@role_required('community')
def upload_cal_documents(application_id):
    """Upload Certificate of Participation and/or Proposal for CA applications"""
    application = Applications.query.filter_by(
        id=application_id,
        user_id=current_user.id
    ).first_or_404()
    
    # Verify this is a CA program
    if application.program.program_type != 'CA':
        flash('This upload is only for CA program applications.', 'danger')
        return redirect(url_for('community.application_detail', application_id=application_id))
    
    certificate_file = request.files.get('certificate')
    proposal_file = request.files.get('proposal')
    proposal_description = request.form.get('proposal_description', '').strip()
    
    if not certificate_file and not proposal_file:
        flash('Please upload at least one document.', 'warning')
        return redirect(url_for('community.application_detail', application_id=application_id))
    
    ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx'}
    
    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    
    try:
        upload_path = os.path.join('static', 'uploads', 'cal_documents', str(application_id))
        os.makedirs(upload_path, exist_ok=True)
        
        uploaded_docs = []
        
        # Process Certificate of Participation
        if certificate_file and certificate_file.filename:
            if not allowed_file(certificate_file.filename):
                flash('Invalid file type for certificate. Allowed: PDF, JPG, PNG, DOC, DOCX', 'danger')
                return redirect(url_for('community.application_detail', application_id=application_id))
            
            # Check if certificate already exists
            existing_cert = CALDocuments.query.filter_by(
                application_id=application_id,
                document_type='certificate'
            ).first()
            
            if existing_cert and existing_cert.verification_status == 'approved':
                flash('Certificate already approved. Cannot replace.', 'warning')
            else:
                # Delete old file if exists
                if existing_cert:
                    if os.path.exists(existing_cert.file_path):
                        os.remove(existing_cert.file_path)
                    db.session.delete(existing_cert)
                
                filename = secure_filename(f"certificate_{application_id}_{certificate_file.filename}")
                file_path = os.path.join(upload_path, filename)
                certificate_file.save(file_path)
                
                cal_doc = CALDocuments(
                    application_id=application_id,
                    document_type='certificate',
                    file_path=file_path,
                    original_filename=certificate_file.filename,
                    description='Certificate of Participation - Seminar/Training'
                )
                db.session.add(cal_doc)
                uploaded_docs.append('Certificate of Participation')
        
        # Process Proposal
        if proposal_file and proposal_file.filename:
            if not allowed_file(proposal_file.filename):
                flash('Invalid file type for proposal. Allowed: PDF, JPG, PNG, DOC, DOCX', 'danger')
                return redirect(url_for('community.application_detail', application_id=application_id))
            
            # Check if proposal already exists
            existing_proposal = CALDocuments.query.filter_by(
                application_id=application_id,
                document_type='proposal'
            ).first()
            
            if existing_proposal and existing_proposal.verification_status == 'approved':
                flash('Proposal already approved. Cannot replace.', 'warning')
            else:
                # Delete old file if exists
                if existing_proposal:
                    if os.path.exists(existing_proposal.file_path):
                        os.remove(existing_proposal.file_path)
                    db.session.delete(existing_proposal)
                
                filename = secure_filename(f"proposal_{application_id}_{proposal_file.filename}")
                file_path = os.path.join(upload_path, filename)
                proposal_file.save(file_path)
                
                cal_doc = CALDocuments(
                    application_id=application_id,
                    document_type='proposal',
                    file_path=file_path,
                    original_filename=proposal_file.filename,
                    description=proposal_description or 'Capital Assistance Proposal'
                )
                db.session.add(cal_doc)
                uploaded_docs.append('Proposal')
        
        db.session.commit()
        
        if uploaded_docs:
            flash(f'Successfully uploaded: {", ".join(uploaded_docs)}', 'success')
            
            # Create notification for admin
            from app.models import Notifications, User
            admins = User.query.filter_by(role='admin').all()
            for admin in admins:
                notif = Notifications(
                    user_id=admin.id,
                    notif_title='CA Documents Uploaded',
                    notif_message=f'{application.applicant.first_name} {application.applicant.last_name} has uploaded CA documents for {application.program.program_name}. Please review.',
                    is_read=False,
                    related_id=application_id,
                    related_type='application'
                )
                db.session.add(notif)
            db.session.commit()
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error uploading documents: {str(e)}', 'danger')
    
    return redirect(url_for('community.application_detail', application_id=application_id))


@community_bp.route('/ca-document/<int:doc_id>/delete', methods=['POST'])
@login_required
@role_required('community')
def delete_ca_document(doc_id):
    """Delete a CA document (Certificate or Proposal)"""
    cal_doc = CALDocuments.query.get_or_404(doc_id)
    
    # Verify ownership
    if cal_doc.application.user_id != current_user.id:
        flash('You do not have permission to delete this document.', 'danger')
        return redirect(url_for('community.applications'))
    
    # Only allow deletion if not yet approved
    if cal_doc.verification_status == 'approved':
        flash('Cannot delete an approved document.', 'warning')
        return redirect(url_for('community.application_detail', application_id=cal_doc.application_id))
    
    try:
        # Delete file from filesystem
        if os.path.exists(cal_doc.file_path):
            os.remove(cal_doc.file_path)
        
        application_id = cal_doc.application_id
        doc_type = cal_doc.document_type
        db.session.delete(cal_doc)
        db.session.commit()
        
        flash(f'{doc_type.title()} deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting document: {str(e)}', 'danger')
    
    return redirect(url_for('community.application_detail', application_id=application_id))