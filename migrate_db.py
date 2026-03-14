"""Run this once to add new security columns to the DB."""
from app import create_app
from extensions import db
import sqlalchemy as sa

app = create_app()
with app.app_context():
    with db.engine.connect() as conn:
        inspector = sa.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('user')]

        if 'registration_token' not in columns:
            conn.execute(sa.text('ALTER TABLE user ADD COLUMN registration_token VARCHAR(64)'))
            print('✅ Added registration_token column')
        else:
            print('ℹ️  registration_token already exists')

        if 'registration_token_expires' not in columns:
            conn.execute(sa.text('ALTER TABLE user ADD COLUMN registration_token_expires DATETIME'))
            print('✅ Added registration_token_expires column')
        else:
            print('ℹ️  registration_token_expires already exists')

        conn.commit()
    print('\n✅ DB migration complete! You can delete this file now.')
