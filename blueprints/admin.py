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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

admin_bp = Blueprint('admin', __name__)

def _move_user_face_data(user, old_rel_path):
    """Helper to move face data folder when user properties change."""
    from utils import get_face_folder_name
    from config import KNOWN_FACES_DIR
    from extensions import frs
    import shutil
    import os

    new_rel_path = get_face_folder_name(user)
    if old_rel_path == new_rel_path:
        return

    old_full_path = os.path.join(KNOWN_FACES_DIR, old_rel_path)
    new_full_path = os.path.join(KNOWN_FACES_DIR, new_rel_path)

    if os.path.exists(old_full_path):
        os.makedirs(os.path.dirname(new_full_path), exist_ok=True)
        try:
            if os.path.exists(new_full_path):
                shutil.rmtree(new_full_path)
            shutil.move(old_full_path, new_full_path)
            frs.rebuild_encodings()
        except Exception as e:

@admin_bp.route('/admin/dashboard')
@login_required(role='principal')
def admin_dashboard():
    admin_id = session.get('user_id')
    admin = User.query.filter_by(id=admin_id, organization_id=session.get("organization_id")).first_or_404()
    total_students = User.query.filter_by(organization_id=session.get('organization_id'), role='student', is_active=True).count()
    total_teachers = User.query.filter_by(organization_id=session.get('organization_id'), role='teacher', is_active=True).count()
    total_classes = Class.query.filter_by(organization_id=session.get('organization_id')).count()
    today_attendance_count = Attendance.query.filter(Attendance.date == date.today()).count()
    return render_template('admin_dashboard.html', 
                           total_students=total_students, 
                           total_teachers=total_teachers, 
                           total_classes=total_classes, 
                           today_attendance_count=today_attendance_count,
                           admin=admin)

# ─────────────────────────────────────────────────────────────────────────────
#  SUBJECT MANAGEMENT (Principal)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/admin/subjects')
@login_required(role='principal')
def admin_manage_subjects():
    org_id = session.get('organization_id')
    subjects = Subject.query.filter_by(organization_id=org_id).order_by(Subject.name).all()
    return render_template('admin_subjects.html', subjects=subjects)

@admin_bp.route('/admin/subjects/add', methods=['POST'])
@login_required(role='principal')
def admin_add_subject():
    org_id = session.get('organization_id')
    name = request.form.get('name', '').strip()
    if not name:
        flash("Subject name cannot be empty.", "danger")
        return redirect(url_for('admin.admin_manage_subjects'))
    
    existing = Subject.query.filter_by(name=name, organization_id=org_id).first()
    if existing:
        flash(f"Subject '{name}' already exists in your school.", "warning")
        return redirect(url_for('admin.admin_manage_subjects'))
    
    new_sub = Subject(name=name, organization_id=org_id)
    try:
        db.session.add(new_sub)
        db.session.commit()
        flash(f"Subject '{name}' added successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error adding subject: {str(e)}", "danger")
    return redirect(url_for('admin.admin_manage_subjects'))

@admin_bp.route('/admin/subjects/delete/<int:subject_id>', methods=['POST'])
@login_required(role='principal')
def admin_delete_subject(subject_id):
    org_id = session.get('organization_id')
    subject = Subject.query.filter_by(id=subject_id, organization_id=org_id).first_or_404()
    
    # Check if subject is in use
    in_use = ClassTeacher.query.filter_by(subject_id=subject.id).first()
    if in_use:
        flash(f"Subject '{subject.name}' cannot be deleted because it is assigned to one or more classes/teachers.", "danger")
        return redirect(url_for('admin.admin_manage_subjects'))
    
    db.session.delete(subject)
    db.session.commit()
    flash(f"Subject '{subject.name}' deleted.", "info")
    return redirect(url_for('admin.admin_manage_subjects'))

@admin_bp.route('/admin/users')
@login_required(role='principal')
def admin_manage_users():
    """Shows ALL users in the organization."""
    users = User.query.filter_by(organization_id=session.get('organization_id')).options(
        joinedload(User.class_ref),
        joinedload(User.class_assignments).joinedload(ClassTeacher.class_ref),
        joinedload(User.class_assignments).joinedload(ClassTeacher.subject)
    ).order_by(User.id).all()
    from extensions import frs
    from utils import get_face_folder_name
    registered_status = {u.id: frs.is_registered(get_face_folder_name(u)) for u in users if u.role == 'student'}
    return render_template('admin_users.html', users=users, registered=registered_status, active_section='all')

@admin_bp.route('/admin/students')
@login_required(role='principal')
def admin_manage_students():
    """Dedicated view for managing students."""
    students = User.query.filter_by(organization_id=session.get('organization_id'), role='student').options(
        joinedload(User.class_ref)
    ).order_by(User.id).all()
    
    from extensions import frs
    from utils import get_face_folder_name
    registered_status = {s.id: frs.is_registered(get_face_folder_name(s)) for s in students}
    
    return render_template('admin_students.html', students=students, registered=registered_status, active_section='students')

@admin_bp.route('/admin/users/add', methods=['GET', 'POST'])
@login_required(role='principal')
def admin_add_user():
    org_id = session.get('organization_id')
    classes = Class.query.filter_by(organization_id=org_id).order_by(Class.name).all()
    subjects = Subject.query.filter_by(organization_id=org_id).order_by(Subject.name).all()

    if request.method == 'POST':
        # Backend security: Ensure principal only creates students or teachers
        role = request.form.get('role')
        if role not in ['student', 'teacher']:
            flash("You do not have permission to create users with this role.", "danger")
            return render_template('admin_user_form.html', user=None, classes=classes, subjects=subjects)

        if not request.form.get('password'):
            flash("Password is required for a new user.", "danger")
            return render_template('admin_user_form.html', user=None, classes=classes, subjects=subjects)
        
        new_user = _create_user_and_associations(request.form)
        if new_user:
            flash(f"User '{new_user.username}' created successfully.", "success")
            if new_user.role == 'student':
                from utils import get_face_folder_name
                os.makedirs(os.path.join(KNOWN_FACES_DIR, get_face_folder_name(new_user)), exist_ok=True)
            return redirect(request.args.get('next') or url_for('admin.admin_manage_users'))
        return render_template('admin_user_form.html', user=None, classes=classes, subjects=subjects)
    
    return render_template('admin_user_form.html', user=None, classes=classes, subjects=subjects)

@admin_bp.route('/admin/users/update/<int:user_id>', methods=['GET', 'POST'])
@login_required(role='principal')
def admin_update_user(user_id):
    org_id = session.get('organization_id')
    user = User.query.filter_by(id=user_id, organization_id=org_id).first_or_404()
    classes = Class.query.filter_by(organization_id=org_id).order_by(Class.name).all()
    subjects = Subject.query.filter_by(organization_id=org_id).order_by(Subject.name).all()

    if request.method == 'POST':
        from utils import get_face_folder_name
        
        # Capture old path before update
        old_rel_path = get_face_folder_name(user)

        username = request.form['username']
        password = request.form.get('password')
        enrollment_number = request.form.get('enrollment_number')
        email = request.form['email']
        role = request.form['role']
        
        # Backend security: Ensure principal only updates to students or teachers
        if role not in ['student', 'teacher']:
            flash("Invalid role assignment.", "danger")
            return render_template('admin_user_form.html', user=user, classes=classes, subjects=subjects)

        class_names_str = request.form.get('class_name')
        subject_name = request.form.get('subject')
        
        if password and len(password) < 8:
            flash("Password must be at least 8 characters long.", "danger")
            return render_template('admin_user_form.html', user=user, classes=classes, subjects=subjects)
            
        existing_email = User.query.filter(User.id != user.id, User.email == email).first()
        if existing_email:
            flash(f"Email '{email}' is already taken by another user.", "danger")
            return render_template('admin_user_form.html', user=user, classes=classes, subjects=subjects)
        
        if role == 'student':
            if not enrollment_number or not enrollment_number.strip():
                flash("Enrollment Number is required for students.", "danger")
                return render_template('admin_user_form.html', user=user, classes=classes, subjects=subjects)
            if not enrollment_number.isdigit():
                flash("Enrollment Number must contain only numbers.", "danger")
                return render_template('admin_user_form.html', user=user, classes=classes, subjects=subjects)
            
            existing_enrollment = User.query.filter(User.id != user.id, User.enrollment_number == enrollment_number, User.organization_id == org_id).first()
            if existing_enrollment:
                flash(f"Enrollment Number '{enrollment_number}' is already taken by another student in your school.", "danger")
                return render_template('admin_user_form.html', user=user, classes=classes, subjects=subjects)
            
            if class_names_str and ',' in class_names_str:
                flash("Students can only be assigned to a single class.", "danger")
                return render_template('admin_user_form.html', user=user, classes=classes, subjects=subjects)

        # Proceed with actual database property assignment globally
        user.username = username
        user.email = email
        user.role = role
        
        if password:
            user.password = generate_password_hash(password)
            
        org_id = session.get('organization_id')
        if user.role == 'student':
            user.enrollment_number = enrollment_number
            if class_names_str:
                class_name = class_names_str.strip()
                class_obj = Class.query.filter_by(name=class_name, organization_id=org_id).first()
                if not class_obj:
                    flash(f"Class '{class_name}' not found.", "danger")
                    return render_template('admin_user_form.html', user=user, classes=classes, subjects=subjects)
                user.class_ref = class_obj
            else:
                user.class_ref = None

        if user.role == 'teacher':
            ClassTeacher.query.filter_by(teacher_id=user.id).delete()
            if class_names_str and subject_name:
                subject_obj = Subject.query.filter_by(name=subject_name.strip(), organization_id=org_id).first()
                if not subject_obj:
                    flash(f"Subject '{subject_name}' not found. Please create it first.", "danger")
                    return render_template('admin_user_form.html', user=user, classes=classes, subjects=subjects)
                
                unique_class_names = {name.strip() for name in class_names_str.split(',') if name.strip()}
                for class_name in unique_class_names:
                    class_obj = Class.query.filter_by(name=class_name, organization_id=org_id).first()
                    if not class_obj:
                        flash(f"Class '{class_name}' does not exist.", "danger")
                        return render_template('admin_user_form.html', user=user, classes=classes, subjects=subjects)
                    db.session.add(ClassTeacher(teacher=user, class_ref=class_obj, subject=subject_obj))

        db.session.commit()
        
        # Handle face data move if path changed using the helper
        _move_user_face_data(user, old_rel_path)

        flash(f"User '{user.username}' updated successfully.", "success")
        return redirect(request.args.get('next') or url_for('admin.admin_manage_users'))

    return render_template('admin_user_form.html', user=user, classes=classes, subjects=subjects)

@admin_bp.route('/admin/users/deactivate/<int:user_id>', methods=['POST'])
@login_required(role='principal')
def admin_deactivate_user(user_id):
    if user_id == session.get('user_id'):
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for('admin.admin_manage_users'))
    
    user = User.query.filter_by(id=user_id, organization_id=session.get("organization_id")).first_or_404()
    user.is_active = False
    
    # We DON'T delete ClassTeacher assignments here, just deactivate the user.
    # This keeps history intact. 
    
    db.session.commit()
    flash(f"User account for '{user.username}' has been deactivated. They can no longer log in, but their history is preserved.", "success")
    return redirect(request.referrer or url_for('admin.admin_manage_users'))

@admin_bp.route('/admin/users/delete_permanent/<int:user_id>', methods=['POST'])
@login_required(role='principal')
def admin_delete_user_permanent(user_id):
    """
    Unified permanent deletion for students and teachers.
    - Students: Deletes biometric data and attendance history.
    - Teachers: Unlinks class assignments but preserves attendance history (marked_by set to NULL).
    """
    org_id = session.get("organization_id")
    if user_id == session.get('user_id'):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for('admin.admin_manage_users'))
        
    user = User.query.filter_by(id=user_id, organization_id=org_id).first_or_404()
    name = user.username
    role = user.role

    # Safety: Confirmation name check
    confirm = request.form.get('confirm_name', '').strip()
    if confirm != name:
        flash(f"Confirmation name did not match. '{name}' was NOT deleted.", "danger")
        return redirect(request.referrer or url_for('admin.admin_manage_users'))

    if role == 'student':
        # 1. Clear Attendance History (Cascade)
        Attendance.query.filter_by(student_id=user.id).delete()
        
        # 2. Clear Biometric Data
        from utils import get_face_folder_name
        face_dir = os.path.join(KNOWN_FACES_DIR, get_face_folder_name(user))
        if os.path.isdir(face_dir):
            shutil.rmtree(face_dir, ignore_errors=True)
        
        # Legacy flat dir check
        legacy_dir = os.path.join(KNOWN_FACES_DIR, user.username)
        if os.path.isdir(legacy_dir) and user.username not in ["org_", "class_"]:
            shutil.rmtree(legacy_dir, ignore_errors=True)
            
        # 3. Final removal
        user.class_id = None
        db.session.delete(user)
        db.session.commit()
        
        # 4. Refresh FRS cache
        from extensions import frs
        frs.rebuild_encodings()
        
        flash(f"Student '{name}' and all associated records have been permanently deleted.", "success")

    elif role == 'teacher':
        # 1. Preserve History (Nullify marked_by_id)
        Attendance.query.filter_by(marked_by_id=user.id).update({'marked_by_id': None})
        
        # 2. Remove Class-Teacher associations
        ClassTeacher.query.filter_by(teacher_id=user.id).delete()
        
        # 3. Final removal
        db.session.delete(user)
        db.session.commit()
        
        flash(f"Teacher '{name}' has been removed. Their contributions to attendance history have been preserved.", "success")
    
    else:
        flash("Action not permitted for this user type.", "danger")
    
    return redirect(request.referrer or url_for('admin.admin_manage_users'))

@admin_bp.route('/admin/users/reactivate/<int:user_id>', methods=['POST'])
@login_required(role='principal')
def admin_reactivate_user(user_id):
    user = User.query.filter_by(id=user_id, organization_id=session.get("organization_id")).first_or_404()
    user.is_active = True
    db.session.commit()
    flash(f"User account for '{user.username}' has been reactivated.", "success")
    return redirect(request.referrer or url_for('admin.admin_manage_users'))

@admin_bp.route('/admin/manage-classes')
@login_required(role='principal')
def admin_manage_classes():
    # Redirect to unified class management route
    return redirect(url_for('admin.admin_classes'))

@admin_bp.route('/admin/class/<int:class_id>/deactivate', methods=['POST'])
@login_required(role='principal')
def admin_deactivate_class(class_id):
    cls = Class.query.filter_by(id=class_id, organization_id=session.get("organization_id")).first_or_404()
    cls.is_active = False
    db.session.commit()
    flash(f"Class '{cls.name}' has been deactivated.", "success")
    return redirect(url_for('admin.admin_manage_classes'))

@admin_bp.route('/admin/class/<int:class_id>/reactivate', methods=['POST'])
@login_required(role='principal')
def admin_reactivate_class(class_id):
    cls = Class.query.filter_by(id=class_id, organization_id=session.get("organization_id")).first_or_404()
    cls.is_active = True
    db.session.commit()
    flash(f"Class '{cls.name}' has been reactivated.", "success")
    return redirect(url_for('admin.admin_manage_classes'))

@admin_bp.route('/admin/class/<int:class_id>/delete', methods=['POST'])
@login_required(role='principal')
def admin_class_delete(class_id):
    """
    Hard delete a class ONLY if it has no attendance records.
    WHY: Handles 'mistake' creation while protecting historical data integrity.
    """
    cls = Class.query.filter_by(id=class_id, organization_id=session.get("organization_id")).first_or_404()
    
    # Check for attendance history
    attendance_count = Attendance.query.filter_by(class_id=class_id).count()
    if attendance_count > 0:
        flash(
            f"Cannot delete '{cls.name}' because it has {attendance_count} attendance records. "
            "Please use 'Deactivate' instead to hide this class while preserving history.",
            "danger"
        )
        return redirect(url_for('admin.admin_classes'))

    class_name = cls.name
    student_count = User.query.filter_by(class_id=class_id, role='student').count()

    # Unlink students and teachers with folder movement
    students = User.query.filter_by(class_id=class_id, role='student').all()
    from utils import get_face_folder_name
    for s in students:
        old_rel_path = get_face_folder_name(s)
        s.class_id = None
        # Move folder to class_unassigned
        _move_user_face_data(s, old_rel_path)
    
    db.session.commit()
    ClassTeacher.query.filter_by(class_id=class_id).delete()

    db.session.delete(cls)
    db.session.commit()

    if student_count > 0:
        flash(f"Class '{class_name}' (mistakenly created) has been deleted. {student_count} student(s) unlinked.", "warning")
    else:
        flash(f"Class '{class_name}' deleted successfully.", "success")
    return redirect(url_for('admin.admin_classes'))

@admin_bp.route('/admin/class/<int:class_id>/edit', methods=['GET', 'POST'])
@login_required(role='principal')
def admin_edit_class(class_id):
    org_id = session.get('organization_id')
    cls = Class.query.filter_by(id=class_id, organization_id=org_id).first_or_404()
    
    if request.method == 'POST':
        new_name = request.form.get('class_name', '').strip()
        if not new_name:
            flash("Class name cannot be empty.", "danger")
            return redirect(url_for('admin.admin_edit_class', class_id=class_id))
        
        # Check for duplicate
        existing = Class.query.filter(Class.name == new_name, Class.organization_id == org_id, Class.id != class_id).first()
        if existing:
            flash(f"A class named '{new_name}' already exists.", "danger")
            return redirect(url_for('admin.admin_edit_class', class_id=class_id))
        
        # Capture old organization folder based on current class name
        from utils import slugify
        from config import KNOWN_FACES_DIR
        import os
        
        # Prepare for folder move (all students in this class)
        # Structure: org_Name / class_ID_Name / enrollment_username
        org_dir = f"org_{slugify(cls.organization.name)}"
        old_class_dir = f"class_{slugify(cls.name)}"
        old_path = os.path.join(KNOWN_FACES_DIR, org_dir, old_class_dir)
        
        cls.name = new_name
        db.session.commit()
        
        new_class_dir = f"class_{slugify(cls.name)}"
        new_path = os.path.join(KNOWN_FACES_DIR, org_dir, new_class_dir)
        
        if old_class_dir != new_class_dir and os.path.exists(old_path):
            try:
                os.rename(old_path, new_path)
                from extensions import frs
                frs.rebuild_encodings()
            except Exception as e:

        flash(f"Class renamed to '{new_name}' successfully.", "success")
        return redirect(url_for('admin.admin_classes'))

    students = User.query.filter_by(class_id=cls.id, role='student').order_by(User.username).all()
    
    # Get teachers and their subjects for this class
    teacher_assignments = ClassTeacher.query.filter_by(class_id=cls.id).options(
        joinedload(ClassTeacher.teacher),
        joinedload(ClassTeacher.subject)
    ).all()
    
    # For adding new ones
    all_students_no_class = User.query.filter_by(organization_id=org_id, role='student', class_id=None).order_by(User.username).all()
    all_teachers = User.query.filter_by(organization_id=org_id, role='teacher').order_by(User.username).all()
    all_subjects = Subject.query.filter_by(organization_id=org_id).order_by(Subject.name).all()
    
    return render_template('admin_edit_class.html', 
                           cls=cls, 
                           students=students, 
                           teacher_assignments=teacher_assignments,
                           available_students=all_students_no_class,
                           available_teachers=all_teachers,
                           available_subjects=all_subjects)

@admin_bp.route('/admin/class/<int:class_id>/add_student', methods=['POST'])
@login_required(role='principal')
def admin_class_add_student(class_id):
    org_id = session.get('organization_id')
    cls = Class.query.filter_by(id=class_id, organization_id=org_id).first_or_404()
    student_id = request.form.get('student_id')
    
    student = User.query.filter_by(id=student_id, organization_id=org_id, role='student').first_or_404()
    from utils import get_face_folder_name
    old_rel_path = get_face_folder_name(student)
    
    student.class_id = cls.id
    db.session.commit()
    
    _move_user_face_data(student, old_rel_path)
    
    flash(f"Student '{student.username}' added to {cls.name}.", "success")
    return redirect(url_for('admin.admin_edit_class', class_id=cls.id))

@admin_bp.route('/admin/class/<int:class_id>/remove_student/<int:student_id>', methods=['POST'])
@login_required(role='principal')
def admin_class_remove_student(class_id, student_id):
    org_id = session.get('organization_id')
    student = User.query.filter_by(id=student_id, class_id=class_id, organization_id=org_id).first_or_404()
    from utils import get_face_folder_name
    old_rel_path = get_face_folder_name(student)
    
    student.class_id = None
    db.session.commit()
    
    _move_user_face_data(student, old_rel_path)
    
    flash(f"Student '{student.username}' removed from class.", "info")
    return redirect(url_for('admin.admin_edit_class', class_id=class_id))

@admin_bp.route('/admin/class/<int:class_id>/assign_teacher', methods=['POST'])
@login_required(role='principal')
def admin_class_assign_teacher(class_id):
    org_id = session.get('organization_id')
    cls = Class.query.filter_by(id=class_id, organization_id=org_id).first_or_404()
    teacher_id = request.form.get('teacher_id')
    subject_id = request.form.get('subject_id')
    
    teacher = User.query.filter_by(id=teacher_id, organization_id=org_id, role='teacher').first_or_404()
    subject = Subject.query.filter_by(id=subject_id, organization_id=org_id).first_or_404()
    
    # Check for existing assignment
    existing = ClassTeacher.query.filter_by(class_id=cls.id, teacher_id=teacher.id, subject_id=subject.id).first()
    if existing:
        flash(f"Teacher '{teacher.username}' is already assigned to {cls.name} for {subject.name}.", "warning")
    else:
        new_assoc = ClassTeacher(class_id=cls.id, teacher_id=teacher.id, subject_id=subject.id)
        db.session.add(new_assoc)
        db.session.commit()
        flash(f"Teacher '{teacher.username}' assigned to {cls.name} for {subject.name}.", "success")
        
    return redirect(url_for('admin.admin_edit_class', class_id=cls.id))

@admin_bp.route('/admin/class/<int:class_id>/unassign_teacher/<int:assignment_id>', methods=['POST'])
@login_required(role='principal')
def admin_class_unassign_teacher(class_id, assignment_id):
    org_id = session.get('organization_id')
    # Ensure the assignment belongs to the class and the class belongs to the org
    cls = Class.query.filter_by(id=class_id, organization_id=org_id).first_or_404()
    assoc = ClassTeacher.query.filter_by(id=assignment_id, class_id=cls.id).first_or_404()
    
    db.session.delete(assoc)
    db.session.commit()
    flash("Teacher assignment removed from class.", "info")
    return redirect(url_for('admin.admin_edit_class', class_id=class_id))


@admin_bp.route('/admin/class/<int:class_id>/students')
@login_required(role='principal')
def admin_view_class_students(class_id):
    target_class = Class.query.filter_by(id=class_id, organization_id=session.get("organization_id")).first_or_404()
    students_in_class = User.query.filter_by(
        class_id=class_id, 
        role='student',
        is_active=True
    ).order_by(User.username).all()
    
    from extensions import frs
    from utils import get_face_folder_name
    registered_status = {s.id: frs.is_registered(get_face_folder_name(s)) for s in students_in_class}
    
    return render_template('admin_class_students.html', target_class=target_class, students=students_in_class, registered=registered_status)

@admin_bp.route('/admin/reports')
@login_required(role='principal')
def admin_reports():
    students = User.query.filter_by(organization_id=session.get('organization_id'), role='student').options(joinedload(User.class_ref)).all()
    return render_template('admin_reports.html', students=students)

@admin_bp.route('/admin/export_attendance/<int:student_id>')
@login_required(role='principal')
def admin_export_attendance(student_id):
    student = User.query.filter_by(id=student_id, organization_id=session.get("organization_id")).first_or_404()
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
# FIX 1: Admin-Initiated Face Registration (Single Photo Upload)
# ----------------------------
@admin_bp.route('/admin/students/upload_face/<int:user_id>', methods=['POST'])
@login_required(role='principal')
def admin_upload_face_photo(user_id):
    student = User.query.filter_by(id=user_id, organization_id=session.get("organization_id")).first_or_404()
    if student.role != 'student':
        flash("Face registration is only for students.", "danger")
        return redirect(url_for('admin.admin_manage_users'))

    if 'file' not in request.files:
        flash("No file provided.", "danger")
        return redirect(request.referrer or url_for('admin.admin_manage_students'))
        
    file = request.files['file']
    if file.filename == '':
        flash("No file picked.", "warning")
        return redirect(request.referrer or url_for('admin.admin_manage_students'))

    from utils import get_face_folder_name
    save_dir = os.path.join(KNOWN_FACES_DIR, get_face_folder_name(student))
    os.makedirs(save_dir, exist_ok=True)
    
    from extensions import frs
    # Use path-based ID for registration
    person_id = get_face_folder_name(student)
    
    if frs.is_registered(person_id):
        flash(f"'{student.username}' already has a face registered. Reset their face data first.", "warning")
        return redirect(request.referrer or url_for('admin.admin_manage_students'))

    import secrets
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.jpg', '.jpeg', '.png']:
        ext = '.jpg'
    
    # Use enrollment_username format as requested
    safe_enrollment = student.enrollment_number or "noenroll"
    filename = f"{safe_enrollment}_{student.username}{ext}"
    filepath = os.path.join(save_dir, filename)
    
    file.save(filepath)

    # Path-based ID used for recognition lookup
    person_id = get_face_folder_name(student)
    success = frs.register_face(person_id, filepath)
    
    if success:
        flash(f"Face successfully registered for '{student.username}'!", "success")
    else:
        # If no face found in image, delete it and warn
        os.remove(filepath)
        flash(f"Could not detect a clear face. Ensure the photo is well-lit, the face is upright/visible, and try again.", "danger")

    return redirect(request.referrer or url_for('admin.admin_manage_students'))

# ----------------------------
# FIX 8: Admin-Only Face Data Reset
# ----------------------------
@admin_bp.route('/admin/students/reset_face/<int:user_id>', methods=['POST'])
@login_required(role='principal')
def admin_reset_face_data(user_id):
    student = User.query.filter_by(id=user_id, organization_id=session.get("organization_id")).first_or_404()
    if student.role != 'student':
        flash("This action is only for students.", "danger")
        return redirect(url_for('admin.admin_manage_users'))

    from utils import get_face_folder_name
    student_face_dir = os.path.join(KNOWN_FACES_DIR, get_face_folder_name(student))
    if os.path.exists(student_face_dir):
        shutil.rmtree(student_face_dir)
        os.makedirs(student_face_dir, exist_ok=True)
    
    # Also check and clear legacy flat-structure folder (static/faces/<username>)
    legacy_dir = os.path.join(KNOWN_FACES_DIR, student.username)
    if os.path.exists(legacy_dir) and student.username not in ["org_", "class_"]:
        shutil.rmtree(legacy_dir)

    # Clear token too
    student.registration_token = None
    student.registration_token_expires = None
    db.session.commit()

    from extensions import frs
    frs.rebuild_encodings()
    flash(f"Face data for '{student.username}' has been reset.", "success")
    return redirect(request.referrer or url_for('admin.admin_manage_students'))

@admin_bp.route('/admin/users/email_credentials/<int:user_id>')
@login_required(role='principal')
def admin_email_credentials(user_id):
    """
    Returns a redirect to a mailto: link so the principal's email client
    opens pre-filled with login info for the teacher or student.
    Principals compose and send the email themselves — no server SMTP needed.
    """
    user = User.query.filter_by(id=user_id, organization_id=session.get("organization_id")).first_or_404()
    if not user.email:
        flash(f"{user.username} has no email address on file.", "danger")
        return redirect(url_for('admin.admin_manage_users'))

    from urllib.parse import quote
    import os
    system_name = os.getenv('SYSTEM_NAME', 'Smart Attendance System')
    if user.role == 'student':
        subject = f"{system_name} — Your Login Credentials"
        body = (
            f"Hello {user.username},\n\n"
            f"Your login credentials for {system_name} are:\n\n"
            f"  Login ID (Enrollment No.): {user.enrollment_number}\n"
            f"  Email: {user.email}\n\n"
            "Please log in and change your password after first login.\n\n"
            "Best regards,\nYour Principal"
        )
    else:
        subject = f"{system_name} — Your Teacher Account Info"
        body = (
            f"Hello {user.username},\n\n"
            f"Your login credentials for {system_name} are:\n\n"
            f"  Email (Login): {user.email}\n\n"
            "Please log in at your earliest convenience.\n\n"
            "Best regards,\nYour Principal"
        )

    mailto = f"mailto:{user.email}?subject={quote(subject)}&body={quote(body)}"
    return redirect(mailto)

# ─────────────────────────────────────────────────────────────────────────────
#  CLASS MANAGEMENT (Principal)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/admin/classes', methods=['GET', 'POST'])
@login_required(role='principal')
def admin_classes():
    org_id = session.get('organization_id')

    if request.method == 'POST':
        class_name = request.form.get('class_name', '').strip()
        if not class_name:
            flash("Class name cannot be empty.", "danger")
            return redirect(url_for('admin.admin_classes'))

        if Class.query.filter_by(name=class_name, organization_id=org_id).first():
            flash(f"A class named '{class_name}' already exists in your school.", "danger")
            return redirect(url_for('admin.admin_classes'))

        new_class = Class(name=class_name, organization_id=org_id, is_active=True)
        db.session.add(new_class)
        db.session.commit()
        flash(f"Class '{class_name}' created successfully.", "success")
        return redirect(url_for('admin.admin_classes'))

    classes = Class.query.filter_by(organization_id=org_id).order_by(Class.name).all()
    # Attach student counts for display
    class_data = []
    for cls in classes:
        student_count = User.query.filter_by(class_id=cls.id, role='student', organization_id=org_id).count()
        teacher_count = ClassTeacher.query.filter_by(class_id=cls.id).count()
        class_data.append({'cls': cls, 'student_count': student_count, 'teacher_count': teacher_count})

    return render_template('admin_classes.html', class_data=class_data)


@admin_bp.route('/admin/classes/deactivate/<int:class_id>', methods=['POST'])
@login_required(role='principal')
def admin_class_deactivate(class_id):
    """
    Soft-delete (deactivate) a class.
    WHY: When a class finishes its semester or is no longer needed, deactivating it
    hides it from teacher dashboards and attendance sessions — without deleting any
    attendance records. All historical data (which students attended which class)
    is fully preserved for reports and audit trails.
    Students remain in the system and their past attendance is intact.
    """
    cls = Class.query.filter_by(id=class_id, organization_id=session.get('organization_id')).first_or_404()
    confirm = request.form.get('confirm_name', '').strip()
    if confirm != cls.name:
        flash("Confirmation name did not match. Class was NOT deactivated.", "danger")
        return redirect(url_for('admin.admin_classes'))

    cls.is_active = False
    db.session.commit()
    flash(
        f"Class '{cls.name}' has been deactivated. It will no longer appear in teacher dashboards. "
        "All attendance records and student data are preserved.",
        "success"
    )
    return redirect(url_for('admin.admin_classes'))


@admin_bp.route('/admin/classes/reactivate/<int:class_id>', methods=['POST'])
@login_required(role='principal')
def admin_class_reactivate(class_id):
    """Reactivate a previously deactivated class."""
    cls = Class.query.filter_by(id=class_id, organization_id=session.get('organization_id')).first_or_404()
    cls.is_active = True
    db.session.commit()
    flash(f"Class '{cls.name}' has been reactivated and is now visible to teachers again.", "success")
    return redirect(url_for('admin.admin_classes'))


# ─────────────────────────────────────────────────────────────────────────────
#  TEACHER MANAGEMENT (Principal)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/admin/teachers')
@login_required(role='principal')
def admin_teachers():
    org_id = session.get('organization_id')
    teachers = User.query.filter_by(
        organization_id=org_id, role='teacher'
    ).options(
        joinedload(User.class_assignments).joinedload(ClassTeacher.class_ref),
        joinedload(User.class_assignments).joinedload(ClassTeacher.subject)
    ).order_by(User.username).all()
    return render_template('admin_teachers.html', teachers=teachers)


# Note: Redirecting legacy teacher removal requests if any exist
@admin_bp.route('/admin/teachers/remove/<int:teacher_id>', methods=['POST'])
@login_required(role='principal')
def admin_remove_teacher_legacy(teacher_id):
    return redirect(url_for('admin.admin_delete_user_permanent', user_id=teacher_id), code=307)

