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
from datetime import datetime
import zoneinfo
import json
import io

from .models import (InstructorProfile, StudentProfile, Course, Enrollment,
                     Lecture, QRCodeUpload, generate_qr_code)

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



# ---------------------------------------------------------------------------
# HW6  — getUploads
# ---------------------------------------------------------------------------



