# RUNG

RUNG is a demo web app that coaches entry level medical billing workers through
claims. An AI review checks each claim against the clinical note and the payer
rules, the help fades as the worker improves, and a specialist can be pulled in
with one click. Every specialist fix is saved to a shared Case Library.

All data is fictional. Do not enter real patient information.

The public home page is at `/`. It explains RUNG to billing workers and clinic
owners and links to the sign in page. Its contact details are placeholders in
`core/views/auth.py` (`CONTACT`); replace them before sharing the site.

The look of the app follows `design-system/rung/MASTER.md` (version 2: greens,
rounded cards, illustrations). Where it differs from Section 5 of the PRD, the
design system file wins.

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

Open http://127.0.0.1:8000 and sign in. The demo has two organizations, and each
one's claims, requests, cases, and people are kept apart from the other's:

| Organization | Admin | Specialist | Workers |
|--------------|-------|------------|---------|
| AGS Health (10 seats) | `om` | `james` | `flora` (holds the 30 sample claims), `kevin`, `cassandra` (ready for promotion) |
| Summit Medical Billing (5 seats, trial) | `steven` | | `kaua` (3 sample claims) |

Everyone signs in with the password from `DEMO_PASSWORD`.

- `python manage.py tailwind` downloads the Tailwind standalone CLI into `.tools/`
  on first use and builds `static/css/output.css`. Add `--watch` while editing
  templates.
- `python manage.py seed_demo` deletes the demo data and loads it again. Run it
  any time to reset the demo.
- Keep `DEBUG=True` for the demo so `runserver` serves the static files.

## Organizations and roles

- **Sign in:** choose the organization first, then username and password.
- **Workers** work their claims, do Daily Training, and ask a specialist for help.
- **Specialists** resolve workers' help requests, coach through the Case Library,
  see workers' Skill Passports, work their own claims (not scored), and open
  tickets to their admin under Messages.
- **Organization Admins** can do everything a specialist can, and also manage the
  organization on the Organization page: overview, employees (change roles,
  promote, deactivate or reactivate within the seat limit), worker performance,
  settings, and subscription. Admins can message any specialist.
- **Start Using RUNG** under the sign in box walks through creating an
  organization (account, organization and company directory, employee seats,
  review). It is a demo: it cannot create an organization or save anything.
- There are no prices or payments anywhere. Seat tiers are suggested packaging.

## What is simulated

RUNG is not connected to billing software, clearinghouses, or payers.

- **Adding claims:** a worker creates a claim with the form on the Add Claims page,
  or uploads a CSV file for many at once.
- **The payer:** submitting a claim gets an instant answer from a simulated payer
  (`core/payer.py`). A correct claim is Paid. A wrong one is Denied with a standard
  code and returns to the worker's queue. Sample claims are judged by their hidden
  answer key, and other claims by their latest AI review.
  When a claim the insurer denied is fixed and then paid, RUNG adds a Case Library
  entry for it automatically: the denial is the problem, the changed fields are the
  fix, and no patient details are copied. These entries are marked "From the
  simulated insurer", and any specialist can edit or delete them.
- **Daily Training:** workers get ten fictional practice cases a day, each with
  several sections (for example modifiers, units, and the final decision). Every
  section is checked on its own, wrong ones get feedback and the right answer, and
  there is no AI help and no specialist. Hints fade with the worker's help level:
  Full shows the rule and where to look, Guided asks one question, Minimal gives
  none. Real claims always get full help. Training updates the Skill Passport, but
  less than real claims: five correct training sections in a category equal one
  correct real claim. The cases live in `data/training_exercises.json`, and
  `python manage.py load_training` reloads them (seed_demo does this too).
- **837 export:** each submitted claim in the Skill Passport has an Export 837 button
  that downloads it as an ANSI X12 837P file (`core/x12.py`). Data the demo does not
  hold, such as the billing provider's address and tax ID, comes from the placeholders
  in `RUNG_X12` in `rung/settings.py`. The file is marked as test data and has not
  been validated by a clearinghouse.

## Test

```bash
python manage.py test
```

The tests never call the AI. They use mocked OpenRouter responses.

## Check the live AI review

With `OPENROUTER_API_KEY` set, sign in as `flora` and open a claim. The review runs
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
| `core/training.py` | Picks the day's ten practice cases and checks each section |
| `core/organizations.py` | The company directory, seat tiers, and role helpers |
| `core/payer.py` | The simulated payer that pays or denies submitted claims |
| `core/x12.py` | Builds the ANSI X12 837P export file |
| `core/templates/core/` | Pages, with shared pieces in `partials/` |
| `core/tests/` | Automated tests |
| `core/management/commands/` | `seed_demo` and `tailwind` |
| `prompts/` | The master prompt and the claim review task prompt |
| `data/` | Sample claims, payer rules, and the upload demo file |
| `design-system/rung/MASTER.md` | The design system every template follows |
| `static/` | Tailwind entry file, HTMX, Alpine.js, icons, and the logo |
| `docs/` | The product requirements document |
