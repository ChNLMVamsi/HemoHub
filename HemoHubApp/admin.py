from django.contrib import admin
from import_export.admin import ImportExportModelAdmin

from .models import BloodBank, BloodUnit, TransferAlert


@admin.register(BloodBank)
class BloodBankAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "phone", "license_no", "created_at")
    search_fields = ("name", "city")


@admin.register(BloodUnit)
class BloodUnitAdmin(ImportExportModelAdmin):
    list_display = ("blood_type", "component", "quantity_ml", "bank",
                    "collected_on", "expiry_date", "is_available")
    list_filter = ("blood_type", "component", "is_available", "bank")
    search_fields = ("donor_name",)


@admin.register(TransferAlert)
class TransferAlertAdmin(admin.ModelAdmin):
    list_display = ("id", "unit", "from_bank", "claimed_by", "status", "created_at")
    list_filter = ("status",)
