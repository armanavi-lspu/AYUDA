from app.extensions import db
from flask_login import UserMixin
from datetime import datetime, timezone
from sqlalchemy.sql import func
from sqlalchemy.orm import validates
import json
import secrets
import string
import re


def get_utc_now():
    """Get current UTC time as timezone-aware datetime"""
    return datetime.now(timezone.utc)


def _normalize_person_name(raw_value):
    """Normalize personal names to a readable per-word capitalized format."""
    text = ' '.join(str(raw_value or '').strip().split())
    if not text:
        return ''

    words = []
    for word in text.split(' '):
        segments = re.split(r"([-'])", word)
        normalized_segments = []
        for segment in segments:
            if segment in {"-", "'"}:
                normalized_segments.append(segment)
                continue

            if not segment:
                normalized_segments.append(segment)
                continue

            if segment.isupper() and len(segment) <= 4:
                normalized_segments.append(segment)
                continue

            normalized_segments.append(segment[0].upper() + segment[1:].lower())

        words.append(''.join(normalized_segments))

    return ' '.join(words)


class JsonSerializableMixin:
    """Mixin to make models JSON serializable"""
    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class User(db.Model, UserMixin):
    __tablename__ = 'users'     
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False, index=True)  
    password_hash = db.Column(db.String(255), nullable=False)  
    first_name = db.Column(db.String(50), nullable=False)
    middle_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(20), nullable=False, index=True) # 'super_admin', 'admin', or 'community'
    profile_pic = db.Column(db.String(255))
    last_activity = db.Column(db.DateTime)
    profile_complete_alert_dismissed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=get_utc_now)
        
    # Relationships
    created_programs = db.relationship('Programs', backref='creator', lazy=True)
    announcements = db.relationship('Announcements', backref='author', lazy=True)
    notifications = db.relationship('Notifications', backref='user', lazy=True, cascade='all, delete-orphan')
    user_activity_logs = db.relationship(
        'UserActivityLog',
        back_populates='user',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='UserActivityLog.user_id'
    )
    applications = db.relationship('Applications', foreign_keys='Applications.user_id', backref='applicant', lazy=True)
    reviewed_applications = db.relationship('Applications', foreign_keys='Applications.reviewed_by', backref='reviewer', lazy=True)
    scheduled_claims = db.relationship('Applications', foreign_keys='Applications.claim_scheduled_by', backref='claim_scheduler', lazy=True)
    community_profile = db.relationship('CommunityUsers', foreign_keys='CommunityUsers.user_id', backref='user', uselist=False, cascade='all, delete-orphan')
    admin_profile = db.relationship('AdminUsers', backref='user', uselist=False, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<User {self.email}>'

    @validates('first_name', 'middle_name', 'last_name')
    def _normalize_name_fields(self, key, value):
        normalized = _normalize_person_name(value)
        if key == 'middle_name' and not normalized:
            return None
        return normalized

class Programs(db.Model):
    __tablename__ = 'programs'
    
    id = db.Column(db.Integer, primary_key=True)
    program_name = db.Column(db.String(200), nullable=False)
    program_type = db.Column(db.String(50), nullable=False, index=True)  # Added index for type queries
    program_period = db.Column(db.String(50), nullable=False)
    priority_group = db.Column(db.String(255))  # Target beneficiaries (e.g., "Low Income Families, Students, PWDs")
    beneficiary_limit = db.Column(db.Integer)  # Maximum number of beneficiaries that can be accepted (NULL = unlimited)
    income_range = db.Column(db.String(100))  # Target income level (e.g., "Below 15,000", "15,000 - 30,000")
    start_date = db.Column(db.Date)  # Program start date (optional, especially for one-time/time-bound programs)
    end_date = db.Column(db.Date)  # Program end date / deadline for document submission (optional)
    description = db.Column(db.Text)
    date = db.Column(db.DateTime, default=get_utc_now)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    file_attachment_id = db.Column(db.Integer, db.ForeignKey('file_attachment.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True, index=True)  # NEW: Track active programs
    allow_online_upload = db.Column(db.Boolean, default=True)  # Enable/disable online document submission
    enable_application_slip = db.Column(db.Boolean, default=True)  # Enable/disable application slip printing
    
    # Relationships
    applications = db.relationship('Applications', back_populates='program', lazy=True)
    requirements = db.relationship('Requirements', secondary='program_requirements', viewonly=True)
    file_attachment = db.relationship('FileAttachment', back_populates='program', uselist=False)
    program_requirements = db.relationship('ProgramRequirements', back_populates='program', lazy='select', cascade='all, delete-orphan')
    workflow_steps = db.relationship('ProgramWorkflowSteps', back_populates='program', lazy='select', cascade='all, delete-orphan', order_by='ProgramWorkflowSteps.step_order')

    def __repr__(self):
        return f'<Program {self.program_name}>'


class ProgramWorkflowSteps(db.Model):
    """Configurable workflow steps for each program"""
    __tablename__ = 'program_workflow_steps'
    
    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.Integer, db.ForeignKey('programs.id'), nullable=False)
    step_order = db.Column(db.Integer, nullable=False)  # 1, 2, 3, etc.
    step_name = db.Column(db.String(100), nullable=False)  # e.g., "Upload Shelter Photos", "Submit Certificate"
    step_description = db.Column(db.Text)  # Detailed instructions for this step
    step_type = db.Column(db.String(50), nullable=False, default='approval')  # 'photo_upload', 'document_upload', 'approval', 'assessment', 'document_submission', 'scheduling'
    is_pre_approval = db.Column(db.Boolean, default=False)  # True if step must be completed before application approval
    requires_verification = db.Column(db.Boolean, default=True)  # True if admin must verify this step
    allowed_file_types = db.Column(db.String(255))  # Comma-separated file extensions: "jpg,jpeg,png,pdf"
    step_config = db.Column(db.Text)  # JSON configuration for step-specific settings (required documents, etc.)
    created_at = db.Column(db.DateTime, default=get_utc_now)
    updated_at = db.Column(db.DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Relationships
    program = db.relationship('Programs', back_populates='workflow_steps')
    application_statuses = db.relationship('ApplicationWorkflowStatus', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<WorkflowStep {self.step_order}: {self.step_name} for Program {self.program_id}>'

    @validates('step_config')
    def _serialize_step_config(self, key, value):
        """Normalize step config to JSON text for Text-backed storage."""
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed or None
        return str(value)
    
    def to_dict(self):
        """Convert model to JSON-serializable dictionary"""
        return {
            'id': self.id,
            'program_id': self.program_id,
            'step_order': self.step_order,
            'step_name': self.step_name,
            'step_description': self.step_description,
            'step_type': self.step_type,
            'is_pre_approval': self.is_pre_approval,
            'requires_verification': self.requires_verification,
            'allowed_file_types': self.allowed_file_types,
            'step_config': self.step_config
        }
    
    @property
    def config_data(self):
        """Return step configuration as dictionary"""
        if self.step_config:
            try:
                return json.loads(self.step_config)
            except:
                return {}
        return {}
    
    def set_config_data(self, config_dict):
        """Set step configuration from dictionary"""
        if config_dict:
            self.step_config = json.dumps(config_dict)
        else:
            self.step_config = None
    
    @property
    def file_types_list(self):
        """Return allowed file types as a list"""
        if self.allowed_file_types:
            return [ft.strip().lower() for ft in self.allowed_file_types.split(',')]
        return []


class Requirements(db.Model):
    __tablename__ = 'requirements'
    
    id = db.Column(db.Integer, primary_key=True)
    requirement_name = db.Column(db.String(255), nullable=False)  # Changed from document_name
    requirement_type = db.Column(db.String(50), nullable=False, default='document', index=True)  # NEW: 'document' or 'qualification'
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_utc_now)
    
    # Relationships
    application_documents = db.relationship('ApplicationDocuments', back_populates='requirement')
    requirement_programs = db.relationship('ProgramRequirements', back_populates='requirement', lazy='dynamic')

    def __repr__(self):
        return f'<Requirement {self.requirement_name} ({self.requirement_type})>'

class ProgramRequirements(db.Model):
    __tablename__ = 'program_requirements'
    
    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.Integer, db.ForeignKey('programs.id'), nullable=False)
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=False)
    is_mandatory = db.Column(db.Boolean, default=True)
    is_completed = db.Column(db.Boolean, default=True)
    document_status = db.Column(db.String(20), nullable=False, default='pending') # 'draft' or 'published'
    copy_type = db.Column(db.Text(), default='[{"type": "original", "count": 1}]')  # JSON array of copy specifications
    created_at = db.Column(db.DateTime, default=get_utc_now)
    
    # Relationships
    program = db.relationship('Programs', back_populates='program_requirements')
    requirement = db.relationship('Requirements', back_populates='requirement_programs')

    def __repr__(self):
        return f'<ProgramRequirement {self.program_id}-{self.requirement_id}>'
    
    def get_copy_specifications(self):
        """Parse JSON copy specifications and return as list of dicts"""
        import json
        try:
            if isinstance(self.copy_type, str):
                specs = json.loads(self.copy_type)
            else:
                specs = self.copy_type
            return specs if isinstance(specs, list) else [{"type": "original", "count": 1}]
        except:
            return [{"type": "original", "count": 1}]
    
    def set_copy_specifications(self, specs):
        """Set copy specifications from list of dicts and store as JSON"""
        import json
        if not specs:
            specs = [{"type": "original", "count": 1}]
        self.copy_type = json.dumps(specs)
    
    @staticmethod
    def get_default_specifications():
        """Get default copy specifications"""
        import json
        return json.dumps([{"type": "original", "count": 1}])

class Announcements(db.Model):
    __tablename__ = 'announcements'
    
    id = db.Column(db.Integer, primary_key=True)
    announcement_title = db.Column(db.String(200), nullable=False)
    announcement_content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), nullable=False, default='General')
    status = db.Column(db.String(50), nullable=False, default='draft') # 'draft' or 'published'
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    program_id = db.Column(db.Integer, db.ForeignKey('programs.id'), nullable=True)  # Link to program
    attachment_url = db.Column(db.String(500), nullable=True)  # External link or attachment URL
    created_at = db.Column(db.DateTime, default=get_utc_now, index=True)
    updated_at = db.Column(db.DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Relationships
    images = db.relationship('AnnouncementImages', backref='announcement', lazy=True, cascade='all, delete-orphan')
    linked_program = db.relationship('Programs', backref='announcements', foreign_keys=[program_id])
    
    def __repr__(self):
        return f'<Announcement {self.announcement_title}>'

class AnnouncementImages(db.Model):
    __tablename__ = 'announcement_images'
    
    id = db.Column(db.Integer, primary_key=True)
    announcement_id = db.Column(db.Integer, db.ForeignKey('announcements.id'), nullable=False)
    image_path = db.Column(db.String(255), nullable=False)
    caption = db.Column(db.String(255))
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=get_utc_now)
    
    def __repr__(self):
        return f'<AnnouncementImage {self.id}>'


class SubsidyPayout(db.Model):
    """Store scheduled subsidy payouts and beneficiary snapshots."""
    __tablename__ = 'subsidy_payouts'

    id = db.Column(db.Integer, primary_key=True)
    payout_id = db.Column(db.String(50), nullable=False, unique=True, index=True)
    payout_datetime = db.Column(db.DateTime, nullable=False, index=True)
    payout_location = db.Column(db.String(255), nullable=False)
    payout_notes = db.Column(db.Text)
    category_key = db.Column(db.String(50), nullable=False, index=True)
    category_label = db.Column(db.String(100), nullable=False)
    beneficiary_count = db.Column(db.Integer, nullable=False, default=0)
    beneficiary_snapshot = db.Column(db.Text, nullable=False)
    beneficiary_list_text = db.Column(db.Text)
    beneficiary_list_html = db.Column(db.Text)
    suggested_title = db.Column(db.String(255))
    suggested_content = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default='draft', index=True)  # draft, saved, announced
    saved_in_system = db.Column(db.Boolean, nullable=False, default=False)
    saved_at = db.Column(db.DateTime)
    announcement_id = db.Column(db.Integer, db.ForeignKey('announcements.id'), nullable=True)
    scheduled_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=get_utc_now)
    updated_at = db.Column(db.DateTime, default=get_utc_now, onupdate=get_utc_now)

    scheduler = db.relationship('User', backref='scheduled_subsidy_payouts', foreign_keys=[scheduled_by])
    announcement = db.relationship('Announcements', backref='linked_subsidy_payouts', foreign_keys=[announcement_id])

    @property
    def snapshot_data(self):
        """Return beneficiary snapshot JSON as a Python list."""
        if self.beneficiary_snapshot:
            try:
                import json
                return json.loads(self.beneficiary_snapshot)
            except Exception:
                return []
        return []

    def set_snapshot_data(self, snapshot_rows):
        """Store beneficiary snapshot as JSON text."""
        import json
        self.beneficiary_snapshot = json.dumps(snapshot_rows or [])

    def __repr__(self):
        return f'<SubsidyPayout {self.payout_id}>'

class Applications(db.Model):
    __tablename__ = 'applications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    program_id = db.Column(db.Integer, db.ForeignKey('programs.id'), nullable=False, index=True)
    application_status = db.Column(db.String(20), nullable=False, default='pending', index=True)  # 'pending' (not yet approved), 'approved' (approved but not yet opened by user), 'rejected', 'active' (approved and opened/recognized by user), 'completed' (scheduled/claimed)
    document_upload_status = db.Column(db.String(20), default='pending', index=True)  # 'pending', 'uploaded', 'verified', 'rejected'
    application_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    review_date = db.Column(db.DateTime, index=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    submission_deadline = db.Column(db.DateTime, index=True)  # Deadline for document submission
    
    # Claim scheduling fields
    claim_date = db.Column(db.DateTime, index=True)  # Scheduled date for claiming assistance
    claim_time = db.Column(db.String(10))  # Time slot (e.g., "09:00 AM", "02:00 PM")
    claim_location = db.Column(db.String(255))  # Location for claiming (office address, etc.)
    claim_instructions = db.Column(db.Text)  # Special instructions for claiming
    claim_status = db.Column(db.String(20), default='not_scheduled', index=True)  # not_scheduled, scheduled, claimed, missed
    claim_scheduled_by = db.Column(db.Integer, db.ForeignKey('users.id'))  # Admin who scheduled
    claim_scheduled_at = db.Column(db.DateTime)  # When the claim was scheduled
    
    # Verification code for document submission
    verification_code = db.Column(db.String(20), unique=True, index=True)  # Unique code for verification
    code_generated_at = db.Column(db.DateTime)  # When code was generated
    code_used_at = db.Column(db.DateTime)  # When code was used
    documents_submitted_at = db.Column(db.DateTime)  # When documents were physically submitted
    
    # Cancellation request fields
    cancellation_requested = db.Column(db.Boolean, default=False, index=True)  # True if cancellation has been requested
    cancellation_reason = db.Column(db.Text)  # User's reason for requesting cancellation
    cancellation_requested_at = db.Column(db.DateTime)  # When cancellation was requested
    cancellation_status = db.Column(db.String(20))  # 'pending', 'approved', 'rejected'
    cancellation_reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))  # Admin who reviewed cancellation
    cancellation_reviewed_at = db.Column(db.DateTime)  # When cancellation was reviewed
    cancellation_admin_notes = db.Column(db.Text)  # Admin notes about cancellation decision
    
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_utc_now)
    updated_at = db.Column(db.DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Add composite indexes for common queries
    __table_args__ = (
        db.Index('idx_app_user_date', 'user_id', 'application_date'),
        db.Index('idx_app_program_status', 'program_id', 'application_status'),
    )
    
    # Relationships
    document_checklist = db.relationship('ApplicationDocuments', backref='application', lazy=True, cascade='all, delete-orphan')
    document_uploads = db.relationship('ApplicationDocumentUploads', backref='application', lazy=True, cascade='all, delete-orphan')
    program = db.relationship('Programs', back_populates='applications')
    shelter_photos = db.relationship('ShelterPhotos', backref='application', lazy=True, cascade='all, delete-orphan')
    cal_documents = db.relationship('CALDocuments', backref='application', lazy=True, cascade='all, delete-orphan')
    workflow_status = db.relationship('ApplicationWorkflowStatus', foreign_keys='ApplicationWorkflowStatus.application_id', lazy=True, cascade='all, delete-orphan')
    
    # Note: applicant, reviewer, and claim_scheduler relationships are defined in User model

    _COMPLETE_DOCUMENT_STATUSES = {'approved', 'verified'}

    def _current_program_document_requirement_ids(self, mandatory_only=False):
        """Return current document requirement IDs configured for this program."""
        query = db.session.query(ProgramRequirements.requirement_id).join(
            Requirements,
            ProgramRequirements.requirement_id == Requirements.id
        ).filter(
            ProgramRequirements.program_id == self.program_id,
            Requirements.requirement_type == 'document'
        )

        if mandatory_only:
            query = query.filter(ProgramRequirements.is_mandatory.is_(True))

        return {requirement_id for requirement_id, in query.distinct().all()}

    def _completed_document_requirement_ids(self):
        """Return requirement IDs whose checklist entries are marked complete."""
        return {
            doc.requirement_id
            for doc in self.document_checklist
            if doc.requirement_id and doc.submission_status in self._COMPLETE_DOCUMENT_STATUSES
        }
    
    @property
    def cal_docs_verified(self):
        """Check if CA Certificate and Proposal are both verified"""
        if not self.cal_documents:
            return False
        certificate = next((d for d in self.cal_documents if d.document_type == 'certificate' and d.verification_status == 'approved'), None)
        proposal = next((d for d in self.cal_documents if d.document_type == 'proposal' and d.verification_status == 'approved'), None)
        return certificate is not None and proposal is not None
    
    @property
    def documents_complete(self):
        """Check if all current mandatory document requirements are complete."""
        mandatory_requirement_ids = self._current_program_document_requirement_ids(mandatory_only=True)
        if not mandatory_requirement_ids:
            return True  # No mandatory document requirements configured

        completed_requirement_ids = self._completed_document_requirement_ids()
        return mandatory_requirement_ids.issubset(completed_requirement_ids)
    
    @property
    def completion_percentage(self):
        """Calculate document completion percentage (excludes qualification requirements)"""
        required_document_ids = self._current_program_document_requirement_ids(mandatory_only=False)
        if not required_document_ids:
            return 100  # No document requirements configured

        completed_requirement_ids = self._completed_document_requirement_ids()
        completed_count = len(required_document_ids.intersection(completed_requirement_ids))
        return round((completed_count / len(required_document_ids)) * 100)
    
    @property
    def documents_list(self):
        """Get only document requirements"""
        return [item for item in self.document_checklist 
                if item.requirement.requirement_type == 'document']
    
    @property
    def qualifications_list(self):
        """Get only qualification requirements"""
        return [item for item in self.document_checklist 
                if item.requirement.requirement_type == 'qualification']
    
    def generate_verification_code(self):
        """Generate a unique verification code for document submission"""
        while True:
            # Generate 8-character alphanumeric code (uppercase letters and digits)
            code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            # Check if code already exists
            existing = Applications.query.filter_by(verification_code=code).first()
            if not existing:
                self.verification_code = code
                self.code_generated_at = datetime.now(timezone.utc)
                return code
    
    def __repr__(self):
        return f'<Application {self.id}: {self.applicant.email} -> {self.program.program_name}>'
    
class ApplicationDocuments(db.Model):
    __tablename__ = 'application_documents'
    
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=False)
    submission_status = db.Column(db.String(20), default='pending')  # For documents: 'not_submitted', 'submitted', 'pending', 'approved', 'rejected', 'returned'
    qualification_met = db.Column(db.Boolean, default=False)  # NEW: For qualifications: True/False
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    verified_at = db.Column(db.DateTime)
    admin_feedback = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_utc_now)
    updated_at = db.Column(db.DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Relationships
    requirement = db.relationship('Requirements', back_populates='application_documents')
    verifier = db.relationship('User', backref='verified_documents')
    
    @property
    def is_mandatory(self):
        """Check if this requirement is mandatory for the program"""
        prog_req = db.session.query(ProgramRequirements).filter_by(
            program_id=self.application.program_id,
            requirement_id=self.requirement_id
        ).first()
        return prog_req.is_mandatory if prog_req else False
    
    @property
    def is_complete(self):
        """Check if requirement is complete (document verified/approved or qualification met)."""
        if self.requirement.requirement_type == 'document':
            return self.submission_status in ['approved', 'verified']
        elif self.requirement.requirement_type == 'qualification':
            return self.qualification_met
        return False
    
    def __repr__(self):
        return f'<ApplicationDocument {self.id}: {self.requirement.requirement_name} ({self.requirement.requirement_type}) - {self.submission_status}>'

class ApplicationDocumentUploads(db.Model):
    """Store uploaded documents for initial verification before physical submission"""
    __tablename__ = 'application_document_uploads'
    
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False, index=True)
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    file_type = db.Column(db.String(100))
    verification_status = db.Column(db.String(20), default='pending', index=True)  # 'pending', 'approved', 'rejected'
    admin_feedback = db.Column(db.Text)  # Feedback from admin review
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    verified_at = db.Column(db.DateTime)
    uploaded_at = db.Column(db.DateTime, default=get_utc_now)
    updated_at = db.Column(db.DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Relationships
    requirement = db.relationship('Requirements')
    verifier = db.relationship('User', backref='verified_uploads', foreign_keys=[verified_by])
    
    @property
    def is_mandatory(self):
        """Check if this requirement is mandatory for the program"""
        prog_req = db.session.query(ProgramRequirements).filter_by(
            program_id=self.application.program_id,
            requirement_id=self.requirement_id
        ).first()
        return prog_req.is_mandatory if prog_req else False
    
    def __repr__(self):
        return f'<ApplicationDocumentUpload {self.id}: {self.requirement.requirement_name} - {self.verification_status}>'

class FileAttachment(db.Model):
    __tablename__ = 'file_attachment'
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    file_type = db.Column(db.String(100))
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    uploaded_at = db.Column(db.DateTime, default=get_utc_now)
    attachment_type = db.Column(db.String(50))
    
    uploader = db.relationship('User', backref='uploaded_files')
    program = db.relationship('Programs', back_populates='file_attachment') 

    
    def __repr__(self):
        return f'<FileAttachment {self.filename}>'

class Notifications(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    notif_title = db.Column(db.String(255), nullable=False)
    notif_message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, index=True)
    related_id = db.Column(db.Integer, nullable=True)  # ID of related resource (application, announcement, etc.)
    related_type = db.Column(db.String(50), nullable=True)  # Type: 'application', 'announcement', 'program', etc.
    created_at = db.Column(db.DateTime, default=get_utc_now)
    
    def get_url(self):
        """Generate the appropriate URL for this notification based on its type"""
        if not self.related_type:
            return None
            
        if self.related_type == 'application':
            return f'/community/applications/{self.related_id}' if self.related_id else '/community/applications'
        elif self.related_type == 'announcement':
            return f'/community/announcements/{self.related_id}' if self.related_id else '/community/announcements'
        elif self.related_type == 'program':
            return f'/community/programs/{self.related_id}' if self.related_id else '/community/programs'
        elif self.related_type == 'subsidy':
            return '/community/other_services'
        elif self.related_type == 'schedule':
            return '/community/schedule'
        elif self.related_type == 'profile':
            return '/community/profile'
        elif self.related_type == 'assessment':
            return f'/admin/assessments/{self.related_id}' if self.related_id else '/admin/assessments'
        else:
            return None

    def get_admin_url(self):
        """Generate the appropriate URL for admin-side notifications"""
        if not self.related_type:
            return None

        if self.related_type == 'application':
            return f'/admin/applications/{self.related_id}' if self.related_id else '/admin/applications'
        elif self.related_type == 'announcement':
            return f'/admin/announcements'
        elif self.related_type == 'program':
            return f'/admin/programs'
        elif self.related_type == 'assessment':
            return f'/admin/assessments/{self.related_id}' if self.related_id else '/admin/assessments'
        elif self.related_type == 'subsidy':
            return '/admin/subsidy'
        elif self.related_type == 'profile':
            return f'/admin/community/view/{self.related_id}' if self.related_id else '/admin/community'
        elif self.related_type == 'admin_alert':
            return '/admin/applications'
        else:
            return None
    
    def __repr__(self):
        return f'<Notification {self.notif_title}>'


class Municipality(db.Model):
    __tablename__ = 'municipalities'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=get_utc_now)
    updated_at = db.Column(db.DateTime, default=get_utc_now, onupdate=get_utc_now)

    def __repr__(self):
        return f'<Municipality {self.name}>'

class CommunityUsers(db.Model):
    __tablename__ = 'community_users'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)  
    age = db.Column(db.Integer, nullable=False, index=True)  
    gender = db.Column(db.String(20))  # Male, Female, Other
    mobile_no = db.Column(db.String(20))
    birth_month = db.Column(db.Integer)
    birth_day = db.Column(db.Integer)
    birth_year = db.Column(db.Integer)
    barangay = db.Column(db.String(100), index=True)  
    sitio = db.Column(db.String(100))
    address = db.Column(db.Text)
    municipality = db.Column(db.String(100), default='Mabitac')
    religion = db.Column(db.String(100))  # NEW: Religion
    place_of_birth = db.Column(db.String(200))  # NEW: Place of birth
    civil_status = db.Column(db.String(50))  # NEW: Civil status (Single, Married, Divorced, Widowed, etc.)
    highest_education_attainment = db.Column(db.String(100))  # NEW: Highest education (Elementary, High School, College, etc.)
    is_currently_employed = db.Column(db.Boolean, default=False, index=True) 
    occupation = db.Column(db.String(100))
    occupation_sector = db.Column(db.String(100))  # Logical grouping: agriculture, services, education, etc.
    is_student = db.Column(db.Boolean, default=False, index=True)  
    is_solo_parent = db.Column(db.Boolean, default=False, index=True) 
    is_pwd = db.Column(db.Boolean, default=False, index=True)  
    disability_type = db.Column(db.String(100))
    family_annual_income = db.Column(db.Numeric(12, 2), index=True)  
    income_category = db.Column(db.String(50), index=True)  # Backend flag: 'Indigent Families', 'Low Income Families', or None
    created_at = db.Column(db.DateTime, default=get_utc_now)
    
    # Verification status fields for Senior Citizen, PWD, Solo Parent
    # Status values: 'none', 'pending', 'approved', 'rejected'
    senior_citizen_verification = db.Column(db.String(20), default='none', index=True)
    senior_citizen_id_number = db.Column(db.String(50))
    senior_citizen_verified_at = db.Column(db.DateTime)
    senior_citizen_verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    senior_citizen_document_path = db.Column(db.String(255))
    senior_citizen_rejection_reason = db.Column(db.Text)
    
    pwd_verification = db.Column(db.String(20), default='none', index=True)
    pwd_id_number = db.Column(db.String(50))
    pwd_verified_at = db.Column(db.DateTime)
    pwd_verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    pwd_document_path = db.Column(db.String(255))
    pwd_rejection_reason = db.Column(db.Text)
    
    solo_parent_verification = db.Column(db.String(20), default='none', index=True)
    solo_parent_id_number = db.Column(db.String(50))
    solo_parent_verified_at = db.Column(db.DateTime)
    solo_parent_verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    solo_parent_document_path = db.Column(db.String(255))
    solo_parent_rejection_reason = db.Column(db.Text)
    
    # Areas of concern for program recommendations
    areas_of_concern = db.Column(db.Text)  # JSON: ['Business', 'Education', 'Medical', 'Emergency']
    
    def __repr__(self):
        return f'<CommunityUser {self.user_id}>'
    
    def calculate_income_category(self):
        """
        Calculate and return the income category based on Family Monthly Income.
        Categories:
        - ≤ 10,000: "Indigent Families"
        - 10,001 - 20,000: "Low Income Families"
        - 20,001 - 30,000: "Low Income Families"
        - Otherwise: None
        """
        if self.family_annual_income is None:
            return None
        
        income = float(self.family_annual_income)
        
        if income <= 10000:
            return "Indigent Families"
        elif 10000 < income <= 30000:
            return "Low Income Families"
        else:
            return None
    
    def update_income_category(self):
        """Update the income_category field based on current family_annual_income."""
        self.income_category = self.calculate_income_category()
    
    def get_areas_of_concern(self):
        """Get areas of concern as a list"""
        if self.areas_of_concern:
            try:
                import json
                return json.loads(self.areas_of_concern)
            except:
                return []
        return []
    
    def set_areas_of_concern(self, areas_list):
        """Set areas of concern from a list"""
        if areas_list:
            import json
            self.areas_of_concern = json.dumps(areas_list)
        else:
            self.areas_of_concern = None

class AdminUsers(db.Model):
    __tablename__ = 'admin_users'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    municipality = db.Column(db.String(100), index=True)
    created_at = db.Column(db.DateTime, default=get_utc_now)
    
    def __repr__(self):
        return f'<AdminUser {self.user_id}>'

class ShelterPhotos(db.Model):
    __tablename__ = 'shelter_photos'
    
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    photo_path = db.Column(db.String(255), nullable=False)
    caption = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=get_utc_now)
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    verified_at = db.Column(db.DateTime)
    verification_status = db.Column(db.String(20), default='pending')  # 'pending', 'approved', 'rejected'
    admin_notes = db.Column(db.Text)
    
    verifier = db.relationship('User', backref='verified_shelter_photos')
    
    def __repr__(self):
        return f'<ShelterPhoto {self.id} for Application {self.application_id}>'


class CALDocuments(db.Model):
    """CA (Capital Assistance) pre-approval documents: Certificate and Proposal"""
    __tablename__ = 'cal_documents'
    
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    document_type = db.Column(db.String(50), nullable=False)  # 'certificate' or 'proposal'
    file_path = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255))
    description = db.Column(db.Text)  # For proposal: brief description of the business plan
    uploaded_at = db.Column(db.DateTime, default=get_utc_now)
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    verified_at = db.Column(db.DateTime)
    verification_status = db.Column(db.String(20), default='pending')  # 'pending', 'approved', 'rejected'
    admin_notes = db.Column(db.Text)
    
    verifier = db.relationship('User', backref='verified_cal_documents')
    
    def __repr__(self):
        return f'<CALDocument {self.document_type} for Application {self.application_id}>'


class AdminActivityLog(db.Model):
    """Track admin activities for audit trail"""
    __tablename__ = 'admin_activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False, index=True)  # e.g., 'approve_application', 'verify_document', 'create_announcement'
    action_type = db.Column(db.String(20), nullable=False, default='update', index=True)  # 'create', 'update', 'delete', 'approve', 'reject', 'verify', 'generate', 'export'
    entity_type = db.Column(db.String(50), nullable=False, index=True)  # 'application', 'document', 'announcement', 'user', 'admin', 'verification', 'beneficiaries_list', 'recommendation'
    entity_id = db.Column(db.Integer)  # ID of the affected entity (nullable for bulk/general actions)
    description = db.Column(db.Text, nullable=False)  # Human-readable description
    details = db.Column(db.Text)  # JSON string for extra context (old/new values, etc.)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    admin = db.relationship('User', backref=db.backref('activity_logs', lazy='dynamic'))
    
    __table_args__ = (
        db.Index('idx_activity_admin_date', 'admin_id', 'created_at'),
        db.Index('idx_activity_entity', 'entity_type', 'entity_id'),
    )
    
    def __repr__(self):
        return f'<AdminActivityLog {self.id}: {self.action} by Admin {self.admin_id}>'
    
    @property
    def admin_name(self):
        """Get the admin's full name"""
        return f'{self.admin.first_name} {self.admin.last_name}' if self.admin else 'Unknown Admin'
    
    @property
    def details_dict(self):
        """Return details as dictionary"""
        if self.details:
            try:
                import json
                return json.loads(self.details)
            except:
                return {}
        return {}


class UserActivityLog(db.Model):
    """Track community user activities for analytics and audit trail"""
    __tablename__ = 'user_activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False, index=True)
    action_type = db.Column(db.String(20), nullable=False, default='view', index=True)  # 'view', 'create', 'update', 'delete', 'search', 'auth', 'upload', 'save', 'hide'
    entity_type = db.Column(db.String(50), nullable=False, index=True)  # 'program', 'application', 'document', 'profile', 'session', 'search'
    entity_id = db.Column(db.Integer)
    description = db.Column(db.Text, nullable=False)
    details = db.Column(db.Text)  # JSON string for extra context
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=get_utc_now, index=True)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], back_populates='user_activity_logs')
    
    __table_args__ = (
        db.Index('idx_user_activity_user_date', 'user_id', 'created_at'),
        db.Index('idx_user_activity_entity', 'entity_type', 'entity_id'),
    )
    
    def __repr__(self):
        return f'<UserActivityLog {self.id}: {self.action} by User {self.user_id}>'
    
    @property
    def user_name(self):
        return f'{self.user.first_name} {self.user.last_name}' if self.user else 'Unknown User'
    
    @property
    def details_dict(self):
        if self.details:
            try:
                import json
                return json.loads(self.details)
            except:
                return {}
        return {}


class SavedProgram(db.Model):
    """Programs saved/bookmarked by community users"""
    __tablename__ = 'saved_programs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey('programs.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('saved_programs', lazy='dynamic'))
    program = db.relationship('Programs', backref=db.backref('saved_by_users', lazy='dynamic'))
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'program_id', name='uq_saved_program'),
    )


class HiddenProgram(db.Model):
    """Programs hidden/not interested by community users"""
    __tablename__ = 'hidden_programs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey('programs.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('hidden_programs', lazy='dynamic'))
    program = db.relationship('Programs', backref=db.backref('hidden_by_users', lazy='dynamic'))
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'program_id', name='uq_hidden_program'),
    )


class ApplicationWorkflowStatus(db.Model):
    """Track workflow step progress for each application"""
    __tablename__ = 'application_workflow_status'
    
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    workflow_step_id = db.Column(db.Integer, db.ForeignKey('program_workflow_steps.id'), nullable=False)
    step_status = db.Column(db.String(20), nullable=False, default='not_started')  # not_started, in_progress, pending_review, approved, rejected, completed
    started_at = db.Column(db.DateTime)  # When user started working on this step
    completed_at = db.Column(db.DateTime)  # When user completed their part
    reviewed_at = db.Column(db.DateTime)  # When admin reviewed this step
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))  # Admin who reviewed
    admin_feedback = db.Column(db.Text)  # Admin comments/feedback
    step_data = db.Column(db.Text)  # JSON data specific to this step (uploaded files, form data, etc.)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    application = db.relationship('Applications', foreign_keys='ApplicationWorkflowStatus.application_id', overlaps='workflow_status')
    reviewer = db.relationship('User', backref='reviewed_workflow_steps')
    workflow_step = db.relationship('ProgramWorkflowSteps', foreign_keys='ApplicationWorkflowStatus.workflow_step_id', lazy='select', overlaps='application_statuses')
    
    # Composite unique constraint to prevent duplicate step status per application
    __table_args__ = (
        db.UniqueConstraint('application_id', 'workflow_step_id'),
        db.Index('idx_workflow_status', 'application_id', 'step_status'),
    )
    
    def __repr__(self):
        return f'<ApplicationWorkflowStatus App:{self.application_id} Step:{self.workflow_step_id} Status:{self.step_status}>'
    
    @property
    def step_data_json(self):
        """Return step data as dictionary"""
        if self.step_data:
            try:
                import json
                return json.loads(self.step_data)
            except:
                return {}
        return {}
    
    def set_step_data(self, data_dict):
        """Set step data from dictionary"""
        if data_dict:
            import json
            self.step_data = json.dumps(data_dict)
        else:
            self.step_data = None


class Assessment(db.Model):
    """SCSR Assessment: interviews, home visits, and case study records"""
    __tablename__ = 'assessments'

    SEVERITY_LEVELS = ('unrated', 'low', 'moderate', 'high', 'critical')

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False, index=True)
    assessment_type = db.Column(db.String(50), nullable=False, index=True)  # 'interview', 'home_visit'
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    scheduled_date = db.Column(db.DateTime, index=True)
    scheduled_time = db.Column(db.String(10))  # e.g. "09:00 AM"
    location = db.Column(db.String(255))
    status = db.Column(db.String(20), nullable=False, default='scheduled', index=True)  # 'scheduled', 'completed', 'cancelled'
    findings = db.Column(db.Text)  # SCSR output / assessment findings
    problems_identified = db.Column(db.Text)
    recommendations = db.Column(db.Text)
    case_severity = db.Column(db.String(20), nullable=False, default='unrated', index=True)
    severity_score = db.Column(db.Integer, index=True)  # 0 to 100
    severity_factors = db.Column(db.Text)  # JSON string breakdown of rubric factors
    severity_justification = db.Column(db.Text)
    severity_updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    severity_updated_at = db.Column(db.DateTime)
    conducted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    application = db.relationship('Applications', backref='assessments')
    conductor = db.relationship('User', backref='conducted_assessments', foreign_keys=[conducted_by])
    severity_reviewer = db.relationship('User', backref='severity_updated_assessments', foreign_keys=[severity_updated_by])
    documents = db.relationship('AssessmentDocument', backref='assessment', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Assessment {self.id}: {self.assessment_type} for Application {self.application_id}>'

    @property
    def severity_display(self):
        """Human-readable severity label"""
        return (self.case_severity or 'unrated').replace('_', ' ').title()

    @property
    def has_scored_severity(self):
        """True when the assessment has both level and numeric score"""
        return self.case_severity not in (None, '', 'unrated') and self.severity_score is not None


class AssessmentDocument(db.Model):
    """Documents attached to an assessment (SCSR output files, photos, etc.)"""
    __tablename__ = 'assessment_documents'

    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey('assessments.id'), nullable=False, index=True)
    file_path = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    file_type = db.Column(db.String(100))
    description = db.Column(db.Text)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    uploader = db.relationship('User', backref='uploaded_assessment_docs', foreign_keys=[uploaded_by])

    def __repr__(self):
        return f'<AssessmentDocument {self.id} for Assessment {self.assessment_id}>'