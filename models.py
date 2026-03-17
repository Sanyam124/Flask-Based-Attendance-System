from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date

db = SQLAlchemy()

# ------------------------
# MODELS
# ------------------------

class Subject(db.Model):
    __tablename__ = 'subject'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)

class Class(db.Model):
    __tablename__ = 'class'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

class ClassTeacher(db.Model):
    __tablename__ = "class_teacher"
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("class.id"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=False)
    
    __table_args__ = (db.UniqueConstraint('class_id', 'teacher_id', 'subject_id', name='_class_teacher_subject_uc'),)
    
    # --- CORRECTED: This is the single source of truth for the relationship ---
    # This defines 'ClassTeacher.teacher' and automatically creates 'User.class_assignments' via the backref.
    teacher = db.relationship("User", backref="class_assignments")
    
    subject = db.relationship("Subject")
    class_ref = db.relationship("Class", backref="class_teachers")

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=True)
    enrollment_number = db.Column(db.String(50), unique=True, nullable=True)

    class_ref = db.relationship('Class', backref='students', foreign_keys=[class_id])
    
    # --- REMOVED: The conflicting 'class_assignments' relationship was removed from here. ---
    # The backref in the ClassTeacher model now creates this property automatically.

class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    marked_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    date = db.Column(db.Date, default=date.today)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(10), nullable=False)
    session = db.Column(db.Integer, nullable=False)

    student = db.relationship('User', foreign_keys=[student_id], backref='attendances')
    marked_by_teacher = db.relationship('User', foreign_keys=[marked_by_id])
    class_ref = db.relationship('Class', backref='attendances')
    subject = db.relationship('Subject', backref='attendances')
    
    __table_args__ = (db.UniqueConstraint('student_id', 'date', 'subject_id', 'session', name='_student_date_subject_session_uc'),)

