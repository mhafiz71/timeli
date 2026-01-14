#!/usr/bin/env python
"""Script to reset password for zener user"""
import sys
import os

# Add the project directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'timeli.settings')

import django
django.setup()

from core.models import User
import getpass

def reset_password():
    username = 'zener'
    
    try:
        user = User.objects.get(username=username)
        print(f"\nResetting password for user: {username}")
        print(f"Current email: {user.email or 'N/A'}")
        print(f"Is superuser: {user.is_superuser}")
        print(f"Is staff: {user.is_staff}")
        
        # Get new password
        print("\n" + "="*60)
        new_password = getpass.getpass("Enter new password: ")
        confirm_password = getpass.getpass("Confirm new password: ")
        
        if new_password != confirm_password:
            print("\n✗ Passwords do not match!")
            return False
        
        if len(new_password) < 8:
            print("\n✗ Password must be at least 8 characters long!")
            return False
        
        # Set password
        user.set_password(new_password)
        user.save()
        
        print("\n✓ Password reset successfully!")
        print(f"✓ User '{username}' can now log in with the new password.")
        return True
        
    except User.DoesNotExist:
        print(f"\n✗ User '{username}' not found!")
        return False
    except Exception as e:
        print(f"\n✗ Error: {e}")
        return False

if __name__ == '__main__':
    reset_password()

