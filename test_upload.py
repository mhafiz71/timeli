#!/usr/bin/env python3
"""
Test script to demonstrate the enhanced upload information display
"""

import requests
import json
import os

# Test data for master timetable
test_timetable = {
    "events": [
        {
            "course_code": "CS101",
            "course_title": "Introduction to Computer Science",
            "day": "Monday",
            "start_time": "09:00",
            "end_time": "10:30",
            "location": "Room A101",
            "lecturer": "Dr. Smith",
            "type": "Lecture"
        },
        {
            "course_code": "CS102",
            "course_title": "Programming Fundamentals",
            "day": "Tuesday",
            "start_time": "11:00",
            "end_time": "12:30",
            "location": "Lab B201",
            "lecturer": "Prof. Johnson",
            "type": "Lab"
        },
        {
            "course_code": "MATH201",
            "course_title": "Calculus I",
            "day": "Wednesday",
            "start_time": "14:00",
            "end_time": "15:30",
            "location": "Room C301",
            "lecturer": "Dr. Wilson",
            "type": "Lecture"
        }
    ]
}

def create_test_json():
    """Create a test JSON file for upload"""
    with open('test_master_timetable.json', 'w') as f:
        json.dump(test_timetable, f, indent=2)
    print("✅ Created test_master_timetable.json")

def create_test_pdf():
    """Create a simple test PDF with course codes"""
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        
        c = canvas.Canvas("test_course_registration.pdf", pagesize=letter)
        c.drawString(100, 750, "Course Registration Document")
        c.drawString(100, 700, "Student: Test Student")
        c.drawString(100, 650, "Courses:")
        c.drawString(120, 600, "CS101 - Introduction to Computer Science")
        c.drawString(120, 550, "CS102 - Programming Fundamentals")
        c.drawString(120, 500, "MATH201 - Calculus I")
        c.save()
        print("✅ Created test_course_registration.pdf")
    except ImportError:
        print("❌ reportlab not installed. Creating a simple text file instead.")
        with open('test_course_registration.txt', 'w') as f:
            f.write("Course Registration Document\n")
            f.write("Student: Test Student\n")
            f.write("Courses:\n")
            f.write("CS101 - Introduction to Computer Science\n")
            f.write("CS102 - Programming Fundamentals\n")
            f.write("MATH201 - Calculus I\n")
        print("✅ Created test_course_registration.txt")

if __name__ == "__main__":
    print("🧪 Creating test files for upload demonstration...")
    create_test_json()
    create_test_pdf()
    print("\n📋 Test files created successfully!")
    print("📁 Files created:")
    print("   - test_master_timetable.json (for admin upload)")
    print("   - test_course_registration.pdf/txt (for student upload)")
    print("\n💡 You can now test the enhanced upload information display by:")
    print("   1. Going to the admin dashboard and uploading the JSON file")
    print("   2. Going to the student dashboard and uploading the PDF/TXT file")
    print("   3. Observing the detailed upload information messages")
