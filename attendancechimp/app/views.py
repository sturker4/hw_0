"""
views.py — HTTP request handlers for AttendanceChimp.

Each view corresponds to one URL endpoint.  Views receive an HTTP request,
interact with the database via models.py, and return an HTTP response.
"""

from django.shortcuts import render, redirect
from django.http import (HttpResponse, HttpResponseForbidden,
                         HttpResponseBadRequest, HttpResponseNotAllowed,
                         JsonResponse)
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login
from django.utils import timezone
from datetime import datetime
import zoneinfo
import json
import io

from .models import (InstructorProfile, StudentProfile, Course, Enrollment,
                     Lecture, QRCodeUpload, generate_qr_code,
                     getUploadsForCourse)

CDT = zoneinfo.ZoneInfo("America/Chicago")


# ---------------------------------------------------------------------------
# HW2  — index, time, sum
# ---------------------------------------------------------------------------

def index(request):
    """Render the home page (index.html)."""

    context = {
        "current_time": datetime.now(CDT).strftime("%H:%M"),
        "user": request.user,
    }
    return render(request, 'app/index.html', context)

def time_view(request):
    current_time = datetime.now(CDT).strftime("%H:%M")
    return HttpResponse(current_time, content_type="text/plain")


def sum_view(request):
    n1 = float(request.GET["n1"])
    n2 = float(request.GET["n2"])
    return JsonResponse({"sum": n1 + n2})

# ---------------------------------------------------------------------------
# HW4  — user creation
# ---------------------------------------------------------------------------

def new(request):
    """sign up page. only GET is allowed here, anything else gets a 405."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    return render(request, 'app/new.html')


@csrf_exempt
def createUser(request):
    """
    makes the User and then a student or instructor profile depending on
    is_student, then logs them in. dup email/username or missing stuff -> 400.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    email = request.POST.get("email", "").strip()
    user_name = request.POST.get("user_name", "").strip()
    password = request.POST.get("password", "")
    is_student = request.POST.get("is_student", "1")

    if not email or not user_name or not password:
        return HttpResponseBadRequest("Missing email, user_name or password.")
    if User.objects.filter(email=email).exists():
        return HttpResponseBadRequest("A user with that email already exists.")
    if User.objects.filter(username=user_name).exists():
        return HttpResponseBadRequest("A user with that user_name already exists.")

    # create_user hashes the password, plain User(...) would just save it as is
    user = User.objects.create_user(username=user_name, email=email,
                                    password=password)
    if is_student == "1":
        StudentProfile.objects.create(user=user)
    else:
        InstructorProfile.objects.create(user=user)

    login(request, user)
    return HttpResponse(f"User {user_name} created.", status=200)


# ---------------------------------------------------------------------------
# HW5  — courses, lectures, QR uploads, dump
# ---------------------------------------------------------------------------

def is_instructor(user):
    """true if logged in and has an InstructorProfile."""
    return (user.is_authenticated
            and InstructorProfile.objects.filter(user=user).exists())


def is_student(user):
    """same thing but for students."""
    return (user.is_authenticated
            and StudentProfile.objects.filter(user=user).exists())


def new_course(request):
    """form page for making a course, posts to createCourse."""
    return render(request, 'app/new_course.html')


def new_lecture(request):
    """form page for a lecture. dropdown is filled with all the course names."""
    courses = Course.objects.all()
    return render(request, 'app/new_lecture.html', {"courses": courses})


def new_qr_upload(request):
    """form page for uploading the qr code pic."""
    return render(request, 'app/new_qr_upload.html')


def parse_time(value):
    """turns "10:30" (or "10:30:00") into a time object, None if its junk."""
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except (ValueError, TypeError):
            pass
    return None


@csrf_exempt
def createCourse(request):
    """
    instructors only (401 otherwise). reads course-name, start/end time and
    the day-xxx checkboxes and saves a Course. bad input -> 400.
    """
    if not is_instructor(request.user):
        return HttpResponse("Instructors only.", status=401)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    name = request.POST.get("course-name", "").strip()
    start = parse_time(request.POST.get("start-time", "").strip())
    end = parse_time(request.POST.get("end-time", "").strip())
    if not name or start is None or end is None:
        return HttpResponseBadRequest("Need course-name, start-time and end-time.")

    # checkboxes only show up in POST when theyre ticked
    day_letters = [("day-mon", "M"), ("day-tue", "T"), ("day-wed", "W"),
                   ("day-thu", "R"), ("day-fri", "F")]
    meeting_days = "".join(letter for field, letter in day_letters
                           if field in request.POST)

    Course.objects.create(
        name=name,
        course=name,
        instructor=InstructorProfile.objects.get(user=request.user),
        meeting_days=meeting_days,
        start_time=start,
        end_time=end,
    )
    return HttpResponse(f"Course {name} created.", status=200)


@csrf_exempt
def createLecture(request):
    """
    instructors only. choice is the course name, makes a Lecture for it with
    a fresh qr code. unknown course -> 400.
    """
    if not is_instructor(request.user):
        return HttpResponse("Instructors only.", status=401)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    choice = request.POST.get("choice", "").strip()
    # filter().first() instead of get() so 0 or 2+ matches dont blow up
    course = Course.objects.filter(name=choice).first()
    if course is None:
        return HttpResponseBadRequest("No course with that name.")

    Lecture.objects.create(course=course, date=timezone.now(),
                           qr_code=generate_qr_code())
    return HttpResponse(f"Lecture for {course.name} created.", status=200)


@csrf_exempt
def createQRCodeUpload(request):
    """
    students only. file comes in request.FILES as imageUpload. gets attached
    to the newest lecture (can be None if there arent any)
    """
    if not is_student(request.user):
        return HttpResponse("Students only.", status=401)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    f = request.FILES.get("imageUpload")
    if f is None:
        return HttpResponseBadRequest("No imageUpload file.")

    QRCodeUpload.objects.create(
        student=StudentProfile.objects.get(user=request.user), image=f,
        lecture=Lecture.objects.order_by("-date").first())
    return HttpResponse("Upload saved.", status=200)


def dumpUploads(request):
    """
    instructors only, GET. gives back every upload as a list of
    {"username", "upload_time"} with the time in chicago time.
    """
    if not is_instructor(request.user):
        return HttpResponse("Instructors only.", status=401)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    data = [
        {
            "username": u.student.user.username,
            "upload_time": timezone.localtime(u.uploaded_at)
                                   .strftime("%Y-%m-%d %H:%M:%S"),
        }
        for u in QRCodeUpload.objects.all()
    ]
    # safe=False because its a list not a dict
    return JsonResponse(data, safe=False)



# ---------------------------------------------------------------------------
# HW6  — getUploads
# ---------------------------------------------------------------------------

def getUploads(request):
    """
    instructors only. ?course=DATA13600 gives the valid uploads for that
    course, same format as dumpUploads. no course param -> 400
    """
    if not is_instructor(request.user):
        return HttpResponse("Instructors only.", status=401)
    course = request.GET.get("course")
    if not course:
        return JsonResponse({"error": "Missing course parameter"}, status=400)

    data = [
        {
            "username": u.student.user.username,
            "upload_time": timezone.localtime(u.uploaded_at)
                                   .strftime("%Y-%m-%d %H:%M:%S"),
        }
        for u in getUploadsForCourse(course)
    ]
    return JsonResponse(data, safe=False)


