#!/usr/bin/env python
"""Script to reset password for zener user directly in database"""
import sqlite3
import hashlib
import os

def reset_password_db():
    """Reset password directly in SQLite database"""
    db_path = 'db.sqlite3'
    username = 'zener'
    
    if not os.path.exists(db_path):
        print(f"✗ Database file '{db_path}' not found!")
        return False
    
    # Get new password
    print(f"\nResetting password for user: {username}")
    print("="*60)
    new_password = input("Enter new password: ")
    confirm_password = input("Confirm new password: ")
    
    if new_password != confirm_password:
        print("\n✗ Passwords do not match!")
        return False
    
    if len(new_password) < 8:
        print("\n✗ Password must be at least 8 characters long!")
        return False
    
    try:
        # This is a simplified approach - Django uses PBKDF2
        # For proper Django password hashing, we need Django installed
        # But we can create the hash using Python's hashlib
        import hashlib
        import base64
        import secrets
        
        # Django uses PBKDF2 with SHA256, iterations, and salt
        # For simplicity, let's use a script that requires Django
        # Or we can use Django's password hashing if available
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute('SELECT id, username, is_superuser FROM core_user WHERE username = ?', (username,))
        user = cursor.fetchone()
        
        if not user:
            print(f"\n✗ User '{username}' not found!")
            conn.close()
            return False
        
        print(f"\nFound user: {username} (ID: {user[0]}, Superuser: {bool(user[2])})")
        print("\n⚠ Note: This script requires Django to properly hash passwords.")
        print("Please install Django and use: python manage.py changepassword zener")
        print("\nAlternatively, run the reset_password.py script which requires Django.")
        
        conn.close()
        return False
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        return False

if __name__ == '__main__':
    reset_password_db()

