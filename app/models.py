from app.extensions import db
from flask_login import UserMixin
from datetime import datetime
from sqlalchemy.sql import func


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
        
    # Relationships
    created_programs = db.relationship('Programs', backref='creator', lazy=True)
    announcements = db.relationship('Announcements', backref='author', lazy=True)
    notifications = db.relationship('Notifications', backref='user', lazy=True, cascade='all, delete-orphan')
    applications = db.relationship('Applications', foreign_keys='Applications.user_id', backref='applicant', lazy=True)
    reviewed_applications = db.relationship('Applications', foreign_keys='Applications.reviewed_by', backref='reviewer', lazy=True)
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
    description = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    file_attachment_id = db.Column(db.Integer, db.ForeignKey('file_attachment.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True, index=True)  # NEW: Track active programs
    
    # Relationships
    applications = db.relationship('Applications', back_populates='program', lazy=True)
    requirements = db.relationship('Requirements', secondary='program_requirements', viewonly=True)
    file_attachment = db.relationship('FileAttachment', back_populates='program', uselist=False)
    program_requirements = db.relationship('ProgramRequirements', back_populates='program', lazy='dynamic', cascade='all, delete-orphan')

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    images = db.relationship('AnnouncementImages', backref='announcement', lazy=True, cascade='all, delete-orphan')
    
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
    application_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    review_date = db.Column(db.DateTime, index=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
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
    program = db.relationship('Programs', back_populates='applications')
    
    @property
    def documents_complete(self):
        """Check if all mandatory documents are approved"""
        if not self.document_checklist:
            return False
        
        mandatory_items = []
        for doc in self.document_checklist:
            prog_req = db.session.query(ProgramRequirements).filter_by(
                program_id=self.program_id,
                requirement_id=doc.requirement_id,
                is_mandatory=True
            ).first()
            if prog_req:
                mandatory_items.append(doc)
        
        if not mandatory_items:
            return True  # No mandatory items required
        
        return all(item.is_complete for item in mandatory_items)
    
    @property
    def completion_percentage(self):
        """Calculate requirement completion percentage"""
        if not self.document_checklist:
            return 0
        
        completed_count = sum(1 for item in self.document_checklist if item.is_complete)
        return round((completed_count / len(self.document_checklist)) * 100)
    
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
    
    def __repr__(self):
        return f'<Application {self.id}: {self.applicant.email} -> {self.program.program_name}>'
    
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
        """Calculate document completion percentage"""
        if not self.document_checklist:
            return 0
        
        approved_count = sum(1 for doc in self.document_checklist 
                           if doc.submission_status == 'approved')
        return round((approved_count / len(self.document_checklist)) * 100)
    
    def __repr__(self):
        return f'<Application {self.id}: {self.applicant.email} -> {self.program.program_name}>'
    
class ApplicationDocuments(db.Model):
    __tablename__ = 'application_documents'
    
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=False)
    submission_status = db.Column(db.String(20), default='not_submitted')  # For documents: 'not_submitted', 'submitted', 'approved', 'rejected'
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Notification {self.notif_title}>'

class CommunityUsers(db.Model):
    __tablename__ = 'community_users'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)  # Added index
    age = db.Column(db.Integer, nullable=False, index=True)  # Added index for age-based queries
    mobile_no = db.Column(db.String(20))
    birth_month = db.Column(db.Integer)
    birth_day = db.Column(db.Integer)
    birth_year = db.Column(db.Integer)
    barangay = db.Column(db.String(100), index=True)  # Added index for barangay queries
    sitio = db.Column(db.String(100))
    municipality = db.Column(db.String(100))
    is_currently_employed = db.Column(db.Boolean, default=False, index=True)  # Added index
    is_student = db.Column(db.Boolean, default=False, index=True)  # Added index
    is_solo_parent = db.Column(db.Boolean, default=False, index=True)  # Added index
    family_annual_income = db.Column(db.Numeric(12, 2), index=True)  # Added index for income-based queries
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