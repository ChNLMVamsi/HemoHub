from celery import shared_task

from .services import run_expiry_sweep


@shared_task
def check_expiring_blood_products():
    retired = run_expiry_sweep()
    return f"expiry sweep complete: {retired} units retired"
