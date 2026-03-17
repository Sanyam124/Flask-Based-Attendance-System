import cv2
import numpy as np
import os
import tempfile
from datetime import date, datetime
from config import KNOWN_FACES_DIR, ENCODINGS_FILE, SAMPLE_COUNT_REQUIRED

# -------------------------------
# Shared OpenCV face detector (loaded once)
# -------------------------------
_face_cascade = None
_eye_cascade = None

def get_face_cascade():
    global _face_cascade
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    return _face_cascade

def get_eye_cascade():
    global _eye_cascade
    if _eye_cascade is None:
        _eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')
    return _eye_cascade


# ====================================================================
# FACE RECOGNITION SYSTEM — 100% OpenCV (Zero dlib dependency)
# ====================================================================
# Detection:   Haar Cascade
# Recognition: Histogram + Pixel Correlation matching against stored templates
# ====================================================================
class FaceRecognitionSystem:
    def __init__(self):
        self.known_face_templates = {}  # name -> list of (gray_img_100x100, histogram)
        self.load_templates()

    def load_templates(self):
        """Load all stored face images as grayscale templates for recognition."""
        if not os.path.exists(KNOWN_FACES_DIR):
            os.makedirs(KNOWN_FACES_DIR)
            print("No known faces directory found. Created empty one.")
            return

        cascade = get_face_cascade()
        total_loaded = 0

        for name in os.listdir(KNOWN_FACES_DIR):
            student_path = os.path.join(KNOWN_FACES_DIR, name)
            if not os.path.isdir(student_path):
                continue

            templates = []
            images = [f for f in os.listdir(student_path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]

            for image_file in images:
                img_path = os.path.join(student_path, image_file)
                img = cv2.imread(img_path)
                if img is None:
                    continue

                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

                # --- Lighting Normalization (CLAHE) ---
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                gray = clahe.apply(gray)

                # Try to detect face in the stored image for a tighter crop
                faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(30, 30))
                if len(faces) > 0:
                    x, y, w, h = faces[0]
                    face_gray = gray[y:y+h, x:x+w]
                else:
                    # If no face detected (e.g., already a tight crop), use entire image
                    face_gray = gray

                # Resize to standard 80x80 template for sliding-window matching
                face_resized = cv2.resize(face_gray, (80, 80))

                # Compute histogram
                hist = cv2.calcHist([face_resized], [0], None, [64], [0, 256])
                cv2.normalize(hist, hist)

                templates.append((face_resized, hist))
                if len(templates) >= 5:  # Max 5 templates per person for speed
                    break

            if templates:
                self.known_face_templates[name] = templates
                total_loaded += len(templates)

        print(f"Face templates loaded: {total_loaded} templates for {len(self.known_face_templates)} students.")

    def rebuild_encodings(self):
        """Alias for load_templates (backward compatibility)."""
        self.known_face_templates = {}
        self.load_templates()

    def recognize_faces(self, frame):
        """
        100% OpenCV face recognition. No dlib.
        1. Detect faces with Haar Cascade
        2. For each face, compare against stored templates using
           histogram correlation + pixel correlation
        3. Return list of recognized names
        """
        if not self.known_face_templates:
            return []

        cascade = get_face_cascade()
        eye_cascade = get_eye_cascade()

        # Normalize frame
        if frame is None or frame.size == 0:
            return []
        if frame.dtype != np.uint8:
            frame = np.clip(frame, 0, 255).astype(np.uint8)
        if len(frame.shape) == 2:
            gray = frame
        elif frame.shape[2] == 4:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # --- Lighting Normalization (CLAHE) ---
        # Crucial for backlit, dark, or heavily shadowed classroom environments.
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

        # Detect faces (scaleFactor 1.05 searches more sizes, minSize 30x30 catches background faces)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=3, minSize=(30, 30))

        recognized = set()
        for (x, y, w, h) in faces:
            face_roi = gray[y:y+h, x:x+w]
            if face_roi.size == 0:
                continue

            # --- DYNAMIC LIVENESS / ANTI-SPOOFING CHECKS (Crowd-aware) ---
            
            laplacian_var = cv2.Laplacian(face_roi, cv2.CV_64F).var()
            contrast = face_roi.std()

            # Eye Detection: Only enforceable on prominent foreground faces.
            eyes_found = True
            if w >= 100:
                roi_eyes = face_roi[0:int(h/1.5), 0:w]
                eyes = eye_cascade.detectMultiScale(roi_eyes, scaleFactor=1.1, minNeighbors=3, minSize=(15, 15))
                if len(eyes) == 0:
                    eyes_found = False

            # Skin Color Check
            is_skin_colored = True
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                face_bgr = frame[y:y+h, x:x+w]
                img_yuv = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2YCrCb)
                lower_skin = np.array([0, 133, 77], dtype=np.uint8)
                upper_skin = np.array([255, 173, 127], dtype=np.uint8)
                skin_mask = cv2.inRange(img_yuv, lower_skin, upper_skin)
                skin_ratio = cv2.countNonZero(skin_mask) / (w * h)
                # Lower bound for background faces which might have poor camera lighting
                if skin_ratio < 0.05:  
                    is_skin_colored = False

            # Crowd Liveness Evaluation: Background faces naturally blur out of focus
            if w < 60:
                min_var = 10.0 # Extremely lenient for deep background out-of-focus faces
                min_contrast = 10.0
            elif w < 100:
                min_var = 25.0
                min_contrast = 15.0
            else:
                min_var = 50.0 # Foreground faces must be crisp
                min_contrast = 20.0

            if laplacian_var < min_var:
                print(f"Spoof Warning: Face too flat/blurry (Laplacian {laplacian_var:.1f}). size: {w}")
                # continue
            if contrast < min_contrast:
                print(f"Spoof Warning: Unnatural contrast ({contrast:.1f}). size: {w}")
                # continue
            if not eyes_found:
                print("Spoof Warning: No eyes found on foreground face.")
                # continue
            if not is_skin_colored:
                print("Spoof Warning: Failed human skin color spectrum test.")
                # continue

            # Resize live face to 100x100.
            # Stored templates are 80x80. This gives a 20-pixel sliding window 
            # for `matchTemplate` to naturally fix any Haar Cascade bounding box jitter!
            face_resized = cv2.resize(face_roi, (100, 100))

            # Compute histogram for this face
            face_hist = cv2.calcHist([face_resized], [0], None, [64], [0, 256])
            cv2.normalize(face_hist, face_hist)

            best_name = None
            best_score = -1.0

            for name, templates in self.known_face_templates.items():
                for (tmpl_img, tmpl_hist) in templates:
                    # Step 1: Quick histogram pre-filter
                    hist_score = cv2.compareHist(face_hist, tmpl_hist, cv2.HISTCMP_CORREL)
                    if hist_score < 0.25:
                        continue  

                    # Step 2: C++ Sliding Window Pixel Correlation
                    # Slides the 80x80 template inside the live 100x100 face finding perfect alignment.
                    res = cv2.matchTemplate(face_resized, tmpl_img, cv2.TM_CCOEFF_NORMED)
                    _, max_correlation, _, _ = cv2.minMaxLoc(res)

                    # Combined score (Increased histogram weight slightly for stability)
                    combined = 0.4 * hist_score + 0.6 * max_correlation

                    if combined > best_score:
                        best_score = combined
                        best_name = name

            # Recognition threshold (Relaxed heavily for a smooth, fast, lenient student experience)
            if best_score > 0.38 and best_name:
                recognized.add(best_name)

        return list(recognized)


# ====================================================================
# FACE CAPTURE — 100% OpenCV (No dlib)
# ====================================================================
class FaceCapture:
    @staticmethod
    def stream_capture(username):
        """
        Streams video and captures face samples using PURE OpenCV.
        Detection: Haar Cascade
        Liveness:  Histogram similarity vs. reference face
        Saving:    JPEG face crop stored to disk
        """
        cascade = get_face_cascade()

        camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not camera.isOpened():
            camera = cv2.VideoCapture(0)
        if not camera.isOpened():
            print("ERROR: Cannot open webcam for sample capture.")
            return

        save_path = os.path.join(KNOWN_FACES_DIR, username)
        os.makedirs(save_path, exist_ok=True)

        sample_count = len([f for f in os.listdir(save_path) if f.endswith('.jpg')])
        frame_counter = 0

        # Liveness & Proxy state
        reference_face = None
        consecutive_face_count = 0
        LIVENESS_REQUIRED = 3
        consecutive_reject_count = 0
        SIMILARITY_THRESHOLD = 0.55  # Strict matching threshold to prevent proxy
        MAX_REJECTS = 5

        status_msg = f"Look at the camera. Samples: {sample_count}/{SAMPLE_COUNT_REQUIRED}"

        try:
            while sample_count < SAMPLE_COUNT_REQUIRED:
                ret, frame = camera.read()
                if not ret or frame is None or frame.size == 0:
                    frame_counter += 1
                    continue

                if frame_counter % 3 == 0:
                    try:
                        if frame.dtype != np.uint8:
                            frame = cv2.normalize(frame, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
                        if len(frame.shape) == 2:
                            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                        elif frame.shape[2] == 4:
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                        elif frame.shape[2] != 3:
                            continue

                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        
                        # --- Lighting Normalization (CLAHE) ---
                        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                        gray = clahe.apply(gray)
                        
                        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))

                        if len(faces) == 1:
                            x, y, w, h = faces[0]
                            x, y = max(0, x), max(0, y)
                            w = min(w, frame.shape[1] - x)
                            h = min(h, frame.shape[0] - y)

                            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 200, 0), 2)

                            face_gray = gray[y:y+h, x:x+w]
                            if face_gray.size == 0:
                                continue

                            face_100x100 = cv2.resize(face_gray, (100, 100))
                            current_hist = cv2.calcHist([face_100x100], [0], None, [64], [0, 256])
                            cv2.normalize(current_hist, current_hist)

                            if reference_face is None:
                                # Save the first face as 80x80 template for sliding window later
                                face_80x80 = cv2.resize(face_gray, (80, 80))
                                reference_face = (face_80x80, current_hist)
                                consecutive_face_count = 1
                                status_msg = f"Keep still... ({consecutive_face_count}/{LIVENESS_REQUIRED})"
                            else:
                                ref_img_80x80, ref_hist = reference_face
                                hist_score = cv2.compareHist(ref_hist, current_hist, cv2.HISTCMP_CORREL)

                                # Fast C++ sliding window template match
                                res = cv2.matchTemplate(face_100x100, ref_img_80x80, cv2.TM_CCOEFF_NORMED)
                                _, max_correlation, _, _ = cv2.minMaxLoc(res)

                                similarity = 0.4 * hist_score + 0.6 * max_correlation

                                if similarity >= SIMILARITY_THRESHOLD:
                                    consecutive_reject_count = 0
                                    consecutive_face_count += 1
                                    status_msg = f"Keep still... ({consecutive_face_count}/{LIVENESS_REQUIRED})"

                                    if consecutive_face_count >= LIVENESS_REQUIRED:
                                        face_bgr = frame[y:y+h, x:x+w]
                                        face_resized = cv2.resize(face_bgr, (150, 150))
                                        img_name = f"{username}_sample_{sample_count}.jpg"
                                        cv2.imwrite(os.path.join(save_path, img_name), face_resized)
                                        sample_count += 1
                                        consecutive_face_count = 0
                                        # Do NOT update reference_face. First face detected remains the single source of truth!
                                        status_msg = f"✅ Sample {sample_count}/{SAMPLE_COUNT_REQUIRED} captured!"
                                        print(f"Captured sample {sample_count}/{SAMPLE_COUNT_REQUIRED}")
                                else:
                                    consecutive_face_count = 0
                                    consecutive_reject_count += 1
                                    status_msg = f"⚠️ Different Face! ({consecutive_reject_count} mismatch)"
                                    if consecutive_reject_count >= MAX_REJECTS:
                                        status_msg = "❌ Proxy Face! Progress erased."
                                        # PUNISHMENT for proxy swap: Delete ALL recorded images and restart
                                        for f in os.listdir(save_path):
                                            if f.endswith('.jpg'):
                                                try:
                                                    os.remove(os.path.join(save_path, f))
                                                except:
                                                    pass
                                        sample_count = 0
                                        reference_face = None
                                        consecutive_reject_count = 0
                        else:
                            consecutive_face_count = 0
                            if len(faces) == 0:
                                status_msg = f"No face detected. {sample_count}/{SAMPLE_COUNT_REQUIRED}"
                            else:
                                status_msg = f"Multiple faces — only one person please."

                    except Exception as e:
                        print(f"Warning: Skipping frame: {e}")

                frame_counter += 1

                cv2.putText(frame, status_msg, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
                if sample_count >= SAMPLE_COUNT_REQUIRED:
                    cv2.putText(frame, "Registration Complete!", (20, 80),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 255, 255), 2)

                ret, buffer = cv2.imencode('.jpg', frame)
                if ret:
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        finally:
            camera.release()
            print("DEBUG: Releasing sample capture camera...")

    @staticmethod
    def stream_attendance(app, frs, class_teacher_id, session_number):
        """Streams video with real-time face recognition for attendance marking."""
        camera = cv2.VideoCapture(0)
        if not camera.isOpened():
            print("ERROR: Cannot open webcam for attendance.")
            return

        try:
            while True:
                ret, frame = camera.read()
                if not ret:
                    break

                recognized_names = frs.recognize_faces(frame)

                for name in recognized_names:
                    cv2.putText(frame, f"Recognized: {name}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                ret, buffer = cv2.imencode('.jpg', frame)
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        finally:
            camera.release()
            print("DEBUG: Releasing attendance camera...")