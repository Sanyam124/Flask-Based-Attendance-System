from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash, generate_password_hash
from models import db, User, Class, ClassTeacher, Subject
from config import KNOWN_FACES_DIR
import os
import re

auth_bp = Blueprint('auth', __name__)

def login_required(role=None):
    from functools import wraps
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if 'user_id' not in session:
                flash("Please log in to access this page.", "danger")
                return redirect(url_for('auth.login'))
            if role and session.get('user_role') != role:
                flash("You do not have permission to access this page.", "warning")
                return redirect(url_for('auth.login'))
            return f(*args, **kwargs)
        return wrapper
    return decorator

def _create_user_and_associations(form):
    """Helper function to create users, with role-based email and class name validation."""
    username = form['username']
    email = form['email']
    password = form.get('password')
    role = form['role']
    class_names_str = form.get('class_name')
    subject_name = form.get('subject')
    enrollment_number = form.get('enrollment_number')

    if role != 'admin' and not email.endswith('@paruluniversity.ac.in'):
        flash("Registration for Students and Teachers requires a valid college email address (e.g., user@paruluniversity.ac.in).", "danger")
        return None
        
    if User.query.filter_by(email=email).first():
        flash("Email already registered.", "danger")
        return None
    if User.query.filter_by(username=username).first():
        flash("Username already taken.", "danger")
        return None
    if role == 'student' and class_names_str and ',' in class_names_str:
        flash("Students can only be assigned to one class.", "danger")
        return None
    if role == 'student' and not enrollment_number:
        flash("Enrollment Number is required for students.", "danger")
        return None
    if enrollment_number and User.query.filter_by(enrollment_number=enrollment_number).first():
        flash("This Enrollment Number is already registered.", "danger")
        return None
    if not password:
        flash("Password is required.", "danger")
        return None

    if role in ['student', 'teacher'] and class_names_str:
        class_names_list = [name.strip() for name in class_names_str.split(',') if name.strip()]
        for class_name in class_names_list:
            match = re.match(r'^(\d{1,2})([A-Z])(\d{1,2})$', class_name)
            if not match:
                flash(f"Class name '{class_name}' has an invalid format. Use format like '5B1' or '12C10'.", "danger")
                return None
            
            semester, course, batch = match.groups()
            if not (1 <= int(semester) <= 12):
                flash(f"Invalid semester '{semester}' in class name '{class_name}'. Must be between 1 and 12.", "danger")
                return None
            if not (1 <= int(batch) <= 99):
                flash(f"Invalid batch number '{batch}' in class name '{class_name}'. Must be between 1 and 99.", "danger")
                return None

    new_user = User(
        username=username,
        email=email,
        password=generate_password_hash(password),
        role=role,
        enrollment_number=enrollment_number if role == 'student' else None
    )
    
    db.session.add(new_user)
    if role == 'student' and class_names_str:
        class_name = class_names_str.strip()
        class_obj = Class.query.filter_by(name=class_name).first()
        if not class_obj:
            class_obj = Class(name=class_name)
            db.session.add(class_obj)
        new_user.class_ref = class_obj
    elif role == 'teacher' and class_names_str and subject_name:
        subject_obj = Subject.query.filter_by(name=subject_name.strip()).first()
        if not subject_obj:
            subject_obj = Subject(name=subject_name.strip())
            db.session.add(subject_obj)
        
        unique_class_names = {name.strip() for name in class_names_str.split(',') if name.strip()}
        for class_name in unique_class_names:
            class_obj = Class.query.filter_by(name=class_name).first()
            if not class_obj:
                class_obj = Class(name=class_name)
                db.session.add(class_obj)
            association = ClassTeacher(teacher=new_user, class_ref=class_obj, subject=subject_obj)
            db.session.add(association)
    db.session.commit()
    return new_user

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_identifier = request.form['login_identifier']
        password = request.form['password']
        
        user = None
        if '@' in login_identifier:
            user = User.query.filter_by(email=login_identifier, is_active=True).first()
        else:
            user = User.query.filter_by(enrollment_number=login_identifier, is_active=True).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['user_role'] = user.role
            session['username'] = user.username
            dashboard_map = {'student': 'student.student_dashboard', 'teacher': 'teacher.teacher_dashboard', 'admin': 'admin.admin_dashboard'}
            return redirect(url_for(dashboard_map.get(user.role, 'auth.login')))
        else:
            flash("Invalid credentials or account is inactive. Please try again.", "danger")
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        new_user = _create_user_and_associations(request.form)
        if new_user:
            if new_user.role == 'student':
                os.makedirs(os.path.join(KNOWN_FACES_DIR, new_user.username), exist_ok=True)
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for('auth.login'))
        return redirect(url_for('auth.register'))
    return render_template('register.html')
