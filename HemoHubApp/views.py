import csv
import io
from functools import wraps
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.management import call_command
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import BankProfileForm, BloodUnitForm, SignupForm
from .models import SHELF_LIFE_DAYS, BloodBank, BloodUnit, TransferAlert
from .services import push_network_event, run_expiry_sweep


# ---------------------------------------------------------------- public
def index(request):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect("oversight")
        if _get_bank(request.user) is not None:
            return redirect("dashboard")
    return render(request, "index.html")


def register(request):
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Welcome to HemoHub. Your blood bank is ready.")
            return redirect("dashboard")
    else:
        form = SignupForm()
    return render(request, "register.html", {"form": form})


class HemoLoginView(LoginView):
    template_name = "login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        """Route each account to the right home after login."""
        user = self.request.user
        if user.is_superuser:
            return reverse("oversight")
        if _get_bank(user) is not None:
            return reverse("dashboard")
        return reverse("index")


# ---------------------------------------------------------------- helpers
def _bank(request):
    return request.user.bloodbank


def _get_bank(user):
    """Return the user's BloodBank, or None (e.g. for the admin superuser)."""
    try:
        return user.bloodbank
    except BloodBank.DoesNotExist:
        return None


def bank_required(view):
    """Like login_required, but also requires the account to be a blood bank.

    Non-bank accounts (admin/superuser) are redirected instead of 500-ing when a
    view reaches for request.user.bloodbank.
    """
    @wraps(view)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if _get_bank(request.user) is None:
            messages.info(request, "That account isn't a blood bank — manage it at /admin.")
            return redirect("index")
        return view(request, *args, **kwargs)
    return _wrapped


def superuser_required(view):
    """Restrict a view to platform admins (superusers)."""
    @wraps(view)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            return redirect("index")
        return view(request, *args, **kwargs)
    return _wrapped


# ---------------------------------------------------------------- dashboard
@bank_required
def dashboard(request):
    bank = _bank(request)
    today = timezone.localdate()
    units = bank.units.filter(is_available=True)

    soon = units.filter(expiry_date__gte=today,
                        expiry_date__lte=today + timedelta(days=7))
    expired = units.filter(expiry_date__lt=today)

    by_type = (units.values("blood_type")
                    .annotate(units=Count("id"), volume=Sum("quantity_ml"))
                    .order_by("blood_type"))

    network = (TransferAlert.objects.filter(status="OPEN")
                            .exclude(from_bank=bank)
                            .select_related("unit", "from_bank"))

    ctx = {
        "bank": bank,
        "total_units": units.count(),
        "total_volume": units.aggregate(v=Sum("quantity_ml"))["v"] or 0,
        "soon_count": soon.count(),
        "expired_count": expired.count(),
        "soon_units": soon.order_by("expiry_date")[:8],
        "by_type": by_type,
        "network": network[:6],
        "network_count": network.count(),
    }
    return render(request, "dashboard.html", ctx)


# ---------------------------------------------------------------- inventory
@bank_required
def inventory(request):
    bank = _bank(request)
    if request.method == "POST":
        form = BloodUnitForm(request.POST)
        if form.is_valid():
            unit = form.save(commit=False)
            unit.bank = bank
            unit.save()
            messages.success(request, "Unit added to inventory.")
            return redirect("inventory")
    else:
        form = BloodUnitForm()

    q = request.GET.get("type", "")
    units = bank.units.filter(is_available=True)
    if q:
        units = units.filter(blood_type=q)

    from .models import BLOOD_TYPES
    return render(request, "inventory.html", {
        "form": form,
        "units": units,
        "active_type": q,
        "types": [t[0] for t in BLOOD_TYPES],
    })


@bank_required
@require_POST
def discard_unit(request, pk):
    unit = get_object_or_404(BloodUnit, pk=pk, bank=_bank(request))
    unit.is_available = False
    unit.save(update_fields=["is_available"])
    unit.alerts.filter(status="OPEN").update(status="EXPIRED")
    messages.info(request, "Unit removed from available stock.")
    return redirect("inventory")


_COMPONENT_LOOKUP = {
    "whole": "WHOLE", "whole blood": "WHOLE",
    "rbc": "RBC", "red cells": "RBC", "red blood cells": "RBC",
    "plasma": "PLASMA",
    "platelets": "PLATELETS", "platelet": "PLATELETS",
}
_VALID_TYPES = {"O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"}


def _parse_date(value):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


@bank_required
@require_POST
def import_units(request):
    bank = _bank(request)
    f = request.FILES.get("csv_file")
    if not f or not f.name.lower().endswith(".csv"):
        messages.error(request, "Please choose a .csv file.")
        return redirect("inventory")

    try:
        rows = csv.DictReader(io.StringIO(f.read().decode("utf-8-sig")))
    except UnicodeDecodeError:
        messages.error(request, "Couldn't read that file — save it as UTF-8 CSV.")
        return redirect("inventory")

    created, skipped = [], 0
    for row in rows:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        blood_type = row.get("blood_type", "").upper()
        component = _COMPONENT_LOOKUP.get(row.get("component", "").lower())
        expiry = _parse_date(row.get("expiry_date", ""))
        collected = _parse_date(row.get("collected_on", "")) or timezone.localdate()
        if blood_type not in _VALID_TYPES or not component or not expiry:
            skipped += 1
            continue
        try:
            qty = int(float(row.get("quantity_ml", "450") or 450))
        except ValueError:
            qty = 450
        created.append(BloodUnit(
            bank=bank, donor_name=row.get("donor_name", ""),
            blood_type=blood_type, component=component, quantity_ml=qty,
            collected_on=collected, expiry_date=expiry,
        ))

    if created:
        BloodUnit.objects.bulk_create(created)
    msg = f"Imported {len(created)} unit{'s' if len(created) != 1 else ''}."
    if skipped:
        msg += f" Skipped {skipped} row{'s' if skipped != 1 else ''} with missing or invalid data."
    (messages.success if created else messages.warning)(request, msg)
    return redirect("inventory")


@login_required
def import_template(request):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="hemohub_units_template.csv"'
    w = csv.writer(resp)
    w.writerow(["donor_name", "blood_type", "component", "quantity_ml",
                "collected_on", "expiry_date"])
    w.writerow(["Jane Doe", "O+", "RBC", "450", "2026-06-01", "2026-07-13"])
    return resp


@bank_required
@require_POST
def broadcast_unit(request, pk):
    bank = _bank(request)
    unit = get_object_or_404(BloodUnit, pk=pk, bank=bank, is_available=True)
    if unit.has_open_alert:
        messages.info(request, "That unit already has a notification out.")
    else:
        alert = TransferAlert.objects.create(
            unit=unit, from_bank=bank,
            note=f"{unit.blood_type} {unit.get_component_display()} · "
                 f"{unit.days_to_expiry} days left",
        )
        push_network_event({
            "event": "new_alert",
            "from_bank_id": bank.id,
            "from_bank": bank.name,
            "blood_type": unit.blood_type,
            "component": unit.get_component_display(),
            "alert_id": alert.id,
        })
        messages.success(request, "Notification sent to other banks.")
    return redirect("inventory")


# ---------------------------------------------------------------- network
@bank_required
def network(request):
    bank = _bank(request)
    incoming = (TransferAlert.objects.filter(status="OPEN")
                            .exclude(from_bank=bank)
                            .select_related("unit", "from_bank"))
    outgoing = (TransferAlert.objects.filter(from_bank=bank)
                            .select_related("unit", "claimed_by"))
    return render(request, "network.html", {
        "incoming": incoming, "outgoing": outgoing,
    })


@bank_required
@require_POST
def claim_alert(request, pk):
    bank = _bank(request)
    alert = get_object_or_404(TransferAlert, pk=pk, status="OPEN")
    if alert.from_bank == bank:
        messages.error(request, "You can't claim your own listing.")
        return redirect("network")
    # Move the physical unit to the claiming bank.
    unit = alert.unit
    unit.bank = bank
    unit.is_available = True
    unit.save(update_fields=["bank", "is_available"])
    alert.status = "CLAIMED"
    alert.claimed_by = bank
    alert.save(update_fields=["status", "claimed_by"])
    push_network_event({
        "event": "claimed",
        "claimed_by": bank.name,
        "alert_id": alert.id,
    })
    messages.success(request, f"Claimed. The unit is now in {bank.name}'s inventory.")
    return redirect("network")


# ---------------------------------------------------------------- profile
@bank_required
def profile(request):
    bank = _bank(request)
    if request.method == "POST":
        form = BankProfileForm(request.POST, instance=bank)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("profile")
    else:
        form = BankProfileForm(instance=bank)
    return render(request, "profile.html", {"form": form, "bank": bank})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("index")


# ---------------------------------------------------------------- json / cron
@bank_required
def alerts_count(request):
    """Polled by the nav to keep the network badge fresh without WebSockets."""
    bank = _bank(request)
    n = TransferAlert.objects.filter(status="OPEN").exclude(from_bank=bank).count()
    return JsonResponse({"open_alerts": n})


@superuser_required
def oversight(request):
    """Platform-wide admin dashboard: banks, stock, wastage prevention, activity."""
    today = timezone.localdate()
    available = BloodUnit.objects.filter(is_available=True)
    soon = available.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=7))
    expired_in_stock = available.filter(expiry_date__lt=today)

    alerts = TransferAlert.objects.all()
    completed = alerts.filter(status="CLAIMED")          # units rescued from wastage
    open_alerts = alerts.filter(status="OPEN")
    lapsed = alerts.filter(status="EXPIRED")             # listed but expired unclaimed

    by_type = (available.values("blood_type")
                        .annotate(units=Count("id"), volume=Sum("quantity_ml"))
                        .order_by("blood_type"))

    banks = (BloodBank.objects.annotate(
                unit_count=Count("units", filter=Q(units__is_available=True)),
                volume=Sum("units__quantity_ml", filter=Q(units__is_available=True)))
             .order_by("-unit_count"))

    recent = (alerts.select_related("unit", "from_bank", "claimed_by")
                    .order_by("-created_at")[:8])

    # Units expiring within 7 days that no one has listed yet — the admin can
    # broadcast them to the network on the owning bank's behalf.
    needs_action = (available.filter(expiry_date__gte=today,
                                     expiry_date__lte=today + timedelta(days=7))
                             .exclude(alerts__status="OPEN")
                             .select_related("bank")
                             .order_by("expiry_date")[:20])

    ctx = {
        "total_banks": BloodBank.objects.count(),
        "total_units": available.count(),
        "total_volume": available.aggregate(v=Sum("quantity_ml"))["v"] or 0,
        "soon_count": soon.count(),
        "expired_count": expired_in_stock.count(),
        "completed_count": completed.count(),
        "open_count": open_alerts.count(),
        "lapsed_count": lapsed.count(),
        "by_type": by_type,
        "banks": banks,
        "recent": recent,
        "needs_action": needs_action,
    }
    return render(request, "oversight.html", ctx)


@superuser_required
@require_POST
def oversight_sweep(request):
    n = run_expiry_sweep()
    messages.success(request, f"Expiry sweep complete — {n} unit(s) retired from stock.")
    return redirect("oversight")


@superuser_required
@require_POST
def oversight_seed(request):
    call_command("seed_demo")
    messages.success(request, "Demo data reset — banks and dated stock repopulated.")
    return redirect("oversight")


@superuser_required
@require_POST
def oversight_delete_bank(request, pk):
    bank = get_object_or_404(BloodBank, pk=pk)
    name, user = bank.name, bank.user
    bank.delete()                       # cascades units + alerts
    if user and not user.is_superuser:
        user.delete()
    messages.info(request, f"Removed blood bank '{name}' and its data.")
    return redirect("oversight")


@superuser_required
@require_POST
def oversight_broadcast(request, pk):
    unit = get_object_or_404(BloodUnit, pk=pk, is_available=True)
    if unit.has_open_alert:
        messages.info(request, "That unit already has a notification out.")
    else:
        alert = TransferAlert.objects.create(
            unit=unit, from_bank=unit.bank,
            note=f"{unit.blood_type} {unit.get_component_display()} · "
                 f"{unit.days_to_expiry} days left (listed by admin)",
        )
        push_network_event({
            "event": "new_alert", "from_bank_id": unit.bank_id,
            "from_bank": unit.bank.name, "blood_type": unit.blood_type,
            "component": unit.get_component_display(), "alert_id": alert.id,
        })
        messages.success(request,
            f"Notified other banks about {unit.bank.name}'s {unit.blood_type} "
            f"{unit.get_component_display()}.")
    return redirect("oversight")


def cron_expire(request):
    """Daily sweep, called by Vercel Cron. Protected by a shared secret."""
    from django.conf import settings
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token != settings.CRON_SECRET:
        return JsonResponse({"error": "unauthorized"}, status=401)
    n = run_expiry_sweep()
    return JsonResponse({"expired_units": n})