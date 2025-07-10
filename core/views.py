# core/views.py
import re
import json
from io import BytesIO
from datetime import time as dt_time, datetime

import pdfplumber
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.template.loader import get_template
from django.views import View
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from django.db import transaction
from xhtml2pdf import pisa
from PIL import Image, ImageDraw, ImageFont
import base64

from .forms import TimetableSourceForm, CustomUserCreationForm, UserProfileForm
from .models import TimetableSource, TimetableEvent, CourseRegistrationHistory

# Simple class to convert dictionary to object for template access


class EventObject:
    def __init__(self, event_dict):
        for key, value in event_dict.items():
            setattr(self, key, value)


# Custom Login View that redirects authenticated users
class CustomLoginView(LoginView):
    template_name = 'core/login.html'

    def dispatch(self, request, *args, **kwargs):
        # If user is already authenticated, redirect to student dashboard
        if request.user.is_authenticated:
            return redirect('student_dashboard')
        return super().dispatch(request, *args, **kwargs)


# Custom Signup View
class SignupView(View):
    template_name = 'core/signup.html'
    form_class = CustomUserCreationForm

    def dispatch(self, request, *args, **kwargs):
        # If user is already authenticated, redirect to student dashboard
        if request.user.is_authenticated:
            return redirect('student_dashboard')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        form = self.form_class()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = self.form_class(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(
                request, 'Account created successfully! You can now log in.')
            return redirect('login')
        return render(request, self.template_name, {'form': form})


# User Profile View
class UserProfileView(LoginRequiredMixin, View):
    template_name = 'core/profile.html'
    form_class = UserProfileForm

    def get(self, request):
        form = self.form_class(instance=request.user)
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = self.form_class(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('profile')
        return render(request, self.template_name, {'form': form})

# --- HELPER 1: For parsing time like "7:00a - 9:55a" ---


def parse_time_range(time_str):
    try:
        start_str, end_str = time_str.split(' - ')

        # Handle both "7:00a" and "7:00AM" formats
        # Convert single letter suffixes to full AM/PM
        if start_str.endswith('a'):
            start_str = start_str[:-1] + 'AM'
        elif start_str.endswith('p'):
            start_str = start_str[:-1] + 'PM'

        if end_str.endswith('a'):
            end_str = end_str[:-1] + 'AM'
        elif end_str.endswith('p'):
            end_str = end_str[:-1] + 'PM'

        start_time = datetime.strptime(start_str, '%I:%M%p').time()
        end_time = datetime.strptime(end_str, '%I:%M%p').time()
        return start_time, end_time
    except (ValueError, AttributeError):
        return None, None

# --- HELPER 2 (FIXED): Robust parser for course strings ---


def parse_course_string(course_str):
    """
    Finds a course code like 'ACT 404' or 'ENV324' within a larger string,
    and returns the display version, a normalized version, and the details.
    """
    # This regex finds "3-4 letters, optional space, 3 digits"
    # Made more flexible to handle various formats
    match = re.search(r'([A-Z]{3,4})\s?(\d{3})', course_str.upper())
    if match:
        dept_code = match.group(1)  # e.g., "ACT"
        course_num = match.group(2)  # e.g., "404"

        # Create both display and normalized versions
        display_code = f"{dept_code} {course_num}"  # e.g., "ACT 404"
        normalized_code = f"{dept_code} {course_num}"  # e.g., "ACT404"

        # Extract details (everything after the course code)
        details = course_str[match.end():].strip()  # e.g., "Lec 1"

        return display_code, normalized_code, details

    # Fallback if no standard code is found
    return course_str, course_str.replace(' ', ''), ''

# --- HELPER 3 (NEW): Normalize course codes consistently ---


def normalize_course_code(code_str):
    """
    Normalizes course codes to a consistent format for matching.
    Handles various input formats like 'ACT 404', 'ACT404', 'act 404', etc.
    """
    if not code_str:
        return ""

    # Clean the string
    clean_code = code_str.strip().upper()

    # Try to match the pattern
    match = re.search(r'([A-Z]{3,4})\s?(\d{3})', clean_code)
    if match:
        dept_code = match.group(1)
        course_num = match.group(2)
        return f"{dept_code} {course_num}"  # Always return without spaces

    # If no match, return the cleaned version
    return clean_code.replace(' ', '')

# --- UPDATED: The JSON parser now uses the improved helpers ---


def parse_and_store_master_timetable(source):
    """Parses a master timetable JSON and stores events in database."""
    try:
        # Check if already parsed
        if source.events_parsed and source.events.exists():
            print(f"Source {source.id} already parsed, skipping...")
            return True

        # Check if the file exists before trying to open it
        if not source.source_json or not source.source_json.path:
            print(f"Error: No JSON file associated with source {source.id}")
            source.status = TimetableSource.FAILED
            source.save()
            return False

        # Check if the file exists on the filesystem
        import os
        if not os.path.exists(source.source_json.path):
            print(
                f"Error: JSON file not found at {source.source_json.path} for source {source.id}")
            source.status = TimetableSource.FAILED
            source.save()
            return False

        with transaction.atomic():
            # Clear existing events for this source
            source.events.all().delete()

            with open(source.source_json.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                events_created = 0

                # Check if this is an exam timetable format
                if source.timetable_type == 'exam' and isinstance(data, dict) and 'schedule' in data:
                    events_created = parse_exam_timetable(source, data)
                else:
                    # Parse as teaching timetable (original format)
                    events_created = parse_teaching_timetable(source, data)

                # Update source status
                source.status = TimetableSource.COMPLETED
                source.events_parsed = True
                source.total_events = events_created
                source.save()

                print(
                    f"Successfully parsed and stored {events_created} events for source {source.id}")
                return True

    except Exception as e:
        print(f"Error parsing master timetable for source {source.id}: {e}")
        source.status = TimetableSource.FAILED
        source.save()
        return False


def parse_exam_timetable(source, data):
    """Parse exam timetable format and create events."""
    events_created = 0

    for week_data in data.get('schedule', []):
        for day_data in week_data.get('days', []):
            day = day_data.get('day', '').title()
            date = day_data.get('date', '')

            for session in day_data.get('sessions', []):
                time = session.get('time', '')

                # Parse time (e.g., "9:00am" -> start and end times)
                start_time, end_time = parse_exam_time(time)
                if not start_time or not end_time:
                    continue

                for exam in session.get('exams', []):
                    level = exam.get('level', '')
                    courses = exam.get('courses', [])

                    for course_code in courses:
                        if course_code.strip():
                            # Create event for each course
                            TimetableEvent.objects.create(
                                source=source,
                                day=day,
                                start_time=start_time,
                                end_time=end_time,
                                location="",  # Venue not specified in exam format
                                course_code=course_code.strip(),
                                normalized_code=normalize_course_code(
                                    course_code.strip()),
                                details=f"Level: {level}, Date: {date}",
                                lecturer="",  # No lecturer for exams
                            )
                            events_created += 1

    return events_created


def parse_teaching_timetable(source, data):
    """Parse teaching timetable format (original format)."""
    events_created = 0

    for item in data:
        start_time, end_time = parse_time_range(item.get("Time"))
        display_code, normalized_code, details = parse_course_string(
            item.get("Course", ""))

        if not all([start_time, end_time, display_code]):
            continue

        TimetableEvent.objects.create(
            source=source,
            day=item.get("Day", "").title(),
            start_time=start_time,
            end_time=end_time,
            location=item.get("Venue", ""),
            course_code=display_code,
            normalized_code=normalized_code,
            details=details,
            lecturer=item.get("Instructor(s)", ""),
        )
        events_created += 1

    return events_created


def parse_exam_time(time_str):
    """Parse exam time format like '9:00am' and create start/end times."""
    try:
        from datetime import datetime, timedelta

        # Clean the time string
        time_str = time_str.strip().lower()

        # Parse the time
        if 'am' in time_str or 'pm' in time_str:
            # Handle formats like "9:00am", "2:00pm"
            time_obj = datetime.strptime(time_str, '%I:%M%p').time()

            # Assume exam duration is 3 hours
            start_datetime = datetime.combine(datetime.today(), time_obj)
            end_datetime = start_datetime + timedelta(hours=3)

            return time_obj, end_datetime.time()

        return None, None
    except (ValueError, AttributeError):
        return None, None


def parse_master_timetable(source):
    """Legacy function - returns events as dictionaries for backward compatibility."""
    events = []
    try:
        # Try to get from database first
        if source.events_parsed and source.events.exists():
            for event in source.events.all():
                events.append({
                    'day': event.day,
                    'start_time': event.start_time,
                    'end_time': event.end_time,
                    'location': event.location,
                    'course_code': event.course_code,
                    'normalized_code': event.normalized_code,
                    'details': event.details,
                    'lecturer': event.lecturer,
                })
            return events

        # If not in database, parse and store
        if parse_and_store_master_timetable(source):
            # Recursive call to get from DB
            return parse_master_timetable(source)

    except Exception as e:
        print(f"Error retrieving events for source {source.id}: {e}")

    return events

# get_master_schedule_data uses the cache for performance


def get_master_schedule_data(source_id):
    """Retrieves master schedule, using cache or database storage with improved fallback."""
    cache_key = f'master_schedule_{source_id}'
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    try:
        source = TimetableSource.objects.get(id=source_id)

        # Try to get from database first (faster than parsing JSON)
        if source.events_parsed and source.events.exists():
            schedule_data = []
            for event in source.events.all():
                schedule_data.append({
                    'day': event.day,
                    'start_time': event.start_time,
                    'end_time': event.end_time,
                    'location': event.location,
                    'course_code': event.course_code,
                    'normalized_code': event.normalized_code,
                    'details': event.details,
                    'lecturer': event.lecturer,
                })

            # Cache for 24 hours (extended from 1 hour)
            if schedule_data:
                cache.set(cache_key, schedule_data, 86400)
            return schedule_data

        # If not in database, parse and store
        if parse_and_store_master_timetable(source):
            # Recursive call to get from database
            return get_master_schedule_data(source_id)

        # Final fallback - try legacy parsing
        schedule_data = parse_master_timetable(source)
        if schedule_data:
            cache.set(cache_key, schedule_data, 86400)  # Cache for 24 hours
        return schedule_data

    except TimetableSource.DoesNotExist:
        print(f"Error: TimetableSource with id {source_id} does not exist")
        return []
    except Exception as e:
        print(
            f"Error retrieving master schedule data for source {source_id}: {e}")
        return []

# AdminDashboardView has no major changes


class AdminDashboardView(LoginRequiredMixin, View):
    def get(self, request):
        form = TimetableSourceForm()
        timetables = TimetableSource.objects.all().order_by('-created_at')
        edit_id = request.GET.get('edit')
        edit_form = None

        if edit_id:
            try:
                edit_timetable = TimetableSource.objects.get(id=edit_id)
                edit_form = TimetableSourceForm(instance=edit_timetable)
            except TimetableSource.DoesNotExist:
                messages.error(request, 'Timetable not found.')

        return render(request, 'core/admin_dashboard.html', {
            'form': form,
            'timetables': timetables,
            'edit_form': edit_form,
            'edit_id': edit_id
        })

    def post(self, request):
        # Handle edit form submission
        if 'edit_id' in request.POST:
            edit_id = request.POST.get('edit_id')
            try:
                timetable_source = TimetableSource.objects.get(id=edit_id)
                edit_form = TimetableSourceForm(
                    request.POST, request.FILES, instance=timetable_source)

                if edit_form.is_valid():
                    # Check if JSON file was updated
                    json_updated = 'source_json' in request.FILES

                    edit_form.save()

                    # If JSON file was updated, reparse events
                    if json_updated:
                        # Delete existing events
                        TimetableEvent.objects.filter(
                            source=timetable_source).delete()
                        timetable_source.events_parsed = False
                        timetable_source.total_events = 0
                        timetable_source.status = TimetableSource.PROCESSING
                        timetable_source.save()

                        # Parse new events
                        try:
                            if parse_and_store_master_timetable(timetable_source):
                                # Get file size for display
                                file_size = timetable_source.source_json.size
                                file_size_mb = round(
                                    file_size / (1024 * 1024), 2)

                                messages.success(
                                    request,
                                    f"🔄 Timetable Updated Successfully!\n"
                                    f"📋 Name: {timetable_source.display_name}\n"
                                    f"📅 Academic Year: {timetable_source.academic_year}\n"
                                    f"📚 Semester: {timetable_source.semester}\n"
                                    f"🏷️ Type: {timetable_source.get_timetable_type_display()}\n"
                                    f"📄 New File Size: {file_size_mb} MB\n"
                                    f"📊 Events Reprocessed: {timetable_source.total_events}\n"
                                    f"⏰ Updated: {timetable_source.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
                                )
                            else:
                                messages.warning(
                                    request,
                                    f"⚠️ Update Warning!\n"
                                    f"📋 File: {timetable_source.display_name}\n"
                                    f"❌ Status: Reprocessing failed\n"
                                    f"💡 Suggestion: Please check the JSON format and try again."
                                )
                        except Exception as e:
                            messages.error(
                                request,
                                f"❌ Update Error!\n"
                                f"📋 File: {timetable_source.display_name}\n"
                                f"🚫 Error: {str(e)}\n"
                                f"💡 Suggestion: Verify JSON structure and file integrity."
                            )
                    else:
                        messages.success(
                            request,
                            f"✅ Timetable Details Updated!\n"
                            f"📋 Name: {timetable_source.display_name}\n"
                            f"📅 Academic Year: {timetable_source.academic_year}\n"
                            f"📚 Semester: {timetable_source.semester}\n"
                            f"🏷️ Type: {timetable_source.get_timetable_type_display()}\n"
                            f"📊 Events: {timetable_source.total_events} (unchanged)\n"
                            f"⏰ Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        )

                    return redirect('admin_dashboard')
                else:
                    # Return to edit mode with errors
                    form = TimetableSourceForm()
                    timetables = TimetableSource.objects.all().order_by('-created_at')
                    return render(request, 'core/admin_dashboard.html', {
                        'form': form,
                        'timetables': timetables,
                        'edit_form': edit_form,
                        'edit_id': edit_id
                    })
            except TimetableSource.DoesNotExist:
                messages.error(request, 'Timetable not found.')
                return redirect('admin_dashboard')

        # Handle new upload form submission
        else:
            form = TimetableSourceForm(request.POST, request.FILES)
            if form.is_valid():
                timetable_source = form.save(commit=False)
                timetable_source.uploader = request.user
                timetable_source.save()

                # Parse and store events immediately after upload
                try:
                    if parse_and_store_master_timetable(timetable_source):
                        # Get file size for display
                        file_size = timetable_source.source_json.size
                        file_size_mb = round(file_size / (1024 * 1024), 2)

                        messages.success(
                            request,
                            f"✅ Master Timetable Upload Successful!\n"
                            f"📋 Name: {timetable_source.display_name}\n"
                            f"📅 Academic Year: {timetable_source.academic_year}\n"
                            f"📚 Semester: {timetable_source.semester}\n"
                            f"🏷️ Type: {timetable_source.get_timetable_type_display()}\n"
                            f"📄 File Size: {file_size_mb} MB\n"
                            f"📊 Events Processed: {timetable_source.total_events}\n"
                            f"⏰ Upload Time: {timetable_source.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                    else:
                        messages.warning(
                            request,
                            f"⚠️ Upload Warning!\n"
                            f"📋 File: {timetable_source.display_name}\n"
                            f"❌ Status: Processing failed\n"
                            f"💡 Suggestion: Please check the JSON format and try again."
                        )
                except Exception as e:
                    messages.error(
                        request,
                        f"❌ Upload Error!\n"
                        f"📋 File: {timetable_source.display_name}\n"
                        f"🚫 Error: {str(e)}\n"
                        f"💡 Suggestion: Verify JSON structure and file integrity."
                    )

                return redirect('admin_dashboard')

        timetables = TimetableSource.objects.all().order_by('-created_at')
        return render(request, 'core/admin_dashboard.html', {'form': form, 'timetables': timetables})


@login_required
def delete_timetable_source(request, source_id):
    """Delete a master timetable source and all its events."""
    if request.method == 'POST':
        try:
            source = TimetableSource.objects.get(
                id=source_id, uploader=request.user)
            source_name = source.display_name

            # Clear cache for this source
            cache_key = f'master_schedule_{source_id}'
            cache.delete(cache_key)

            # Delete the source (this will cascade delete events)
            source.delete()

            messages.success(
                request, f"'{source_name}' has been deleted successfully.")
            return JsonResponse({'success': True, 'message': f"'{source_name}' deleted successfully."})

        except TimetableSource.DoesNotExist:
            messages.error(
                request, "Timetable not found or you don't have permission to delete it.")
            return JsonResponse({'success': False, 'message': 'Timetable not found or permission denied.'})
        except Exception as e:
            messages.error(request, f"Error deleting timetable: {str(e)}")
            return JsonResponse({'success': False, 'message': f'Error: {str(e)}'})

    return JsonResponse({'success': False, 'message': 'Invalid request method.'})


def save_course_registration_history(user, source, course_codes, display_name=None, program=None, level=None):
    """Save course registration to history for reuse."""
    try:
        # Create display name if not provided
        if not display_name:
            program_part = f"{program} " if program else ""
            level_part = f"({level}) " if level else ""
            display_name = f"{program_part}{level_part}- {source.display_name} - {len(course_codes)} courses"

        # Check if similar history exists and update it
        existing = CourseRegistrationHistory.objects.filter(
            user=user,
            source=source,
            course_codes=json.dumps(sorted(course_codes))
        ).first()

        if existing:
            existing.last_used = datetime.now()
            existing.display_name = display_name
            if program:
                existing.program = program
            if level:
                existing.level = level
            existing.save()
            return existing
        else:
            # Create new history entry
            history = CourseRegistrationHistory.objects.create(
                user=user,
                source=source,
                course_codes=json.dumps(sorted(course_codes)),
                display_name=display_name,
                program=program,
                level=level
            )
            return history
    except Exception as e:
        print(f"Error saving course registration history: {e}")
        return None


# --- UPDATED: TimetableGeneratorView - Works for both authenticated and anonymous users ---
class TimetableGeneratorView(View):
    def get(self, request):
        sources = TimetableSource.objects.filter(
            status=TimetableSource.COMPLETED
        ).order_by('-created_at')

        # Get user's course registration history only if authenticated
        history = []
        if request.user.is_authenticated:
            history = CourseRegistrationHistory.objects.filter(
                user=request.user).order_by('-last_used')[:5]

        # Get selected source if provided
        selected_source_id = request.GET.get('source')
        selected_source = None
        if selected_source_id:
            try:
                selected_source = TimetableSource.objects.get(
                    id=selected_source_id,
                    status=TimetableSource.COMPLETED
                )
            except TimetableSource.DoesNotExist:
                messages.error(request, 'Selected timetable source not found.')

        return render(request, 'core/timetable_generator.html', {
            'sources': sources,
            'history': history,
            'selected_source': selected_source,
            'is_authenticated': request.user.is_authenticated
        })

    def post(self, request):
        sources = TimetableSource.objects.filter(
            status=TimetableSource.COMPLETED
        ).order_by('-created_at')

        # Handle both PDF upload and manual course code input
        source_id = request.POST.get(
            'timetable_source') or request.POST.get('source_id')
        course_reg_pdf = request.FILES.get('course_reg_pdf')
        course_codes_input = request.POST.get('course_codes', '').strip()
        program = request.POST.get('program', '').strip()
        level = request.POST.get('level', '').strip()

        if not source_id:
            messages.error(request, 'Please select a timetable source.')
            return self.get(request)

        # Require either PDF upload or manual course codes
        if not course_reg_pdf and not course_codes_input:
            messages.error(
                request, 'Please either upload your course registration PDF or enter course codes manually.')
            return self.get(request)

        student_course_codes = set()
        raw_extracted_codes = []  # For debugging

        # Handle manual course code input
        if course_codes_input:
            # Split by common delimiters and clean up
            raw_codes = re.split(r'[,\n\r\s]+', course_codes_input.strip())
            for code in raw_codes:
                if code.strip():
                    raw_extracted_codes.append(code.strip())
                    normalized = normalize_course_code(code.strip())
                    if normalized:
                        student_course_codes.add(normalized)

        # Handle PDF upload
        elif course_reg_pdf:
            try:
                with pdfplumber.open(course_reg_pdf) as pdf:
                    for page in pdf.pages:
                        # Try table extraction first
                        table = page.extract_table()
                        if table:
                            for row in table[1:]:  # Skip header
                                if row and len(row) > 1 and row[1]:
                                    course_code = row[1].strip()
                                    raw_extracted_codes.append(course_code)
                                    normalized = normalize_course_code(
                                        course_code)
                                    if normalized:
                                        student_course_codes.add(normalized)

                        # Also try text extraction as backup
                        text = page.extract_text()
                        if text:
                            # Find course codes in text using regex
                            course_matches = re.findall(
                                r'([A-Z]{3,4})\s?(\d{3})', text.upper())
                            for match in course_matches:
                                course_code = f"{match[0]} {match[1]}"
                                raw_extracted_codes.append(course_code)
                                normalized = normalize_course_code(course_code)
                                if normalized:
                                    student_course_codes.add(normalized)

            except Exception as e:
                messages.error(
                    request, f'Could not process your PDF. Error: {e}')
                return self.get(request)

        if not student_course_codes:
            messages.warning(
                request, 'No course codes found in your PDF. Please check if the file contains a valid course registration.')
            return render(request, 'core/student_dashboard.html', {'sources': sources})

        master_schedule = get_master_schedule_data(source_id)

        # Check if master schedule data is available
        if not master_schedule:
            messages.error(
                request, 'The selected timetable source is not available or the file is missing. Please <a href="mailto:abdulnasirmhafiz567@gmail.com" class="text-blue-400 hover:text-blue-300 underline">contact the administrator</a> or try a different timetable source.', extra_tags='safe')
            return render(request, 'core/student_dashboard.html', {'sources': sources})

        # Filter matching events
        student_events = []
        for event in master_schedule:
            event_code = event.get('normalized_code')
            if event_code in student_course_codes:
                student_events.append(event)

        days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        # Sort events by start time within each day
        schedule = {
            day: sorted([e for e in student_events if e['day']
                        == day], key=lambda x: x['start_time'])
            for day in days_of_week
        }

        # Save course registration history for reuse (only for authenticated users)
        if request.user.is_authenticated:
            try:
                source = TimetableSource.objects.get(id=source_id)
                save_course_registration_history(
                    user=request.user,
                    source=source,
                    course_codes=list(student_course_codes),
                    program=program or None,
                    level=level or None
                )


            except Exception as e:
                print(f"Error saving history: {e}")
                # Continue without saving history

        # Get updated history for display (only for authenticated users)
        history = []
        if request.user.is_authenticated:
            history = CourseRegistrationHistory.objects.filter(
                user=request.user).order_by('-last_used')[:5]

        # Generate download URLs
        course_codes_str = ','.join(student_course_codes)
        pdf_url = f"/download-timetable/?source_id={source_id}&codes={course_codes_str}"
        jpg_url = f"/download-timetable-jpg/?source_id={source_id}&codes={course_codes_str}"

        return render(request, 'core/timetable_generator.html', {
            'sources': sources,
            'schedule': schedule,
            'processed_codes': list(student_course_codes),
            'raw_codes': raw_extracted_codes,  # For debugging
            'selected_source_id': int(source_id),
            'history': history,
            'is_authenticated': request.user.is_authenticated,
            'show_results': True,
            'pdf_url': pdf_url,
            'jpg_url': jpg_url,
            'course_codes_input': course_codes_input,
            'selected_source': TimetableSource.objects.get(id=source_id)
        })


@login_required
def reuse_course_registration(request, history_id):
    """Reuse a previous course registration to generate timetable."""
    try:
        history = CourseRegistrationHistory.objects.get(
            id=history_id, user=request.user)
        course_codes = json.loads(history.course_codes)

        # Update last_used timestamp
        history.last_used = datetime.now()
        history.save()

        # Get master schedule data
        master_schedule = get_master_schedule_data(history.source.id)

        if not master_schedule:
            messages.error(
                request, 'The timetable source is no longer available.')
            return redirect('student_dashboard')

        # Filter matching events
        student_events = []
        for event in master_schedule:
            event_code = event.get('normalized_code')
            if event_code in course_codes:
                student_events.append(event)

        days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        schedule = {
            day: sorted([e for e in student_events if e['day']
                        == day], key=lambda x: x['start_time'])
            for day in days_of_week
        }

        sources = TimetableSource.objects.all().order_by('-created_at')
        history_list = CourseRegistrationHistory.objects.filter(
            user=request.user).order_by('-last_used')[:5]

        # Generate download URLs
        course_codes_str = ','.join(course_codes)
        pdf_url = f"/download-timetable/?source_id={history.source.id}&codes={course_codes_str}"
        jpg_url = f"/download-timetable-jpg/?source_id={history.source.id}&codes={course_codes_str}"

        return render(request, 'core/timetable_generator.html', {
            'sources': sources,
            'schedule': schedule,
            'processed_codes': course_codes,
            'selected_source_id': history.source.id,
            'history': history_list,
            'is_authenticated': True,
            'show_results': True,
            'pdf_url': pdf_url,
            'jpg_url': jpg_url,
            'selected_source': history.source
        })

    except CourseRegistrationHistory.DoesNotExist:
        messages.error(request, 'Course registration history not found.')
        return redirect('student_dashboard')
    except Exception as e:
        messages.error(request, f'Error reusing registration: {str(e)}')
        return redirect('student_dashboard')


# --- UPDATED: download_timetable_pdf with consistent normalization ---


def download_timetable_pdf(request):
    source_id = request.GET.get('source_id')
    course_codes_str = request.GET.get('codes', '')
    template_type = request.GET.get('template', 'modern')  # Default to modern
    course_codes = [normalize_course_code(
        code) for code in course_codes_str.split(',') if code.strip()]

    if not source_id or not course_codes:
        return HttpResponse("Invalid request.", status=400)

    master_schedule = get_master_schedule_data(source_id)
    student_events = [e for e in master_schedule if e.get(
        'normalized_code') in course_codes]

    try:
        source = TimetableSource.objects.get(id=source_id)
    except TimetableSource.DoesNotExist:
        return HttpResponse("Timetable source not found.", status=404)

    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    # Convert event dictionaries to objects for template access
    event_objects = [EventObject(e) for e in student_events]
    schedule = {day: sorted([e for e in event_objects if e.day == day],
                            key=lambda x: x.start_time) for day in days_of_week}

    # Only grid template available
    template_path = 'core/timetable_pdf_grid.html'
    template = get_template(template_path)
    html = template.render(
        {'schedule': schedule, 'days_of_week': days_of_week, 'source_name': source.display_name, 'template_type': template_type, 'source': source})

    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
    if not pdf.err:
        response = HttpResponse(
            result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="my_timetable.pdf"'
        return response

    return HttpResponse("Error Generating PDF", status=500)


class PublicTimetablesView(View):
    """Public view for browsing available timetables without modification privileges"""

    def get(self, request):
        # Get all completed timetables ordered by creation date
        timetables = TimetableSource.objects.filter(
            status=TimetableSource.COMPLETED
        ).order_by('-created_at')

        return render(request, 'core/public_timetables.html', {
            'timetables': timetables
        })


def download_timetable_jpg(request):
    """Generate and download timetable as JPG image"""
    source_id = request.GET.get('source_id')
    course_codes_str = request.GET.get('codes', '')

    course_codes = [normalize_course_code(
        code) for code in course_codes_str.split(',') if code.strip()]

    if not source_id or not course_codes:
        return HttpResponse("Invalid request.", status=400)

    master_schedule = get_master_schedule_data(source_id)

    # Check if master schedule data is available
    if not master_schedule:
        return HttpResponse("No timetable data available for the selected source.", status=404)

    student_events = [e for e in master_schedule if e.get(
        'normalized_code') in course_codes]

    # Debug: Check if we have any matching events
    if not student_events:
        return HttpResponse(f"No matching courses found. Available courses: {[e.get('normalized_code', 'N/A') for e in master_schedule[:5]]}", status=404)

    try:
        source = TimetableSource.objects.get(id=source_id)
    except TimetableSource.DoesNotExist:
        return HttpResponse("Timetable source not found.", status=404)

    # Create image using PIL - Different layouts for exam vs teaching
    img_width, img_height = 1400, 900

    # Different background colors based on type
    if source.timetable_type == 'exam':
        bg_color = '#fef3f2'  # Light red background for exams
        header_color = '#dc2626'  # Red header for exams
    else:  # teaching or other types
        bg_color = '#fafafa'  # Light background for teaching
        header_color = '#1e293b'  # Dark header for teaching

    img = Image.new('RGB', (img_width, img_height), color=bg_color)
    draw = ImageDraw.Draw(img)

    try:
        # Try to use a better font with larger sizes for better readability
        title_font = ImageFont.truetype("arial.ttf", 32)
        subtitle_font = ImageFont.truetype("arial.ttf", 18)
        header_font = ImageFont.truetype("arial.ttf", 16)
        text_font = ImageFont.truetype("arial.ttf", 14)  # Increased from 11
        small_font = ImageFont.truetype("arial.ttf", 12)  # Increased from 9
    except:
        # Fallback to default font
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        header_font = ImageFont.load_default()
        text_font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    # Draw header section with type-specific styling
    header_height = 80

    # Draw header background with type-specific color
    draw.rectangle([0, 0, img_width, header_height],
                   fill=header_color, outline=header_color)

    # Draw title with type indicator
    if source.timetable_type == 'exam':
        type_indicator = "📝 EXAM SCHEDULE"
        subtitle = f"{source.display_name}"
    else:  # teaching or other types
        type_indicator = "📚 CLASS SCHEDULE"
        subtitle = f"{source.display_name}"

    # Main title
    title_bbox = draw.textbbox((0, 0), type_indicator, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((img_width - title_width) // 2, 10),
              type_indicator, fill='white', font=title_font)

    # Subtitle
    subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
    draw.text(((img_width - subtitle_width) // 2, 45),
              subtitle, fill='white', font=subtitle_font)

    # Draw subtitle
    subtitle = f"{source.display_name} - Generated by Timeli AI"
    subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
    draw.text(((img_width - subtitle_width) // 2, 50),
              subtitle, fill='#666', font=subtitle_font)

    # Draw table with day-based row layout (like grid template)
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    cell_height = 140  # Further increased height for larger event cards
    start_x, start_y = 30, header_height + 20
    day_col_width = 120
    events_col_width = img_width - day_col_width - 60  # Rest of width for events

    # Draw main table border
    table_width = day_col_width + events_col_width
    table_height = len(days) * cell_height + 40
    draw.rectangle([start_x, start_y, start_x + table_width, start_y + table_height],
                   outline='#ddd', fill='white')

    # Draw "Day" header
    draw.rectangle([start_x, start_y, start_x + day_col_width, start_y + 40],
                   outline='#ddd', fill='#e9ecef')
    draw.text((start_x + 35, start_y + 12), "Day",
              fill='#333', font=header_font)

    # Draw "Classes" header
    events_x = start_x + day_col_width
    draw.rectangle([events_x, start_y, events_x + events_col_width, start_y + 40],
                   outline='#ddd', fill='#e9ecef')
    classes_text = "Classes"
    classes_bbox = draw.textbbox((0, 0), classes_text, font=header_font)
    classes_width = classes_bbox[2] - classes_bbox[0]
    draw.text((events_x + (events_col_width - classes_width) // 2, start_y + 12),
              classes_text, fill='#333', font=header_font)

    # Draw day rows and events with minimal-inspired styling
    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    event_objects = [EventObject(e) for e in student_events]
    schedule = {day: sorted([e for e in event_objects if e.day == day],
                            key=lambda x: x.start_time) for day in days_of_week}

    # Debug: Print schedule info
    print(f"JPG Generation - Total events: {len(event_objects)}")
    for day, events in schedule.items():
        print(f"{day}: {len(events)} events")
        for event in events:
            print(
                f"  - {event.course_code} at {event.start_time.hour}:{event.start_time.minute:02d}")

    for day_idx, day in enumerate(days):
        y = start_y + 40 + day_idx * cell_height

        # Draw day header
        draw.rectangle([start_x, y, start_x + day_col_width, y + cell_height],
                       outline='#ddd', fill='#f8f9fa')

        # Center day text vertically
        day_bbox = draw.textbbox((0, 0), day.upper(), font=header_font)
        day_height = day_bbox[3] - day_bbox[1]
        draw.text((start_x + 15, y + (cell_height - day_height) // 2),
                  day.upper(), fill='#333', font=header_font)

        # Draw events cell background
        events_x = start_x + day_col_width
        draw.rectangle([events_x, y, events_x + events_col_width, y + cell_height],
                       outline='#ddd', fill='#fafafa')

        # Draw event cards horizontally for this day
        day_events = schedule.get(day, [])
        if day_events:
            card_width = 200   # Increased width for larger text
            card_height = 120  # Increased height for day + content
            card_spacing = 12  # Increased spacing between cards
            cards_per_row = events_col_width // (card_width + card_spacing)

            for event_idx, event in enumerate(day_events):
                # Calculate position for this event card
                row = event_idx // cards_per_row
                col = event_idx % cards_per_row

                card_x = events_x + 10 + col * (card_width + card_spacing)
                card_y = y + 10 + row * (card_height + 5)

                # Skip if card would go outside the cell
                if card_y + card_height > y + cell_height - 10:
                    break

                # Event card background with type-specific styling
                if source.timetable_type == 'exam':
                    # Red styling for exam cards
                    card_bg = '#fee2e2'  # Light red background
                    card_border = '#dc2626'  # Red border
                    text_color = '#7f1d1d'  # Dark red text
                    time_color = '#991b1b'  # Red time text
                else:
                    # Blue styling for teaching cards
                    card_bg = '#dbeafe'  # Light blue background
                    card_border = '#2563eb'  # Blue border
                    text_color = '#1e293b'  # Dark text
                    time_color = '#334155'  # Gray time text

                draw.rectangle([card_x, card_y, card_x + card_width, card_y + card_height],
                               outline=card_border, fill=card_bg, width=2)

                # Course code (prominent and bold)
                course_text = event.course_code
                if len(course_text) > 12:  # Adjusted for larger font
                    course_text = course_text[:12] + "..."
                draw.text((card_x + 12, card_y + 10),
                          course_text, fill=text_color, font=text_font)

                # Time (larger and clearer)
                time_text = f"{event.start_time.hour}:{event.start_time.minute:02d} - {event.end_time.hour}:{event.end_time.minute:02d}"
                draw.text((card_x + 12, card_y + 35),
                          time_text, fill=time_color, font=small_font)

                # Different content based on timetable type
                y_offset = 60

                if source.timetable_type == 'exam':
                    # EXAM TIMETABLE: Show ONLY date and level (NO venue)
                    if hasattr(event, 'details') and event.details:
                        # Extract date from details field (format: "Level: {level}, Date: {date}")
                        if "Date: " in event.details:
                            date_part = event.details.split(
                                "Date: ")[1] if "Date: " in event.details else ""
                            if date_part:
                                date_text = date_part[:15] + \
                                    "..." if len(date_part) > 15 else date_part
                                draw.text((card_x + 12, card_y + 60),
                                          f"📅 {date_text}", fill='#dc2626', font=small_font)
                                y_offset = 85

                        # Extract level from details
                        if "Level: " in event.details:
                            level_part = event.details.split("Level: ")[1].split(
                                ",")[0] if "Level: " in event.details else ""
                            if level_part:
                                draw.text((card_x + 12, y_offset),
                                          f"🎓 {level_part}", fill='#991b1b', font=small_font)

                else:
                    # TEACHING TIMETABLE: Show ONLY venue and lecturer (NO dates)
                    # Location/Venue (truncated, larger text)
                    if event.location:
                        location_text = event.location[:18] + "..." if len(
                            event.location) > 18 else event.location
                        draw.text((card_x + 12, y_offset),
                                  f"📍 {location_text}", fill='#475569', font=small_font)
                        y_offset += 20

                    # Lecturer (truncated, larger text)
                    if event.lecturer:
                        lecturer_text = event.lecturer[:16] + "..." if len(
                            event.lecturer) > 16 else event.lecturer
                        draw.text((card_x + 12, y_offset),
                                  f"👨‍🏫 {lecturer_text}", fill='#475569', font=small_font)
        else:
            # Empty state - no classes for this day
            no_classes_text = "No classes scheduled"
            no_classes_bbox = draw.textbbox(
                (0, 0), no_classes_text, font=text_font)
            no_classes_width = no_classes_bbox[2] - no_classes_bbox[0]
            draw.text((events_x + (events_col_width - no_classes_width) // 2,
                       y + cell_height // 2 - 10),
                      no_classes_text, fill='#9ca3af', font=text_font)

    # Draw footer with minimal styling
    footer_y = start_y + table_height + 20
    footer_text = "Powered by Timeli - Your AI Timetable Assistant"
    footer_bbox = draw.textbbox((0, 0), footer_text, font=small_font)
    footer_width = footer_bbox[2] - footer_bbox[0]

    # Draw footer border
    draw.line([start_x, footer_y, start_x + table_width,
              footer_y], fill='#ddd', width=1)

    # Center footer text
    draw.text(((img_width - footer_width) // 2, footer_y + 10),
              footer_text, fill='#999', font=small_font)

    # Save image to BytesIO
    img_buffer = BytesIO()
    img.save(img_buffer, format='JPEG', quality=95)
    img_buffer.seek(0)

    # Generate filename based on timetable type
    if source.timetable_type == 'exam':
        filename = "my_exam_schedule.jpg"
    else:
        filename = "my_class_schedule.jpg"

    response = HttpResponse(img_buffer.getvalue(), content_type='image/jpeg')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
