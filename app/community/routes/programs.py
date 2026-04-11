from flask import render_template, jsonify, redirect, url_for, request, flash, send_file, current_app
from flask_login import login_required, current_user
from app.community import community_bp
from datetime import datetime
from dateutil.relativedelta import relativedelta
from app.models import Programs, Requirements, ProgramRequirements, Applications, ApplicationDocuments, Notifications, ShelterPhotos, SavedProgram, HiddenProgram, ProgramWorkflowSteps, ApplicationWorkflowStatus, AdminUsers, User
from app.extensions import db
from app.utils import role_required, calculate_profile_completion, evaluate_program_profile_eligibility, manila_strftime
from app.user_activity_logger import log_program_detail_view, log_application_started, log_save_program, log_unsave_program, log_hide_program, log_unhide_program, log_search_query
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename
import os
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def _get_current_user_municipality():
    """Return the logged-in community user's municipality."""
    profile = getattr(current_user, 'community_profile', None)
    if not profile or not profile.municipality:
        return None
    return profile.municipality.strip()


def _municipality_program_query():
    """Programs created by admins assigned to the current user's municipality."""
    municipality = _get_current_user_municipality()
    if not municipality:
        return db.session.query(Programs).filter(False)

    municipality_key = municipality.lower()
    return db.session.query(Programs).select_from(Programs).join(
        User, Programs.user_id == User.id
    ).join(
        AdminUsers, AdminUsers.user_id == User.id
    ).options(
        joinedload(Programs.creator)
    ).filter(
        User.role == 'admin',
        func.lower(func.trim(AdminUsers.municipality)) == municipality_key
    )


def _get_scoped_program_or_none(program_id):
    """Return a program only if it belongs to an admin in the user's municipality."""
    return _municipality_program_query().filter(Programs.id == program_id).first()


def _build_user_profile_document(profile, activity_signals=None):
    """Build a normalized text profile used for content-based matching."""
    if not profile:
        return ''

    activity_signals = activity_signals or {}
    tokens = []

    # Explicitly include areas of concern as primary preference signals.
    areas = [str(a).strip().lower() for a in (profile.get_areas_of_concern() or []) if str(a).strip()]
    tokens.extend(areas)
    tokens.extend(areas)

    if profile.is_student:
        tokens.append('student education scholarship training')
    if profile.is_solo_parent:
        tokens.append('solo parent family support')
    if profile.is_pwd:
        tokens.append('pwd disability special assistance medical')
    if profile.age and profile.age >= 60:
        tokens.append('senior citizen elderly')

    if profile.is_currently_employed:
        tokens.append('employed livelihood')
    else:
        tokens.append('unemployed job livelihood support')

    if profile.income_category:
        tokens.append(str(profile.income_category).lower())
    if profile.occupation:
        tokens.append(str(profile.occupation).lower())
    if profile.occupation_sector:
        tokens.append(str(profile.occupation_sector).lower())

    # Activity-based personalization signals
    saved_program_text = activity_signals.get('saved_program_text', '')
    applied_program_text = activity_signals.get('applied_program_text', '')
    if saved_program_text:
        tokens.append(saved_program_text)
        tokens.append(saved_program_text)
    if applied_program_text:
        tokens.append(applied_program_text)

    return ' '.join(tokens).strip()


def _build_program_document(program):
    """Build a program text representation for TF-IDF vectorization."""
    type_hints = {
        'AICS': 'medical emergency crisis food education transportation social assistance',
        'ESA': 'emergency shelter disaster housing calamity relief',
        '4Ps': 'education family children conditional cash transfer poverty',
        'CA': 'business livelihood entrepreneurship capital assistance employment skills'
    }

    parts = [
        str(program.program_name or ''),
        str(program.description or ''),
        str(program.priority_group or ''),
        str(program.income_range or ''),
        str(program.program_type or ''),
        type_hints.get(program.program_type, '')
    ]
    return ' '.join(parts).lower().strip()


def _build_recommendation_reasons(program, profile, activity_signals, saved_ids):
    """Generate simple user-facing reasons for why a program was recommended."""
    reasons = []
    haystack = ' '.join([
        str(program.program_name or ''),
        str(program.description or ''),
        str(program.priority_group or ''),
        str(program.program_type or '')
    ]).lower()

    areas = [str(a).strip() for a in (profile.get_areas_of_concern() or []) if str(a).strip()] if profile else []
    matched_areas = [area for area in areas if area.lower() in haystack]
    if matched_areas:
        reasons.append(f"Matches your selected areas of concern: {', '.join(matched_areas[:2])}.")

    if profile and profile.is_student and ('student' in haystack or 'education' in haystack):
        reasons.append('Aligned with your student and education profile.')
    if profile and profile.is_solo_parent and 'solo parent' in haystack:
        reasons.append('Aligned with solo parent support priorities.')
    if profile and profile.is_pwd and ('pwd' in haystack or 'disability' in haystack):
        reasons.append('Aligned with PWD-related assistance.')
    if profile and profile.income_category and str(profile.income_category).lower() in haystack:
        reasons.append('Matches your income category profile.')

    applied_types = activity_signals.get('applied_program_types', set())
    program_type = str(program.program_type or '').strip().upper()
    if program_type and program_type in applied_types:
        reasons.append('Similar to programs you previously applied to.')

    if program.id in saved_ids:
        reasons.append('You previously saved a related program.')

    if not reasons:
        reasons.append('Recommended based on overall similarity to your profile and activity history.')
    return reasons


def _get_content_based_recommended_programs(user, limit=4):
    """Return top-N program recommendations using TF-IDF + cosine similarity."""
    profile = user.community_profile
    hidden_ids = [p.program_id for p in HiddenProgram.query.filter_by(user_id=user.id).all()]
    saved_ids = [p.program_id for p in SavedProgram.query.filter_by(user_id=user.id).all()]
    applied_rows = db.session.query(Programs.program_type, Programs.program_name, Programs.description).join(
        Applications, Applications.program_id == Programs.id
    ).filter(
        Applications.user_id == user.id
    ).all()

    saved_rows = _municipality_program_query().filter(Programs.id.in_(saved_ids)).all() if saved_ids else []

    activity_signals = {
        'saved_program_text': ' '.join(
            f"{row.program_name or ''} {row.description or ''} {row.program_type or ''}" for row in saved_rows
        ).lower(),
        'applied_program_text': ' '.join(
            f"{name or ''} {desc or ''} {ptype or ''}" for ptype, name, desc in applied_rows
        ).lower(),
        'applied_program_types': {str(ptype).strip().upper() for ptype, _, _ in applied_rows if ptype}
    }

    user_document = _build_user_profile_document(profile, activity_signals=activity_signals)
    if not user_document:
        return []

    active_programs = _municipality_program_query().filter(Programs.is_active.is_(True)).all()

    candidate_programs = [
        p for p in active_programs
        if p.id not in hidden_ids and not is_emergency_program(p)
    ]

    if not candidate_programs:
        return []

    program_documents = [_build_program_document(program) for program in candidate_programs]
    corpus = [user_document] + program_documents

    vectorizer = TfidfVectorizer(stop_words='english', ngram_range=(1, 2), min_df=1)
    tfidf_matrix = vectorizer.fit_transform(corpus)

    user_vector = tfidf_matrix[0:1]
    program_vectors = tfidf_matrix[1:]
    similarities = cosine_similarity(user_vector, program_vectors)[0]

    applied_types = activity_signals.get('applied_program_types', set())
    scored = []
    for index, score in enumerate(similarities):
        if score <= 0:
            continue

        program = candidate_programs[index]
        final_score = float(score)

        # Similar-program history boost: prioritize programs similar to what user already applied for.
        if str(program.program_type or '').strip().upper() in applied_types:
            final_score += 0.08

        # Positive feedback boost for saved programs.
        if program.id in saved_ids:
            final_score += 0.05

        # Hidden programs are filtered out above; this is kept as a defensive guard.
        if program.id in hidden_ids:
            continue

        scored.append((program, final_score))

    scored.sort(key=lambda row: row[1], reverse=True)

    recommended = []
    for program, score in scored[:limit]:
        program.recommendation_score = round(score, 3)
        program.recommendation_reasons = _build_recommendation_reasons(
            program,
            profile,
            activity_signals,
            saved_ids
        )
        recommended.append(program)
    return recommended


def is_emergency_program(program):
    """Check if a program is an emergency-type program."""
    if not program:
        return False
    type_text = str(program.program_type or '').strip().lower()
    name_text = str(program.program_name or '').strip().lower()
    desc_text = str(program.description or '').strip().lower()
    priority_text = str(program.priority_group or '').strip().lower()
    period_text = str(program.program_period or '').strip().lower()
    haystack = ' '.join([type_text, name_text, desc_text, priority_text, period_text])
    return (
        type_text == 'esa'
        or period_text == 'emergency'
        or 'emergency' in haystack
        or 'burial assistance' in haystack
        or 'funeral assistance' in haystack
        or 'burial' in name_text
        or 'funeral' in name_text
    )


def get_application_restriction(user_id, program_id=None):
    """Return application restrictions for a user based on active and recent completed applications."""
    
    # Check for ongoing application for THIS SPECIFIC PROGRAM
    if program_id:
        active_application = Applications.query.filter(
            Applications.user_id == user_id,
            Applications.program_id == program_id,
            Applications.application_status.in_(['pending', 'approved', 'active'])
        ).order_by(Applications.application_date.desc()).first()

        if active_application:
            return {
                'is_blocked': True,
                'type': 'active_application',
                'application': active_application,
                'program_name': active_application.program.program_name if active_application.program else 'this program',
                'message': 'You already have an ongoing application for this program. Please complete or resolve it before applying again.'
            }

    # Check for cooldown period (only applicable to non-emergency programs)
    # Skip cooldown for emergency-period/type programs as they're crisis-response programs
    current_program = Programs.query.get(program_id) if program_id else None
    if not is_emergency_program(current_program):
        cooldown_reference = datetime.utcnow() - relativedelta(months=3)
        recent_applications = Applications.query.filter(
            Applications.user_id == user_id,
            or_(
                Applications.application_status == 'completed',
                Applications.claim_date.isnot(None)
            )
        ).order_by(Applications.updated_at.desc()).all()

        for app in recent_applications:
            reference_date = app.claim_date or app.updated_at or app.review_date or app.application_date
            if reference_date and reference_date >= cooldown_reference:
                # But check if the completed/claimed program was also an emergency program
                # If it was emergency, don't apply cooldown
                completed_program = app.program if hasattr(app, 'program') else None
                if not is_emergency_program(completed_program):
                    lock_until = (reference_date + relativedelta(months=3)).date()
                    return {
                        'is_blocked': True,
                        'type': 'cooldown',
                        'application': app,
                        'program_name': app.program.program_name if app.program else 'your previous program',
                        'reference_date': reference_date,
                        'lock_until': lock_until,
                        'message': f'You can apply again after {manila_strftime(lock_until, "%B %d, %Y", "N/A")} due to the 3-month cooldown after completion or scheduled release.'
                    }

    return {
        'is_blocked': False,
        'type': None,
        'application': None,
        'message': None
    }

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
        count = _municipality_program_query().filter(Programs.program_type == category_key).count()
        program_stats[category_key] = {
            'name': category_name,
            'count': count
        }
        total_programs += count
    
    # Total categories count
    total_categories = len(categories)
    recommended_programs = _get_content_based_recommended_programs(current_user)
    
    return render_template('community/programs_category.html',
                         categories=program_stats,
                         total_categories=total_categories,
                         total_programs=total_programs,
                         recommended_programs=recommended_programs,
                         today=datetime.utcnow().date())

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
    
    if category not in category_names:
        return redirect(url_for('community.programs'))
    
    # Get programs for this category
    programs = _municipality_program_query().filter(Programs.program_type == category).order_by(desc(Programs.date)).all()
    
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
    program = _get_scoped_program_or_none(program_id)
    if not program:
        flash('This program is not available for your municipality.', 'warning')
        return redirect(url_for('community.programs'))
    
    # Get user's community profile
    user_profile = current_user.community_profile
    profile_eligibility = evaluate_program_profile_eligibility(program.priority_group, user_profile)
    
    # Get program requirements with is_mandatory info from junction table
    program_requirements = db.session.query(
        Requirements, ProgramRequirements
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
    
    for req, prog_req in program_requirements:
        import json
        
        # Parse copy specifications from JSON
        try:
            copy_specs = json.loads(prog_req.copy_type) if isinstance(prog_req.copy_type, str) else prog_req.copy_type
        except:
            copy_specs = [{"type": "original", "count": 1}]
        
        req_data = {
            'id': req.id,
            'requirement_name': req.requirement_name,
            'description': req.description,
            'is_mandatory': prog_req.is_mandatory,
            'requirement_type': req.requirement_type,
            'copy_specs': copy_specs  # New: list of {type, count}
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
        approved_count = Applications.query.filter(
            Applications.program_id == program_id,
            Applications.application_status.in_(['approved', 'active', 'completed'])
        ).count()
        is_full = approved_count >= program.beneficiary_limit
    
    # Get profile completion status
    completion_data = calculate_profile_completion(current_user)
    
    # Check if user has saved/hidden this program
    is_saved = SavedProgram.query.filter_by(user_id=current_user.id, program_id=program_id).first() is not None
    is_hidden = HiddenProgram.query.filter_by(user_id=current_user.id, program_id=program_id).first() is not None
    application_restriction = get_application_restriction(current_user.id, program_id)
    
    # Log detail view
    log_program_detail_view(program)
    db.session.commit()
    
    return render_template('community/program_detail.html',
                         program=program,
                         document_requirements=document_requirements,
                         qualification_requirements=qualification_requirements,
                         user_profile=user_profile,
                         is_full=is_full,
                         profile_eligibility=profile_eligibility,
                         approved_count=approved_count,
                         completion=completion_data,
                         application_restriction=application_restriction,
                         is_saved=is_saved,
                         is_hidden=is_hidden,
                         today=datetime.utcnow().date())
    
@community_bp.route('/program/<int:program_id>/apply', methods=['POST'])
@login_required
@role_required('community')
def submit_application(program_id):
    """Create an application for a program"""
    program = _get_scoped_program_or_none(program_id)
    if not program:
        flash('This program is not available for your municipality.', 'warning')
        return redirect(url_for('community.programs'))
    
    # Check if program application period has ended
    if program.end_date and program.end_date < datetime.utcnow().date():
        flash(f'The application period for this program ended on {program.end_date.strftime("%B %d, %Y")}. Applications are no longer being accepted.', 'danger')
        return redirect(url_for('community.program_detail', program_id=program_id))
    
    # Check if profile is complete before allowing application
    completion_data = calculate_profile_completion(current_user)
    if not completion_data['is_complete']:
        flash(f'Please complete your profile before applying for programs. You have {completion_data["missing_count"]} required fields missing.', 'warning')
        return redirect(url_for('community.edit_profile'))

    # Enforce profile-based eligibility based on selected program priority groups.
    profile_eligibility = evaluate_program_profile_eligibility(program.priority_group, current_user.community_profile)
    if not profile_eligibility['is_eligible']:
        required_groups = ', '.join(g.title() for g in profile_eligibility['required_groups'])
        flash(
            f'You are not eligible to apply for this program. Allowed profile groups: {required_groups}.',
            'danger'
        )
        return redirect(url_for('community.program_detail', program_id=program_id))
    
    # Restrict concurrent applications and enforce cooldown after completion/scheduled release
    application_restriction = get_application_restriction(current_user.id, program_id)
    if application_restriction['is_blocked']:
        if application_restriction['type'] == 'active_application':
            flash(
                f'You already have an ongoing application for {application_restriction["program_name"]}. '
                'Please complete or resolve it before applying to another program.',
                'warning'
            )
        else:
            flash(application_restriction['message'], 'warning')
        return redirect(url_for('community.program_detail', program_id=program_id))
    
    # Check if program has reached beneficiary limit
    if program.beneficiary_limit:
        approved_count = Applications.query.filter(
            Applications.program_id == program_id,
            Applications.application_status.in_(['approved', 'active', 'completed'])
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
    
    # Initialize workflow status for all workflow steps
    # This ensures workflow status records are created immediately on application submission
    workflow_steps = program.workflow_steps if program.workflow_steps else []
    for step in workflow_steps:
        existing_status = ApplicationWorkflowStatus.query.filter_by(
            application_id=new_application.id,
            workflow_step_id=step.id
        ).first()
        
        if not existing_status:
            status = ApplicationWorkflowStatus(
                application_id=new_application.id,
                workflow_step_id=step.id,
                step_status='not_started'
            )
            db.session.add(status)
    
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
    
    # Log application started
    log_application_started(new_application, program)
    
    db.session.commit()
    
    flash('Application submitted! Please proceed with the workflow steps for initial verification.', 'success')
    
    # Redirect to application workflow
    return redirect(url_for('community.application_workflow', application_id=new_application.id))


@community_bp.route('/program/<int:program_id>/save', methods=['POST'])
@login_required
@role_required('community')
def save_program(program_id):
    """Save/bookmark a program."""
    program = _get_scoped_program_or_none(program_id)
    if not program:
        return jsonify({'status': 'error', 'message': 'Program is not available for your municipality'}), 404
    existing = SavedProgram.query.filter_by(user_id=current_user.id, program_id=program_id).first()
    
    if existing:
        # Unsave
        db.session.delete(existing)
        log_unsave_program(program)
        db.session.commit()
        return jsonify({'status': 'unsaved', 'message': 'Program removed from saved list'})
    else:
        # Save
        saved = SavedProgram(user_id=current_user.id, program_id=program_id)
        db.session.add(saved)
        log_save_program(program)
        db.session.commit()
        return jsonify({'status': 'saved', 'message': 'Program saved to your list'})


@community_bp.route('/program/<int:program_id>/hide', methods=['POST'])
@login_required
@role_required('community')
def hide_program(program_id):
    """Hide/mark a program as not interested."""
    program = _get_scoped_program_or_none(program_id)
    if not program:
        return jsonify({'status': 'error', 'message': 'Program is not available for your municipality'}), 404
    existing = HiddenProgram.query.filter_by(user_id=current_user.id, program_id=program_id).first()
    
    if existing:
        # Unhide
        db.session.delete(existing)
        log_unhide_program(program)
        db.session.commit()
        return jsonify({'status': 'unhidden', 'message': 'Program is now visible again'})
    else:
        # Hide
        hidden = HiddenProgram(user_id=current_user.id, program_id=program_id)
        db.session.add(hidden)
        log_hide_program(program)
        db.session.commit()
        return jsonify({'status': 'hidden', 'message': 'Program hidden from your list'})


@community_bp.route('/programs/search')
@login_required
@role_required('community')
def search_programs():
    """Search and filter programs with activity logging."""
    query_text = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    
    filters = {}
    if category:
        filters['category'] = category
    
    programs_query = _municipality_program_query()
    
    if query_text:
        programs_query = programs_query.filter(
            db.or_(
                Programs.program_name.ilike(f'%{query_text}%'),
                Programs.description.ilike(f'%{query_text}%')
            )
        )
    
    if category:
        programs_query = programs_query.filter(Programs.program_type == category)
    
    results = programs_query.order_by(desc(Programs.date)).all()
    
    # Log the search
    log_search_query(query_text, filters, len(results))
    db.session.commit()
    
    return jsonify({
        'results': [{
            'id': p.id,
            'name': p.program_name,
            'description': p.description[:150] if p.description else '',
            'type': p.program_type,
            'date': manila_strftime(p.date, '%B %d, %Y', None)
        } for p in results],
        'count': len(results)
    })


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
                    
                    # Create upload directory in Flask's static folder
                    upload_dir = os.path.join(current_app.static_folder, 'uploads', 'shelter_photos', str(application_id))
                    os.makedirs(upload_dir, exist_ok=True)
                    
                    # Secure filename and save
                    filename = secure_filename(file.filename)
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    unique_filename = f"{timestamp}_{idx}_{filename}"
                    file_path = os.path.join(upload_dir, unique_filename)
                    
                    file.save(file_path)
                    
                    # Get caption if provided
                    caption = captions[idx] if idx < len(captions) else ''
                    
                    # Save to database - store path relative to static folder
                    relative_path = os.path.join('uploads', 'shelter_photos', str(application_id), unique_filename).replace('\\', '/')
                    shelter_photo = ShelterPhotos(
                        application_id=application_id,
                        photo_path=f'uploads/shelter_photos/{application_id}/{unique_filename}',
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
        full_path = os.path.join(current_app.static_folder, photo.photo_path)
        if os.path.exists(full_path):
            os.remove(full_path)
        
        application_id = photo.application_id
        db.session.delete(photo)
        db.session.commit()
        
        flash('Shelter photo deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting photo: {str(e)}', 'danger')
    
    return redirect(url_for('community.application_detail', application_id=application_id))


@community_bp.route('/shelter-photo/<int:photo_id>/edit-caption', methods=['POST'])
@login_required
@role_required('community')
def edit_shelter_photo_caption(photo_id):
    """Edit the caption of a shelter photo"""
    photo = ShelterPhotos.query.get_or_404(photo_id)
    
    # Verify ownership
    if photo.application.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403
    
    # Only allow editing if not approved
    if photo.verification_status == 'approved':
        return jsonify({'success': False, 'message': 'Cannot edit approved photo'}), 400
    
    try:
        caption = request.form.get('caption', '').strip()
        photo.caption = caption if caption else None
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Caption updated successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500


@community_bp.route('/shelter-photo/<int:photo_id>/replace', methods=['POST'])
@login_required
@role_required('community')
def replace_shelter_photo(photo_id):
    """Replace an existing shelter photo with a new one"""
    photo = ShelterPhotos.query.get_or_404(photo_id)
    application = photo.application
    
    # Verify ownership
    if application.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403
    
    # Only allow replacement if not approved
    if photo.verification_status == 'approved':
        return jsonify({'success': False, 'message': 'Cannot replace approved photo'}), 400
    
    file = request.files.get('file')
    if not file or file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400
    
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    
    try:
        # Validate file
        file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        if file_ext not in ALLOWED_EXTENSIONS:
            return jsonify({'success': False, 'message': f'Invalid file type. Allowed: {", ".join(ALLOWED_EXTENSIONS)}'}), 400
        
        # Check file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > MAX_FILE_SIZE:
            return jsonify({'success': False, 'message': 'File is too large. Maximum size is 5MB.'}), 400
        
        # Delete old file
        old_full_path = os.path.join(current_app.static_folder, photo.photo_path)
        if os.path.exists(old_full_path):
            os.remove(old_full_path)
        
        # Save new file in same directory
        upload_dir = os.path.dirname(old_full_path)
        os.makedirs(upload_dir, exist_ok=True)
        
        filename = secure_filename(file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_replaced_{filename}"
        new_file_path = os.path.join(upload_dir, unique_filename)
        
        file.save(new_file_path)
        
        # Update database - store relative path
        photo.photo_path = f'uploads/shelter_photos/{application.id}/{unique_filename}'
        photo.verification_status = 'pending'  # Reset to pending for re-review
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Photo replaced successfully!',
            'photo_path': f'uploads/shelter_photos/{application.id}/{unique_filename}'
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Upload error: {str(e)}'}), 500


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