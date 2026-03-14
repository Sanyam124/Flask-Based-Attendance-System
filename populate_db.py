from app import app, db
from models import User, Class, Subject, ClassTeacher
from werkzeug.security import generate_password_hash

def populate():
    with app.app_context():
        # Ensure tables exist
        db.create_all()

        # 1. Create dummy classes
        class_6b1 = Class.query.filter_by(name='6B1').first() or Class(name='6B1')
        db.session.add(class_6b1)
        db.session.flush()

        # 2. Create dummy subjects
        subject_python = Subject.query.filter_by(name='Python Programming').first() or Subject(name='Python Programming')
        db.session.add(subject_python)
        db.session.flush()

        # 3. Create Admin
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                email='admin@paruluniversity.ac.in',
                password=generate_password_hash('admin123'),
                role='admin'
            )
            db.session.add(admin)

        # 4. Create Teacher
        teacher = User.query.filter_by(username='teacher1').first()
        if not teacher:
            teacher = User(
                username='teacher1',
                email='teacher1@paruluniversity.ac.in',
                password=generate_password_hash('teacher123'),
                role='teacher'
            )
            db.session.add(teacher)
            db.session.flush()

            # Associate teacher with class and subject
            assoc = ClassTeacher(teacher_id=teacher.id, class_id=class_6b1.id, subject_id=subject_python.id)
            db.session.add(assoc)

        # 5. Create Student
        if not User.query.filter_by(username='student1').first():
            student = User(
                username='student1',
                email='student1@paruluniversity.ac.in',
                password=generate_password_hash('student123'),
                role='student',
                enrollment_number='PU12345',
                class_id=class_6b1.id
            )
            db.session.add(student)

        db.session.commit()
        print("Database populated with dummy data successfully!")

if __name__ == "__main__":
    populate()
