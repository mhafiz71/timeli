"""
Timetable generation utilities and functions.
Handles PDF and JPG generation for timetables.
"""

import json
import re
from datetime import datetime
from io import BytesIO

from django.http import HttpResponse
from django.template.loader import get_template
from django.core.cache import cache
from django.contrib import messages
from django.shortcuts import redirect

from PIL import Image, ImageDraw, ImageFont
try:
    import pdfkit
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    # Fallback to xhtml2pdf
    from xhtml2pdf import pisa

from .models import TimetableSource, TimetableEvent


class EventObject:
    """Simple class to convert dictionary to object for template access"""

    def __init__(self, event_dict):
        for key, value in event_dict.items():
            setattr(self, key, value)


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
        from .views import parse_and_store_master_timetable
        if parse_and_store_master_timetable(source):
            # Recursive call to get from database
            return get_master_schedule_data(source_id)

        # Final fallback - try legacy parsing
        from .views import parse_master_timetable
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


def generate_pdf_timetable(source_id, course_codes, template_type='grid'):
    """Generate PDF timetable for given course codes"""
    try:
        source = TimetableSource.objects.get(id=source_id)
    except TimetableSource.DoesNotExist:
        return None, "Timetable source not found."

    master_schedule = get_master_schedule_data(source_id)
    if not master_schedule:
        return None, "Master schedule data not available."

    # Filter events for student courses
    student_events = []
    for event in master_schedule:
        event_code = event.get('normalized_code')
        if event_code in course_codes:
            student_events.append(event)

    if not student_events:
        return None, "No matching courses found."

    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    # Convert event dictionaries to objects for template access
    event_objects = [EventObject(e) for e in student_events]
    schedule = {day: sorted([e for e in event_objects if e.day == day],
                            key=lambda x: x.start_time) for day in days_of_week}

    # Only grid template available
    template_path = 'core/timetable_pdf_grid.html'
    template = get_template(template_path)
    html = template.render({
        'schedule': schedule,
        'days_of_week': days_of_week,
        'source_name': source.display_name,
        'template_type': template_type,
        'source': source
    })

    # Generate PDF using available library
    try:
        if PDF_AVAILABLE:
            # Use pdfkit if available
            options = {
                'page-size': 'A4',
                'margin-top': '0.75in',
                'margin-right': '0.75in',
                'margin-bottom': '0.75in',
                'margin-left': '0.75in',
                'encoding': "UTF-8",
                'no-outline': None,
                'enable-local-file-access': None
            }
            pdf = pdfkit.from_string(html, False, options=options)
            return pdf, None
        else:
            # Fallback to xhtml2pdf
            result = BytesIO()
            pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
            if not pdf.err:
                return result.getvalue(), None
            else:
                return None, "Error generating PDF with xhtml2pdf"
    except Exception as e:
        return None, f"Error generating PDF: {str(e)}"


def generate_jpg_timetable(request, source_id, course_codes, format_type='classic'):
    """Generate JPG timetable for given course codes"""
    try:
        source = TimetableSource.objects.get(id=source_id)
    except TimetableSource.DoesNotExist:
        return None, "Timetable source not found."

    master_schedule = get_master_schedule_data(source_id)
    if not master_schedule:
        return None, "Master schedule data not available."

    # Filter events for student courses
    student_events = []
    for event in master_schedule:
        event_code = event.get('normalized_code')
        if event_code in course_codes:
            student_events.append(event)

    if not student_events:
        return None, "No matching courses found."

    # Get program and level from request for modern format
    program = request.GET.get('program', 'BSC COMPUTER SCIENCE')
    level = request.GET.get('level', 'SECOND SEMESTER')

    # Choose generation method based on format
    if format_type == 'modern':
        return create_modern_timetable_jpg(student_events, source, program, level), None
    else:
        return create_classic_timetable_jpg(student_events, source), None


def create_classic_timetable_jpg(student_events, source):
    """Create classic JPG format timetable with proper text colors"""
    # Create image using PIL - Different layouts for exam vs teaching
    img_width, img_height = 1400, 900

    # Different background colors based on type
    if source.timetable_type == 'exam':
        bg_color = '#ffffff'  # White background for exams
        header_color = '#dc2626'  # Red header for exams
        text_color = '#1f2937'  # Dark gray text
        card_bg = '#fef2f2'  # Light red background for cards
        card_border = '#dc2626'  # Red border
    else:  # teaching or other types
        bg_color = '#ffffff'  # White background for teaching
        header_color = '#1e40af'  # Blue header for teaching
        text_color = '#1f2937'  # Dark gray text
        card_bg = '#eff6ff'  # Light blue background for cards
        card_border = '#1e40af'  # Blue border

    img = Image.new('RGB', (img_width, img_height), color=bg_color)
    draw = ImageDraw.Draw(img)

    try:
        # Try to use a better font with larger sizes for better readability
        title_font = ImageFont.truetype("arial.ttf", 38)
        subtitle_font = ImageFont.truetype("arial.ttf", 22)
        header_font = ImageFont.truetype("arial.ttf", 20)
        text_font_bold = ImageFont.truetype(
            "arialbd.ttf", 18)  # Bold for course codes
        text_font = ImageFont.truetype("arial.ttf", 16)
        small_font = ImageFont.truetype("arial.ttf", 14)
    except:
        # Fallback to default font
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        header_font = ImageFont.load_default()
        text_font_bold = ImageFont.load_default()
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

    # Draw table with day-based row layout
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    cell_height = 140
    start_x, start_y = 30, header_height + 20
    day_col_width = 120
    events_col_width = img_width - day_col_width - 60

    # Draw main table border
    table_width = day_col_width + events_col_width
    table_height = len(days) * cell_height + 40
    draw.rectangle([start_x, start_y, start_x + table_width, start_y + table_height],
                   outline='#cccccc', fill='white')

    # Draw "Day" header
    draw.rectangle([start_x, start_y, start_x + day_col_width, start_y + 40],
                   outline='#cccccc', fill='#f3f4f6')
    draw.text((start_x + 35, start_y + 12), "Day",
              fill=text_color, font=header_font)

    # Draw "Classes" header
    events_x = start_x + day_col_width
    draw.rectangle([events_x, start_y, events_x + events_col_width, start_y + 40],
                   outline='#cccccc', fill='#f3f4f6')
    classes_text = "Classes"
    classes_bbox = draw.textbbox((0, 0), classes_text, font=header_font)
    classes_width = classes_bbox[2] - classes_bbox[0]
    draw.text((events_x + (events_col_width - classes_width) // 2, start_y + 12),
              classes_text, fill=text_color, font=header_font)

    # Process events by day
    event_objects = [EventObject(e) for e in student_events]
    schedule = {day: sorted([e for e in event_objects if e.day == day],
                            key=lambda x: x.start_time) for day in days}

    for day_idx, day in enumerate(days):
        y = start_y + 40 + day_idx * cell_height

        # Draw day header
        draw.rectangle([start_x, y, start_x + day_col_width, y + cell_height],
                       outline='#cccccc', fill='#f9fafb')

        # Center day text vertically
        day_bbox = draw.textbbox((0, 0), day.upper(), font=header_font)
        day_height = day_bbox[3] - day_bbox[1]
        draw.text((start_x + 15, y + (cell_height - day_height) // 2),
                  day.upper(), fill=text_color, font=header_font)

        # Draw events cell background
        events_x = start_x + day_col_width
        draw.rectangle([events_x, y, events_x + events_col_width, y + cell_height],
                       outline='#cccccc', fill='white')

        # Draw event cards horizontally for this day
        day_events = schedule.get(day, [])
        if day_events:
            card_width = 220
            card_height = 120
            card_spacing = 15
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

                # Event card background
                draw.rectangle([card_x, card_y, card_x + card_width, card_y + card_height],
                               outline=card_border, fill=card_bg, width=2)

                # Course code (prominent and bold) - DARK TEXT
                course_text = event.course_code
                if len(course_text) > 12:
                    course_text = course_text[:12] + "..."
                draw.text((card_x + 12, card_y + 10),
                          course_text, fill='#000000', font=text_font_bold)  # BLACK TEXT

                # Time (with icon) - DARK TEXT
                time_text = f"⏰ {event.start_time.hour}:{event.start_time.minute:02d} - {event.end_time.hour}:{event.end_time.minute:02d}"
                draw.text((card_x + 12, card_y + 35),
                          time_text, fill='#374151', font=small_font)  # DARK GRAY TEXT

                # Different content based on timetable type
                y_offset = 60

                if source.timetable_type == 'exam':
                    # EXAM TIMETABLE: Show date
                    if hasattr(event, 'details') and event.details:
                        if "Date: " in event.details:
                            date_part = event.details.split(
                                "Date: ")[1] if "Date: " in event.details else ""
                            if date_part:
                                # Clean up the date text - remove common unwanted terms
                                date_text = date_part.replace("Level: ", "").replace("Undergraduate", "").replace(
                                    "Graduate", "").replace("Postgraduate", "").replace(",", "").replace(" -", "").strip()
                                # Take only the first 12 characters for clean display
                                date_text = date_text[:12] if len(
                                    date_text) > 12 else date_text
                                draw.text((card_x + 12, card_y + 60),
                                          # RED TEXT
                                          f"📅 {date_text}", fill='#dc2626', font=small_font)
                                y_offset = 85

                        # Extract level from details
                        if "Level: " in event.details:
                            level_part = event.details.split("Level: ")[1].split(
                                ",")[0] if "Level: " in event.details else ""
                            if level_part:
                                draw.text((card_x + 12, y_offset),
                                          # DARK RED TEXT
                                          f"🎓 {level_part}", fill='#991b1b', font=small_font)

                else:
                    # TEACHING TIMETABLE: Show venue and lecturer
                    if event.location:
                        location_text = event.location[:18] + "..." if len(
                            event.location) > 18 else event.location
                        draw.text((card_x + 12, y_offset),
                                  # DARK BLUE-GRAY TEXT
                                  f"📍 {location_text}", fill='#475569', font=small_font)
                        y_offset += 20

                    if event.lecturer:
                        lecturer_text = event.lecturer[:16] + "..." if len(
                            event.lecturer) > 16 else event.lecturer
                        draw.text((card_x + 12, y_offset),
                                  # DARK BLUE-GRAY TEXT
                                  f"👨‍🏫 {lecturer_text}", fill='#475569', font=small_font)
        else:
            # Empty state - no classes for this day
            no_classes_text = "No classes scheduled"
            no_classes_bbox = draw.textbbox(
                (0, 0), no_classes_text, font=text_font)
            no_classes_width = no_classes_bbox[2] - no_classes_bbox[0]
            draw.text((events_x + (events_col_width - no_classes_width) // 2,
                       y + cell_height // 2 - 10),
                      no_classes_text, fill='#9ca3af', font=text_font)  # LIGHT GRAY TEXT

    # Draw footer
    footer_y = start_y + table_height + 20
    footer_text = "Powered by Timeli - Your AI Timetable Assistant"
    footer_bbox = draw.textbbox((0, 0), footer_text, font=small_font)
    footer_width = footer_bbox[2] - footer_bbox[0]

    # Draw footer border
    draw.line([start_x, footer_y, start_x + table_width,
              footer_y], fill='#cccccc', width=1)

    # Center footer text - DARK TEXT
    draw.text(((img_width - footer_width) // 2, footer_y + 10),
              footer_text, fill='#6b7280', font=small_font)  # MEDIUM GRAY TEXT

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


def create_modern_timetable_jpg(student_events, source, program="BSC COMPUTER SCIENCE", level="SECOND SEMESTER"):
    """Create modern JPG format timetable with dark theme"""
    # Modern design dimensions
    img_width, img_height = 1600, 1000

    # Create image with dark gradient background
    img = Image.new('RGB', (img_width, img_height), color='#0f172a')
    draw = ImageDraw.Draw(img)

    # Create gradient background
    for y in range(img_height):
        ratio = y / img_height
        r = int(15 + (20 - 15) * ratio)
        g = int(23 + (55 - 23) * ratio)
        b = int(42 + (74 - 42) * ratio)
        color = f'#{r:02x}{g:02x}{b:02x}'
        draw.line([(0, y), (img_width, y)], fill=color)

    try:
        # Load fonts
        title_font = ImageFont.truetype("arial.ttf", 56)
        subtitle_font = ImageFont.truetype("arial.ttf", 28)
        day_font = ImageFont.truetype("arial.ttf", 24)
        course_font_bold = ImageFont.truetype("arialbd.ttf", 22)
        time_font = ImageFont.truetype("arial.ttf", 16)
        detail_font = ImageFont.truetype("arial.ttf", 14)
    except:
        # Fallback fonts
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        day_font = ImageFont.load_default()
        course_font_bold = ImageFont.load_default()
        time_font = ImageFont.load_default()
        detail_font = ImageFont.load_default()

    # Header section
    program_text = program.upper() if program else source.display_name.upper()

    if source.timetable_type == 'exam':
        main_title = f"{level.upper()} EXAM SCHEDULE" if level else "EXAM SCHEDULE"
    else:
        main_title = f"{level.upper()} TIMETABLE" if level else "CLASS TIMETABLE"

    # Draw program text
    program_bbox = draw.textbbox((0, 0), program_text, font=subtitle_font)
    program_width = program_bbox[2] - program_bbox[0]
    draw.text(((img_width - program_width) // 2, 40),
              program_text, fill='#94a3b8', font=subtitle_font)

    # Draw main title
    title_bbox = draw.textbbox((0, 0), main_title, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((img_width - title_width) // 2, 80),
              main_title, fill='white', font=title_font)

    # Create container
    container_y = 160
    container_height = 700
    container_margin = 80

    # Draw glass-like container
    draw.rounded_rectangle(
        [container_margin, container_y, img_width -
            container_margin, container_y + container_height],
        radius=20, fill='#1e293b', outline='#334155', width=2
    )

    # Process events by day
    days = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]
    event_objects = [EventObject(e) for e in student_events]
    schedule = {day.lower(): sorted([e for e in event_objects if e.day.lower() == day.lower()],
                                    key=lambda x: x.start_time) for day in days}

    # Draw day rows
    row_height = 140
    start_y = container_y + 40

    for day_idx, day in enumerate(days):
        y = start_y + day_idx * row_height

        # Draw day background
        day_bg = '#334155' if day_idx % 2 == 0 else '#475569'

        draw.rounded_rectangle(
            [container_margin + 20, y, img_width -
                container_margin - 20, y + row_height - 10],
            radius=10, fill=day_bg, outline='#64748b', width=1
        )

        # Draw day label
        draw.text((container_margin + 40, y + 45),
                  day, fill='white', font=day_font)

        # Draw events for this day
        day_events = schedule.get(day.lower(), [])
        if day_events:
            event_x = container_margin + 200
            event_spacing = 20

            # Limit to 4 events per row
            for event_idx, event in enumerate(day_events[:4]):
                card_x = event_x + event_idx * (300 + event_spacing)
                card_y = y + 15
                card_width = 280
                card_height = 110

                # Skip if card would overflow
                if card_x + card_width > img_width - container_margin - 40:
                    break

                # Draw event card
                draw.rounded_rectangle(
                    [card_x, card_y, card_x + card_width, card_y + card_height],
                    radius=8, fill='#1e293b', outline='#3b82f6', width=2
                )

                # Course code (bold)
                course_text = event.course_code[:12] if len(
                    event.course_code) > 12 else event.course_code
                draw.text((card_x + 15, card_y + 10), course_text,
                          fill='white', font=course_font_bold)

                # Time
                time_text = f"⏰ {event.start_time.hour}:{event.start_time.minute:02d} - {event.end_time.hour}:{event.end_time.minute:02d}"
                draw.text((card_x + 15, card_y + 40), time_text,
                          fill='#60a5fa', font=time_font)

                # Content based on type
                if source.timetable_type == 'exam':
                    # Show clean date for exams
                    if hasattr(event, 'details') and event.details and "Date: " in event.details:
                        date_part = event.details.split(
                            "Date: ")[1] if "Date: " in event.details else ""
                        if date_part:
                            # Clean up the date text - remove common unwanted terms
                            date_text = date_part.replace("Level: ", "").replace("Undergraduate", "").replace(
                                "Graduate", "").replace("Postgraduate", "").replace(",", "").replace(" -", "").strip()
                            # Take only the first 10 characters for clean display
                            date_text = date_text[:10] if len(
                                date_text) > 10 else date_text
                            draw.text(
                                (card_x + 15, card_y + 70), f"📅 {date_text}", fill='#fbbf24', font=detail_font)
                else:
                    # Show venue for teaching
                    if event.location:
                        location_text = event.location[:15] + "..." if len(
                            event.location) > 15 else event.location
                        draw.text((card_x + 15, card_y + 70),
                                  f"📍 {location_text}", fill='#94a3b8', font=detail_font)

    # Save image
    img_buffer = BytesIO()
    img.save(img_buffer, format='JPEG', quality=95)
    img_buffer.seek(0)

    filename = f"modern_timetable_{source.display_name.replace(' ', '_')}.jpg"

    response = HttpResponse(img_buffer.getvalue(), content_type='image/jpeg')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
