from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .claims import FORM_FIELDS
from .models import Claim, PayerRule

# Codes, IDs, and amounts use Fira Code so they are easy to compare character by character.
CODE_FIELDS = {
    "patient_dob", "member_id", "rendering_npi", "billing_npi", "place_of_service", "date_of_service",
    "icd10_primary", "icd10_secondary", "cpt_1", "modifiers_1", "units_1", "charge_1",
    "cpt_2", "modifiers_2", "units_2", "charge_2", "prior_auth_number", "referral_number", "ndc_code",
}  # fmt: skip


class LoginForm(AuthenticationForm):
    """The sign in form. One error message that never says which field was wrong."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "That username or password is not right. Please try again.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "input"


def payer_choices(current=""):
    names = PayerRule.objects.exclude(payer_name=PayerRule.ALL_PAYERS).values_list("payer_name", flat=True)
    names = sorted({*names, current} - {""})
    return [(name, name) for name in names]


class ClaimForm(forms.ModelForm):
    """The claim fields a worker or specialist can edit. The answer key is never part of this form."""

    class Meta:
        model = Claim
        fields = FORM_FIELDS
        widgets = {
            "patient_dob": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "date_of_service": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "patient_sex": forms.Select(choices=[("", "Not recorded"), ("F", "F"), ("M", "M")]),
        }

    def __init__(self, *args, read_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payer_name"] = forms.ChoiceField(label="Payer", choices=payer_choices(self.instance.payer_name))
        for name, field in self.fields.items():
            field.widget.attrs.update(
                {"class": "input code" if name in CODE_FIELDS else "input", "aria-describedby": f"hint-{name}"}
            )
            field.disabled = read_only
