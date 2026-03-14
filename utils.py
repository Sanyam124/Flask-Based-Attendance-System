from sqlalchemy import func
from models import db, Attendance
from config import KNOWN_FACES_DIR
import face_recognition
import os
import pickle


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
        print(f"[INFO] Encodings saved for {username} at {encoding_file}")
    else:
        print(f"[WARNING] No faces detected for {username}")


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
