from app.extensions import db
from flask_login import UserMixin
from datetime import datetime
from sqlalchemy.sql import func
import secrets
import string


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
    role = db.Column(db.String(20), nullable=False, index=True) # 'admin' or 'community'
    profile_pic = db.Column(db.String(255))
    last_activity = db.Column(db.DateTime)
    profile_complete_alert_dismissed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
        
    # Relationships
    created_programs = db.relationship('Programs', backref='creator', lazy=True)
    announcements = db.relationship('Announcements', backref='author', lazy=True)
    notifications = db.relationship('Notifications', backref='user', lazy=True, cascade='all, delete-orphan')
    applications = db.relationship('Applications', foreign_keys='Applications.user_id', backref='applicant', lazy=True)
    reviewed_applications = db.relationship('Applications', foreign_keys='Applications.reviewed_by', backref='reviewer', lazy=True)
    scheduled_claims = db.relationship('Applications', foreign_keys='Applications.claim_scheduled_by', backref='claim_scheduler', lazy=True)
    community_profile = db.relationship('CommunityUsers', backref='user', uselist=False, cascade='all, delete-orphan')
    admin_profile = db.relationship('AdminUsers', backref='user', uselist=False, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<User {self.email}>'

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
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    file_attachment_id = db.Column(db.Integer, db.ForeignKey('file_attachment.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True, index=True)  # NEW: Track active programs
    allow_online_upload = db.Column(db.Boolean, default=True)  # Enable/disable online document submission
    
    # Relationships
    applications = db.relationship('Applications', back_populates='program', lazy=True)
    requirements = db.relationship('Requirements', secondary='program_requirements', viewonly=True)
    file_attachment = db.relationship('FileAttachment', back_populates='program', uselist=False)
    program_requirements = db.relationship('ProgramRequirements', back_populates='program', lazy='select', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Program {self.program_name}>'

class Requirements(db.Model):
    __tablename__ = 'requirements'
    
    id = db.Column(db.Integer, primary_key=True)
    requirement_name = db.Column(db.String(255), nullable=False)  # Changed from document_name
    requirement_type = db.Column(db.String(50), nullable=False, default='document', index=True)  # NEW: 'document' or 'qualification'
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    program = db.relationship('Programs', back_populates='program_requirements')
    requirement = db.relationship('Requirements', back_populates='requirement_programs')

    def __repr__(self):
        return f'<ProgramRequirement {self.program_id}-{self.requirement_id}>'

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<AnnouncementImage {self.id}>'

class Applications(db.Model):
    __tablename__ = 'applications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    program_id = db.Column(db.Integer, db.ForeignKey('programs.id'), nullable=False, index=True)
    application_status = db.Column(db.String(20), nullable=False, default='pending', index=True)
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
    
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
    
    # Note: applicant, reviewer, and claim_scheduler relationships are defined in User model
    
    @property
    def cal_docs_verified(self):
        """Check if CAL Certificate and Proposal are both verified"""
        if not self.cal_documents:
            return False
        certificate = next((d for d in self.cal_documents if d.document_type == 'certificate' and d.verification_status == 'approved'), None)
        proposal = next((d for d in self.cal_documents if d.document_type == 'proposal' and d.verification_status == 'approved'), None)
        return certificate is not None and proposal is not None
    
    @property
    def documents_complete(self):
        """Check if all mandatory documents are approved"""
        if not self.document_checklist:
            return False
            
        mandatory_docs = []
        for doc in self.document_checklist:
            prog_req = db.session.query(ProgramRequirements).filter_by(
                program_id=self.program_id,
                requirement_id=doc.requirement_id,
                is_mandatory=True
            ).first()
            if prog_req:
                mandatory_docs.append(doc)
        
        if not mandatory_docs:
            return True  # No mandatory docs required
            
        return all(doc.submission_status == 'approved' for doc in mandatory_docs)
    
    @property
    def completion_percentage(self):
        """Calculate document completion percentage (excludes qualification requirements)"""
        if not self.document_checklist:
            return 0
        
        # Only count document type requirements, not qualifications
        document_items = [item for item in self.document_checklist 
                         if item.requirement.requirement_type == 'document']
        
        if not document_items:
            return 100  # No documents required means 100% complete
        
        approved_count = sum(1 for doc in document_items 
                           if doc.submission_status == 'approved')
        return round((approved_count / len(document_items)) * 100)
    
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
                self.code_generated_at = datetime.utcnow()
                return code
    
    def __repr__(self):
        return f'<Application {self.id}: {self.applicant.email} -> {self.program.program_name}>'
    
class ApplicationDocuments(db.Model):
    __tablename__ = 'application_documents'
    
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=False)
    submission_status = db.Column(db.String(20), default='pending')  # For documents: 'pending', 'on-hold', 'approved', 'rejected'
    qualification_met = db.Column(db.Boolean, default=False)  # NEW: For qualifications: True/False
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    verified_at = db.Column(db.DateTime)
    admin_feedback = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
        """Check if requirement is complete (document approved or qualification met)"""
        if self.requirement.requirement_type == 'document':
            return self.submission_status == 'approved'
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
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def get_url(self):
        """Generate the appropriate URL for this notification based on its type"""
        if not self.related_type or not self.related_id:
            return None
            
        if self.related_type == 'application':
            return f'/community/applications/{self.related_id}'
        elif self.related_type == 'announcement':
            return f'/community/announcements/{self.related_id}'
        elif self.related_type == 'program':
            return f'/community/programs/{self.related_id}'
        elif self.related_type == 'schedule':
            return '/community/schedule'
        elif self.related_type == 'profile':
            return '/community/profile'
        else:
            return None
    
    def __repr__(self):
        return f'<Notification {self.notif_title}>'

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
    is_currently_employed = db.Column(db.Boolean, default=False, index=True) 
    occupation = db.Column(db.String(100))
    is_student = db.Column(db.Boolean, default=False, index=True)  
    is_solo_parent = db.Column(db.Boolean, default=False, index=True) 
    is_pwd = db.Column(db.Boolean, default=False, index=True)  
    disability_type = db.Column(db.String(100))
    family_annual_income = db.Column(db.Numeric(12, 2), index=True)  
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<CommunityUser {self.user_id}>'

class AdminUsers(db.Model):
    __tablename__ = 'admin_users'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<AdminUser {self.user_id}>'

class ShelterPhotos(db.Model):
    __tablename__ = 'shelter_photos'
    
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    photo_path = db.Column(db.String(255), nullable=False)
    caption = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    verified_at = db.Column(db.DateTime)
    verification_status = db.Column(db.String(20), default='pending')  # 'pending', 'approved', 'rejected'
    admin_notes = db.Column(db.Text)
    
    verifier = db.relationship('User', backref='verified_shelter_photos')
    
    def __repr__(self):
        return f'<ShelterPhoto {self.id} for Application {self.application_id}>'


class CALDocuments(db.Model):
    """CAL (Capital Assistance for Livelihood) pre-approval documents: Certificate and Proposal"""
    __tablename__ = 'cal_documents'
    
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    document_type = db.Column(db.String(50), nullable=False)  # 'certificate' or 'proposal'
    file_path = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255))
    description = db.Column(db.Text)  # For proposal: brief description of the business plan
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    verified_at = db.Column(db.DateTime)
    verification_status = db.Column(db.String(20), default='pending')  # 'pending', 'approved', 'rejected'
    admin_notes = db.Column(db.Text)
    
    verifier = db.relationship('User', backref='verified_cal_documents')
    
    def __repr__(self):
        return f'<CALDocument {self.document_type} for Application {self.application_id}>'