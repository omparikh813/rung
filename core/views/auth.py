from django.conf import settings
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from ..context_processors import nav_for
from ..forms import LoginForm


class Login(LoginView):
    template_name = "core/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, show_demo_hint=settings.DEBUG)


# Placeholder contact details for the home page. Replace them before sharing the site.
CONTACT = {
    "email": "hello@example.com",
    "phone": "(555) 010-0000",
    "phone_link": "+15550100000",
    "address": "123 Placeholder Street, Your City, ST 00000",
}

FAQS = [
    {
        "question": "Is any of this real patient data?",
        "answer": "No. Every patient, provider, member ID, and claim in this demo is fictional. The codes are real "
        "CPT, HCPCS, and ICD-10-CM codes used the way billers use them. Do not enter real patient information.",
    },
    {
        "question": "Does RUNG send claims to payers?",
        "answer": "Not in this demo. Submit only changes the claim's status inside RUNG. It is not connected to "
        "billing software, clearinghouses, or payer portals.",
    },
    {
        "question": "Where does the AI get its answers?",
        "answer": "Only from the claim, the provider's clinical note, the payer rule table, and cases your own "
        "specialists have already resolved. If a rule it needs is not on file, it says so and recommends a specialist.",
    },
    {
        "question": "What happens when the AI is unsure?",
        "answer": "It marks the issue as low confidence and suggests asking a specialist. The worker always makes "
        "the final call, and one click sends the full case to a person.",
    },
    {
        "question": "How does the help fade?",
        "answer": "Real claims always get full help. In Daily Training, each worker starts with full hints in six skill "
        "areas. Correct real claims, and more slowly correct training answers, lower the hints one step. A wrong real "
        "claim raises them again, so support returns when needed.",
    },
]


def home(request):
    """The public home page. Signed in users go to their landing page: the first link in their sidebar."""
    if not request.user.is_authenticated:
        return render(request, "core/home.html", {"contact": CONTACT, "faqs": FAQS})
    links = nav_for(request.user)
    if not links:
        raise PermissionDenied
    return redirect(links[0]["url"])
