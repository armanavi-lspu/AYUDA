"""
Tests for the Recommendation API endpoints
"""
import pytest
import json
from app.models import Programs, User, UserProgramInteraction
from app import db
from flask import Flask


@pytest.fixture
def app():
    """Create and configure a test application instance."""
    from app import create_app
    
    # Create a test app with SQLite
    test_app = Flask(__name__, template_folder='../templates',
                     static_folder='../static')
    test_app.config['TESTING'] = True
    test_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    test_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    test_app.config['SECRET_KEY'] = 'test-secret-key'
    test_app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for testing
    test_app.config['LOGIN_DISABLED'] = False
    
    # Initialize database
    db.init_app(test_app)
    
    # Register only the recommendations blueprint for focused testing
    from app.recommendations_api import recommendations_bp
    test_app.register_blueprint(recommendations_bp)
    
    # Setup login manager without redirect
    from flask_login import LoginManager
    login_manager = LoginManager()
    login_manager.init_app(test_app)
    
    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))
    
    @login_manager.unauthorized_handler
    def unauthorized():
        # Return 401 instead of redirecting
        return {'error': 'Unauthorized'}, 401
    
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
        # Create a test admin user
        from werkzeug.security import generate_password_hash
        admin = User(
            email='admin@test.com',
            password_hash=generate_password_hash('password123', method='pbkdf2:sha256'),
            first_name='Admin',
            last_name='User',
            role='admin'
        )
        db.session.add(admin)
        db.session.commit()
        
        programs = [
            Programs(
                program_name='Emergency Financial Aid',
                program_type='Emergency',
                program_period='Short-term',
                description='Immediate financial assistance',
                user_id=admin.id
            ),
            Programs(
                program_name='Education Grant',
                program_type='Education',
                program_period='Long-term',
                description='Support for educational expenses',
                user_id=admin.id
            ),
            Programs(
                program_name='Business Loan',
                program_type='Business',
                program_period='Medium-term',
                description='Small business funding',
                user_id=admin.id
            ),
        ]
        
        for program in programs:
            db.session.add(program)
        
        db.session.commit()
        return programs


def test_get_popular_programs_no_auth(client, app, sample_programs):
    """Test getting popular programs without authentication."""
    with app.app_context():
        response = client.get('/api/recommendations/popular?limit=5')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        
        assert 'popular_programs' in data
        assert 'count' in data
        assert isinstance(data['popular_programs'], list)
        # Should return programs even without interactions
        assert data['count'] > 0


def test_get_popular_programs_with_limit(client, app, sample_programs):
    """Test getting popular programs with custom limit."""
    with app.app_context():
        response = client.get('/api/recommendations/popular?limit=2')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        
        assert len(data['popular_programs']) <= 2


def test_track_interaction_requires_auth(client, app, sample_programs):
    """Test that tracking interaction requires authentication."""
    with app.app_context():
        programs = Programs.query.all()
        
        response = client.post('/api/recommendations/track-interaction',
                              json={'program_id': programs[0].id, 'interaction_type': 'view'},
                              content_type='application/json')
        
        # Should redirect to login or return 401
        assert response.status_code in [302, 401]


def test_get_recommendations_requires_auth(client, app):
    """Test that getting recommendations requires authentication."""
    with app.app_context():
        response = client.get('/api/recommendations/for-user')
        
        # Should redirect to login or return 401
        assert response.status_code in [302, 401]


def test_get_similar_programs_requires_auth(client, app, sample_programs):
    """Test that getting similar programs requires authentication."""
    with app.app_context():
        programs = Programs.query.all()
        
        response = client.get(f'/api/recommendations/similar/{programs[0].id}')
        
        # Should redirect to login or return 401
        assert response.status_code in [302, 401]


def test_track_interaction_missing_fields(client, app):
    """Test tracking interaction with missing fields."""
    with app.app_context():
        # Try without authentication (will fail before field validation)
        response = client.post('/api/recommendations/track-interaction',
                              json={},
                              content_type='application/json')
        
        # Should require auth or return validation error
        assert response.status_code in [302, 400, 401]


def test_api_endpoints_exist(client):
    """Test that API endpoints exist and return appropriate responses."""
    # Test popular programs (no auth required)
    response = client.get('/api/recommendations/popular')
    assert response.status_code == 200
    
    # Test authenticated endpoints return 401 or redirect
    response = client.get('/api/recommendations/for-user')
    assert response.status_code in [302, 401]
    
    response = client.post('/api/recommendations/track-interaction',
                          json={'program_id': 1, 'interaction_type': 'view'},
                          content_type='application/json')
    assert response.status_code in [302, 401]


def test_popular_programs_structure(client, app, sample_programs):
    """Test the structure of popular programs response."""
    with app.app_context():
        response = client.get('/api/recommendations/popular')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        
        # Check structure
        assert 'popular_programs' in data
        assert 'count' in data
        
        if data['count'] > 0:
            program = data['popular_programs'][0]
            # Check program structure
            assert 'id' in program
            assert 'program_name' in program
            assert 'program_type' in program
            assert 'program_period' in program
            assert 'description' in program
            assert 'interaction_count' in program

