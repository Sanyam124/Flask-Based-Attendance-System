# 🚀 Smart Attendance System

A professional, Flask-based attendance management system that leverages **Face Recognition** (dlib 128-D embeddings) to provide a seamless, secure, and automated experience for schools, colleges, and offices.

---

## 🌟 Key Features

- **Advanced Face Recognition**: High-accuracy recognition using the `face_recognition` library (dlib).
- **Single-Photo Registration**: Register students or staff with just a single profile picture—no complex training required.
- **Remote Phone Camera Streaming**: Use any smartphone as a wireless attendance camera via a secure, auto-generated SSH tunnel.
- **Real-Time Feedback**: Instant "toast" notifications show recognized faces during live sessions.
- **Multi-Organization Support**: Manage multiple schools or branches under a single platform.
- **Dynamic Session Handling**: Automatically calculates session numbers for multiple classes in a single day.
- **Automated CSV Reports**: Generate and export attendance summaries and daily logs with one click.
- **Intelligent Data Management**: Automatic movement of biometric data when students change classes or organizations are renamed.
- **Professional UI**: Responsive, modern dashboard with sophisticated administrative controls.

---

## 🛠️ Technology Stack

| Component | Technology |
| :--- | :--- |
| **Backend** | Python, Flask |
| **Database** | SQLAlchemy (SQLite/MySQL/PostgreSQL) |
| **AI/ML** | face_recognition, dlib, OpenCV |
| **Real-time** | Flask-SocketIO (WebSockets) |
| **Tunneling** | localhost.run (via SSH) |
| **Security** | Password Hashing (Werkzeug), Role-Based Access Control |

---

## 🔄 Project Workflow

### 1. Administration Setup
- **Super Admin**: Manages Organizations and Principals.
- **Principal**: Manages Teachers, Classes, Subjects, and Students within their institution.

### 2. Biometric Registration
- Admins upload a single, clear photo for each student.
- Systems automatically generate 128-D encodings and store them in a human-readable folder structure: `org_Name/class_Name/enrollment_username/`.

### 3. Attendance Marking
- **Teacher Dashboard**: Teachers start a session for their assigned class and subject.
- **Live Stream**: The system streams video from the laptop camera or a connected phone.
- **Face Detection**: The `attendance_logic.py` engine processes frames in real-time, matching faces against the class roster.
- **Auto-Log**: Recognized students are instantly marked 'Present' and logged in the database.

### 4. Reporting & Analytics
- Teachers and Principals can view attendance logs.
- Export detailed reports to CSV for external record-keeping.

---

## 📦 Installation & Setup

### Prerequisites
- Python 3.8+
- [dlib](https://cmake.org/download/) (required for face_recognition)

### Steps
1. **Clone the repository**:
   ```bash
   git clone https://github.com/Sanyam124/Flask-Based-Attendance-System.git
   cd Flask-Attendance_System
   ```

2. **Create a Virtual Environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables**:
   Create a `.env` file in the root directory:
   ```env
   SECRET_KEY=your_secret_key_here
   SQLALCHEMY_DATABASE_URI=sqlite:///attendance.db
   ```

5. **Run the Application**:
   ```bash
   python app.py
   ```
   The system will automatically migrate the database and open your browser at `http://localhost:5000`.

---

## 📂 Project Structure

- `app.py`: Application entry point and configuration.
- `attendance_logic.py`: Core AI engine for face recognition and streaming.
- `models.py`: Database schema and relationships.
- `utils.py`: Helper functions for slugification and data migration.
- `blueprints/`: Modular route handling (Admin, Teacher, Student, Auth, System).
- `static/`: Frontend assets (CSS, JS, registered face photos).
- `templates/`: Jinja2 HTML templates.

---

## 🤝 Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License
Distributed under the MIT License. See `LICENSE` for more information.
