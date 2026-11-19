"""
models.py — Data model for AttendanceChimp.

AttendanceChimp is an electronic class attendance tool.  Instructors create
courses and lectures; each lecture is assigned a random QR code.  Students
photograph the QR code and upload the image.  The system decodes the QR code,
matches it to a lecture, and records the attendance.

Entities
--------
- InstructorProfile   : extends Django User → instructor-specific data
- StudentProfile  : extends Django User → student-specific data
- Course          : a course taught by one instructor
- Enrollment      : junction table linking students to courses
- Lecture         : a single class meeting (has a QR-code identifier)
- QRCodeUpload    : a student's uploaded QR-code photograph
"""

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

import logging
import string
import random

logger = logging.getLogger(__name__) # set up tracking, auditing, and debugging
                                                               # allows using logger.warning(), logger.error(), 
                                                               # logger.info(), etc. Better than print() for debuggin... 


# ---------------------------------------------------------------------------
# User profiles
# ---------------------------------------------------------------------------

class InstructorProfile(models.Model):
    """
    Instructor role. this extends Django's built-in User one-to-one, so
    login, name and email stay in auth_user and only the role's here.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    def __str__(self):
        return f"Instructor: {self.user.username}"


class StudentProfile(models.Model):
    """
    Student role. separate from InstructorProfile so one account is
    exactly one role and student-only queries donti  mix with instructors ones.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    def __str__(self):
        return f"Student: {self.user.username}"


# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------

class Course(models.Model):
    """
    A course taught by exactly one instructor. meeting_days areweekday
    letters such as "MWF"; start_time and end_time hold the meeting time.
    course is the course number like DATA13600
    """
    name = models.CharField(max_length=200)
    course = models.CharField(max_length=50, default="")
    instructor = models.ForeignKey(InstructorProfile, on_delete=models.CASCADE)
    meeting_days = models.CharField(max_length=20)
    start_time = models.TimeField()
    end_time = models.TimeField()

    def meets_on_day(self, weekday):
        """weekday is python's weekday() so 0 is monday, R is thursday"""
        return weekday < 5 and "MTWRF"[weekday] in self.meeting_days

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------

class Enrollment(models.Model):
    """
    Junction table: one row = one student enrolled in one course.
    This is how students <-> courses becomes many-to-many.
    """
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("student", "course")

    def __str__(self):
        return f"{self.student} in {self.course}"


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------

class Lecture(models.Model):
    """
    One class meeting of a course. qr_code is the random string shown
    on screen in the clas. it is unique so each upload maps to one lecture.
    """
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    date = models.DateTimeField()
    qr_code = models.CharField(max_length=32, unique=True)

    def __str__(self):
        return f"{self.course} on {self.date:%Y-%m-%d}"


# ---------------------------------------------------------------------------
# QR Code Upload
# ---------------------------------------------------------------------------

class QRCodeUpload(models.Model):
    """
    A QR-code photo uploaded by a student. lecture is optional because the
    upload is stored first and matched after decoding. uploaded_at defaults
    to now but can be set by hand
    """
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE)
    lecture = models.ForeignKey(Lecture, on_delete=models.SET_NULL,
                                null=True, blank=True)
    image = models.FileField(upload_to="qr_uploads/")
    uploaded_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.student} -> {self.lecture}"


# ---------------------------------------------------------------------------
# Helper / API functions
# ---------------------------------------------------------------------------


def generate_qr_code(length=32):
    """Return a random alphanumeric to use as a Lecture.qr_code."""
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def getUploadsForCourse(course):
    """
    course is the course number. returns a list of the uploads that happened
    during class (right day and time, checked in chicago time). [] if theres
    no such course
    """
    c = Course.objects.filter(course=course).first()
    if c is None:
        return []
    valid = []
    for u in QRCodeUpload.objects.filter(lecture__course=c):
        t = timezone.localtime(u.uploaded_at)
        if c.meets_on_day(t.weekday()) and c.start_time <= t.time() <= c.end_time:
            valid.append(u)
    return valid
