import sqlite3
import os

# Using absolute path confirmed by find_by_name
db_path = r'c:\Users\sanya\OneDrive\Desktop\Flask-Attendance_System\instance\attendance.db'

print(f"Opening database at: {db_path}")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    def add_column(table, column, definition):
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            print(f"   [+] Added {column} to {table}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print(f"   [-] Column {column} already exists in {table}")
            else:
                print(f"   [!] Error adding {column} to {table}: {e}")

    # Add columns to User table
    print("Migrating 'user' table...")
    add_column("user", "registration_token", "VARCHAR(64) UNIQUE")
    add_column("user", "registration_token_expires", "DATETIME")
    add_column("user", "is_active", "BOOLEAN DEFAULT 1 NOT NULL")

    # Add columns to Class table
    print("\nMigrating 'class' table...")
    add_column("class", "is_active", "BOOLEAN DEFAULT 1 NOT NULL")

    conn.commit()
    conn.close()
    print("\n[✔] Migration complete.")
except Exception as e:
    print(f"\n[✘] Migration failed: {e}")
