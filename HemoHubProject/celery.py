import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "HemoHubProject.settings")

app = Celery("HemoHubProject")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Daily expiry sweep at 01:00. Runs when a worker + beat are online (locally,
# or on Render if you enable the paid workers). On the free deploy the same
# task is triggered over HTTP by a scheduled ping instead.
app.conf.beat_schedule = {
    "daily-expiry-sweep": {
        "task": "HemoHubApp.tasks.check_expiring_blood_products",
        "schedule": crontab(hour=1, minute=0),
    },
}
