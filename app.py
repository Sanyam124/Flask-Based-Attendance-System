from flask import Flask, render_template, request, redirect, url_for, Response, session, send_file, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, date
import shutil
import os
import re
import csv
from io import StringIO
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from flask import Flask, render_template, request, redirect, url_for, Response, session, send_file, jsonify, flash
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, date
import os
import re
import csv
import pickle
import base64
import numpy as np
from io import StringIO, BytesIO
from PIL import Image
from sqlalchemy.orm import joinedload
from sqlalchemy import func
import cv2
import face_recognition

# Local imports
from attendance_logic import FaceRecognitionSystem, FaceCapture, KNOWN_FACES_DIR
from models import db, Class, ClassTeacher, User, Attendance, Subject
from utils import get_next_session_number

KNOWN_FACES_DIR = "static/faces"
ENCODINGS_FILE = "encodings.pkl"

# ------------------------
# App & DB setup
# ------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
socketio = SocketIO(app)


frs = FaceRecognitionSystem()

with app.app_context():
    db.create_all()

# ------------------------
# HELPER FUNCTIONS
# ------------------------

def _create_user_and_associations(form):
    """Helper function to create users, with role-based email and class name validation."""
    username = form['username']
    email = form['email']
    password = form.get('password')
    role = form['role']
    class_names_str = form.get('class_name')
    subject_name = form.get('subject')
    enrollment_number = form.get('enrollment_number')

    # --- Validation ---
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

    # --- NEW: Class Name Format Validation ---
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

    # --- Database Operations ---
    new_user = User(
        username=username,
        email=email,
        password=generate_password_hash(password),
        role=role,
        enrollment_number=enrollment_number if role == 'student' else None
    )
    # ... (rest of function is the same)
    db.session.add(new_user)
    if role == 'student' and class_names_str:
        class_name = class_names_str.strip()
        class_obj = Class.query.filter_by(name=class_name).first() or Class(name=class_name)
        new_user.class_ref = class_obj
    elif role == 'teacher' and class_names_str and subject_name:
        subject_obj = Subject.query.filter_by(name=subject_name.strip()).first() or Subject(name=subject_name.strip())
        unique_class_names = {name.strip() for name in class_names_str.split(',') if name.strip()}
        for class_name in unique_class_names:
            class_obj = Class.query.filter_by(name=class_name).first() or Class(name=class_name)
            association = ClassTeacher(teacher=new_user, class_ref=class_obj, subject=subject_obj)
            db.session.add(association)
    db.session.commit()
    return new_user

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if 'user_id' not in session:
                flash("Please log in to access this page.", "danger")
                return redirect(url_for('login'))
            if role and session.get('user_role') != role:
                flash("You do not have permission to access this page.", "warning")
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return wrapper
    return decorator

@app.route('/teacher/recognize_frame', methods=['POST'])
@login_required(role='teacher')
def recognize_frame():
    data = request.json
    image_data = base64.b64decode(data['image'].split(',')[1])
    class_teacher_id = data['assoc_id']
    # --- CORRECTED: Use the session number sent from the frontend ---
    session_number = data['session_number'] 
    
    image = Image.open(BytesIO(image_data))
    frame = np.array(image)
    
    recognized_names = frs.recognize_faces(frame)
    
    assoc = ClassTeacher.query.get(class_teacher_id)
    if not assoc:
        return jsonify({"error": "Invalid association"}), 400
        
    valid_students_in_class = {
        user.username for user in User.query.filter_by(
            class_id=assoc.class_id, role='student', is_active=True
        ).all()
    }

    today = date.today()
    marked_students = []

    for name in recognized_names:
        if name in valid_students_in_class:
            student = User.query.filter_by(username=name).first()
            if student:
                # Check if a record already exists for this specific session
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
                    # Add to the list to be sent back to the browser for real-time update
                    marked_students.append({'username': name, 'timestamp': datetime.now().strftime("%H:%M:%S")})

    if marked_students:
        db.session.commit()
        
    return jsonify({"present": marked_students})

# ------------------------
# MAIN ROUTES
# ------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # --- MODIFIED: Accept either email or enrollment number ---
        login_identifier = request.form['login_identifier']
        password = request.form['password']
        
        user = None
        # Check if the identifier is an email or an enrollment number
        if '@' in login_identifier:
            user = User.query.filter_by(email=login_identifier, is_active=True).first()
        else:
            user = User.query.filter_by(enrollment_number=login_identifier, is_active=True).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['user_role'] = user.role
            session['username'] = user.username
            dashboard_map = {'student': 'student_dashboard', 'teacher': 'teacher_dashboard', 'admin': 'admin_dashboard'}
            return redirect(url_for(dashboard_map.get(user.role, 'login')))
        else:
            flash("Invalid credentials or account is inactive. Please try again.", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        new_user = _create_user_and_associations(request.form)
        if new_user:
            if new_user.role == 'student':
                # We still create the directory, but we no longer auto-redirect
                os.makedirs(os.path.join(KNOWN_FACES_DIR, new_user.username), exist_ok=True)
            
            # For all successful registrations, redirect to the login page
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for('login'))
            
        # If user creation fails, the helper function sets the flash message
        return redirect(url_for('register'))
        
    return render_template('register.html')

# ------------------------
# NEW PROFILE ROUTE
# ------------------------
@app.route('/profile/<int:user_id>')
@login_required()
def view_profile(user_id):
    # Security check: A user can only view their own profile.
    if user_id != session.get('user_id'):
        flash("You can only view your own profile.", "danger")
        return redirect(url_for(session.get('user_role') + '_dashboard'))

    user = User.query.options(
        joinedload(User.class_ref),
        joinedload(User.class_assignments).joinedload(ClassTeacher.class_ref),
        joinedload(User.class_assignments).joinedload(ClassTeacher.subject)
    ).get_or_404(user_id)

    profile_image_url = None
    if user.role == 'student':
        student_face_dir = os.path.join(app.static_folder, 'faces', user.username)
        if os.path.exists(student_face_dir):
            face_samples = sorted([f for f in os.listdir(student_face_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
            if face_samples:
                profile_image_url = f"faces/{user.username}/{face_samples[0]}"

    return render_template('profile.html', user=user, profile_image_url=profile_image_url)

# ------------------------
# STUDENT ROUTES
# ------------------------
@app.route('/student/dashboard')
@login_required(role='student')
def student_dashboard():
    student_id = session.get('user_id')
    student_obj = User.query.get_or_404(student_id)

    profile_image_url = None
    student_face_dir = os.path.join(app.static_folder, 'faces', student_obj.username)
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
    # --- NEW: Calculate absent count ---
    absent_count = total_records - present_count
    attendance_percentage = (present_count / total_records) * 100 if total_records > 0 else 0
    
    return render_template('student_dashboard.html', 
                           student=student_obj,
                           attendance_records=attendance_records,
                           total_records=total_records, # Renamed for clarity
                           present_count=present_count,
                           absent_count=absent_count, # Pass new count
                           attendance_percentage=attendance_percentage,
                           has_samples=has_samples,
                           profile_image_url=profile_image_url)

@app.route('/student/capture_samples')
@login_required(role='student')
def capture_samples():
    return render_template('capture_samples.html', username=session.get('username'))

@app.route('/student/video_feed')
@login_required(role='student')
def student_video_feed():
    username = session.get('username')
    return Response(FaceCapture.stream_capture(username), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/student/check_capture_status/<username>')
@login_required(role='student')
def student_check_capture_status(username):
    save_path = os.path.join(KNOWN_FACES_DIR, username)
    completed = os.path.exists(save_path) and len(os.listdir(save_path)) >= 50
    if completed:
        frs.rebuild_encodings()
        flash("Face samples captured and system updated!", "success")
    return jsonify({"completed": completed})

# ------------------------
# TEACHER ROUTES
# ------------------------
@app.route("/teacher/dashboard")
@login_required(role='teacher')
def teacher_dashboard():
    teacher_id = session.get("user_id")
    teacher = User.query.get_or_404(teacher_id)
    # Fetch only associations where the class is active
    classes_taught = ClassTeacher.query.join(Class).filter(
        ClassTeacher.teacher_id == teacher_id,
        Class.is_active == True
    ).options(
        joinedload(ClassTeacher.class_ref), 
        joinedload(ClassTeacher.subject)
    ).all()
    return render_template("teacher_dashboard.html", classes_taught=classes_taught, teacher=teacher)

# ---------------------------------
# NEW ROUTES FOR UPDATING ATTENDANCE
# ---------------------------------
@app.route('/teacher/update_attendance', methods=['GET', 'POST'])
@login_required(role='teacher')
def update_attendance():
    teacher_id = session.get('user_id')
    classes_taught = ClassTeacher.query.filter_by(teacher_id=teacher_id).options(
        joinedload(ClassTeacher.class_ref),
        joinedload(ClassTeacher.subject)
    ).all()
    
    students_for_update = []
    student_statuses = {}
    
    # Use request.values to get parameters from both GET (redirect) and POST (form submit)
    selected_ct_id = request.values.get('class_teacher_id', type=int)
    selected_date = request.values.get('date')
    selected_session = request.values.get('session', type=int)

    # Only fetch records if all parameters are present
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
        # If it's a POST but some fields are missing
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

@app.route('/teacher/handle_update', methods=['POST'])
@login_required(role='teacher')
def handle_update_attendance():
    teacher_id = session.get('user_id')
    ct_id = request.form.get('class_teacher_id', type=int)
    update_date_str = request.form.get('date')
    session_number = request.form.get('session', type=int)
    
    assoc = ClassTeacher.query.get(ct_id)
    if not assoc or assoc.teacher_id != teacher_id:
        flash("Unauthorized action.", "danger")
        return redirect(url_for('teacher_dashboard'))

    update_date = datetime.strptime(update_date_str, '%Y-%m-%d').date()
    all_students_in_class = User.query.filter_by(role='student', class_id=assoc.class_id).all()
    present_student_ids = request.form.getlist("present_students")

    for student in all_students_in_class:
        # Manually check for an existing record
        existing_record = Attendance.query.filter_by(
            student_id=student.id,
            date=update_date,
            subject_id=assoc.subject_id,
            session=session_number
        ).first()

        new_status = 'present' if str(student.id) in present_student_ids else 'absent'

        if existing_record:
            # If it exists, update its status and timestamp
            existing_record.status = new_status
            existing_record.marked_by_id = teacher_id
            existing_record.timestamp = datetime.now()
        else:
            # If it doesn't exist, create a new record
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
    # Redirect with query parameters to pre-fill the form with the user's last selection
    return redirect(url_for('update_attendance', 
                            class_teacher_id=ct_id, 
                            date=update_date_str, 
                            session=session_number))

# ------------------------
# API ROUTE
# ------------------------
@app.route('/api/sessions_for_date')
@login_required(role='teacher')
def get_sessions_for_date():
    date_str = request.args.get('date')
    # --- MODIFIED: Get the class_teacher_id to find the specific class and subject ---
    ct_id = request.args.get('class_teacher_id', type=int)

    if not date_str or not ct_id:
        return jsonify({"error": "Date and Class parameters are required"}), 400
    
    assoc = ClassTeacher.query.get(ct_id)
    if not assoc:
        return jsonify({"error": "Invalid class selection"}), 404
    
    try:
        query_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        # --- MODIFIED: Query is now filtered by class and subject ---
        sessions = db.session.query(Attendance.session).filter_by(
            date=query_date, 
            class_id=assoc.class_id, 
            subject_id=assoc.subject_id
        ).distinct().order_by(Attendance.session).all()
        
        session_numbers = [s[0] for s in sessions]
        return jsonify({"sessions": session_numbers})
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

@app.route("/teacher/manual_attendance", methods=["GET", "POST"])
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
            
            # --- NEW: Fetch today's attendance to pre-fill checkboxes ---
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
            return redirect(url_for('teacher_dashboard'))
        
        if not assoc.class_ref.is_active:
            flash(f"Cannot save attendance for inactive class '{assoc.class_ref.name}'.", "danger")
            return redirect(url_for('manual_attendance'))

        today = date.today()
        session_number = get_next_session_number(assoc.class_id, assoc.subject_id, today)
        all_students_in_class = User.query.filter_by(role='student', class_id=assoc.class_id).all()
        
        # --- CORRECTED: Get a list of student IDs from checkboxes named 'present_students' ---
        present_student_ids = request.form.getlist("present_students")

        for student in all_students_in_class:
            new_status = 'present' if str(student.id) in present_student_ids else 'absent'
            # Use merge to create/update the record for the new session
            db.session.merge(Attendance(
                student_id=student.id, date=today, subject_id=assoc.subject_id, session=session_number,
                class_id=assoc.class_id, marked_by_id=teacher_id, status=new_status
            ))
        
        db.session.commit()
        flash(f"Manual attendance for Session {session_number} recorded successfully.", "success")
        return redirect(url_for('manual_attendance', class_teacher_id=ct_id))

    return render_template(
        "manual_attendance.html", 
        classes_taught=classes_taught, 
        students=students, 
        selected_ct_id=selected_ct_id,
        attendance_today=attendance_today  # Pass today's data to the template
    )

@app.route("/teacher/attendance_reports")
@login_required(role='teacher')
def teacher_attendance_reports():
    teacher_id = session.get("user_id")
    # Fetch all class assignments for the teacher
    classes_taught = ClassTeacher.query.filter_by(teacher_id=teacher_id).options(
        joinedload(ClassTeacher.class_ref), 
        joinedload(ClassTeacher.subject)
    ).all()
    
    reports = {}
    for assoc in classes_taught:
        # Find all active students in the current class assignment
        students = User.query.filter_by(
            role="student", 
            class_id=assoc.class_id,
            is_active=True
        ).all()

        student_reports = []
        for student in students:
            # Query all attendance records for this specific student, class, and subject
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
                "percentage": round(percentage, 2)
            })
            
        # Use the class and subject names as a key for the report dictionary
        report_key = f"{assoc.class_ref.name} - {assoc.subject.name}"
        reports[report_key] = student_reports
        
    return render_template("teacher_attendance_reports.html", reports=reports)

@app.route('/teacher/attendance/<int:class_teacher_id>')
@login_required(role='teacher')
def teacher_attendance(class_teacher_id):
    # This route now just renders the page. The session logic is handled by Socket.IO.
    assoc = ClassTeacher.query.get_or_404(class_teacher_id)
    if assoc.teacher_id != session.get('user_id'):
        return redirect(url_for('teacher_dashboard'))
    session_number = get_next_session_number(assoc.class_id, assoc.subject_id, date.today())
    students_in_class = User.query.filter_by(class_id=assoc.class_id, role='student', is_active=True).all()
    return render_template('teacher_attendance.html', students=students_in_class, association=assoc, session_number=session_number)

@app.route('/camera_client')
def camera_client_page():
    return render_template('camera_client.html')

@app.route('/teacher/video_feed/<int:class_teacher_id>/<int:session_number>')
@login_required(role='teacher')
def teacher_video_feed(class_teacher_id, session_number):
    return Response(FaceCapture.stream_attendance(app, frs, class_teacher_id, session_number), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/teacher/attendance_status/<int:class_teacher_id>')
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

@app.route("/teacher/end_session/<int:class_teacher_id>/<int:session_number>", methods=["POST"])
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
    return jsonify({"status": "ended", "redirect_url": url_for('teacher_dashboard')})

# ------------------------
# ADMIN ROUTES
# ------------------------
@app.route('/admin/dashboard')
@login_required(role='admin')
def admin_dashboard():
    # --- ADDED: Get admin user object for the new header ---
    admin_id = session.get('user_id')
    admin = User.query.get_or_404(admin_id)

    # Counts only active users for the dashboard stats
    total_students = User.query.filter_by(role='student', is_active=True).count()
    total_teachers = User.query.filter_by(role='teacher', is_active=True).count()
    total_classes = Class.query.count()
    today_attendance_count = Attendance.query.filter(Attendance.date == date.today()).count()
    
    return render_template('admin_dashboard.html', 
                           total_students=total_students, 
                           total_teachers=total_teachers, 
                           total_classes=total_classes, 
                           today_attendance_count=today_attendance_count,
                           admin=admin) # Pass the admin object to the template

@app.route('/admin/users')
@login_required(role='admin')
def admin_manage_users():
    users = User.query.options(
        joinedload(User.class_ref),
        joinedload(User.class_assignments).joinedload(ClassTeacher.class_ref),
        joinedload(User.class_assignments).joinedload(ClassTeacher.subject)
    ).order_by(User.id).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/add', methods=['GET', 'POST'])
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
            return redirect(url_for('admin_manage_users'))
        return render_template('admin_user_form.html', user=None)
    return render_template('admin_user_form.html', user=None)

@app.route('/admin/users/update/<int:user_id>', methods=['GET', 'POST'])
@login_required(role='admin')
def admin_update_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        username = request.form['username']
        password = request.form.get('password')
        enrollment_number = request.form.get('enrollment_number')
        
        # --- NEW: Username, Password, and Enrollment Number Validation ---
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

        # --- Class Name Format Validation ---
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

        # --- Enrollment and Class Assignment Logic ---
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
                class_obj = Class.query.filter_by(name=class_names_str.strip()).first() or Class(name=class_names_str.strip())
                user.class_ref = class_obj
        else:
            user.enrollment_number = None

        if user.role == 'teacher':
            user.class_id = None
            ClassTeacher.query.filter_by(teacher_id=user.id).delete()
            if class_names_str and subject_name:
                subject_obj = Subject.query.filter_by(name=subject_name.strip()).first() or Subject(name=subject_name.strip())
                unique_class_names = {name.strip() for name in class_names_str.split(',') if name.strip()}
                for class_name in unique_class_names:
                    class_obj = Class.query.filter_by(name=class_name).first() or Class(name=class_name)
                    db.session.add(ClassTeacher(teacher=user, class_ref=class_obj, subject=subject_obj))

        db.session.commit()
        flash(f"User '{user.username}' updated successfully.", "success")
        return redirect(url_for('admin_manage_users'))

    return render_template('admin_user_form.html', user=user)

@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@login_required(role='admin')
def admin_delete_user(user_id):
    # This function now acts as "deactivate"
    if user_id == session.get('user_id'):
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for('admin_manage_users'))
    
    user = User.query.get_or_404(user_id)
    user.is_active = False
    
    if user.role == 'teacher':
        ClassTeacher.query.filter_by(teacher_id=user.id).delete()
    
    db.session.commit()
    flash(f"User account for '{user.username}' has been deactivated.", "success")
    return redirect(url_for('admin_manage_users'))

@app.route('/admin/users/delete_student/<int:user_id>', methods=['POST'])
@login_required(role='admin')
def admin_delete_student(user_id):
    if user_id == session.get('user_id'):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for('admin_manage_users'))
        
    user = User.query.get_or_404(user_id)
    
    if user.role != 'student':
        flash("This action is only for deleting students.", "danger")
        return redirect(url_for('admin_manage_users'))

    username_for_flash = user.username
    
    Attendance.query.filter_by(student_id=user.id).delete()
    
    student_face_dir = os.path.join(KNOWN_FACES_DIR, user.username)
    if os.path.exists(student_face_dir):
        shutil.rmtree(student_face_dir)
        
    db.session.delete(user)
    db.session.commit()
    
    frs.rebuild_encodings()

    flash(f"Student '{username_for_flash}' and all associated data have been permanently deleted.", "success")
    return redirect(url_for('admin_manage_users'))

@app.route('/admin/users/reactivate/<int:user_id>', methods=['POST'])
@login_required(role='admin')
def admin_reactivate_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = True
    db.session.commit()
    flash(f"User account for '{user.username}' has been reactivated.", "success")
    return redirect(url_for('admin_manage_users'))

@app.route('/admin/classes')
@login_required(role='admin')
def admin_manage_classes():
    """
    Fetches and displays all classes, sorted logically by semester,
    course, and then batch number.
    """
    # Fetch all class objects with their related teacher and subject data
    all_classes = Class.query.options(
        joinedload(Class.class_teachers).joinedload(ClassTeacher.teacher),
        joinedload(Class.class_teachers).joinedload(ClassTeacher.subject)
    ).all()

    # --- NEW: Custom sorting logic ---
    def get_sort_key(cls):
        """
        Creates a sort key from a class name like '5B1'.
        Sorts by: 1. Semester (numeric), 2. Course (alpha), 3. Batch (numeric).
        """
        # Regex to parse names like "5B1", "12C10", etc.
        match = re.match(r'(\d+)([A-Za-z]+)(\d+)', cls.name)
        if match:
            semester, course, batch = match.groups()
            # Return a tuple that Python can use for multi-level sorting
            return (int(semester), course.upper(), int(batch))
        else:
            # For any class names that don't match the pattern (e.g., "Library"),
            # sort them alphabetically at the very end of the list.
            return (float('inf'), cls.name, 0)

    # Sort the list of class objects using our custom key function
    sorted_classes = sorted(all_classes, key=get_sort_key)

    return render_template("admin_classes.html", classes=sorted_classes)

@app.route('/admin/class/<int:class_id>/deactivate', methods=['POST'])
@login_required(role='admin')
def admin_deactivate_class(class_id):
    cls = Class.query.get_or_404(class_id)
    cls.is_active = False
    db.session.commit()
    flash(f"Class '{cls.name}' has been deactivated.", "success")
    return redirect(url_for('admin_manage_classes'))

@app.route('/admin/class/<int:class_id>/reactivate', methods=['POST'])
@login_required(role='admin')
def admin_reactivate_class(class_id):
    cls = Class.query.get_or_404(class_id)
    cls.is_active = True
    db.session.commit()
    flash(f"Class '{cls.name}' has been reactivated.", "success")
    return redirect(url_for('admin_manage_classes'))

@app.route('/admin/class/<int:class_id>/delete', methods=['POST'])
@login_required(role='admin')
def admin_delete_class(class_id):
    cls = Class.query.get_or_404(class_id)
    class_name = cls.name

    # --- NEW: Find and delete all students in this class ---
    students_to_delete = User.query.filter_by(class_id=class_id, role='student').all()
    for student in students_to_delete:
        # Delete all attendance records for this student
        Attendance.query.filter_by(student_id=student.id).delete()
        
        # Delete the student's face samples directory
        student_face_dir = os.path.join(KNOWN_FACES_DIR, student.username)
        if os.path.exists(student_face_dir):
            shutil.rmtree(student_face_dir)
            
        # Delete the student user object
        db.session.delete(student)
    
    # Delete all teacher associations for this class
    ClassTeacher.query.filter_by(class_id=class_id).delete()

    # Finally, delete the class itself
    db.session.delete(cls)
    db.session.commit()

    # Rebuild face encodings since student data has been removed
    frs.rebuild_encodings()
    
    flash(f"Class '{class_name}', its assignments, and all its students have been permanently deleted.", "success")
    return redirect(url_for('admin_manage_classes'))

@app.route('/admin/class/<int:class_id>/students')
@login_required(role='admin')
def admin_view_class_students(class_id):
    target_class = Class.query.get_or_404(class_id)
    students_in_class = User.query.filter_by(
        class_id=class_id, 
        role='student',
        is_active=True
    ).order_by(User.username).all()
    
    return render_template('admin_class_students.html', target_class=target_class, students=students_in_class)

@app.route('/admin/reports')
@login_required(role='admin')
def admin_reports():
    students = User.query.filter_by(role='student').options(joinedload(User.class_ref)).all()
    return render_template('admin_reports.html', students=students)

@app.route('/admin/export_attendance/<int:student_id>')
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

# ------------------------
# SOCKET.IO EVENT HANDLERS
# ------------------------
@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

# --- These handlers just pass messages between the two clients ---
@socketio.on('teacher-ready')
def handle_teacher_ready():
    emit('teacher-connect', broadcast=True, include_self=False)

@socketio.on('offer-from-camera')
def handle_offer(offer):
    emit('offer-from-camera', offer, broadcast=True, include_self=False)

@socketio.on('answer-from-teacher')
def handle_answer(answer):
    emit('answer-from-teacher', answer, broadcast=True, include_self=False)

@socketio.on('candidate-from-camera')
def handle_camera_candidate(candidate):
    emit('candidate-from-camera', candidate, broadcast=True, include_self=False)

@socketio.on('candidate-from-teacher')
def handle_teacher_candidate(candidate):
    emit('candidate-from-teacher', candidate, broadcast=True, include_self=False)

if __name__ == "__main__":
    # --- MODIFIED: Added ssl_context to run a secure HTTPS server ---
    socketio.run(
        app, 
        debug=True, 
        host='0.0.0.0', 
        ssl_context=('cert.pem', 'key.pem')
    )