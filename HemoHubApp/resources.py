from import_export import resources

from .models import BloodUnit


class BloodUnitResource(resources.ModelResource):
    class Meta:
        model = BloodUnit
        fields = ("id", "bank", "donor_name", "blood_type", "component",
                  "quantity_ml", "collected_on", "expiry_date", "is_available")
