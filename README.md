# RUNG

RUNG is a demo web app that coaches entry level medical billing workers through
claims. An AI review checks each claim against the clinical note and the payer
rules, the help fades as the worker improves, and a specialist can be pulled in
with one click. Every specialist fix is saved to a shared Case Library.

All data is fictional. Do not enter real patient information.

## Setup

Requires Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `OPENROUTER_API_KEY`, `DEMO_PASSWORD`, and `DJANGO_SECRET_KEY`.

## Run

```bash
python manage.py migrate
python manage.py tailwind
python manage.py seed_demo
python manage.py runserver
```

Open http://127.0.0.1:8000 and sign in as `maria` (Worker) or `dan` (Specialist)
with the password from `DEMO_PASSWORD`.

- `python manage.py tailwind` downloads the Tailwind standalone CLI into `.tools/`
  on first use and builds `static/css/output.css`. Add `--watch` while editing
  templates.
- `python manage.py seed_demo` deletes the demo data and loads it again. Run it
  any time to reset the demo.
- Keep `DEBUG=True` for the demo so `runserver` serves the static files.

## Test

```bash
python manage.py test
```

The tests never call the AI. They use mocked OpenRouter responses.

## Check the live AI review

With `OPENROUTER_API_KEY` set, sign in as `maria` and open a claim. The review runs
on first open. These four claims cover the checks the AI does from the payer rules,
today's date, and the patient's other claims:

| Claim | What the review should flag |
|-------|-----------------------------|
| CLM-1024 | The Medicare ID contains the letter O |
| CLM-1028 | The filing deadline has passed |
| CLM-1029 | A duplicate of CLM-1005 |
| CLM-1022 | Coverage was inactive on the date of service |

If the AI cannot be reached, the review panel shows a Try again button and the rest
of the app keeps working.

## Layout

| Path | What it holds |
|------|---------------|
| `rung/` | Django project: settings and root URLs |
| `core/` | The only Django app |
| `core/models.py` | All models and their status and category choices |
| `core/views/` | One module per screen: auth, queue, workspace, help requests, library, passport, upload |
| `core/ai.py` | Prompt assembly and the OpenRouter client |
| `core/reviews.py` | Turns a stored AI review into issue cards and flagged fields |
| `core/skills.py` | Scoring, fading help levels, and Skill Passport numbers |
| `core/claims.py` | Claim helpers: CSV rows, filing deadlines, audit log, similar cases |
| `core/uploads.py` | CSV upload parsing and row validation |
| `core/templates/core/` | Pages, with shared pieces in `partials/` |
| `core/tests/` | Automated tests |
| `core/management/commands/` | `seed_demo` and `tailwind` |
| `prompts/` | The master prompt and the claim review task prompt |
| `data/` | Sample claims, payer rules, and the upload demo file |
| `design-system/rung/MASTER.md` | The design system every template follows |
| `static/` | Tailwind entry file, HTMX, Alpine.js, icons, and the logo |
| `docs/` | The product requirements document |
