import csv

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render

from ..claims import CSV_COLUMNS
from ..decorators import role_required
from ..models import Role
from ..uploads import check_rows, import_rows, read_upload

ROWS_KEY = "upload_rows"
SUMMARY_KEY = "upload_summary"


@role_required(Role.WORKER, Role.SPECIALIST)
def upload(request):
    """Step 1 previews the file with a message per row. Step 2 imports only the valid rows."""
    if request.method == "POST" and request.POST.get("step") == "import":
        rows = request.session.pop(ROWS_KEY, None)
        if not rows:
            messages.error(request, "Preview a file before importing.")
            return redirect("upload")
        imported, skipped = import_rows(rows, request.user)
        request.session[SUMMARY_KEY] = {"imported": imported, "skipped": skipped}
        messages.success(request, f"Upload complete. {imported} imported, {skipped} skipped.")
        return redirect("upload")

    context = {"summary": request.session.pop(SUMMARY_KEY, None)}
    if request.method == "POST":
        rows, error = read_upload(request.FILES.get("file"))
        if error:
            request.session.pop(ROWS_KEY, None)
            context["file_error"] = error
        else:
            request.session[ROWS_KEY] = rows
            checked = check_rows(rows)
            invalid = sum(bool(item["errors"]) for item in checked)
            context.update(
                preview=checked,
                file_name=request.FILES["file"].name,
                valid_count=len(checked) - invalid,
                invalid_count=invalid,
            )
    return render(request, "core/upload.html", context)


@role_required(Role.WORKER, Role.SPECIALIST)
def upload_template(request):
    """The header row of sample_claims.csv, as a file to fill in."""
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="rung_claims_template.csv"'
    csv.writer(response).writerow(CSV_COLUMNS)
    return response
