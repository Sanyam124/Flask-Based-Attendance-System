from flask import Blueprint, render_template, request, redirect, url_for, session, Response, jsonify, flash, current_app
import csv
from io import StringIO
from models import db, User, Class, ClassTeacher, Attendance, Subject
from config import KNOWN_FACES_DIR
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from datetime import datetime, date
import base64
import cv2
import numpy as np
from PIL import Image
from io import BytesIO
from blueprints.auth import login_required
from utils import get_next_session_number

teacher_bp = Blueprint('teacher', __name__)

@teacher_bp.route("/teacher/get_tunnel_url")
def get_tunnel_url():
    pub = current_app.jinja_env.globals.get('get_public_url', lambda: None)()
    return jsonify({"url": pub})

@teacher_bp.route("/teacher/dashboard")
@login_required(role='teacher')
def teacher_dashboard():
    teacher_id = session.get("user_id")
    teacher = User.query.get_or_404(teacher_id)
    classes_taught = ClassTeacher.query.join(Class).filter(
        ClassTeacher.teacher_id == teacher_id,
        Class.is_active == True
    ).options(
        joinedload(ClassTeacher.class_ref), 
        joinedload(ClassTeacher.subject)
    ).all()
    return render_template("teacher_dashboard.html", classes_taught=classes_taught, teacher=teacher)

@teacher_bp.route('/teacher/update_attendance', methods=['GET', 'POST'])
@login_required(role='teacher')
def update_attendance():
    teacher_id = session.get('user_id')
    classes_taught = ClassTeacher.query.filter_by(teacher_id=teacher_id).options(
        joinedload(ClassTeacher.class_ref),
        joinedload(ClassTeacher.subject)
    ).all()
    
    students_for_update = []
    student_statuses = {}
    
    selected_ct_id = request.values.get('class_teacher_id', type=int)
    selected_date = request.values.get('date')
    selected_session = request.values.get('session', type=int)

    if all([selected_ct_id, selected_date, selected_session]):
        assoc = ClassTeacher.query.get(selected_ct_id)
        if assoc and assoc.teacher_id == teacher_id:
            students_for_update = User.query.filter_by(role="student", class_id=assoc.class_id).order_by(User.username).all()
            records = Attendance.query.filter_by(
                date=selected_date,
                session=selected_session,
                class_id=assoc.class_id,
                subject_id=assoc.subject_id
            ).all()
            student_statuses = {record.student_id: record.status for record in records}
        else:
            flash("Invalid class selection.", "danger")
    elif request.method == 'POST':
        flash("Please select a class, date, and session to fetch records.", "danger")

    return render_template(
        'update_attendance.html',
        classes_taught=classes_taught,
        students_for_update=students_for_update,
        student_statuses=student_statuses,
        selected_ct_id=selected_ct_id,
        selected_date=selected_date,
        selected_session=selected_session
    )

@teacher_bp.route('/teacher/handle_update', methods=['POST'])
@login_required(role='teacher')
def handle_update_attendance():
    teacher_id = session.get('user_id')
    ct_id = request.form.get('class_teacher_id', type=int)
    update_date_str = request.form.get('date')
    session_number = request.form.get('session', type=int)
    
    assoc = ClassTeacher.query.get(ct_id)
    if not assoc or assoc.teacher_id != teacher_id:
        flash("Unauthorized action.", "danger")
        return redirect(url_for('teacher.teacher_dashboard'))

    update_date = datetime.strptime(update_date_str, '%Y-%m-%d').date()
    all_students_in_class = User.query.filter_by(role='student', class_id=assoc.class_id).all()
    present_student_ids = request.form.getlist("present_students")

    for student in all_students_in_class:
        existing_record = Attendance.query.filter_by(
            student_id=student.id,
            date=update_date,
            subject_id=assoc.subject_id,
            session=session_number
        ).first()

        new_status = 'present' if str(student.id) in present_student_ids else 'absent'

        if existing_record:
            existing_record.status = new_status
            existing_record.marked_by_id = teacher_id
            existing_record.timestamp = datetime.now()
        else:
            new_record = Attendance(
                student_id=student.id,
                date=update_date,
                subject_id=assoc.subject_id,
                session=session_number,
                status=new_status,
                class_id=assoc.class_id,
                marked_by_id=teacher_id
            )
            db.session.add(new_record)
    
    db.session.commit()
    flash(f"Attendance for {update_date_str}, Session {session_number} has been updated.", "success")
    return redirect(url_for('teacher.update_attendance', 
                            class_teacher_id=ct_id, 
                            date=update_date_str, 
                            session=session_number))

@teacher_bp.route("/teacher/manual_attendance", methods=["GET", "POST"])
@login_required(role='teacher')
def manual_attendance():
    teacher_id = session.get("user_id")
    classes_taught = ClassTeacher.query.join(Class).filter(
        ClassTeacher.teacher_id == teacher_id,
        Class.is_active == True
    ).all()
    
    selected_ct_id = request.values.get('class_teacher_id', type=int)
    
    students, assoc, attendance_today = [], None, {}
    if selected_ct_id:
        assoc = ClassTeacher.query.get(selected_ct_id)
        if assoc and assoc.teacher_id == teacher_id:
            students = User.query.filter_by(role="student", class_id=assoc.class_id).order_by(User.username).all()
            today = date.today()
            latest_session = db.session.query(func.max(Attendance.session)).filter_by(
                class_id=assoc.class_id, subject_id=assoc.subject_id, date=today
            ).scalar()

            if latest_session:
                todays_records = Attendance.query.filter_by(
                    class_id=assoc.class_id, subject_id=assoc.subject_id, 
                    date=today, session=latest_session
                ).all()
                attendance_today = {record.student_id: record.status for record in todays_records}
        else:
            flash("Invalid class selection.", "danger")
            selected_ct_id = None

    if request.method == "POST":
        ct_id = request.form.get("class_teacher_id", type=int)
        assoc = ClassTeacher.query.get(ct_id)

        if not assoc or assoc.teacher_id != teacher_id:
            flash("Unauthorized action.", "danger")
            return redirect(url_for('teacher.teacher_dashboard'))
        
        if not assoc.class_ref.is_active:
            flash(f"Cannot save attendance for inactive class '{assoc.class_ref.name}'.", "danger")
            return redirect(url_for('teacher.manual_attendance'))

        today = date.today()
        session_number = get_next_session_number(assoc.class_id, assoc.subject_id, today)
        all_students_in_class = User.query.filter_by(role='student', class_id=assoc.class_id).all()
        present_student_ids = request.form.getlist("present_students")

        for student in all_students_in_class:
            new_status = 'present' if str(student.id) in present_student_ids else 'absent'
            db.session.merge(Attendance(
                student_id=student.id, date=today, subject_id=assoc.subject_id, session=session_number,
                class_id=assoc.class_id, marked_by_id=teacher_id, status=new_status
            ))
        
        db.session.commit()
        flash(f"Manual attendance for Session {session_number} recorded successfully.", "success")
        return redirect(url_for('teacher.manual_attendance', class_teacher_id=ct_id))

    return render_template(
        "manual_attendance.html", 
        classes_taught=classes_taught, 
        students=students, 
        selected_ct_id=selected_ct_id,
        attendance_today=attendance_today
    )

@teacher_bp.route("/teacher/attendance_reports")
@login_required(role='teacher')
def teacher_attendance_reports():
    teacher_id = session.get("user_id")
    classes_taught = ClassTeacher.query.filter_by(teacher_id=teacher_id).options(
        joinedload(ClassTeacher.class_ref), 
        joinedload(ClassTeacher.subject)
    ).all()
    
    reports = {}
    for assoc in classes_taught:
        students = User.query.filter_by(
            role="student", 
            class_id=assoc.class_id,
            is_active=True
        ).all()

        student_reports = []
        for student in students:
            records = Attendance.query.filter_by(
                student_id=student.id, 
                class_id=assoc.class_id, 
                subject_id=assoc.subject_id
            ).all()
            
            total_count = len(records)
            present_count = sum(1 for r in records if r.status == 'present')
            percentage = (present_count / total_count) * 100 if total_count > 0 else 0
            
            student_reports.append({
                "student": student, 
                "present_count": present_count,
                "total_count": total_count, 
                "percentage": round(float(percentage), 2)
            })
            
        reports[assoc] = student_reports
        
    return render_template("teacher_attendance_reports.html", reports=reports)

@teacher_bp.route('/teacher/attendance/<int:class_teacher_id>')
@login_required(role='teacher')
def teacher_attendance(class_teacher_id):
    assoc = ClassTeacher.query.get_or_404(class_teacher_id)
    if assoc.teacher_id != session.get('user_id'):
        return redirect(url_for('teacher.teacher_dashboard'))
    session_number = get_next_session_number(assoc.class_id, assoc.subject_id, date.today())
    students_in_class = User.query.filter_by(class_id=assoc.class_id, role='student', is_active=True).all()
    return render_template('teacher_attendance.html', students=students_in_class, association=assoc, session_number=session_number)

@teacher_bp.route('/teacher/recognize_frame', methods=['POST'])
def recognize_frame():
    from extensions import frs
    data = request.json
    image_data = base64.b64decode(data['image'].split(',')[1])
    class_teacher_id = data['assoc_id']
    session_number = data['session_number'] 
    image = Image.open(BytesIO(image_data)).convert('RGB')
    rgb_array = np.array(image)
    # Convert RGB (from browser) to BGR (for OpenCV)
    frame = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
    
    print(f"\n[PHONE DEBUG] Received frame of shape: {frame.shape}")
    
    recognized_names = frs.recognize_faces(frame)
    print(f"[PHONE DEBUG] Faces recognized by Haar: {recognized_names}")
    
    assoc = ClassTeacher.query.get(class_teacher_id)
    if not assoc:
        print("[PHONE DEBUG] ERROR: Invalid Association ID")
        return jsonify({"error": "Invalid association"}), 400
        
    valid_students_in_class = {
        user.username for user in User.query.filter_by(
            class_id=assoc.class_id, role='student', is_active=True
        ).all()
    }
    print(f"[PHONE DEBUG] Valid students in class DB: {valid_students_in_class}")

    today = date.today()
    marked_students = []

    for name in recognized_names:
        if name in valid_students_in_class:
            student = User.query.filter_by(username=name).first()
            if student:
                existing_record = Attendance.query.filter_by(
                    student_id=student.id, date=today, subject_id=assoc.subject_id, session=session_number
                ).first()

                if not existing_record:
                    new_attendance = Attendance(
                        student_id=student.id, date=today, subject_id=assoc.subject_id,
                        session=session_number, status='present', class_id=assoc.class_id, 
                        marked_by_id=assoc.teacher_id
                    )
                    db.session.add(new_attendance)
                    marked_students.append({'username': name, 'timestamp': datetime.now().strftime("%H:%M:%S")})

    if marked_students:
        db.session.commit()
    return jsonify({"present": marked_students})

@teacher_bp.route('/teacher/video_feed/<int:class_teacher_id>/<int:session_number>')
@login_required(role='teacher')
def teacher_video_feed(class_teacher_id, session_number):
    from extensions import frs
    from attendance_logic import FaceCapture
    return Response(FaceCapture.stream_attendance(current_app, frs, class_teacher_id, session_number), mimetype='multipart/x-mixed-replace; boundary=frame')

@teacher_bp.route('/teacher/attendance_status/<int:class_teacher_id>')
@login_required(role='teacher')
def attendance_status(class_teacher_id):
    assoc = ClassTeacher.query.get_or_404(class_teacher_id)
    today = date.today()
    current_session = request.args.get('session', type=int)
    if not current_session:
        return jsonify({"present": [], "session": None})

    present_records = db.session.query(User.username, Attendance.timestamp).join(
        User, User.id == Attendance.student_id
    ).filter(
        Attendance.class_id == assoc.class_id,
        Attendance.subject_id == assoc.subject_id,
        Attendance.date == today,
        Attendance.session == current_session,
        Attendance.status == 'present'
    ).all()
    
    present_data = [{"username": r.username, "timestamp": r.timestamp.strftime("%H:%M:%S")} for r in present_records]
    return jsonify({"present": present_data, "session": current_session})

@teacher_bp.route("/teacher/end_session/<int:class_teacher_id>/<int:session_number>", methods=["POST"])
@login_required(role="teacher")
def end_session(class_teacher_id, session_number):
    assoc = ClassTeacher.query.get_or_404(class_teacher_id)
    if assoc.teacher_id != session.get('user_id'):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    today = date.today()
    all_students = User.query.filter_by(class_id=assoc.class_id, role='student').all()
    for student in all_students:
        existing_record = Attendance.query.filter_by(
            student_id=student.id, date=today, subject_id=assoc.subject_id, session=session_number
        ).first()
        if not existing_record:
            absent_record = Attendance(
                student_id=student.id, date=today, subject_id=assoc.subject_id, session=session_number,
                status='absent', class_id=assoc.class_id, marked_by_id=assoc.teacher_id
            )
            db.session.add(absent_record)
    db.session.commit()
    flash(f"Attendance session {session_number} ended. Unmarked students recorded as absent.", "success")
    return jsonify({"status": "ended", "redirect_url": url_for('teacher.teacher_dashboard')})

@teacher_bp.route('/teacher/phone_camera/<int:class_teacher_id>/<int:session_number>')
def phone_camera(class_teacher_id, session_number):
    """Mobile-optimized camera page — teacher opens this URL on their phone."""
    assoc = ClassTeacher.query.get_or_404(class_teacher_id)
    return render_template('phone_camera.html', association=assoc, session_number=session_number)
@teacher_bp.route('/api/sessions_for_date')
@login_required(role='teacher')
def sessions_for_date():
    date_str = request.args.get('date')
    ct_id = request.args.get('class_teacher_id', type=int)
    if not date_str or not ct_id:
        return jsonify({"sessions": []})
    
    assoc = ClassTeacher.query.get(ct_id)
    if not assoc:
        return jsonify({"sessions": []})

    sessions = db.session.query(Attendance.session).filter_by(
        date=date_str,
        class_id=assoc.class_id,
        subject_id=assoc.subject_id
    ).distinct().order_by(Attendance.session).all()
    return jsonify({"sessions": [s[0] for s in sessions]})

@teacher_bp.route('/teacher/export_attendance/<int:class_teacher_id>')
@login_required(role='teacher')
def export_attendance(class_teacher_id):
    teacher_id = session.get('user_id')
    assoc = ClassTeacher.query.get_or_404(class_teacher_id)
    
    if assoc.teacher_id != teacher_id:
        flash("Unauthorized access to this class's records.", "danger")
        return redirect(url_for('teacher.teacher_dashboard'))

    attendance_records = Attendance.query.filter_by(
        class_id=assoc.class_id, 
        subject_id=assoc.subject_id
    ).options(
        joinedload(Attendance.student)
    ).order_by(Attendance.date, Attendance.session, User.username).all()

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["Date", "Session", "Enrollment No.", "Student Name", "Status", "Marked By"])
    
    for record in attendance_records:
        writer.writerow([
            record.date, 
            record.session, 
            record.student.enrollment_number or "N/A", 
            record.student.username, 
            record.status.title(),
            record.marked_by_teacher.username if record.marked_by_teacher else "System"
        ])
    
    output = si.getvalue()
    si.close()
    
    filename = f"{assoc.class_ref.name}_{assoc.subject.name}_Attendance_{date.today()}.csv"
    return Response(
        output, 
        mimetype="text/csv", 
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )

@teacher_bp.route('/teacher/export_summary/<int:class_teacher_id>')
@login_required(role='teacher')
def export_summary(class_teacher_id):
    teacher_id = session.get('user_id')
    assoc = ClassTeacher.query.get_or_404(class_teacher_id)
    
    if assoc.teacher_id != teacher_id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('teacher.teacher_dashboard'))

    students = User.query.filter_by(class_id=assoc.class_id, role='student', is_active=True).all()
    
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["Enrollment No.", "Student Name", "Present Count", "Total Sessions", "Percentage %"])
    
    for student in students:
        records = Attendance.query.filter_by(
            student_id=student.id, 
            class_id=assoc.class_id, 
            subject_id=assoc.subject_id
        ).all()
        
        total = len(records)
        present = sum(1 for r in records if r.status == 'present')
        pct = round((present / total * 100), 2) if total > 0 else 0
        
        writer.writerow([
            student.enrollment_number or "N/A",
            student.username,
            present,
            total,
            f"{pct}%"
        ])
    
    output = si.getvalue()
    si.close()
    
    filename = f"{assoc.class_ref.name}_{assoc.subject.name}_Summary_{date.today()}.csv"
    return Response(
        output, 
        mimetype="text/csv", 
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )
