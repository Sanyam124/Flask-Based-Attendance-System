from flask import Blueprint, render_template, session, flash, redirect, url_for, request, Response
from models import db, User, Class, Attendance, ClassTeacher, Subject
from config import KNOWN_FACES_DIR
from sqlalchemy.orm import joinedload
from datetime import date, datetime, timedelta
import os
import re
import csv
import secrets
import shutil
from io import StringIO
from werkzeug.security import generate_password_hash
from blueprints.auth import login_required, _create_user_and_associations

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/dashboard')
@login_required(role='admin')
def admin_dashboard():
    admin_id = session.get('user_id')
    admin = User.query.get_or_404(admin_id)
    total_students = User.query.filter_by(role='student', is_active=True).count()
    total_teachers = User.query.filter_by(role='teacher', is_active=True).count()
    total_classes = Class.query.count()
    today_attendance_count = Attendance.query.filter(Attendance.date == date.today()).count()
    return render_template('admin_dashboard.html', 
                           total_students=total_students, 
                           total_teachers=total_teachers, 
                           total_classes=total_classes, 
                           today_attendance_count=today_attendance_count,
                           admin=admin)

@admin_bp.route('/admin/users')
@login_required(role='admin')
def admin_manage_users():
    users = User.query.options(
        joinedload(User.class_ref),
        joinedload(User.class_assignments).joinedload(ClassTeacher.class_ref),
        joinedload(User.class_assignments).joinedload(ClassTeacher.subject)
    ).order_by(User.id).all()
    return render_template('admin_users.html', users=users)

@admin_bp.route('/admin/users/add', methods=['GET', 'POST'])
@login_required(role='admin')
def admin_add_user():
    if request.method == 'POST':
        if not request.form.get('password'):
            flash("Password is required for a new user.", "danger")
            return render_template('admin_user_form.html', user=None)
        
        new_user = _create_user_and_associations(request.form)
        if new_user:
            flash(f"User '{new_user.username}' created successfully.", "success")
            if new_user.role == 'student':
                os.makedirs(os.path.join(KNOWN_FACES_DIR, new_user.username), exist_ok=True)
            return redirect(url_for('admin.admin_manage_users'))
        return render_template('admin_user_form.html', user=None)
    return render_template('admin_user_form.html', user=None)

@admin_bp.route('/admin/users/update/<int:user_id>', methods=['GET', 'POST'])
@login_required(role='admin')
def admin_update_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        username = request.form['username']
        password = request.form.get('password')
        enrollment_number = request.form.get('enrollment_number')
        
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', username):
            flash("Invalid username. It must start with a letter and contain only letters, numbers, and underscores.", "danger")
            return render_template('admin_user_form.html', user=user)
            
        if password and len(password) < 8:
            flash("Password must be at least 8 characters long.", "danger")
            return render_template('admin_user_form.html', user=user)
        
        if user.role == 'student' and enrollment_number and not enrollment_number.isdigit():
            flash("Enrollment Number must contain only numbers.", "danger")
            return render_template('admin_user_form.html', user=user)

        user.username = username
        user.email = request.form['email']
        user.role = request.form['role']
        if password:
            user.password = generate_password_hash(password)

        class_names_str = request.form.get('class_name')
        subject_name = request.form.get('subject')

        if user.role in ['student', 'teacher'] and class_names_str:
            class_names_list = [name.strip() for name in class_names_str.split(',') if name.strip()]
            for class_name in class_names_list:
                match = re.match(r'^(\d{1,2})([A-Z])(\d{1,2})$', class_name)
                if not match:
                    flash(f"Class name '{class_name}' has an invalid format. Use format like '5B1' or '12C10'.", "danger")
                    return render_template('admin_user_form.html', user=user)
                
                semester, course, batch = match.groups()
                if not (1 <= int(semester) <= 12):
                    flash(f"Invalid semester '{semester}' in class name '{class_name}'. Must be between 1 and 12.", "danger")
                    return render_template('admin_user_form.html', user=user)
                if not (1 <= int(batch) <= 99):
                    flash(f"Invalid batch number '{batch}' in class name '{class_name}'. Must be between 1 and 99.", "danger")
                    return render_template('admin_user_form.html', user=user)

        if user.role == 'student':
            if enrollment_number:
                existing_user = User.query.filter(User.id != user.id, User.enrollment_number == enrollment_number).first()
                if existing_user:
                    flash(f"Enrollment Number '{enrollment_number}' is already taken.", "danger")
                    return render_template('admin_user_form.html', user=user)
                user.enrollment_number = enrollment_number
            else:
                 user.enrollment_number = None

            if class_names_str:
                class_obj = Class.query.filter_by(name=class_names_str.strip()).first()
                if not class_obj:
                    class_obj = Class(name=class_names_str.strip())
                    db.session.add(class_obj)
                user.class_ref = class_obj
        else:
            user.enrollment_number = None

        if user.role == 'teacher':
            user.class_id = None
            ClassTeacher.query.filter_by(teacher_id=user.id).delete()
            if class_names_str and subject_name:
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
                    db.session.add(ClassTeacher(teacher=user, class_ref=class_obj, subject=subject_obj))

        db.session.commit()
        flash(f"User '{user.username}' updated successfully.", "success")
        return redirect(url_for('admin.admin_manage_users'))

    return render_template('admin_user_form.html', user=user)

@admin_bp.route('/admin/users/deactivate/<int:user_id>', methods=['POST'])
@login_required(role='admin')
def admin_deactivate_user(user_id):
    if user_id == session.get('user_id'):
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for('admin.admin_manage_users'))
    
    user = User.query.get_or_404(user_id)
    user.is_active = False
    
    # We DON'T delete ClassTeacher assignments here, just deactivate the user.
    # This keeps history intact. 
    
    db.session.commit()
    flash(f"User account for '{user.username}' has been deactivated. They can no longer log in, but their history is preserved.", "success")
    return redirect(url_for('admin.admin_manage_users'))

@admin_bp.route('/admin/users/delete_student_permanent/<int:user_id>', methods=['POST'])
@login_required(role='admin')
def admin_delete_student_permanent(user_id):
    if user_id == session.get('user_id'):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for('admin.admin_manage_users'))
        
    user = User.query.get_or_404(user_id)
    
    if user.role != 'student':
        flash("Permanent deletion via this route is only for students.", "danger")
        return redirect(url_for('admin.admin_manage_users'))

    # Check for attendance history
    has_history = Attendance.query.filter_by(student_id=user.id).first() is not None
    if has_history:
        flash(f"Student '{user.username}' has attendance records. Please 'Deactivate' them instead of deleting to preserve school records.", "warning")
        return redirect(url_for('admin.admin_manage_users'))

    username_for_flash = user.username
    
    student_face_dir = os.path.join(KNOWN_FACES_DIR, user.username)
    if os.path.exists(student_face_dir):
        shutil.rmtree(student_face_dir)
        
    db.session.delete(user)
    db.session.commit()
    
    from extensions import frs
    frs.rebuild_encodings()

    flash(f"Student '{username_for_flash}' has been permanently removed from the system.", "success")
    return redirect(url_for('admin.admin_manage_users'))

@admin_bp.route('/admin/users/reactivate/<int:user_id>', methods=['POST'])
@login_required(role='admin')
def admin_reactivate_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = True
    db.session.commit()
    flash(f"User account for '{user.username}' has been reactivated.", "success")
    return redirect(url_for('admin.admin_manage_users'))

@admin_bp.route('/admin/classes')
@login_required(role='admin')
def admin_manage_classes():
    all_classes = Class.query.options(
        joinedload(Class.class_teachers).joinedload(ClassTeacher.teacher),
        joinedload(Class.class_teachers).joinedload(ClassTeacher.subject)
    ).all()

    def get_sort_key(cls):
        match = re.match(r'(\d+)([A-Za-z]+)(\d+)', cls.name)
        if match:
            semester, course, batch = match.groups()
            return (int(semester), course.upper(), int(batch))
        else:
            return (float('inf'), cls.name, 0)

    sorted_classes = sorted(all_classes, key=get_sort_key)
    return render_template("admin_classes.html", classes=sorted_classes)

@admin_bp.route('/admin/class/<int:class_id>/deactivate', methods=['POST'])
@login_required(role='admin')
def admin_deactivate_class(class_id):
    cls = Class.query.get_or_404(class_id)
    cls.is_active = False
    db.session.commit()
    flash(f"Class '{cls.name}' has been deactivated.", "success")
    return redirect(url_for('admin.admin_manage_classes'))

@admin_bp.route('/admin/class/<int:class_id>/reactivate', methods=['POST'])
@login_required(role='admin')
def admin_reactivate_class(class_id):
    cls = Class.query.get_or_404(class_id)
    cls.is_active = True
    db.session.commit()
    flash(f"Class '{cls.name}' has been reactivated.", "success")
    return redirect(url_for('admin.admin_manage_classes'))

@admin_bp.route('/admin/class/<int:class_id>/delete', methods=['POST'])
@login_required(role='admin')
def admin_delete_class(class_id):
    cls = Class.query.get_or_404(class_id)
    class_name = cls.name
    
    # Check if there is attendance history
    has_history = Attendance.query.filter_by(class_id=class_id).first() is not None
    if has_history:
        flash(f"Class '{class_name}' has attendance records. Please 'Deactivate' it instead of deleting it to preserve history.", "warning")
        return redirect(url_for('admin.admin_manage_classes'))

    # Unlink students instead of deleting them
    students = User.query.filter_by(class_id=class_id, role='student').all()
    for student in students:
        student.class_id = None
    
    # Remove teacher assignments
    ClassTeacher.query.filter_by(class_id=class_id).delete()
    
    db.session.delete(cls)
    db.session.commit()
    
    flash(f"Class '{class_name}' has been deleted. Assigned students are now 'Unassigned'.", "success")
    return redirect(url_for('admin.admin_manage_classes'))

@admin_bp.route('/admin/class/<int:class_id>/students')
@login_required(role='admin')
def admin_view_class_students(class_id):
    target_class = Class.query.get_or_404(class_id)
    students_in_class = User.query.filter_by(
        class_id=class_id, 
        role='student',
        is_active=True
    ).order_by(User.username).all()
    return render_template('admin_class_students.html', target_class=target_class, students=students_in_class)

@admin_bp.route('/admin/reports')
@login_required(role='admin')
def admin_reports():
    students = User.query.filter_by(role='student').options(joinedload(User.class_ref)).all()
    return render_template('admin_reports.html', students=students)

@admin_bp.route('/admin/export_attendance/<int:student_id>')
@login_required(role='admin')
def admin_export_attendance(student_id):
    student = User.query.get_or_404(student_id)
    attendance_records = Attendance.query.filter_by(student_id=student_id).options(
        joinedload(Attendance.class_ref), joinedload(Attendance.subject)
    ).order_by(Attendance.date, Attendance.session).all()
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["Student Name", "Class", "Subject", "Session", "Date", "Timestamp", "Status"])
    for record in attendance_records:
        writer.writerow([
            student.username, record.class_ref.name, record.subject.name, record.session, record.date, record.timestamp.strftime("%H:%M:%S"), record.status
        ])
    output = si.getvalue()
    si.close()
    return Response(output, mimetype="text/csv", headers={"Content-disposition": f"attachment; filename={student.username}_attendance.csv"})

# ----------------------------
# FIX 1: Admin-Initiated Face Registration
# ----------------------------
@admin_bp.route('/admin/students/issue_token/<int:user_id>', methods=['POST'])
@login_required(role='admin')
def admin_issue_registration_token(user_id):
    student = User.query.get_or_404(user_id)
    if student.role != 'student':
        flash("Registration tokens can only be issued for students.", "danger")
        return redirect(url_for('admin.admin_manage_users'))

    # Check if already registered
    save_path = os.path.join(KNOWN_FACES_DIR, student.username)
    if os.path.exists(save_path) and len(os.listdir(save_path)) >= 50:
        flash(f"'{student.username}' already has a face registered. Reset their face data first if needed.", "warning")
        return redirect(url_for('admin.admin_view_class_students', class_id=student.class_id))

    # Generate a secure random token, valid for 10 minutes
    token = secrets.token_hex(32)
    student.registration_token = token
    student.registration_token_expires = datetime.now() + timedelta(minutes=10)
    db.session.commit()

    flash(
        f"Registration token issued for '{student.username}'. They have 10 minutes to complete face capture. "
        f"Tell them to log in and go to their dashboard.",
        "success"
    )
    return redirect(url_for('admin.admin_view_class_students', class_id=student.class_id))

# ----------------------------
# FIX 8: Admin-Only Face Data Reset
# ----------------------------
@admin_bp.route('/admin/students/reset_face/<int:user_id>', methods=['POST'])
@login_required(role='admin')
def admin_reset_face_data(user_id):
    student = User.query.get_or_404(user_id)
    if student.role != 'student':
        flash("This action is only for students.", "danger")
        return redirect(url_for('admin.admin_manage_users'))

    student_face_dir = os.path.join(KNOWN_FACES_DIR, student.username)
    if os.path.exists(student_face_dir):
        shutil.rmtree(student_face_dir)
        os.makedirs(student_face_dir, exist_ok=True)

    # Clear token too
    student.registration_token = None
    student.registration_token_expires = None
    db.session.commit()

    from extensions import frs
    frs.rebuild_encodings()
    flash(f"Face data for '{student.username}' has been reset. Issue a new registration token to re-register.", "success")
    return redirect(url_for('admin.admin_view_class_students', class_id=student.class_id))
