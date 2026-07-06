from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

BLOOD_TYPES = [
    ("O+", "O+"), ("O-", "O-"), ("A+", "A+"), ("A-", "A-"),
    ("B+", "B+"), ("B-", "B-"), ("AB+", "AB+"), ("AB-", "AB-"),
]

# Typical shelf life per component (days) — used to pre-fill the expiry date.
COMPONENTS = [
    ("WHOLE", "Whole Blood"),
    ("RBC", "Red Cells"),
    ("PLASMA", "Plasma"),
    ("PLATELETS", "Platelets"),
]
SHELF_LIFE_DAYS = {"WHOLE": 35, "RBC": 42, "PLASMA": 365, "PLATELETS": 5}


class BloodBank(models.Model):
    """A tenant. One user account == one blood bank."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="bloodbank")
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    license_no = models.CharField("License number", max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class BloodUnit(models.Model):
    """A single dated bag of a blood component held by a bank."""
    bank = models.ForeignKey(BloodBank, on_delete=models.CASCADE, related_name="units")
    donor_name = models.CharField(max_length=200, blank=True)
    blood_type = models.CharField(max_length=3, choices=BLOOD_TYPES)
    component = models.CharField(max_length=20, choices=COMPONENTS)
    quantity_ml = models.PositiveIntegerField(default=450)
    collected_on = models.DateField(default=timezone.localdate)
    expiry_date = models.DateField()
    # False once the unit is discarded, transfused, or transferred away.
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["expiry_date"]

    def __str__(self):
        return f"{self.blood_type} {self.get_component_display()} ({self.expiry_date})"

    @property
    def days_to_expiry(self):
        return (self.expiry_date - timezone.localdate()).days

    @property
    def status(self):
        d = self.days_to_expiry
        if d < 0:
            return "expired"
        if d <= 3:
            return "critical"
        if d <= 7:
            return "warning"
        return "ok"

    @property
    def has_open_alert(self):
        return self.alerts.filter(status="OPEN").exists()


class TransferAlert(models.Model):
    """Broadcast of an expiring unit to the network so another bank can claim it."""
    STATUS = [("OPEN", "Open"), ("CLAIMED", "Claimed"), ("EXPIRED", "Expired")]

    unit = models.ForeignKey(BloodUnit, on_delete=models.CASCADE, related_name="alerts")
    from_bank = models.ForeignKey(BloodBank, on_delete=models.CASCADE, related_name="alerts_sent")
    claimed_by = models.ForeignKey(
        BloodBank, null=True, blank=True, on_delete=models.SET_NULL, related_name="alerts_claimed"
    )
    status = models.CharField(max_length=10, choices=STATUS, default="OPEN")
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Alert #{self.pk} · {self.unit} · {self.status}"
