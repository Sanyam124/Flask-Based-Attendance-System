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
from blueprints.system import system_bp

# Load environment variables from .env
load_dotenv()


# Global Tunnel URL for remote camera access
PUBLIC_URL = None

def start_public_tunnel():
    """Starts a secure public SSH tunnel in the background using localhost.run."""
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
        pass

def create_app():
    """Application factory for the Smart Attendance System."""
    app = Flask(__name__)
    
    # Expose the public URL to Jinja templates globally
    app.jinja_env.globals['get_public_url'] = lambda: PUBLIC_URL
    app.jinja_env.add_extension('jinja2.ext.do')
    
    # Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-secret-key-change-me')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI', 'sqlite:///attendance.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions with app
    db.init_app(app)
    socketio.init_app(app)

    # Database Migration Helper (Ensures schema is up to date)
    def migrate_database(app):
        engine = db.engine
        import sqlalchemy as sa
        inspector = sa.inspect(engine)
        
        with engine.connect() as conn:
            try:
                user_columns = [c['name'] for c in inspector.get_columns('user')]
                if 'is_active' not in user_columns:
                    conn.execute(sa.text("ALTER TABLE user ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL"))
                if 'registration_token' not in user_columns:
                    conn.execute(sa.text("ALTER TABLE user ADD COLUMN registration_token VARCHAR(64)"))
                if 'registration_token_expires' not in user_columns:
                    conn.execute(sa.text("ALTER TABLE user ADD COLUMN registration_token_expires DATETIME"))
                if 'organization_id' not in user_columns:
                    conn.execute(sa.text("ALTER TABLE user ADD COLUMN organization_id INTEGER REFERENCES organization(id)"))

                class_columns = [c['name'] for c in inspector.get_columns('class')]
                if 'is_active' not in class_columns:
                    conn.execute(sa.text("ALTER TABLE class ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL"))
                if 'organization_id' not in class_columns:
                    conn.execute(sa.text("ALTER TABLE class ADD COLUMN organization_id INTEGER REFERENCES organization(id)"))
                
                subject_columns = [c['name'] for c in inspector.get_columns('subject')]
                if 'organization_id' not in subject_columns:
                    conn.execute(sa.text("ALTER TABLE subject ADD COLUMN organization_id INTEGER REFERENCES organization(id)"))
                
                conn.commit()
                
                # Refine Organization and Class tables for case-insensitive uniqueness if needed
                cursor = conn.connection.cursor()
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='organization'")
                row = cursor.fetchone()
                if row and 'NOCASE' not in row[0].upper():
                    conn.execute(sa.text("PRAGMA foreign_keys = OFF"))
                    conn.execute(sa.text("ALTER TABLE organization RENAME TO organization_old"))
                    db.create_all()
                    old_cols = [c['name'] for c in sa.inspect(engine).get_columns('organization_old')]
                    cols_str = ", ".join(old_cols)
                    conn.execute(sa.text(f"INSERT INTO organization ({cols_str}) SELECT {cols_str} FROM organization_old"))
                    conn.execute(sa.text("DROP TABLE organization_old"))
                    conn.execute(sa.text("PRAGMA foreign_keys = ON"))
                    conn.commit()

                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='class'")
                row = cursor.fetchone()
                if row and 'NOCASE' not in row[0].upper():
                    conn.execute(sa.text("PRAGMA foreign_keys = OFF"))
                    conn.execute(sa.text("ALTER TABLE class RENAME TO class_old"))
                    db.create_all()
                    old_cols = [c['name'] for c in sa.inspect(engine).get_columns('class_old')]
                    cols_str = ", ".join(old_cols)
                    conn.execute(sa.text(f"INSERT INTO class ({cols_str}) SELECT {cols_str} FROM class_old"))
                    conn.execute(sa.text("DROP TABLE class_old"))
                    conn.execute(sa.text("PRAGMA foreign_keys = ON"))
                    conn.commit()

                # Refine enrollment unique constraint for cross-school reuse
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='user'")
                user_sql = cursor.fetchone()[0].upper()
                has_composite_unique = 'UNIQUE (ENROLLMENT_NUMBER, ORGANIZATION_ID)' in user_sql or 'UNIQUE ("ENROLLMENT_NUMBER", "ORGANIZATION_ID")' in user_sql
                if not has_composite_unique:
                    conn.execute(sa.text("PRAGMA foreign_keys = OFF"))
                    conn.execute(sa.text("ALTER TABLE user RENAME TO user_old"))
                    db.create_all()
                    old_cols = [c['name'] for c in sa.inspect(engine).get_columns('user_old')]
                    cols_str = ", ".join(old_cols)
                    conn.execute(sa.text(f"INSERT INTO user ({cols_str}) SELECT {cols_str} FROM user_old"))
                    conn.execute(sa.text("DROP TABLE user_old"))
                    conn.execute(sa.text("PRAGMA foreign_keys = ON"))
                    conn.commit()
            except Exception:
                pass

    # Initialize Database
    with app.app_context():
        migrate_database(app)
        db.create_all()

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(system_bp)

    @app.route('/')
    def index():
        if 'user_id' in session:
            role = session.get('user_role')
            dashboard_map = {
                'student': 'student.student_dashboard',
                'teacher': 'teacher.teacher_dashboard',
                'principal': 'admin.admin_dashboard',
                'admin': 'system.superadmin_dashboard'
            }
            return redirect(url_for(dashboard_map.get(role, 'auth.login')))
        return render_template('index.html')

    # WebSocket handlers for remote camera
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

    # Auto-open browser
    threading.Timer(1.5, lambda: webbrowser.open(URL)).start()

    print(f"\n{'='*45}")
    print(f"  ✅ Smart Attendance System is running!")
    print(f"  👉 Open your browser at: {URL}")
    print(f"{'='*45}\n")

    threading.Thread(target=start_public_tunnel, daemon=True).start()

    socketio.run(
        app, 
        debug=True, 
        host='0.0.0.0', 
        port=PORT,
        use_reloader=True
    )