def alerts_badge(request):
    """Expose the count of open network alerts from *other* banks to every template."""
    if not request.user.is_authenticated:
        return {"open_alerts": 0}
    bank = getattr(request.user, "bloodbank", None)
    if bank is None:
        return {"open_alerts": 0}
    from .models import TransferAlert
    count = TransferAlert.objects.filter(status="OPEN").exclude(from_bank=bank).count()
    return {"open_alerts": count}
