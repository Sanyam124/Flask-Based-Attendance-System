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

    profile_image_url = None
    student_face_dir = os.path.join(current_app.static_folder, 'faces', student_obj.username)
    if os.path.exists(student_face_dir):
        face_samples = sorted([f for f in os.listdir(student_face_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
        if face_samples:
            profile_image_url = f"faces/{student_obj.username}/{face_samples[0]}"
    
    has_samples = profile_image_url is not None

    attendance_records = Attendance.query.filter_by(student_id=student_id) \
        .options(
            joinedload(Attendance.marked_by_teacher),
            joinedload(Attendance.subject),
            joinedload(Attendance.class_ref)
        ) \
        .order_by(Attendance.date.desc(), Attendance.session.desc()).all()

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

@student_bp.route('/student/capture_samples')
@login_required(role='student')
def capture_samples():
    username = session.get('username')
    save_path = os.path.join(KNOWN_FACES_DIR, username)
    # FIX 8: Block re-registration — student can't redo face capture once done
    if os.path.exists(save_path) and len(os.listdir(save_path)) >= 50:
        flash("Your face is already registered. Contact an admin if you need to re-register.", "info")
        return redirect(url_for('student.student_dashboard'))
    # FIX 1: Only allow capture if admin issued a registration token
    student = User.query.filter_by(username=username).first()
    from datetime import datetime
    if not student.registration_token:
        flash("Face registration must be initiated by your admin. Please contact them.", "warning")
        return redirect(url_for('student.student_dashboard'))
    if student.registration_token_expires and student.registration_token_expires < datetime.now():
        student.registration_token = None
        student.registration_token_expires = None
        db.session.commit()
        flash("Your registration link has expired. Please ask your admin for a new one.", "danger")
        return redirect(url_for('student.student_dashboard'))
    return render_template('capture_samples.html', username=username)

@student_bp.route('/student/video_feed')
@login_required(role='student')
def student_video_feed():
    from attendance_logic import FaceCapture
    username = session.get('username')
    # FIX 8: Double-check server-side — never trust client to enforce this
    save_path = os.path.join(KNOWN_FACES_DIR, username)
    if os.path.exists(save_path) and len(os.listdir(save_path)) >= 50:
        return "Registration complete", 403
    return Response(FaceCapture.stream_capture(username), mimetype='multipart/x-mixed-replace; boundary=frame')

@student_bp.route('/student/check_capture_status')
@login_required(role='student')
def student_check_capture_status():
    # FIX 4: Never use URL param for identity — always use session
    from extensions import frs
    username = session.get('username')
    save_path = os.path.join(KNOWN_FACES_DIR, username)
    completed = os.path.exists(save_path) and len(os.listdir(save_path)) >= 50
    if completed:
        # Clear the registration token after successful completion
        student = User.query.filter_by(username=username).first()
        if student:
            student.registration_token = None
            student.registration_token_expires = None
            db.session.commit()
        frs.rebuild_encodings()
        flash("Face samples captured and system updated!", "success")
    return jsonify({"completed": completed})

@student_bp.route('/profile/<int:user_id>')
@login_required()
def view_profile(user_id):
    if user_id != session.get('user_id'):
        flash("You can only view your own profile.", "danger")
        return redirect(url_for(session.get('user_role') + '.' + session.get('user_role') + '_dashboard'))

    user = User.query.get_or_404(user_id)

    profile_image_url = None
    if user.role == 'student':
        student_face_dir = os.path.join(current_app.static_folder, 'faces', user.username)
        if os.path.exists(student_face_dir):
            face_samples = sorted([f for f in os.listdir(student_face_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
            if face_samples:
                profile_image_url = f"faces/{user.username}/{face_samples[0]}"

    return render_template('profile.html', user=user, profile_image_url=profile_image_url)
