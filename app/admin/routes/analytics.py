
from flask import render_template, jsonify, request, redirect, url_for
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.utils import role_required
from app.models import Applications, Programs, CommunityUsers, User, Requirements, ProgramRequirements
from app.extensions import db
from app.forecasting import arima_forecast, forecast_program_growth, forecast_program_timeseries
from app.recommender import get_recommendations, SENIOR_CITIZEN_AGE, BeneficiaryRecommender
from app.config.recommender_configs import ConfigFactory, ConfigManager
from app.ml.explainer import BeneficiaryExplainer
from app.ml.fairness_auditor import FairnessAuditor
from app.ml.program_compatibility import ProgramCompatibilityScorer
from app.ml.weight_optimizer import WeightOptimizer
from app.activity_logger import log_recommendation_saved
from sqlalchemy import func, extract
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import json

# Default age for target profile when program priority group is not senior citizens;
# 30 represents a typical working-age beneficiary demographic
DEFAULT_TARGET_AGE = 30

@admin_bp.route('/adm_analytics')
@login_required
@role_required('admin')
def analytics():
    """Main analytics dashboard - redirect to analysis page"""
    return redirect(url_for('admin.analytics_analysis'))

@admin_bp.route('/adm_analytics/analysis')
@login_required
@role_required('admin')
def analytics_analysis():
    """Analysis page with graphs and statistics"""
    # Get date range for filtering (default: last 12 months)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=365)
    
    # 1. Applicants count over time (monthly aggregation)
    applicants_over_time_raw = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()
    
    # Convert to JSON-friendly format
    applicants_over_time = {
        'labels': [row.month.strftime('%B %Y') if row.month else '' for row in applicants_over_time_raw],
        'data': [row.count for row in applicants_over_time_raw]
    }
    
    # 2. Applications per program type
    applications_by_type_raw = db.session.query(
        Programs.program_type,
        func.count(Applications.id).label('count')
    ).join(
        Applications, Programs.id == Applications.program_id
    ).group_by(Programs.program_type).all()
    
    applications_by_type = {
        'labels': [row.program_type for row in applications_by_type_raw],
        'data': [row.count for row in applications_by_type_raw]
    }
    
    # 3. Applicants per barangay
    applicants_by_barangay_raw = db.session.query(
        CommunityUsers.barangay,
        func.count(Applications.id).label('count')
    ).join(
        User, CommunityUsers.user_id == User.id
    ).join(
        Applications, User.id == Applications.user_id
    ).filter(
        CommunityUsers.barangay.isnot(None)
    ).group_by(CommunityUsers.barangay).order_by(func.count(Applications.id).desc()).limit(10).all()
    
    applicants_by_barangay = {
        'labels': [row.barangay for row in applicants_by_barangay_raw],
        'data': [row.count for row in applicants_by_barangay_raw]
    }
    
    # Summary statistics
    total_applications = Applications.query.count()
    total_applicants = db.session.query(func.count(func.distinct(Applications.user_id))).scalar()
    total_programs = Programs.query.count()
    
    # Application status breakdown
    status_breakdown = db.session.query(
        Applications.application_status,
        func.count(Applications.id).label('count')
    ).group_by(Applications.application_status).all()
    
    return render_template(
        'admin/analytics_analysis.html',
        user=current_user,
        applicants_over_time_json=json.dumps(applicants_over_time),
        applications_by_type_json=json.dumps(applications_by_type),
        applicants_by_barangay_json=json.dumps(applicants_by_barangay),
        total_applications=total_applications,
        total_applicants=total_applicants,
        total_programs=total_programs,
        status_breakdown=status_breakdown
    )

@admin_bp.route('/adm_analytics/recommend')
@login_required
@role_required('admin')
def analytics_recommend():
    """Recommendation page for beneficiary selection"""
    # Exclude ESA and Emergency-period programs — they are crisis-response programs
    # that do not benefit from predictive beneficiary selection.
    programs = Programs.query.filter(
        Programs.program_type != 'ESA',
        Programs.program_period != 'Emergency'
    ).all()
    
    # Get available barangays
    barangays = db.session.query(
        CommunityUsers.barangay
    ).filter(
        CommunityUsers.barangay.isnot(None)
    ).distinct().all()
    
    return render_template(
        'admin/analytics_recommend.html',
        user=current_user,
        programs=programs,
        barangays=[b[0] for b in barangays]
    )

@admin_bp.route('/api/program/<int:program_id>/parameters')
@login_required
@role_required('admin')
def api_get_program_parameters(program_id):
    """API endpoint to fetch program parameters for auto-fill"""
    program = Programs.query.get_or_404(program_id)
    
    return jsonify({
        'success': True,
        'priority_group': program.priority_group,
        'income_range': program.income_range,
        'beneficiary_limit': program.beneficiary_limit
    })

@admin_bp.route('/api/analytics/applicants-timeseries')
@login_required
@role_required('admin')
def api_applicants_timeseries():
    """API endpoint for applicants time series data"""
    months = request.args.get('months', 18, type=int)  # Changed from 12 to 18 for better ARIMA accuracy
    end_date = datetime.utcnow()
    # Use relativedelta for accurate calendar-month arithmetic; timedelta(days=months*30)
    # undershoots by ~5 days/year and can exclude the earliest data point.
    start_date = end_date - relativedelta(months=months)
    
    data = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()
    
    return jsonify({
        'labels': [d.month.strftime('%B %Y') for d in data],
        'values': [d.count for d in data]
    })

@admin_bp.route('/api/analytics/generate-recommendations', methods=['POST'])
@login_required
@role_required('admin')
def api_generate_recommendations():
    """
    API endpoint to generate beneficiary recommendations using content-based filtering.
    
    Request Body (JSON):
        program_id: Target program ID for recommendations
        max_beneficiaries: Maximum number of recommendations to return (default: 50)
        priority_barangays: List of barangay names to filter by. If empty list or not 
                           provided, all barangays are included in recommendations.
        priority_groups: Comma-separated string of priority groups (e.g., "Solo Parent, Student, PWD, Senior Citizen")
                        Takes precedence over individual priority flags if provided.
        min_income: Minimum annual income filter (default: 0)
        max_income: Maximum annual income filter (default: 999999999)
        solo_parent_priority: Boolean to prioritize solo parents in scoring (default: False)
        student_priority: Boolean to prioritize students in scoring (default: False)
        pwd_priority: Boolean to prioritize PWDs in scoring (default: False)
        senior_citizen_priority: Boolean to prioritize senior citizens in scoring (default: False)
    
    Returns:
        JSON with success status, count, recommendations list, and message
    """
    data = request.get_json()
    
    # Extract parameters with validation
    program_id = data.get('program_id')

    # Reject requests for ESA or Emergency-period programs
    if program_id:
        _prog = Programs.query.get(program_id)
        if _prog and (_prog.program_type == 'ESA' or _prog.program_period == 'Emergency'):
            return jsonify({
                'success': False,
                'message': 'Recommendations are not available for ESA or Emergency-type programs.'
            }), 400
    
    try:
        max_beneficiaries = int(data.get('max_beneficiaries', 50))
        if max_beneficiaries < 1:
            return jsonify({'success': False, 'message': 'Max beneficiaries must be at least 1'}), 400
        if max_beneficiaries > 1000:
            return jsonify({'success': False, 'message': 'Max beneficiaries cannot exceed 1000'}), 400
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid max_beneficiaries value'}), 400
    
    # priority_barangays is a list of barangay names; empty list means include all barangays
    priority_barangays = data.get('priority_barangays', [])
    
    # Validate income range with comprehensive error handling
    try:
        min_income = float(data.get('min_income', 0) or 0)
        max_income = float(data.get('max_income', 10000000) or 10000000)
        
        # Validate min_income
        if min_income < 0:
            return jsonify({'success': False, 'message': 'Minimum income cannot be negative'}), 400
        if min_income > 10000000:
            return jsonify({'success': False, 'message': 'Minimum income exceeds maximum allowed value (₱10,000,000)'}), 400
        
        # Validate max_income
        if max_income < 0:
            return jsonify({'success': False, 'message': 'Maximum income cannot be negative'}), 400
        if max_income > 10000000:
            return jsonify({'success': False, 'message': 'Maximum income exceeds maximum allowed value (₱10,000,000)'}), 400
        
        # Validate range logic
        if min_income > max_income:
            return jsonify({'success': False, 'message': 'Minimum income cannot be greater than maximum income'}), 400
            
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': f'Invalid income range format: {str(e)}'}), 400
    
    # If a config_type is supplied, load defaults from the config framework
    # and let explicit request parameters override them.
    config_type = data.get('config_type')
    if config_type:
        try:
            preset = ConfigFactory.get_config(config_type)
        except KeyError:
            return jsonify({'success': False, 'message': f'Unknown config_type: {config_type}'}), 400
        # Apply preset defaults for values not explicitly provided
        if 'max_beneficiaries' not in data:
            max_beneficiaries = preset.max_beneficiaries
        if 'min_income' not in data:
            min_income = preset.min_income
        if 'max_income' not in data:
            max_income = preset.max_income
        if 'priority_barangays' not in data and preset.priority_barangays:
            priority_barangays = preset.priority_barangays

    solo_parent_priority = data.get('solo_parent_priority', preset.solo_parent_priority if config_type else False)
    student_priority = data.get('student_priority', preset.student_priority if config_type else False)
    pwd_priority = data.get('pwd_priority', preset.pwd_priority if config_type else False)
    senior_citizen_priority = data.get('senior_citizen_priority', preset.senior_citizen_priority if config_type else False)
    
    # Query all community users with their profiles
    query = db.session.query(
        User.id,
        User.first_name,
        User.last_name,
        User.email,
        CommunityUsers.age,
        CommunityUsers.barangay,
        CommunityUsers.family_annual_income,
        CommunityUsers.is_solo_parent,
        CommunityUsers.is_student,
        CommunityUsers.is_pwd,
        CommunityUsers.is_currently_employed,
        CommunityUsers.occupation
    ).join(
        CommunityUsers, User.id == CommunityUsers.user_id
    )
    
    all_users = query.all()

    # Build per-user application history map: user_id -> space-separated program names/types
    app_history_rows = (
        db.session.query(Applications.user_id, Programs.program_name, Programs.program_type)
        .join(Programs, Applications.program_id == Programs.id)
        .filter(Applications.application_status.in_(['approved', 'active', 'completed']))
        .all()
    )
    app_history_map: dict = {}
    for user_id, prog_name, prog_type in app_history_rows:
        tokens = ' '.join(filter(None, [prog_name, prog_type]))
        if user_id in app_history_map:
            app_history_map[user_id] += ' ' + tokens
        else:
            app_history_map[user_id] = tokens

    # Convert to list of dictionaries for the recommender with income validation
    beneficiaries_data = [
        {
            'user_id': u.id,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'email': u.email,
            'age': u.age,
            'barangay': u.barangay,
            'family_annual_income': float(u.family_annual_income) if u.family_annual_income and 0 <= u.family_annual_income <= 10000000 else 0,
            'is_solo_parent': u.is_solo_parent,
            'is_student': u.is_student,
            'is_pwd': u.is_pwd,
            'is_currently_employed': u.is_currently_employed,
            'occupation': u.occupation,
            'past_applications': app_history_map.get(u.id, ''),
        }
        for u in all_users
    ]

    # Exclude beneficiaries already enrolled (approved/completed) in the selected program
    if program_id:
        enrolled_user_ids = set(
            row[0] for row in db.session.query(Applications.user_id).filter(
                Applications.program_id == program_id,
                Applications.application_status.in_(['approved', 'completed'])
            ).all()
        )
        beneficiaries_data = [b for b in beneficiaries_data if b['user_id'] not in enrolled_user_ids]

    # Build a target_profile from the program's priority group and requirements so
    # that the CBF (content-based filtering) KNN pipeline can be used instead of
    # plain rule-based scoring.
    target_profile = None
    effective_priority_groups = data.get('priority_groups')
    if program_id:
        program = Programs.query.get(program_id)
        if program:
            if not effective_priority_groups and program.priority_group:
                effective_priority_groups = program.priority_group

            # Gather qualification requirements to build a rich text feature
            requirements = db.session.query(Requirements).join(
                ProgramRequirements, Requirements.id == ProgramRequirements.requirement_id
            ).filter(
                ProgramRequirements.program_id == program_id,
                Requirements.requirement_type == 'qualification'
            ).all()

            req_text = ' '.join([
                r.requirement_name + ' ' + (r.description or '')
                for r in requirements
            ])
            priority_group = (program.priority_group or '').lower()
            priority_tokens = [token.strip() for token in priority_group.split(',') if token.strip()]
            senior_targeted = any(
                token in {'senior', 'senior citizen', 'senior citizens', 'seniors', 'elderly'} or
                'senior' in token
                for token in priority_tokens
            )

            # Parse income range if available (e.g., "0-250000" or "Below 250,000")
            # sensible default for low-income programs
            max_inc = 250000
            if program.income_range:
                try:
                    parts = str(program.income_range).replace(',', '').replace(' ', '').split('-')
                    if len(parts) == 2:
                        max_inc = float(parts[1])
                except (ValueError, IndexError):
                    pass

            target_profile = {
                # Use a representative age aligned with recommender configuration
                'age': SENIOR_CITIZEN_AGE if senior_targeted else DEFAULT_TARGET_AGE,
                'family_annual_income': max_inc / 2,  # midpoint of target income range
                'barangay': 'Unknown',
                'is_solo_parent': 'solo parent' in priority_group or 'solo_parent' in priority_group,
                'is_student': 'student' in priority_group,
                'is_pwd': 'pwd' in priority_group or 'disability' in priority_group,
                'is_currently_employed': False,
                'occupation': req_text or program.description or '',
                # Represent the program itself as a past-application signal so that
                # beneficiaries who have applied to similar programs score higher.
                'past_applications': ' '.join(filter(None, [
                    program.program_name,
                    program.program_type,
                    program.priority_group or '',
                ])),
            }
    
    # Use content-based filtering (CBF) when a target_profile is available;
    # otherwise fall back to rule-based priority scoring.
    recommendations = get_recommendations(
        beneficiaries_data=beneficiaries_data,
        target_profile=target_profile,
        max_beneficiaries=max_beneficiaries,
        solo_parent_priority=solo_parent_priority,
        student_priority=student_priority,
        pwd_priority=pwd_priority,
        senior_citizen_priority=senior_citizen_priority,
        priority_barangays=priority_barangays if priority_barangays else None,
        priority_groups=effective_priority_groups,
        min_income=min_income,
        max_income=max_income
    )
    
    return jsonify({
        'success': True,
        'count': len(recommendations),
        'recommendations': [
            {
                'user_id': r.get('user_id'),
                'name': f"{r.get('first_name', '')} {r.get('last_name', '')}",
                'email': r.get('email', ''),
                'barangay': r.get('barangay', 'N/A'),
                'income': r.get('family_annual_income', 0),
                'age': r.get('age', None),
                'is_solo_parent': r.get('is_solo_parent', False),
                'is_student': r.get('is_student', False),
                'is_pwd': r.get('is_pwd', False),
                'is_senior': (r.get('age') or 0) >= 60,
                # CBF path produces similarity_score; rule-based path produces score.
                # Use whichever is non-zero so the UI always shows a meaningful value.
                'score': r.get('score') or r.get('similarity_score', 0.0) or 0.0,
                'score_breakdown': r.get('score_breakdown', {}),
                'similarity_score': r.get('similarity_score', None),
                'past_applications': r.get('past_applications', ''),
            }
            for r in recommendations
        ],
        'algorithm': 'content-based-knn' if target_profile else 'rule-based-scoring',
        'program_matched': program_id is not None,
        'priority_groups': effective_priority_groups or '',
        'message': 'Recommendations generated using content-based filtering algorithm'
    })


@admin_bp.route('/api/analytics/recommender-configs')
@login_required
@role_required('admin')
def api_recommender_configs():
    """List available pre-defined recommender configurations."""
    return jsonify({
        'success': True,
        'configs': ConfigFactory.list_available_detailed(),
    })


@admin_bp.route('/api/analytics/recommender-config/<config_type>')
@login_required
@role_required('admin')
def api_recommender_config_detail(config_type):
    """Return the full parameter set for a specific config type."""
    try:
        config = ConfigFactory.get_config(config_type)
    except KeyError:
        return jsonify({'success': False, 'message': f'Unknown config type: {config_type}'}), 404
    return jsonify({'success': True, 'config': config.to_dict()})


@admin_bp.route('/api/analytics/save-recommendations', methods=['POST'])
@login_required
@role_required('admin')
def api_save_recommendations():
    """Save/log a recommendation list generation for audit trail"""
    data = request.get_json()
    
    program_id = data.get('program_id')
    recommendation_count = data.get('count', 0)
    
    program = Programs.query.get(program_id) if program_id else None
    program_name = program.program_name if program else 'Unknown Program'
    
    try:
        log_recommendation_saved(
            program_name=program_name,
            recommendation_count=recommendation_count,
            details_extra={
                'program_id': program_id,
                'filters': data.get('filters', {}),
            }
        )
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Recommendation list saved to activity log'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/analytics/arima-forecast')
@login_required
@role_required('admin')
def api_arima_forecast():
    """API endpoint for ARIMA-based applicants forecast"""
    # Get parameters
    months = request.args.get('months', 18, type=int)  # Changed from 12 to 18 for better ARIMA accuracy
    forecast_periods = request.args.get('forecast_periods', 6, type=int)
    force_arima = request.args.get('force_arima', 'false').lower() == 'true'
    
    # Limit forecast periods for stability
    forecast_periods = min(forecast_periods, 12)
    
    end_date = datetime.utcnow()
    # Use relativedelta for accurate calendar-month arithmetic; timedelta(days=months*30)
    # undershoots by ~5 days/year and can exclude the earliest data point.
    start_date = end_date - relativedelta(months=months)
    
    # Query historical data
    historical_data = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).filter(
        Applications.application_date >= start_date
    ).group_by('month').order_by('month').all()
    
    # Prepare data for ARIMA
    labels = [d.month.strftime('%B %Y') for d in historical_data if d.month]
    values = [d.count for d in historical_data]
    
    # Generate ARIMA forecast with force mode
    forecast_result = arima_forecast(values, labels, periods=forecast_periods, force_arima=force_arima)
    
    return jsonify({
        'historical': {
            'labels': labels,
            'values': values
        },
        'forecast': forecast_result,
        'model': forecast_result.get('model', 'unknown'),
        'data_points': len(values),
        'force_arima_mode': force_arima,
        'arima_error': forecast_result.get('arima_error', None)
    })

@admin_bp.route('/api/analytics/program-forecast')
@login_required
@role_required('admin')
def api_program_forecast():
    """API endpoint for program category growth forecast"""
    growth_rate = request.args.get('growth_rate', type=float)
    
    # Query current program applications
    applications_by_type = db.session.query(
        Programs.program_type,
        func.count(Applications.id).label('count')
    ).join(
        Applications, Programs.id == Applications.program_id
    ).group_by(Programs.program_type).all()
    
    program_data = {
        'labels': [row.program_type for row in applications_by_type],
        'data': [row.count for row in applications_by_type]
    }
    
    # Generate program growth forecast
    forecast_result = forecast_program_growth(program_data, growth_rate)
    
    return jsonify(forecast_result)

@admin_bp.route('/api/analytics/test-arima')
@login_required
@role_required('admin')
def api_test_arima():
    """Test endpoint to validate ARIMA model performance"""
    # Get all historical data
    all_data = db.session.query(
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).group_by('month').order_by('month').all()
    
    labels = [d.month.strftime('%B %Y') for d in all_data if d.month]
    values = [d.count for d in all_data]
    
    # Test with different configurations
    results = {}
    
    # Test 1: Standard ARIMA (12 months minimum)
    forecast_12 = arima_forecast(values, labels, periods=6, force_arima=False)
    results['standard_12mo'] = {
        'model': forecast_12.get('model'),
        'success': forecast_12.get('success'),
        'data_points': len(values),
        'error': forecast_12.get('arima_error')
    }
    
    # Test 2: Forced ARIMA mode
    forecast_forced = arima_forecast(values, labels, periods=6, force_arima=True)
    results['forced_mode'] = {
        'model': forecast_forced.get('model'),
        'success': forecast_forced.get('success'),
        'data_points': len(values),
        'error': forecast_forced.get('arima_error')
    }
    
    # Test 3: Last 6 months only
    if len(values) >= 6:
        forecast_6 = arima_forecast(values[-6:], labels[-6:], periods=3, force_arima=False)
        results['last_6mo'] = {
            'model': forecast_6.get('model'),
            'success': forecast_6.get('success'),
            'data_points': 6,
            'error': forecast_6.get('arima_error')
        }
    
    return jsonify({
        'total_data_points': len(values),
        'date_range': f"{labels[0]} to {labels[-1]}" if labels else "No data",
        'tests': results,
        'recommendations': {
            'min_points_for_arima': 4,
            'min_points_for_seasonality': 36,
            'current_status': 'ARIMA ready' if len(values) >= 4 else 'Need more data'
        }
    })

@admin_bp.route('/api/analytics/program-timeseries-forecast')
@login_required
@role_required('admin')
def api_program_timeseries_forecast():
    """API endpoint for per-program-type ARIMA time series forecast"""
    periods = request.args.get('forecast_periods', 6, type=int)
    months = request.args.get('months', 24, type=int)

    end_date = datetime.utcnow()
    # Use relativedelta for accurate calendar-month arithmetic
    start_date = end_date - relativedelta(months=months)

    # Query per-program-type monthly counts
    raw = db.session.query(
        Programs.program_type,
        func.date_trunc('month', Applications.application_date).label('month'),
        func.count(Applications.id).label('count')
    ).join(
        Applications, Programs.id == Applications.program_id
    ).filter(
        Applications.application_date >= start_date
    ).group_by(Programs.program_type, 'month').order_by(Programs.program_type, 'month').all()

    # Group into per-program-type histories
    histories = {}
    for row in raw:
        pt = row.program_type
        if pt not in histories:
            histories[pt] = {'labels': [], 'values': []}
        if row.month:
            histories[pt]['labels'].append(row.month.strftime('%B %Y'))
            histories[pt]['values'].append(row.count)

    forecasts = forecast_program_timeseries(histories, periods=periods)
    return jsonify({'success': True, 'forecasts': forecasts})


# ---------------------------------------------------------------------------
# Explainability endpoints
# ---------------------------------------------------------------------------

@admin_bp.route('/api/recommender/explain/<int:user_id>')
@login_required
@role_required('admin')
def api_explain_recommendation(user_id):
    """Explain recommendation score for a specific beneficiary."""
    cu = CommunityUsers.query.filter_by(user_id=user_id).first()
    if not cu:
        return jsonify({'success': False, 'message': 'Beneficiary not found'}), 404

    user = User.query.get(user_id)
    beneficiary = {
        'user_id': cu.user_id,
        'first_name': user.first_name if user else '',
        'last_name': user.last_name if user else '',
        'age': cu.age,
        'barangay': cu.barangay,
        'family_annual_income': float(cu.family_annual_income) if cu.family_annual_income else 0,
        'is_solo_parent': cu.is_solo_parent,
        'is_student': cu.is_student,
        'is_pwd': cu.is_pwd,
        'is_currently_employed': cu.is_currently_employed,
        'occupation': cu.occupation,
    }

    # Load population for comparison
    all_cu = CommunityUsers.query.all()
    population = [
        {
            'family_annual_income': float(c.family_annual_income) if c.family_annual_income else 0,
            'is_solo_parent': c.is_solo_parent,
            'is_student': c.is_student,
            'is_pwd': c.is_pwd,
        }
        for c in all_cu
    ]

    explainer = BeneficiaryExplainer(population=population)
    # Use a quick rule-based score for the explanation
    recommender = BeneficiaryRecommender()
    scored = recommender.score_beneficiaries([beneficiary])
    score = scored[0]['score'] if scored else 0

    explanation = explainer.explain_score(beneficiary, score)
    return jsonify({'success': True, 'explanation': explanation, 'beneficiary': beneficiary})


@admin_bp.route('/api/recommender/recommendations/with-explanations', methods=['POST'])
@login_required
@role_required('admin')
def api_recommendations_with_explanations():
    """Generate recommendations with explanations attached."""
    data = request.get_json()

    program_id = data.get('program_id')
    max_beneficiaries = int(data.get('max_beneficiaries', 50))

    # Reuse the main recommendation logic
    all_users = db.session.query(
        User.id, User.first_name, User.last_name, User.email,
        CommunityUsers.age, CommunityUsers.barangay,
        CommunityUsers.family_annual_income,
        CommunityUsers.is_solo_parent, CommunityUsers.is_student,
        CommunityUsers.is_pwd, CommunityUsers.is_currently_employed,
        CommunityUsers.occupation,
    ).join(CommunityUsers, User.id == CommunityUsers.user_id).all()

    beneficiaries_data = [
        {
            'user_id': u.id,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'email': u.email,
            'age': u.age,
            'barangay': u.barangay,
            'family_annual_income': float(u.family_annual_income) if u.family_annual_income and 0 <= u.family_annual_income <= 10_000_000 else 0,
            'is_solo_parent': u.is_solo_parent,
            'is_student': u.is_student,
            'is_pwd': u.is_pwd,
            'is_currently_employed': u.is_currently_employed,
            'occupation': u.occupation,
        }
        for u in all_users
    ]

    recommendations = get_recommendations(
        beneficiaries_data=beneficiaries_data,
        max_beneficiaries=max_beneficiaries,
        solo_parent_priority=data.get('solo_parent_priority', False),
        student_priority=data.get('student_priority', False),
        pwd_priority=data.get('pwd_priority', False),
        senior_citizen_priority=data.get('senior_citizen_priority', False),
    )

    explainer = BeneficiaryExplainer(population=beneficiaries_data)
    explained = explainer.explain_batch(recommendations)

    return jsonify({
        'success': True,
        'count': len(explained),
        'recommendations': [
            {
                'user_id': r.get('user_id'),
                'name': f"{r.get('first_name', '')} {r.get('last_name', '')}",
                'score': r.get('score', 0),
                'explanation': r.get('explanation', {}),
            }
            for r in explained
        ],
    })


# ---------------------------------------------------------------------------
# Fairness audit endpoint
# ---------------------------------------------------------------------------

@admin_bp.route('/api/recommender/fairness-audit', methods=['POST'])
@login_required
@role_required('admin')
def api_fairness_audit():
    """Run a fairness audit on generated recommendations.

    Expects a JSON body with ``recommendations`` (list of scored dicts)
    or ``program_id`` to generate recommendations first.
    """
    data = request.get_json()

    # Either use provided recommendations or generate them
    recommendations = data.get('recommendations')
    if not recommendations:
        program_id = data.get('program_id')
        max_beneficiaries = int(data.get('max_beneficiaries', 75))

        all_users = db.session.query(
            User.id, CommunityUsers.age, CommunityUsers.barangay,
            CommunityUsers.family_annual_income,
            CommunityUsers.is_solo_parent, CommunityUsers.is_student,
            CommunityUsers.is_pwd, CommunityUsers.is_currently_employed,
            CommunityUsers.occupation,
        ).join(CommunityUsers, User.id == CommunityUsers.user_id).all()

        beneficiaries_data = [
            {
                'user_id': u.id,
                'age': u.age,
                'barangay': u.barangay,
                'family_annual_income': float(u.family_annual_income) if u.family_annual_income else 0,
                'is_solo_parent': u.is_solo_parent,
                'is_student': u.is_student,
                'is_pwd': u.is_pwd,
                'is_currently_employed': u.is_currently_employed,
                'occupation': u.occupation,
            }
            for u in all_users
        ]

        recommendations = get_recommendations(
            beneficiaries_data=beneficiaries_data,
            max_beneficiaries=max_beneficiaries,
            solo_parent_priority=data.get('solo_parent_priority', True),
            student_priority=data.get('student_priority', True),
            pwd_priority=data.get('pwd_priority', True),
            senior_citizen_priority=data.get('senior_citizen_priority', True),
        )

        auditor = FairnessAuditor(beneficiaries_data, recommendations)
    else:
        # Use all community users as the population baseline
        all_cu = CommunityUsers.query.all()
        population = [
            {
                'barangay': c.barangay,
                'is_solo_parent': c.is_solo_parent,
                'is_student': c.is_student,
                'is_pwd': c.is_pwd,
            }
            for c in all_cu
        ]
        auditor = FairnessAuditor(population, recommendations)

    audit_result = auditor.audit()
    return jsonify({'success': True, 'audit': audit_result})


# ---------------------------------------------------------------------------
# Program compatibility endpoint
# ---------------------------------------------------------------------------

@admin_bp.route('/api/recommender/program/<int:program_id>/compatibility')
@login_required
@role_required('admin')
def api_program_compatibility(program_id):
    """Score beneficiary compatibility for a specific program."""
    program = Programs.query.get_or_404(program_id)
    user_id = request.args.get('user_id', type=int)

    program_dict = {
        'id': program.id,
        'priority_group': program.priority_group,
        'income_range': program.income_range,
        'beneficiary_limit': program.beneficiary_limit,
        'requirements': [],
    }

    # Load program requirements
    prog_reqs = ProgramRequirements.query.filter_by(program_id=program_id).all()
    for pr in prog_reqs:
        req = Requirements.query.get(pr.requirement_id)
        if req:
            program_dict['requirements'].append({
                'field': req.requirement_name.lower().replace(' ', '_'),
                'name': req.requirement_name,
                'mandatory': pr.is_mandatory,
            })

    # Load historical data for approval rate calculation
    historical_raw = db.session.query(
        Applications.user_id, Applications.program_id,
        Applications.application_status, CommunityUsers.age,
    ).join(
        CommunityUsers, Applications.user_id == CommunityUsers.user_id
    ).filter(
        Applications.program_id == program_id
    ).all()

    historical_data = [
        {
            'user_id': h.user_id,
            'program_id': h.program_id,
            'application_status': h.application_status,
            'age': h.age,
        }
        for h in historical_raw
    ]

    scorer = ProgramCompatibilityScorer(historical_data=historical_data)

    if user_id:
        cu = CommunityUsers.query.filter_by(user_id=user_id).first()
        if not cu:
            return jsonify({'success': False, 'message': 'Beneficiary not found'}), 404

        beneficiary = {
            'user_id': cu.user_id,
            'age': cu.age,
            'family_annual_income': float(cu.family_annual_income) if cu.family_annual_income else 0,
            'is_solo_parent': cu.is_solo_parent,
            'is_student': cu.is_student,
            'is_pwd': cu.is_pwd,
            'is_currently_employed': cu.is_currently_employed,
            'occupation': cu.occupation,
        }
        result = scorer.calculate_fit(beneficiary, program_dict)
        return jsonify({'success': True, 'compatibility': result})

    # Score all community users
    all_cu = CommunityUsers.query.limit(200).all()
    beneficiaries = [
        {
            'user_id': c.user_id,
            'age': c.age,
            'barangay': c.barangay,
            'family_annual_income': float(c.family_annual_income) if c.family_annual_income else 0,
            'is_solo_parent': c.is_solo_parent,
            'is_student': c.is_student,
            'is_pwd': c.is_pwd,
            'is_currently_employed': c.is_currently_employed,
            'occupation': c.occupation,
        }
        for c in all_cu
    ]

    results = scorer.score_batch(beneficiaries, program_dict)
    return jsonify({
        'success': True,
        'count': len(results),
        'top_matches': [
            {
                'user_id': r['user_id'],
                'compatibility': r['compatibility'],
            }
            for r in results[:50]
        ],
    })


# ---------------------------------------------------------------------------
# Weight optimization endpoint
# ---------------------------------------------------------------------------

@admin_bp.route('/api/recommender/optimize-weights', methods=['POST'])
@login_required
@role_required('admin')
def api_optimize_weights():
    """Run weight optimization to find the best configuration."""
    data = request.get_json() or {}
    objectives = data.get('objectives', ['coverage', 'equity', 'efficiency'])

    # Load all beneficiaries
    all_cu = CommunityUsers.query.all()
    beneficiaries = [
        {
            'user_id': c.user_id,
            'age': c.age,
            'barangay': c.barangay,
            'family_annual_income': float(c.family_annual_income) if c.family_annual_income else 0,
            'is_solo_parent': c.is_solo_parent,
            'is_student': c.is_student,
            'is_pwd': c.is_pwd,
            'is_currently_employed': c.is_currently_employed,
        }
        for c in all_cu
    ]

    # Gather ground truth from approved applications
    ground_truth = None
    program_id = data.get('program_id')
    if program_id:
        approved = db.session.query(Applications.user_id).filter(
            Applications.program_id == program_id,
            Applications.application_status.in_(['approved', 'completed']),
        ).all()
        ground_truth = [a.user_id for a in approved] if approved else None

    optimizer = WeightOptimizer(beneficiaries, ground_truth_approvals=ground_truth)
    result = optimizer.optimize_weights(objectives=objectives)

    return jsonify({'success': True, 'optimization': result})
