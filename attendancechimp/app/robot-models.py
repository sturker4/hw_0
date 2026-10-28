# LLM used: GPT 6 Sol High
#
# Prompt:
#   Write a Django models.py for an app called AttendanceChimp that tracks
#   class attendance via QR codes.
#
#   - Users: students and instructors (two roles).
#   - Courses: each has one instructor. Students can enroll in multiple courses.
#   - Lectures: individual class meetings, each associated with a course.
#   - QR Code Uploads: photos uploaded by students, each associated with a
#     student and a lecture.
#
#   Design requirements: ideally simple to use, supports attendance analytics,
#   and also prevents cheating.
#   Return only the Python code and nothing else ready t copy paste into the
#   python file
#
# --- LLM output below (unmodified) ---


from datetime import timedelta
import hashlib
import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# --------------------------------------------------
# USERS
# --------------------------------------------------

class UserProfile(models.Model):
    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        INSTRUCTOR = "instructor", "Instructor"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendance_profile",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
    )

    def __str__(self):
        return f"{self.user} ({self.get_role_display()})"


def has_role(user, role):
    if not user or not user.is_authenticated:
        return False

    return UserProfile.objects.filter(
        user=user,
        role=role,
    ).exists()


# --------------------------------------------------
# COURSES
# --------------------------------------------------

class Course(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=30, unique=True)

    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="courses_taught",
    )

    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="Enrollment",
        related_name="enrolled_courses",
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.instructor_id and not has_role(
            self.instructor,
            UserProfile.Role.INSTRUCTOR,
        ):
            raise ValidationError({
                "instructor": "User must have the instructor role."
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code}: {self.name}"


# --------------------------------------------------
# ENROLLMENTS
# --------------------------------------------------

class Enrollment(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_enrollments",
    )

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )

    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course"],
                name="unique_student_course_enrollment",
            )
        ]

    def clean(self):
        if self.student_id and not has_role(
            self.student,
            UserProfile.Role.STUDENT,
        ):
            raise ValidationError({
                "student": "Only students can enroll in courses."
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} - {self.course}"


# --------------------------------------------------
# LECTURES
# --------------------------------------------------

class Lecture(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="lectures",
    )

    title = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at"]

    def clean(self):
        if self.starts_at and self.ends_at:
            if self.ends_at <= self.starts_at:
                raise ValidationError({
                    "ends_at": "Lecture must end after it starts."
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def attendance_count(self):
        return self.qr_uploads.filter(
            status=QRCodeUpload.Status.VERIFIED
        ).count()

    @property
    def attendance_rate(self):
        total_students = self.course.enrollments.filter(
            enrolled_at__lte=self.starts_at
        ).count()

        if total_students == 0:
            return 0.0

        return round(
            100 * self.attendance_count / total_students,
            2,
        )

    def __str__(self):
        return f"{self.course.code}: {self.title}"


# --------------------------------------------------
# QR CODES
# --------------------------------------------------

class QRCode(models.Model):
    """
    Short-lived QR codes used to verify attendance.

    Only the SHA-256 hash of the token is stored.
    The plaintext token is returned when generated
    and should be encoded into the displayed QR image.
    """

    lecture = models.ForeignKey(
        Lecture,
        on_delete=models.CASCADE,
        related_name="qr_codes",
    )

    token_hash = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
    )

    valid_from = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        if self.valid_from and self.expires_at:
            if self.expires_at <= self.valid_from:
                raise ValidationError(
                    "Expiration must be after the start time."
                )

    @classmethod
    def generate(cls, lecture, lifetime_seconds=60):
        """
        Generate a temporary attendance QR token.

        Returns:
            (qr_code_instance, plaintext_token)

        The plaintext token must be displayed as a QR
        code and should not be stored in the database.
        """

        if lifetime_seconds <= 0:
            raise ValidationError(
                "QR code lifetime must be positive."
            )

        now = timezone.now()

        if not (lecture.starts_at <= now < lecture.ends_at):
            raise ValidationError(
                "QR codes can only be generated during a lecture."
            )

        token = secrets.token_urlsafe(32)

        token_hash = hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

        qr_code = cls.objects.create(
            lecture=lecture,
            token_hash=token_hash,
            valid_from=now,
            expires_at=min(
                now + timedelta(seconds=lifetime_seconds),
                lecture.ends_at,
            ),
        )

        return qr_code, token

    def is_valid(self, token, at=None):
        at = at or timezone.now()

        submitted_hash = hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

        return (
            self.is_active
            and self.valid_from <= at < self.expires_at
            and secrets.compare_digest(
                self.token_hash,
                submitted_hash,
            )
        )

    def __str__(self):
        return f"QR for {self.lecture}"


# --------------------------------------------------
# QR CODE PHOTO UPLOADS
# --------------------------------------------------

def attendance_photo_path(instance, filename):
    extension = Path(filename).suffix.lower()

    return (
        f"attendance/lecture_{instance.lecture_id}/"
        f"{uuid.uuid4().hex}{extension}"
    )


class QRCodeUpload(models.Model):
    """
    Student attendance submissions.

    Anti-cheating measures:
    - Students must be enrolled.
    - One submission per student per lecture.
    - QR tokens expire quickly.
    - Duplicate image files are rejected.
    - Instructors must approve submissions.

    IMPORTANT:
    The submitted QR token must be decoded from the
    uploaded image on the server, not trusted directly
    from a client-provided text field.

    Image decoding and physical-presence verification
    must be implemented in the application layer.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending Review"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendance_uploads",
    )

    lecture = models.ForeignKey(
        Lecture,
        on_delete=models.CASCADE,
        related_name="qr_uploads",
    )

    qr_code = models.ForeignKey(
        QRCode,
        on_delete=models.PROTECT,
        related_name="submissions",
    )

    photo = models.ImageField(
        upload_to=attendance_photo_path,
    )

    photo_hash = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_attendance",
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-uploaded_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["student", "lecture"],
                name="unique_student_lecture_attendance",
            )
        ]

        indexes = [
            models.Index(fields=["lecture", "status"]),
            models.Index(fields=["student", "status"]),
        ]

    def clean(self):
        errors = {}

        if self.student_id and not has_role(
            self.student,
            UserProfile.Role.STUDENT,
        ):
            errors["student"] = (
                "Only students can submit attendance."
            )

        if self.student_id and self.lecture_id:
            enrolled = Enrollment.objects.filter(
                student_id=self.student_id,
                course_id=self.lecture.course_id,
            ).exists()

            if not enrolled:
                errors["student"] = (
                    "Student is not enrolled in this course."
                )

        if self.qr_code_id and self.lecture_id:
            if self.qr_code.lecture_id != self.lecture_id:
                errors["qr_code"] = (
                    "QR code belongs to a different lecture."
                )

        if self.status != self.Status.PENDING:
            if not self.reviewed_by_id or not self.reviewed_at:
                errors["status"] = (
                    "Reviewed submissions need a reviewer and timestamp."
                )
            elif self.lecture_id:
                if (
                    self.reviewed_by_id
                    != self.lecture.course.instructor_id
                ):
                    errors["reviewed_by"] = (
                        "Only the course instructor can review attendance."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.photo and not self.photo_hash:
            digest = hashlib.sha256()

            self.photo.open("rb")

            try:
                for chunk in self.photo.chunks():
                    digest.update(chunk)
            finally:
                self.photo.seek(0)

            self.photo_hash = digest.hexdigest()

        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def submit(cls, student, lecture, photo, decoded_qr_token):
        """
        Create an attendance submission.

        decoded_qr_token must come from server-side
        decoding of the uploaded photo.

        Returns the new QRCodeUpload instance.
        """

        now = timezone.now()

        if not has_role(
            student,
            UserProfile.Role.STUDENT,
        ):
            raise ValidationError(
                "Only students can submit attendance."
            )

        enrolled = Enrollment.objects.filter(
            student=student,
            course=lecture.course,
            enrolled_at__lte=now,
        ).exists()

        if not enrolled:
            raise ValidationError(
                "Student is not enrolled in this course."
            )

        if cls.objects.filter(
            student=student,
            lecture=lecture,
        ).exists():
            raise ValidationError(
                "Attendance was already submitted."
            )

        token_hash = hashlib.sha256(
            decoded_qr_token.encode("utf-8")
        ).hexdigest()

        qr_code = QRCode.objects.filter(
            lecture=lecture,
            token_hash=token_hash,
            is_active=True,
            valid_from__lte=now,
            expires_at__gt=now,
        ).first()

        if not qr_code or not qr_code.is_valid(
            decoded_qr_token,
            at=now,
        ):
            raise ValidationError(
                "Invalid or expired QR code."
            )

        submission = cls(
            student=student,
            lecture=lecture,
            qr_code=qr_code,
            photo=photo,
            status=cls.Status.PENDING,
        )

        submission.save()

        return submission

    def review(self, instructor, approved):
        """
        Instructor approves or rejects attendance.
        """

        if instructor.pk != self.lecture.course.instructor_id:
            raise ValidationError(
                "Only the course instructor can review attendance."
            )

        self.status = (
            self.Status.VERIFIED
            if approved
            else self.Status.REJECTED
        )

        self.reviewed_by = instructor
        self.reviewed_at = timezone.now()

        self.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
            ]
        )

    @property
    def is_present(self):
        return self.status == self.Status.VERIFIED

    @property
    def is_late(self):
        if not self.uploaded_at:
            return False

        return (
            self.uploaded_at
            > self.lecture.starts_at + timedelta(minutes=10)
        )

    def __str__(self):
        return (
            f"{self.student} - {self.lecture} "
            f"({self.get_status_display()})"
        )

