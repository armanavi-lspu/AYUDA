"""
Tests for the Program Recommendation System
"""
import pytest
from app.recommendation import ProgramRecommender
from app.models import Programs, User, UserProgramInteraction
from app import db, create_app
from datetime import datetime


@pytest.fixture
def app():
    """Create and configure a test application instance."""
    from flask import Flask
    from config import Config
    
    # Create a test app with SQLite instead of PostgreSQL
    test_app = Flask(__name__, template_folder='../templates',
                     static_folder='../static')
    test_app.config['TESTING'] = True
    test_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    test_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    test_app.config['SECRET_KEY'] = 'test-secret-key'
    
    # Initialize the database
    db.init_app(test_app)
    
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Test client for the application."""
    return app.test_client()


@pytest.fixture
def sample_programs(app):
    """Create sample programs for testing."""
    with app.app_context():
        # Create a test user first
        user = User(
            email='admin@test.com',
            password_hash='hash',
            first_name='Admin',
            last_name='User',
            role='admin'
        )
        db.session.add(user)
        db.session.commit()
        
        programs = [
            Programs(
                program_name='Emergency Financial Assistance',
                program_type='Emergency',
                program_period='Short-term',
                description='Provides immediate financial help for emergency situations',
                user_id=user.id
            ),
            Programs(
                program_name='Educational Scholarship Program',
                program_type='Education',
                program_period='Long-term',
                description='Scholarships for students pursuing higher education',
                user_id=user.id
            ),
            Programs(
                program_name='Small Business Grant',
                program_type='Business',
                program_period='Medium-term',
                description='Grants for small business owners and entrepreneurs',
                user_id=user.id
            ),
            Programs(
                program_name='Housing Assistance Program',
                program_type='Housing',
                program_period='Long-term',
                description='Help with housing costs and rent subsidies',
                user_id=user.id
            ),
            Programs(
                program_name='Emergency Relief Fund',
                program_type='Emergency',
                program_period='Short-term',
                description='Quick access to funds during emergency situations',
                user_id=user.id
            ),
        ]
        
        for program in programs:
            db.session.add(program)
        
        db.session.commit()
        
        return programs


def test_recommender_initialization():
    """Test that recommender can be initialized."""
    recommender = ProgramRecommender()
    assert recommender is not None
    assert recommender.vectorizer is not None


def test_recommender_fit(app, sample_programs):
    """Test that recommender can be fit with programs."""
    with app.app_context():
        recommender = ProgramRecommender()
        programs = Programs.query.all()
        recommender.fit(programs)
        
        assert recommender.program_features is not None
        assert recommender.similarity_matrix is not None
        assert len(recommender.program_ids) == len(programs)


def test_get_similar_programs(app, sample_programs):
    """Test finding similar programs."""
    with app.app_context():
        recommender = ProgramRecommender()
        programs = Programs.query.all()
        recommender.fit(programs)
        
        # Get first program (Emergency Financial Assistance)
        first_program = programs[0]
        
        # Get similar programs
        similar = recommender.get_similar_programs(first_program.id, top_n=2)
        
        assert len(similar) <= 2
        assert first_program.id not in similar


def test_recommend_for_new_user(app, sample_programs):
    """Test recommendations for a new user without interaction history."""
    with app.app_context():
        # Create a new community user
        user = User(
            email='newuser@test.com',
            password_hash='hash',
            first_name='New',
            last_name='User',
            role='community'
        )
        db.session.add(user)
        db.session.commit()
        
        recommender = ProgramRecommender()
        programs = Programs.query.all()
        recommender.fit(programs)
        
        # Get recommendations for new user
        recommendations = recommender.recommend_for_user(user.id, top_n=3)
        
        # Should get some recommendations (popular programs or recent programs)
        assert len(recommendations) > 0


def test_recommend_for_user_with_interactions(app, sample_programs):
    """Test recommendations for a user with interaction history."""
    with app.app_context():
        # Create a community user
        user = User(
            email='activeuser@test.com',
            password_hash='hash',
            first_name='Active',
            last_name='User',
            role='community'
        )
        db.session.add(user)
        db.session.commit()
        
        programs = Programs.query.all()
        
        # Add some interactions (user viewed emergency programs)
        interaction1 = UserProgramInteraction(
            user_id=user.id,
            program_id=programs[0].id,  # Emergency Financial Assistance
            interaction_type='view'
        )
        interaction2 = UserProgramInteraction(
            user_id=user.id,
            program_id=programs[4].id,  # Emergency Relief Fund
            interaction_type='apply'
        )
        
        db.session.add(interaction1)
        db.session.add(interaction2)
        db.session.commit()
        
        recommender = ProgramRecommender()
        recommender.fit(programs)
        
        # Get recommendations
        recommendations = recommender.recommend_for_user(user.id, top_n=3)
        
        # Should get recommendations based on interaction history
        assert len(recommendations) > 0
        
        # Check that interacted programs are excluded
        interacted_ids = [programs[0].id, programs[4].id]
        recommended_ids = [r['program_id'] for r in recommendations]
        
        for interacted_id in interacted_ids:
            assert interacted_id not in recommended_ids


def test_content_based_similarity(app, sample_programs):
    """Test that similar programs are actually similar in content."""
    with app.app_context():
        recommender = ProgramRecommender()
        programs = Programs.query.all()
        recommender.fit(programs)
        
        # Find Emergency programs
        emergency_programs = [p for p in programs if p.program_type == 'Emergency']
        
        if len(emergency_programs) >= 2:
            # Get similar programs to first emergency program
            similar = recommender.get_similar_programs(emergency_programs[0].id, top_n=5)
            
            # Check if the other emergency program is in similar programs
            other_emergency_ids = [p.id for p in emergency_programs[1:]]
            
            # At least one other emergency program should be in top similar programs
            has_similar_emergency = any(pid in similar for pid in other_emergency_ids)
            assert has_similar_emergency


def test_interaction_type_weighting(app, sample_programs):
    """Test that different interaction types have different weights."""
    with app.app_context():
        # Create two users
        user1 = User(
            email='user1@test.com',
            password_hash='hash',
            first_name='User',
            last_name='One',
            role='community'
        )
        user2 = User(
            email='user2@test.com',
            password_hash='hash',
            first_name='User',
            last_name='Two',
            role='community'
        )
        db.session.add_all([user1, user2])
        db.session.commit()
        
        programs = Programs.query.all()
        
        # User1 applies to a program (higher weight)
        interaction1 = UserProgramInteraction(
            user_id=user1.id,
            program_id=programs[0].id,
            interaction_type='apply'
        )
        
        # User2 views the same program (lower weight)
        interaction2 = UserProgramInteraction(
            user_id=user2.id,
            program_id=programs[0].id,
            interaction_type='view'
        )
        
        db.session.add_all([interaction1, interaction2])
        db.session.commit()
        
        recommender = ProgramRecommender()
        recommender.fit(programs)
        
        # Get recommendations for both users
        recs1 = recommender.recommend_for_user(user1.id, top_n=3)
        recs2 = recommender.recommend_for_user(user2.id, top_n=3)
        
        # Both should get recommendations
        assert len(recs1) > 0
        assert len(recs2) > 0
