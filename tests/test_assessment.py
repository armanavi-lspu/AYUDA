"""
Tests for the Assessment module (models and routes).
"""
import pytest
from datetime import datetime
from flask import Flask
from app.extensions import db
from app.models import (
    Assessment, AssessmentDocument, User, Applications, Programs, Notifications
)


@pytest.fixture
def app():
    """Create a lightweight test application with SQLite."""
    test_app = Flask(__name__)
    test_app.config['TESTING'] = True
    test_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    test_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    test_app.config['SECRET_KEY'] = 'test-secret'
    db.init_app(test_app)
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


def _seed():
    """Seed minimal data for assessment tests."""
    admin = User(
        email='admin@test.com',
        password_hash='pbkdf2:sha256:test',
        first_name='Admin',
        last_name='User',
        role='admin',
    )
    community = User(
        email='community@test.com',
        password_hash='pbkdf2:sha256:test',
        first_name='Community',
        last_name='User',
        role='community',
    )
    db.session.add_all([admin, community])
    db.session.flush()

    program = Programs(
        program_name='Test Program',
        program_type='AICS',
        program_period='One-time',
        user_id=admin.id,
    )
    db.session.add(program)
    db.session.flush()

    application = Applications(
        user_id=community.id,
        program_id=program.id,
        application_status='approved',
    )
    db.session.add(application)
    db.session.commit()
    return admin, community, program, application


# ── Model tests ──────────────────────────────────────────────

def test_assessment_model_creation(app):
    """Test creating an Assessment record."""
    with app.app_context():
        admin, _community, _program, application = _seed()
        assessment = Assessment(
            application_id=application.id,
            assessment_type='interview',
            title='Initial SCSR Interview',
            description='Conduct initial interview.',
            scheduled_date=datetime(2026, 3, 1),
            scheduled_time='09:00 AM',
            location='MSWD Office',
            conducted_by=admin.id,
        )
        db.session.add(assessment)
        db.session.commit()

        saved = Assessment.query.first()
        assert saved is not None
        assert saved.title == 'Initial SCSR Interview'
        assert saved.assessment_type == 'interview'
        assert saved.status == 'scheduled'
        assert saved.application_id == application.id
        assert saved.conducted_by == admin.id


def test_assessment_document_model(app):
    """Test creating an AssessmentDocument linked to an Assessment."""
    with app.app_context():
        admin, _community, _program, application = _seed()
        assessment = Assessment(
            application_id=application.id,
            assessment_type='home_visit',
            title='Home Visit',
            conducted_by=admin.id,
        )
        db.session.add(assessment)
        db.session.flush()

        doc = AssessmentDocument(
            assessment_id=assessment.id,
            file_path='static/uploads/assessments/1/test.pdf',
            original_filename='test.pdf',
            file_size=1024,
            file_type='application/pdf',
            uploaded_by=admin.id,
        )
        db.session.add(doc)
        db.session.commit()

        saved_doc = AssessmentDocument.query.first()
        assert saved_doc is not None
        assert saved_doc.original_filename == 'test.pdf'
        assert saved_doc.assessment_id == assessment.id


def test_assessment_cascade_delete(app):
    """Deleting an assessment cascades to its documents."""
    with app.app_context():
        admin, _community, _program, application = _seed()
        assessment = Assessment(
            application_id=application.id,
            assessment_type='interview',
            title='To Delete',
            conducted_by=admin.id,
        )
        db.session.add(assessment)
        db.session.flush()

        doc = AssessmentDocument(
            assessment_id=assessment.id,
            file_path='path/to/file.pdf',
            original_filename='file.pdf',
            uploaded_by=admin.id,
        )
        db.session.add(doc)
        db.session.commit()

        assert AssessmentDocument.query.count() == 1
        db.session.delete(assessment)
        db.session.commit()
        assert AssessmentDocument.query.count() == 0


def test_assessment_relationship_to_application(app):
    """Assessment.application relationship works."""
    with app.app_context():
        admin, _community, _program, application = _seed()
        assessment = Assessment(
            application_id=application.id,
            assessment_type='interview',
            title='Rel Test',
            conducted_by=admin.id,
        )
        db.session.add(assessment)
        db.session.commit()

        saved = Assessment.query.first()
        assert saved.application is not None
        assert saved.application.id == application.id
        assert saved.conductor.id == admin.id


# ── Notification URL test ────────────────────────────────────

def test_notification_url_for_assessment(app):
    """Notifications with related_type='assessment' return correct URL."""
    with app.app_context():
        admin = User(
            email='admin2@test.com',
            password_hash='pbkdf2:sha256:test',
            first_name='A', last_name='B', role='admin',
        )
        db.session.add(admin)
        db.session.flush()
        notif = Notifications(
            user_id=admin.id,
            notif_title='Test',
            notif_message='Test message',
            related_id=42,
            related_type='assessment',
        )
        db.session.add(notif)
        db.session.commit()
        assert notif.get_url() == '/admin/assessments/42'
