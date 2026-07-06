"""Shared logic used by views, the Celery task, and the cron endpoint."""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from .consumers import NETWORK_GROUP


def push_network_event(payload: dict):
    """Broadcast a JSON event to every connected blood bank (live, via Channels)."""
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(
        NETWORK_GROUP, {"type": "network.event", "payload": payload}
    )


def run_expiry_sweep() -> int:
    """Mark past-expiry units as unavailable and close stale open alerts.

    Returns the number of units retired. Idempotent — safe to run repeatedly.
    """
    from .models import BloodUnit, TransferAlert

    today = timezone.localdate()
    expired = BloodUnit.objects.filter(is_available=True, expiry_date__lt=today)
    n = expired.count()
    expired.update(is_available=False)
    TransferAlert.objects.filter(
        status="OPEN", unit__expiry_date__lt=today
    ).update(status="EXPIRED")
    if n:
        push_network_event({"event": "sweep", "retired": n})
    return n