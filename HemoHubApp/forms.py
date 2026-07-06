from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import BloodBank, BloodUnit

INPUT = (
    "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm "
    "text-slate-800 placeholder-slate-400 focus:border-crimson focus:ring-2 "
    "focus:ring-crimson/20 focus:outline-none"
)


class SignupForm(UserCreationForm):
    bank_name = forms.CharField(max_length=200, label="Blood bank name")
    city = forms.CharField(max_length=120, required=False)
    phone = forms.CharField(max_length=30, required=False)
    license_no = forms.CharField(max_length=60, required=False, label="License number")
    email = forms.EmailField(required=False)

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs["class"] = INPUT

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get("email", "")
        if commit:
            user.save()
            BloodBank.objects.create(
                user=user,
                name=self.cleaned_data["bank_name"],
                city=self.cleaned_data.get("city", ""),
                phone=self.cleaned_data.get("phone", ""),
                license_no=self.cleaned_data.get("license_no", ""),
            )
        return user


class BloodUnitForm(forms.ModelForm):
    class Meta:
        model = BloodUnit
        fields = ["donor_name", "blood_type", "component", "quantity_ml",
                  "collected_on", "expiry_date"]
        widgets = {
            "collected_on": forms.DateInput(attrs={"type": "date"}),
            "expiry_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            base = f.widget.attrs.get("class", "")
            f.widget.attrs["class"] = (base + " " + INPUT).strip()


class BankProfileForm(forms.ModelForm):
    class Meta:
        model = BloodBank
        fields = ["name", "city", "phone", "license_no"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs["class"] = INPUT
