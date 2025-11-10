"""
API endpoints for the recommendation system.

This module provides Flask routes for accessing program recommendations.
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from .recommendation import recommend_programs_for_user, get_recommender
from .models import UserProgramInteraction, Programs
from . import db

recommendations_bp = Blueprint('recommendations', __name__, url_prefix='/api/recommendations')


@recommendations_bp.route('/for-user', methods=['GET'])
@login_required
def get_recommendations_for_current_user():
    """
    Get personalized program recommendations for the currently logged-in user.
    
    Query Parameters:
        limit (int): Number of recommendations to return (default: 5, max: 20)
    
    Returns:
        JSON response with recommended programs
    """
    # Get limit from query params
    limit = request.args.get('limit', default=5, type=int)
    limit = min(limit, 20)  # Cap at 20 recommendations
    
    # Get recommendations
    recommended_programs = recommend_programs_for_user(current_user.id, top_n=limit)
    
    # Format response
    recommendations = []
    for program in recommended_programs:
        recommendations.append({
            'id': program.id,
            'program_name': program.program_name,
            'program_type': program.program_type,
            'program_period': program.program_period,
            'description': program.description,
            'date': program.date.isoformat() if program.date else None
        })
    
    return jsonify({
        'user_id': current_user.id,
        'recommendations': recommendations,
        'count': len(recommendations)
    })


@recommendations_bp.route('/similar/<int:program_id>', methods=['GET'])
@login_required
def get_similar_programs(program_id):
    """
    Get programs similar to a specific program.
    
    Path Parameters:
        program_id (int): ID of the program to find similar programs for
    
    Query Parameters:
        limit (int): Number of similar programs to return (default: 5, max: 20)
    
    Returns:
        JSON response with similar programs
    """
    # Check if program exists
    program = Programs.query.get(program_id)
    if not program:
        return jsonify({'error': 'Program not found'}), 404
    
    # Get limit from query params
    limit = request.args.get('limit', default=5, type=int)
    limit = min(limit, 20)
    
    # Get similar programs
    recommender = get_recommender()
    similar_ids = recommender.get_similar_programs(program_id, top_n=limit)
    
    # Fetch program details
    similar_programs = Programs.query.filter(Programs.id.in_(similar_ids)).all()
    
    # Format response
    similar = []
    for prog in similar_programs:
        similar.append({
            'id': prog.id,
            'program_name': prog.program_name,
            'program_type': prog.program_type,
            'program_period': prog.program_period,
            'description': prog.description,
            'date': prog.date.isoformat() if prog.date else None
        })
    
    return jsonify({
        'source_program': {
            'id': program.id,
            'program_name': program.program_name,
            'program_type': program.program_type
        },
        'similar_programs': similar,
        'count': len(similar)
    })


@recommendations_bp.route('/track-interaction', methods=['POST'])
@login_required
def track_interaction():
    """
    Track a user interaction with a program.
    
    Request Body (JSON):
        program_id (int): ID of the program
        interaction_type (str): Type of interaction ('view', 'bookmark', 'apply')
    
    Returns:
        JSON response confirming the interaction was tracked
    """
    data = request.get_json()
    
    # Validate input
    if not data or 'program_id' not in data or 'interaction_type' not in data:
        return jsonify({'error': 'Missing required fields: program_id, interaction_type'}), 400
    
    program_id = data['program_id']
    interaction_type = data['interaction_type']
    
    # Validate interaction type
    valid_types = ['view', 'bookmark', 'apply']
    if interaction_type not in valid_types:
        return jsonify({
            'error': f'Invalid interaction_type. Must be one of: {", ".join(valid_types)}'
        }), 400
    
    # Check if program exists
    program = Programs.query.get(program_id)
    if not program:
        return jsonify({'error': 'Program not found'}), 404
    
    # Create interaction record
    interaction = UserProgramInteraction(
        user_id=current_user.id,
        program_id=program_id,
        interaction_type=interaction_type
    )
    
    db.session.add(interaction)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Interaction tracked successfully',
        'interaction': {
            'user_id': current_user.id,
            'program_id': program_id,
            'interaction_type': interaction_type
        }
    }), 201


@recommendations_bp.route('/popular', methods=['GET'])
def get_popular_programs():
    """
    Get most popular programs based on interaction count.
    No authentication required - can be used for anonymous users.
    
    Query Parameters:
        limit (int): Number of programs to return (default: 5, max: 20)
    
    Returns:
        JSON response with popular programs
    """
    limit = request.args.get('limit', default=5, type=int)
    limit = min(limit, 20)
    
    # Get most interacted programs
    from sqlalchemy import func
    popular = db.session.query(
        Programs,
        func.count(UserProgramInteraction.id).label('interaction_count')
    ).join(
        UserProgramInteraction,
        Programs.id == UserProgramInteraction.program_id
    ).group_by(
        Programs.id
    ).order_by(
        func.count(UserProgramInteraction.id).desc()
    ).limit(limit).all()
    
    # Format response
    programs = []
    for program, count in popular:
        programs.append({
            'id': program.id,
            'program_name': program.program_name,
            'program_type': program.program_type,
            'program_period': program.program_period,
            'description': program.description,
            'date': program.date.isoformat() if program.date else None,
            'interaction_count': count
        })
    
    # If no interactions yet, return most recent programs
    if not programs:
        recent_programs = Programs.query.order_by(Programs.date.desc()).limit(limit).all()
        for program in recent_programs:
            programs.append({
                'id': program.id,
                'program_name': program.program_name,
                'program_type': program.program_type,
                'program_period': program.program_period,
                'description': program.description,
                'date': program.date.isoformat() if program.date else None,
                'interaction_count': 0
            })
    
    return jsonify({
        'popular_programs': programs,
        'count': len(programs)
    })
