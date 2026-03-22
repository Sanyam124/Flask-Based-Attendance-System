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
            if role:
                allowed_roles = role if isinstance(role, list) else [role]
                if session.get('user_role') not in allowed_roles:
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

    # Removed paruluniversity.ac.in domain restriction to allow general integrations
    if User.query.filter_by(email=email).first():
        flash("Email already registered.", "danger")
        return None
    if role == 'student' and class_names_str and ',' in class_names_str:
        flash("Students can only be assigned to one class.", "danger")
        return None
    if role == 'student' and (not enrollment_number or not enrollment_number.strip()):
        flash("Enrollment Number is required for students.", "danger")
        return None
    if role == 'student' and enrollment_number and not enrollment_number.strip().isdigit():
        flash("Enrollment Number must contain only numbers.", "danger")
        return None
    org_id = session.get('organization_id')
    if enrollment_number and User.query.filter_by(enrollment_number=enrollment_number, organization_id=org_id).first():
        flash("This Enrollment Number is already registered in your organization.", "danger")
        return None
    if not password:
        flash("Password is required.", "danger")
        return None

    if role in ['student', 'teacher'] and class_names_str:
        pass  # Format validation completely removed as per user request

    new_user = User(
        username=username,
        email=email,
        password=generate_password_hash(password),
        role=role,
        enrollment_number=enrollment_number if role == 'student' else None,
        organization_id=org_id
    )
    
    db.session.add(new_user)

    if role == 'student' and class_names_str:
        class_name = class_names_str.strip()
        class_obj = Class.query.filter_by(name=class_name, organization_id=org_id).first()
        if not class_obj:
            flash(f"Class '{class_name}' does not exist in your organization.", "danger")
            return None
        new_user.class_ref = class_obj

    elif role == 'teacher' and class_names_str and subject_name:
        # Get subject (must exist)
        subject_obj = Subject.query.filter_by(name=subject_name.strip(), organization_id=org_id).first()
        if not subject_obj:
            flash(f"Subject '{subject_name}' does not exist in your organization. Please create it first.", "danger")
            return None
        
        unique_class_names = {name.strip() for name in class_names_str.split(',') if name.strip()}
        for class_name in unique_class_names:
            class_obj = Class.query.filter_by(name=class_name, organization_id=org_id).first()
            if not class_obj:
                flash(f"Class '{class_name}' does not exist.", "danger")
                return None
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
            # Try enrollment number first (for students), then username (for teachers/admins)
            user = User.query.filter_by(enrollment_number=login_identifier, is_active=True).first()
            if not user:
                user = User.query.filter_by(username=login_identifier, is_active=True).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['user_role'] = user.role
            session['username'] = user.username
            session['organization_id'] = user.organization_id
            
            dashboard_map = {
                'student': 'student.student_dashboard', 
                'teacher': 'teacher.teacher_dashboard', 
                'principal': 'admin.admin_dashboard',
                'admin': 'system.superadmin_dashboard'  # to be built
            }
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
    flash("Public registration is currently closed. Please consult your administrator to gain access.", "danger")
    return redirect(url_for('auth.login'))
