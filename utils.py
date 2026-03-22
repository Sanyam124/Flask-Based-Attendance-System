from sqlalchemy import func
from models import db, Attendance
from config import KNOWN_FACES_DIR
import face_recognition
import os
import pickle
import re

def slugify(text):
    """Convert text to a filesystem-safe slug."""
    if not text:
        return "unassigned"
    # Replace non-alphanumeric with underscore and collapse multiples
    text = re.sub(r'[^a-zA-Z0-9]', '_', text)
    return re.sub(r'_+', '_', text).strip('_')


def generate_face_encodings(username):
    """
    Generates face encodings from images stored in static/faces/<username>/
    and saves them as a pickle file for fast loading.
    """
    face_dir = os.path.join(KNOWN_FACES_DIR, username)
    encoding_file = os.path.join(face_dir, 'encodings.pkl')

    encodings = []

    for img_name in os.listdir(face_dir):
        if img_name.endswith(".jpg"):
            img_path = os.path.join(face_dir, img_name)
            image = face_recognition.load_image_file(img_path)
            face_locations = face_recognition.face_locations(image)
            face_encs = face_recognition.face_encodings(image, face_locations)

            if face_encs:  # Only store if a face is detected
                encodings.append(face_encs[0])

    if encodings:
        with open(encoding_file, 'wb') as f:
            pickle.dump(encodings, f)


def get_next_session_number(class_id, subject_id, for_date):
    """
    Calculates the next session number for a specific class and subject on a given date.
    """
    max_session = db.session.query(func.max(Attendance.session)).filter_by(
        date=for_date,
        class_id=class_id,
        subject_id=subject_id
    ).scalar()
    return (max_session or 0) + 1


def get_face_folder_name(user):
    """
    Returns the relative path for storing face images for a user.
    Uses human-readable names: org_Name / class_Name / enrollment_username
    """
    if not user.organization_id:
        org_part = "org_global"
    else:
        org_name = slugify(user.organization.name) if user.organization else "org"
        org_part = f"org_{org_name}"

    if user.role == 'student':
        if not user.class_id:
            class_part = "class_unassigned"
        else:
            class_name = slugify(user.class_ref.name) if user.class_ref else "class"
            class_part = f"class_{class_name}"
        
        user_part = f"{user.enrollment_number}_{user.username}" if user.enrollment_number else user.username
    else:
        class_part = "staff"
        user_part = user.username
    
    return os.path.join(org_part, class_part, user_part)

def migrate_existing_face_data():
    """
    Scans KNOWN_FACES_DIR and renames folders and files to new descriptive formats.
    This is a maintenance utility to ensure folder structures match current logic.
    """
    from config import KNOWN_FACES_DIR
    from models import Organization, Class, User
    import shutil

    if not os.path.exists(KNOWN_FACES_DIR):
        return

    # 1. Migrate Org Folders (Remove ID if present)
    for org_dir in os.listdir(KNOWN_FACES_DIR):
        org_path = os.path.join(KNOWN_FACES_DIR, org_dir)
        if not os.path.isdir(org_path): continue
        if org_dir == "org_global": continue
        
        parts = org_dir.split('_')
        if len(parts) >= 3 and parts[0] == "org" and parts[1].isdigit():
            org_id = int(parts[1])
            org_obj = Organization.query.get(org_id)
            if org_obj:
                new_name = f"org_{slugify(org_obj.name)}"
                new_path = os.path.join(KNOWN_FACES_DIR, new_name)
                if not os.path.exists(new_path):
                    os.rename(org_path, new_path)
                    org_path = new_path
                else:
                    try:
                        for item in os.listdir(org_path):
                            shutil.move(os.path.join(org_path, item), os.path.join(new_path, item))
                        os.rmdir(org_path)
                        org_path = new_path
                    except Exception:
                        pass

    # 2. & 3. Migrate Class and Student Folders inside each Org
    for org_dir in os.listdir(KNOWN_FACES_DIR):
        org_path = os.path.join(KNOWN_FACES_DIR, org_dir)
        if not os.path.isdir(org_path): continue
        
        for class_dir in os.listdir(org_path):
            class_path = os.path.join(org_path, class_dir)
            if not os.path.isdir(class_path): continue
            
            class_parts = class_dir.split('_')
            target_class_path = class_path
            
            if len(class_parts) >= 3 and class_parts[0] == "class" and class_parts[1].isdigit():
                class_id = int(class_parts[1])
                class_obj = Class.query.get(class_id)
                if class_obj:
                    new_class_name = f"class_{slugify(class_obj.name)}"
                    new_class_path = os.path.join(org_path, new_class_name)
                    if not os.path.exists(new_class_path):
                        os.rename(class_path, new_class_path)
                        target_class_path = new_class_path
                    else:
                        try:
                            for item in os.listdir(class_path):
                                shutil.move(os.path.join(class_path, item), os.path.join(new_class_path, item))
                            os.rmdir(class_path)
                            target_class_path = new_class_path
                        except Exception:
                            pass
            
            elif len(class_parts) == 2 and class_parts[0] == "class" and class_parts[1].isdigit():
                class_id = int(class_parts[1])
                class_obj = Class.query.get(class_id)
                if class_obj:
                    new_class_name = f"class_{slugify(class_obj.name)}"
                    new_class_path = os.path.join(org_path, new_class_name)
                    if not os.path.exists(new_class_path):
                        os.rename(class_path, new_class_path)
                        target_class_path = new_class_path
                    else:
                        target_class_path = new_class_path

            if os.path.isdir(target_class_path):
                for student_dir in os.listdir(target_class_path):
                    student_path = os.path.join(target_class_path, student_dir)
                    if not os.path.isdir(student_path): continue
                    if student_dir == "staff": continue
                    
                    org_name_slug = org_dir[4:]
                    org_match = Organization.query.all()
                    curr_org_id = None
                    for o in org_match:
                        if slugify(o.name) == org_name_slug:
                            curr_org_id = o.id
                            break
                    
                    if curr_org_id:
                        std_user = User.query.filter_by(username=student_dir, organization_id=curr_org_id, role='student').first()
                        if std_user and std_user.enrollment_number:
                            new_std_dir = f"{std_user.enrollment_number}_{std_user.username}"
                            if student_dir != new_std_dir:
                                new_std_path = os.path.join(target_class_path, new_std_dir)
                                if not os.path.exists(new_std_path):
                                    os.rename(student_path, new_std_path)
