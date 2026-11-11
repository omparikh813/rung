from django import forms
from django.contrib.auth.forms import AuthenticationForm


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
