import cv2
import face_recognition
import os
import pickle
from datetime import date, datetime
from utils import get_next_session_number
# Local imports
from models import db, User, Attendance, ClassTeacher

# Configuration
KNOWN_FACES_DIR = "static/faces"
ENCODINGS_FILE = "encodings.pkl"
SAMPLE_COUNT_REQUIRED = 50

# -------------------------------
# HELPER FUNCTION
# -------------------------------
# --- MODIFIED: Function now accepts class_id and subject_id for isolated session counting ---

# -------------------------------
# FACE ENCODINGS MANAGEMENT
# -------------------------------
class FaceRecognitionSystem:
    def __init__(self):
        self.known_face_encodings = []
        self.known_face_names = []
        self.load_encodings()

    def load_encodings(self):
        if os.path.exists(ENCODINGS_FILE):
            try:
                with open(ENCODINGS_FILE, "rb") as f:
                    data = pickle.load(f)
                    self.known_face_encodings = data["encodings"]
                    self.known_face_names = data["names"]
                    print("Face encodings loaded from cache.")
            except (IOError, pickle.UnpicklingError, KeyError) as e:
                print(f"Error loading encodings cache: {e}. Rebuilding...")
                self.rebuild_encodings()
        else:
            self.rebuild_encodings()

    def rebuild_encodings(self):
        print("Rebuilding face encodings...")
        self.known_face_encodings = []
        self.known_face_names = []
        if not os.path.exists(KNOWN_FACES_DIR):
            os.makedirs(KNOWN_FACES_DIR)
            
        for name in os.listdir(KNOWN_FACES_DIR):
            student_path = os.path.join(KNOWN_FACES_DIR, name)
            if not os.path.isdir(student_path):
                continue
            
            images = [f for f in os.listdir(student_path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            
            for image_file in images:
                image_path = os.path.join(student_path, image_file)
                try:
                    image = face_recognition.load_image_file(image_path)
                    encodings = face_recognition.face_encodings(image)
                    if encodings:
                        self.known_face_encodings.append(encodings[0])
                        self.known_face_names.append(name)
                        break 
                except Exception as e:
                    print(f"Could not process image {image_path}: {e}")
        
        if self.known_face_encodings:
            with open(ENCODINGS_FILE, "wb") as f:
                pickle.dump({"encodings": self.known_face_encodings, "names": self.known_face_names}, f)
            print("Encodings rebuilt and saved.")
        else:
            print("No faces found to encode.")

    def recognize_faces(self, frame):
        """
        Recognizes faces in a single frame and returns a list of names.
        """
        # --- FIX: Removed the unnecessary BGR to RGB conversion ---
        # The frame from the browser is already in the correct format.
        face_locations = face_recognition.face_locations(frame)
        face_encodings = face_recognition.face_encodings(frame, face_locations)

        recognized_names = set()
        for face_encoding in face_encodings:
            matches = face_recognition.compare_faces(self.known_face_encodings, face_encoding)
            if True in matches:
                first_match_index = matches.index(True)
                name = self.known_face_names[first_match_index]
                recognized_names.add(name)
        return list(recognized_names)

# -------------------------------
# VIDEO STREAMING & FACE CAPTURE
# -------------------------------
class FaceCapture:
    @staticmethod
    def stream_capture(username):
        """Streams video from the webcam to capture 50 face samples for a student."""
        camera = cv2.VideoCapture(0)
        if not camera.isOpened():
            print("ERROR: Cannot open webcam for sample capture.")
            return

        save_path = os.path.join(KNOWN_FACES_DIR, username)
        os.makedirs(save_path, exist_ok=True)
        
        sample_count = len(os.listdir(save_path))
        frame_counter = 0

        try:
            while sample_count < SAMPLE_COUNT_REQUIRED:
                ret, frame = camera.read()
                if not ret:
                    break

                if frame_counter % 5 == 0:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    face_locations = face_recognition.face_locations(rgb_frame)

                    if len(face_locations) == 1:
                        img_name = f"{username}_sample_{sample_count}.jpg"
                        cv2.imwrite(os.path.join(save_path, img_name), frame)
                        sample_count += 1
                        print(f"Captured sample {sample_count}/{SAMPLE_COUNT_REQUIRED}")

                frame_counter += 1
                
                # Visual feedback on the stream
                cv2.putText(frame, f"Samples: {sample_count}/{SAMPLE_COUNT_REQUIRED}", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                if sample_count >= SAMPLE_COUNT_REQUIRED:
                    cv2.putText(frame, "Capture Complete!", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

                ret, buffer = cv2.imencode('.jpg', frame)
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        finally:
            camera.release()
            print("DEBUG: Releasing sample capture camera...")