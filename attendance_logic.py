"""
attendance_logic.py
──────────────────
Face recognition engine using the `face_recognition` library (dlib 128-d embeddings).
Registration : admin uploads one clear photo  →  stored in static/faces/<username>/
Recognition  : live frame → 128-d encoding → distance check vs stored encodings
"""

import os
import cv2
import pickle
import numpy as np
import face_recognition
from PIL import Image, ImageOps

from config import (
    KNOWN_FACES_DIR,
    ENCODINGS_FILE,
    FACE_RECOGNITION_TOLERANCE,
    FACE_RECOGNITION_MARGIN,
)


def encode_image_file(path: str):
    """
    Load an image from disk and return its 128-d face encoding.
    Corrects orientation, ensures RGB mode, and retries with upsampling if needed.
    Returns: 128-d numpy array or None if no face is detected.
    """
    try:
        # Load with PIL to fix EXIF rotation and ensure proper orientation
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)
        
        if img.mode != 'RGB':
            img = img.convert('RGB')
            
        # Convert to numpy and ensure it is an 8-bit contiguous array for dlib
        img_arr = np.array(img, dtype=np.uint8)
        if not img_arr.flags.c_contiguous:
            img_arr = np.ascontiguousarray(img_arr)

        # Detect face locations
        face_locations = face_recognition.face_locations(img_arr)
        
        # Retry with higher resolution upsampling if no face is found initially
        if len(face_locations) == 0:
            face_locations = face_recognition.face_locations(img_arr, number_of_times_to_upsample=2)
            
        if len(face_locations) == 0:
            return None
            
        encs = face_recognition.face_encodings(img_arr, known_face_locations=face_locations, num_jitters=2)
        return encs[0] if encs else None
    except Exception:
        return None


class FaceRecognitionSystem:
    """
    Core face recognition engine. Handles encoding persistence, registration,
    and real-time face matching within specified folder scopes.
    """

    def __init__(self):
        self.known_encodings: list = []
        self.known_names: list     = []
        self._load_encodings()

    def _load_encodings(self):
        """Loads cached encodings from disk or triggers a full rebuild."""
        if os.path.exists(ENCODINGS_FILE):
            try:
                with open(ENCODINGS_FILE, "rb") as f:
                    data = pickle.load(f)
                self.known_encodings = data.get("encodings", [])
                self.known_names     = data.get("names",     [])
                return
            except Exception:
                pass
        self.rebuild_encodings()

    def rebuild_encodings(self):
        """
        Scans the KNOWN_FACES_DIR to build face encodings for all students.
        Uses relative folder paths as unique person identifiers (person_id).
        """
        encodings, names = [], []

        if not os.path.exists(KNOWN_FACES_DIR):
            self.known_encodings, self.known_names = [], []
            self._save(encodings, names)
            return

        for root, dirs, files in os.walk(KNOWN_FACES_DIR):
            rel_path = os.path.relpath(root, KNOWN_FACES_DIR)
            parts = rel_path.split(os.sep)
            
            # Structure matches get_face_folder_name: org_X / class_Y / enrollment_username
            if len(parts) == 3:
                person_id = rel_path
                for img_file in sorted(files):
                    if img_file.lower().endswith((".jpg", ".jpeg", ".png")):
                        enc = encode_image_file(os.path.join(root, img_file))
                        if enc is not None:
                            encodings.append(enc)
                            names.append(person_id)
            
            # Legacy/Flat structure support
            elif len(parts) == 1 and parts[0] != '.' and any(f.lower().endswith((".jpg", ".jpeg", ".png")) for f in files):
                person_id = parts[0]
                for img_file in sorted(files):
                    if img_file.lower().endswith((".jpg", ".jpeg", ".png")):
                        enc = encode_image_file(os.path.join(root, img_file))
                        if enc is not None:
                            encodings.append(enc)
                            names.append(person_id)

        self.known_encodings = encodings
        self.known_names     = names
        self._save(encodings, names)

    def _save(self, encodings, names):
        """Saves current embeddings and identifiers to the cache file."""
        with open(ENCODINGS_FILE, "wb") as f:
            pickle.dump({"encodings": encodings, "names": names}, f)

    def register_face(self, person_id: str, image_path: str) -> bool:
        """
        Encodes a new face image and updates the system state.
        Returns: True if registration was successful.
        """
        enc = encode_image_file(image_path)
        if enc is None:
            return False
            
        # Clear existing data for this identifier to prevent duplicate entries
        filtered = [(e, n) for e, n in zip(self.known_encodings, self.known_names) if n != person_id]
        if filtered:
            new_encs, new_names = zip(*filtered)
            self.known_encodings = list(new_encs)
            self.known_names     = list(new_names)
        else:
            self.known_encodings, self.known_names = [], []

        self.known_encodings.append(enc)
        self.known_names.append(person_id)
        self._save(self.known_encodings, self.known_names)
        return True

    def is_registered(self, person_id: str) -> bool:
        """Checks if a specific person identifier is currently registered."""
        return person_id in self.known_names

    def recognize_faces(self, frame, path_prefix=None) -> list[str]:
        """
        Identifies faces in a BGR frame within an optional folder scope.
        Returns: List of recognized person identifiers (paths).
        """
        if not self.known_encodings:
            return []

        search_encodings = self.known_encodings
        search_names = self.known_names

        if path_prefix is not None:
            norm_prefix = os.path.normpath(path_prefix)
            sep_prefix = norm_prefix if norm_prefix.endswith(os.sep) else norm_prefix + os.sep
            indices = [i for i, name in enumerate(self.known_names) if name.startswith(sep_prefix)]
            if not indices:
                return []
            search_encodings = [self.known_encodings[i] for i in indices]
            search_names = [self.known_names[i] for i in indices]

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        locations = face_recognition.face_locations(rgb, model="hog")
        if not locations:
            return []

        live_encs = face_recognition.face_encodings(rgb, locations, num_jitters=1)
        recognized = set()
        known_arr  = np.array(search_encodings)

        for live_enc in live_encs:
            distances = face_recognition.face_distance(known_arr, live_enc)
            if len(distances) == 0:
                continue

            sorted_idx  = np.argsort(distances)
            best_dist   = distances[sorted_idx[0]]
            best_id     = search_names[sorted_idx[0]]

            if best_dist <= FACE_RECOGNITION_TOLERANCE:
                # Margin-of-victory check to prevent ambiguous matches
                if len(sorted_idx) > 1:
                    margin = distances[sorted_idx[1]] - best_dist
                    if margin < FACE_RECOGNITION_MARGIN:
                        continue
                recognized.add(best_id)

        return list(recognized)


def stream_attendance_feed(frs, path_prefix: str, student_paths: set):
    """
    MJPEG generator for the teacher's live camera feed.
    Draws recognition boxes and labels on recognized faces.
    """
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        return

    try:
        while True:
            ret, frame = camera.read()
            if not ret or frame is None:
                continue

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            locs = face_recognition.face_locations(rgb, model="hog")
            live_encs = face_recognition.face_encodings(rgb, locs, num_jitters=1)

            norm_prefix = os.path.normpath(path_prefix)
            sep_prefix = norm_prefix if norm_prefix.endswith(os.sep) else norm_prefix + os.sep
            
            filtered_indices = [i for i, name in enumerate(frs.known_names) if name.startswith(sep_prefix)]
            
            if filtered_indices and frs.known_encodings:
                search_encs = [frs.known_encodings[i] for i in filtered_indices]
                search_names = [frs.known_names[i] for i in filtered_indices]
                known_arr = np.array(search_encs)

                for (top, right, bottom, left), enc in zip(locs, live_encs):
                    label, color = "Unknown", (100, 100, 100)

                    distances = face_recognition.face_distance(known_arr, enc)
                    if len(distances) > 0:
                        sorted_idx = np.argsort(distances)
                        best_dist = distances[sorted_idx[0]]
                        if best_dist <= FACE_RECOGNITION_TOLERANCE:
                            best_id = search_names[sorted_idx[0]]
                            
                            is_ambiguous = False
                            if len(sorted_idx) > 1:
                                margin = distances[sorted_idx[1]] - best_dist
                                if margin < FACE_RECOGNITION_MARGIN:
                                    is_ambiguous = True

                            if not is_ambiguous:
                                folder_name = os.path.basename(best_id)
                                display_name = folder_name.split('_', 1)[1] if '_' in folder_name else folder_name
                                label, color = display_name, (0, 220, 80) if best_id in student_paths else (60, 180, 255)

                    cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                    cv2.rectangle(frame, (left, bottom - 26), (right, bottom), color, cv2.FILLED)
                    cv2.putText(frame, label, (left + 6, bottom - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
    finally:
        camera.release()
走,StartLine:1,TargetContent:
                                margin = distances[sorted_idx[1]] - best_dist
                                if margin < FACE_RECOGNITION_MARGIN:
                                    is_ambiguous = True

                            if not is_ambiguous:
                                # Extract username for display
                                folder_name = os.path.basename(best_id)
                                display_name = folder_name.split('_', 1)[1] if '_' in folder_name else folder_name
                                
                                label = display_name
                                color = (0, 220, 80) if best_id in student_paths else (60, 180, 255)

                    cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                    cv2.rectangle(frame, (left, bottom - 26), (right, bottom), color, cv2.FILLED)
                    cv2.putText(frame, label, (left + 6, bottom - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
    finally:
        camera.release()
        print("[Stream] Laptop camera released.")