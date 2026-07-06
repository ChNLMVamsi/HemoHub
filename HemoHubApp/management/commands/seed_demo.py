import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from HemoHubApp.models import (BLOOD_TYPES, SHELF_LIFE_DAYS, BloodBank,
                               BloodUnit, TransferAlert)

BANKS = [
    ("redcross", "Red Cross Blood Bank", "Hyderabad"),
    ("apollo", "Apollo Blood Centre", "Secunderabad"),
    ("nims", "NIMS Blood Bank", "Punjagutta"),
]
DONORS = ["Stephen Brown", "Andrew McDonald", "Kimberly Gordon", "Joe Martinez",
          "Michelle Davis", "Priya Nair", "Rahul Verma", "Aisha Khan",
          "Sanjay Rao", "Meera Iyer", "David Chen", "Fatima Sheikh"]


class Command(BaseCommand):
    help = "Create demo blood banks and realistic dated stock for the live demo."

    def handle(self, *args, **kwargs):
        today = timezone.localdate()
        TransferAlert.objects.all().delete()
        BloodUnit.objects.all().delete()

        banks = []
        for username, name, city in BANKS:
            user, _ = User.objects.get_or_create(username=username)
            user.set_password("hemohub123")
            user.save()
            bank, _ = BloodBank.objects.get_or_create(
                user=user, defaults={"name": name, "city": city, "phone": "040-1234567"})
            bank.name, bank.city = name, city
            bank.save()
            banks.append(bank)

        types = [t[0] for t in BLOOD_TYPES]
        comps = list(SHELF_LIFE_DAYS.keys())
        for bank in banks:
            for _ in range(random.randint(14, 20)):
                comp = random.choice(comps)
                # spread expiries so some are critical, some healthy
                offset = random.choice([-2, 1, 2, 3, 5, 6, 9, 15, 25, 40])
                expiry = today + timedelta(days=offset)
                collected = expiry - timedelta(days=SHELF_LIFE_DAYS[comp])
                BloodUnit.objects.create(
                    bank=bank, donor_name=random.choice(DONORS),
                    blood_type=random.choice(types), component=comp,
                    quantity_ml=random.choice([250, 350, 450]),
                    collected_on=collected, expiry_date=expiry,
                    is_available=offset >= 0,
                )

        # broadcast a couple of expiring units from the first bank
        for u in banks[0].units.filter(is_available=True).order_by("expiry_date")[:2]:
            TransferAlert.objects.create(
                unit=u, from_bank=banks[0],
                note=f"{u.blood_type} {u.get_component_display()} · {u.days_to_expiry} days left")

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(banks)} banks. Login: redcross / hemohub123"))
