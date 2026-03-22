from flask import Blueprint, render_template, session, flash, redirect, url_for, Response, jsonify, current_app
from models import db, User, Attendance, ClassTeacher, Subject
from config import KNOWN_FACES_DIR
from sqlalchemy.orm import joinedload
from datetime import date
import os
from blueprints.auth import login_required

student_bp = Blueprint('student', __name__)

@student_bp.route('/student/dashboard')
@login_required(role='student')
def student_dashboard():
    student_id = session.get('user_id')
    student_obj = User.query.get_or_404(student_id)

    from utils import get_face_folder_name
    profile_image_url = None
    face_rel_dir = get_face_folder_name(student_obj)
    student_face_dir = os.path.join(current_app.static_folder, 'faces', face_rel_dir)
    
    if os.path.exists(student_face_dir):
        face_samples = sorted([f for f in os.listdir(student_face_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
        if face_samples:
            # Use forward slashes for URLs
            url_friendly_path = face_rel_dir.replace(os.sep, '/')
            profile_image_url = f"faces/{url_friendly_path}/{face_samples[0]}"
    
    has_samples = profile_image_url is not None

    attendance_records = Attendance.query.filter_by(student_id=student_id) \
        .options(
            joinedload(Attendance.marked_by_teacher),
            joinedload(Attendance.subject),
            joinedload(Attendance.class_ref)
        ) \
        .order_by(Attendance.timestamp.desc()).all()

    total_records = len(attendance_records)
    present_count = sum(1 for r in attendance_records if r.status == 'present')
    absent_count = total_records - present_count
    attendance_percentage = (present_count / total_records) * 100 if total_records > 0 else 0
    
    # Check for active token
    import datetime
    has_active_token = student_obj.registration_token is not None and \
                       (student_obj.registration_token_expires is None or student_obj.registration_token_expires > datetime.datetime.now())

    # Subject-wise breakdown
    subject_stats = {}
    for record in attendance_records:
        s_name = record.subject.name if record.subject else "Uncategorized"
        if s_name not in subject_stats:
            subject_stats[s_name] = {"present": 0, "total": 0}
        subject_stats[s_name]["total"] += 1
        if record.status == 'present':
            subject_stats[s_name]["present"] += 1
    
    for s_name in subject_stats:
        stats = subject_stats[s_name]
        stats["percentage"] = round((stats["present"] / stats["total"]) * 100, 1)

    return render_template('student_dashboard.html', 
                           student=student_obj,
                           attendance_records=attendance_records,
                           total_records=total_records, 
                           present_count=present_count,
                           absent_count=absent_count, 
                           attendance_percentage=attendance_percentage,
                           subject_stats=subject_stats,
                           has_samples=has_samples,
                           has_active_token=has_active_token,
                           profile_image_url=profile_image_url)

# Removed legacy 50-sample face capture routes.
# Face registration is now handled by Admins via single high-quality photo upload.

@student_bp.route('/profile/<int:user_id>')
@login_required()
def view_profile(user_id):
    if user_id != session.get('user_id'):
        flash("You can only view your own profile.", "danger")
        dashboard_map = {
            'student': 'student.student_dashboard',
            'teacher': 'teacher.teacher_dashboard',
            'admin':   'admin.admin_dashboard'
        }
        return redirect(url_for(dashboard_map.get(session.get('user_role'), 'auth.login')))

    user = User.query.get_or_404(user_id)

    profile_image_url = None
    if user.role == 'student':
        from utils import get_face_folder_name
        face_rel_dir = get_face_folder_name(user)
        student_face_dir = os.path.join(current_app.static_folder, 'faces', face_rel_dir)
        if os.path.exists(student_face_dir):
            face_samples = sorted([f for f in os.listdir(student_face_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
            if face_samples:
                url_friendly_path = face_rel_dir.replace(os.sep, '/')
                profile_image_url = f"faces/{url_friendly_path}/{face_samples[0]}"

    return render_template('profile.html', user=user, profile_image_url=profile_image_url)
