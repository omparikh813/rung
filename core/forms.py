from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .claims import FORM_FIELDS
from .models import CaseEntry, Category, Claim, Outcome, PayerRule

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


class NewClaimForm(ClaimForm):
    """Create one claim on the page, so nobody needs to build a CSV file."""

    class Meta(ClaimForm.Meta):
        fields = [*FORM_FIELDS, "clinical_note"]
        widgets = {**ClaimForm.Meta.widgets, "clinical_note": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        payer = self.fields["payer_name"]
        payer.choices = [("", "Choose a payer"), *payer.choices]
        self.fields["clinical_note"].help_text = "What the provider wrote about the visit. RUNG checks the claim against it."
        self.fields["units_1"].initial = 1


class ResolutionForm(forms.Form):
    """How a specialist resolves a help request, with an optional Case Library entry."""

    outcome = forms.ChoiceField(choices=Outcome.choices, widget=forms.RadioSelect, initial=Outcome.RETURNED)
    resolution_note = forms.CharField(
        label="Resolution note",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="The worker sees this note in the claim history.",
    )
    save_to_library = forms.BooleanField(label="Save to Case Library", required=False, initial=True)
    title = forms.CharField(max_length=150, required=False)
    category = forms.ChoiceField(choices=[("", "Choose a category"), *Category.choices], required=False)
    payer_name = forms.CharField(label="Payer", max_length=100, required=False)
    codes = forms.CharField(max_length=100, required=False)
    denial_code = forms.CharField(label="Denial code", max_length=20, required=False)
    problem = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
    fix = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
    tip = forms.CharField(
        label="Tip for workers", widget=forms.Textarea(attrs={"rows": 2}), required=False, help_text="Optional."
    )

    LIBRARY_REQUIRED = ["title", "category", "problem", "fix"]
    LIBRARY_FIELDS = ["title", "category", "payer_name", "codes", "denial_code", "problem", "fix", "tip"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in ("outcome", "save_to_library"):
                css = "input code" if name in ("codes", "denial_code") else "input"
                field.widget.attrs.update({"class": css, "aria-describedby": f"hint-{self.add_prefix(name)}"})

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("save_to_library"):
            for name in self.LIBRARY_REQUIRED:
                if not cleaned.get(name):
                    self.add_error(name, "This field is needed to save the entry.")
        return cleaned

    def case_entry(self, **extra):
        return CaseEntry(**{name: self.cleaned_data[name] for name in self.LIBRARY_FIELDS}, **extra)


class CaseEntryForm(forms.ModelForm):
    """Edit a Case Library entry. Only the specialist who created it can."""

    class Meta:
        model = CaseEntry
        fields = ResolutionForm.LIBRARY_FIELDS
        widgets = {name: forms.Textarea(attrs={"rows": 3}) for name in ("problem", "fix", "tip")}
        labels = {"tip": "Tip for workers", "denial_code": "Denial code"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            css = "input code" if name in ("codes", "denial_code") else "input"
            field.widget.attrs.update({"class": css, "aria-describedby": f"hint-{name}"})
