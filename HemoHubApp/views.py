from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import BankProfileForm, BloodUnitForm, SignupForm
from .models import SHELF_LIFE_DAYS, BloodUnit, TransferAlert
from .services import push_network_event, run_expiry_sweep


# ---------------------------------------------------------------- public
def index(request):
    if request.user.is_authenticated:
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


# ---------------------------------------------------------------- helpers
def _bank(request):
    return request.user.bloodbank


# ---------------------------------------------------------------- dashboard
@login_required
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
@login_required
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


@login_required
@require_POST
def discard_unit(request, pk):
    unit = get_object_or_404(BloodUnit, pk=pk, bank=_bank(request))
    unit.is_available = False
    unit.save(update_fields=["is_available"])
    unit.alerts.filter(status="OPEN").update(status="EXPIRED")
    messages.info(request, "Unit removed from available stock.")
    return redirect("inventory")


@login_required
@require_POST
def broadcast_unit(request, pk):
    bank = _bank(request)
    unit = get_object_or_404(BloodUnit, pk=pk, bank=bank, is_available=True)
    if unit.has_open_alert:
        messages.info(request, "That unit is already on the network.")
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
        messages.success(request, "Unit broadcast to the network.")
    return redirect("inventory")


# ---------------------------------------------------------------- network
@login_required
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


@login_required
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
@login_required
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
@login_required
def alerts_count(request):
    """Polled by the nav to keep the network badge fresh without WebSockets."""
    bank = _bank(request)
    n = TransferAlert.objects.filter(status="OPEN").exclude(from_bank=bank).count()
    return JsonResponse({"open_alerts": n})


def cron_expire(request):
    """Daily sweep, called by Vercel Cron. Protected by a shared secret."""
    from django.conf import settings
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token != settings.CRON_SECRET:
        return JsonResponse({"error": "unauthorized"}, status=401)
    n = run_expiry_sweep()
    return JsonResponse({"expired_units": n})
