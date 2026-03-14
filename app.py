import os
import webbrowser
import threading
import subprocess
import re
from flask import Flask, render_template, redirect, url_for, session
from flask_socketio import emit
from dotenv import load_dotenv

# Extensions & Models
from extensions import db, socketio

# Blueprints
from blueprints.auth import auth_bp
from blueprints.admin import admin_bp
from blueprints.teacher import teacher_bp
from blueprints.student import student_bp

# Load environment variables from .env
load_dotenv()


# Global Tunnel URL
PUBLIC_URL = None

def start_public_tunnel():
    global PUBLIC_URL
    cmd = ["ssh", "-R", "80:127.0.0.1:5000", "-o", "StrictHostKeyChecking=no", "nokey@localhost.run"]
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        for line in iter(process.stdout.readline, ''):
            match = re.search(r'(https://[a-zA-Z0-9-]+\.lhr\.life|https://[a-zA-Z0-9-]+\.localhost\.run)', line)
            if match:
                PUBLIC_URL = match.group(1)
                print("\n" + "="*55)
                print(" 🚀 PUBLIC INTERNET TUNNEL READY! 🚀")
                print(" Your Phone Camera Link will use this URL automatically!")
                print(f" 👉 {PUBLIC_URL}")
                print("="*55 + "\n")
    except Exception as e:
        print(f"Background tunnel failed: {e}")

def create_app():
    app = Flask(__name__)
    
    # Expose the public URL to Jinja templates globally
    app.jinja_env.globals['get_public_url'] = lambda: PUBLIC_URL
    
    # Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-secret-key-change-me')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI', 'sqlite:///attendance.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions with app
    db.init_app(app)
    socketio.init_app(app)

    # Database Migration Helper (Fixes missing columns)
    def migrate_database(app):
        print("🔍 Checking database schema for updates...")
        with app.app_context():
            engine = db.engine
            import sqlalchemy as sa
            inspector = sa.inspect(engine)
            
            # Check User table
            user_columns = [c['name'] for c in inspector.get_columns('user')]
            with engine.connect() as conn:
                try:
                    if 'is_active' not in user_columns:
                        print("➕ Adding 'is_active' to User table...")
                        conn.execute(sa.text("ALTER TABLE user ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL"))
                    if 'registration_token' not in user_columns:
                        print("➕ Adding 'registration_token' to User table...")
                        conn.execute(sa.text("ALTER TABLE user ADD COLUMN registration_token VARCHAR(64)"))
                    if 'registration_token_expires' not in user_columns:
                        print("➕ Adding 'registration_token_expires' to User table...")
                        conn.execute(sa.text("ALTER TABLE user ADD COLUMN registration_token_expires DATETIME"))
                    
                    # Check Class table
                    class_columns = [c['name'] for c in inspector.get_columns('class')]
                    if 'is_active' not in class_columns:
                        print("➕ Adding 'is_active' to Class table...")
                        conn.execute(sa.text("ALTER TABLE class ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL"))
                    
                    conn.commit()
                    print("✅ Database schema is up to date.")
                except Exception as e:
                    print(f"⚠️ Migration warning (might be already fixed): {e}")
                    # Don't crash the app if migration fails (e.g. column already exists but inspector missed it)

    # Initialize Database and Face Recognition
    with app.app_context():
        migrate_database(app)
        db.create_all()

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(student_bp)

    # Global Routes
    @app.route('/')
    def index():
        if 'user_id' in session:
            role = session.get('user_role')
            dashboard_map = {
                'student': 'student.student_dashboard',
                'teacher': 'teacher.teacher_dashboard',
                'admin': 'admin.admin_dashboard'
            }
            return redirect(url_for(dashboard_map.get(role, 'auth.login')))
        return render_template('index.html')

    # Real-time WebSocket handlers
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

    return app

if __name__ == "__main__":
    app = create_app()
    PORT = 5000
    URL = f"http://localhost:{PORT}"

    # Auto-open browser after a short delay to let the server start first
    threading.Timer(1.5, lambda: webbrowser.open(URL)).start()

    print(f"\n{'='*45}")
    print(f"  ✅ Smart Attendance System is running!")
    print(f"  👉 Open your browser at: {URL}")
    print(f"{'='*45}\n")

    # Start the secure public SSH tunnel in the background
    threading.Thread(target=start_public_tunnel, daemon=True).start()

    # For production SSL, use a reverse proxy (e.g., nginx).
    socketio.run(
        app, 
        debug=True, 
        host='0.0.0.0', 
        port=PORT,
        use_reloader=False
    )