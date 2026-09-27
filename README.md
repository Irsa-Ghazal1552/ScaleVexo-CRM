# ScaleVexo CRM - Release 1 (internal pilot)

A sales-to-delivery system for ScaleVexo's own team, built to the scope of
**SVX-PRD-001 (Product and Delivery Brief)** and **SVX-TECH-001 (Technical Specification)**.
Layout is inspired by Bitrix24 (dark sidebar, kanban pipeline, record timeline), in a black / grey / white theme.

One continuous journey: **lead → deal → won → handover → onboarding project → milestones → tickets**,
with rule-based follow-ups, alerts, reporting, optional AI and full export.

| Layer | Technology |
|---|---|
| Backend | Python 3.13, Django 5.2 LTS, Django REST Framework 3.16 |
| Database | PostgreSQL 17 |
| Background worker | `python manage.py run_worker` (rules A01-A08 every 60 s, stored in PostgreSQL - no Redis) |
| Frontend | React 19, Vite 7, TypeScript, React Router 7, TanStack Query 5, lucide icons |
| Web server | Caddy 2 (HTTPS, serves the React build, proxies `/api`) |
| Backups | restic (encrypted, off-server) |
| AI (optional) | Anthropic Claude API via direct HTTP, or a free offline test provider |

---

## 1. Quick start with Docker (recommended)

Needs Docker Desktop (Windows/Mac) or Docker Engine + Compose (Linux).

```bash
cp .env.example .env          # Windows: copy .env.example .env
# edit .env: set DJANGO_SECRET_KEY, POSTGRES_PASSWORD, OWNER_EMAIL, OWNER_PASSWORD
# for a first look also set SEED_DEMO=true and REQUIRE_MFA_FOR_PRIVILEGED=false
docker compose up -d --build
```

Open **http://localhost** and sign in with `OWNER_EMAIL` / `OWNER_PASSWORD`.

On first start the API container automatically:
1. creates the database migrations (saved into `apps/api/modules/*/migrations` - commit them to git),
2. migrates the database,
3. creates the workspace and the CEO/owner account,
4. loads demo data when `SEED_DEMO=true`.

Demo logins (password `DemoPass!2026`): `sara@demo.scalevexo.local` (sales manager),
`rabia@demo.scalevexo.local` (sales rep), `hamza@demo.scalevexo.local` (delivery manager),
`zainab@demo.scalevexo.local` (developer), `usman@demo.scalevexo.local` (admin).
Remove all demo records later with:

```bash
docker compose exec api python manage.py seed_demo --remove
```

### Going live on a server (one budget VPS, Ubuntu 24.04)
1. Point a domain (e.g. `crm.scalevexo.com`) to the server.
2. In `.env`: `SITE_ADDRESS=crm.scalevexo.com`, `DJANGO_ALLOWED_HOSTS=crm.scalevexo.com`,
   `DJANGO_CSRF_TRUSTED_ORIGINS=https://crm.scalevexo.com`, `APP_BASE_URL=https://crm.scalevexo.com`,
   `DJANGO_SECURE_COOKIES=true`, `DJANGO_DEBUG=false`, `REQUIRE_MFA_FOR_PRIVILEGED=true`, `SEED_DEMO=false`.
3. `docker compose up -d --build` - Caddy gets the HTTPS certificate automatically.
4. Set up backups (section 5) and **test a restore before entering real data** (release gate G1).

---

## 2. Local development without Docker

**Backend** (needs Python 3.12+ and PostgreSQL; or use SQLite for a quick trial):

```bash
cd apps/api
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# quick trial on SQLite (Windows PowerShell: $env:DB_ENGINE="sqlite")
export DB_ENGINE=sqlite
python manage.py makemigrations identity crm work support automation reporting ai
python manage.py migrate
python manage.py bootstrap_workspace --owner-email ceo@scalevexo.com --owner-password "Change-Me-2026"
python manage.py seed_demo          # optional demo data
python manage.py runserver 8000
```

In a second terminal run the rule worker: `python manage.py run_worker`

**Frontend** (needs Node 20.19+ / 22+ and pnpm):

```bash
cd apps/web
pnpm install
pnpm dev            # http://localhost:5173  (API calls are proxied to :8000)
```

For PostgreSQL instead of SQLite, set `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`.

---

## 3. Roles

| Role | Sees / does |
|---|---|
| CEO / owner | Everything, CEO dashboard, cash receipts, workspace export, AI budget |
| Administrator | Members, invitations, rules, AI settings, audit log - no pipeline data, no HR authority |
| Sales manager | All leads and deals, team follow-ups, import/export, sales reports, accountability for sales team |
| Sales representative | Own and shared leads/deals, own tasks |
| Delivery manager | All clients, handovers, projects, tickets; accepts handovers and milestones |
| Delivery employee | Assigned projects, milestones, tasks and tickets; no deal values |

Access is invitation-only (Team → Invitations → copy link). Suspending a member ends their
sessions immediately and keeps all history. Owners/admins must use an authenticator app when
`REQUIRE_MFA_FOR_PRIVILEGED=true`.

---

## 4. AI (CRM12)

AI is **off by default**. Settings → AI:
* **Offline test provider** - free, deterministic, for trying the workflow.
* **Anthropic Claude API** - put `ANTHROPIC_API_KEY=...` in `.env`, restart, choose the provider,
  set the model (default `claude-haiku-4-5`) and the per-token prices from the current price list.

AI only summarizes the notes on a record and drafts follow-ups for the user to edit, copy or save.
It never sends messages, changes stages, promises prices or assesses employees. A monthly
organisation-wide budget is enforced with a database lock; when it is reached, AI stops and the
rest of the CRM keeps working.

---

## 5. Backups and recovery (CRM13)

```bash
# .env: RESTIC_REPOSITORY=s3:... or b2:... , RESTIC_PASSWORD=..., plus storage credentials
./infra/backup.sh     # daily via cron; keeps 7 daily / 4 weekly / 6 monthly
./infra/restore.sh    # restore latest (asks for confirmation)
```

Settings → Export & backup also offers a full JSON export (owner) and a formula-safe leads CSV.

---

## 6. Tests

```bash
cd apps/api
pytest               # needs PostgreSQL (or DB_ENGINE=sqlite)
```
`tests/test_requirements.py` maps to TEST01-TEST14 of the brief (isolation, suspension, import
reconciliation, stale updates, won evidence, self-reported activity, rescheduling, rule idempotency,
conversion idempotency, milestone dependencies, ticket resolution, reporting, AI budget, export).

---

## 7. Requirement map

| Req | Where |
|---|---|
| CRM01 identity & access | `modules/identity` (invitations, roles, suspension, MFA, transfer of work), `modules/common/access.py` |
| CRM02 import & contact quality | `modules/crm/services.py` (`import_preview`, `import_confirm`, duplicate rules, error file), Settings → Import |
| CRM03 leads & opportunities | `modules/crm` (separate Lead/Opportunity, stage rules, versions → HTTP 409, per-currency totals), Deals board |
| CRM04 activities | `Activity` + `ActivityRevision` (self-reported label, correction trail) |
| CRM05 Today & follow-ups | `modules/work` tasks, reschedule history, Today page |
| CRM06 rules & alerts | `modules/automation` (templates A01-A08, idempotent executions, auto-resolve, pause), Settings → Rules |
| CRM07 conversion & onboarding | `work.services.win_opportunity`, handover accept/return, exception queue |
| CRM08 projects & milestones | milestones with dependencies, evidence, reviewer acceptance, override, reopen, scope change vs defect |
| CRM09 tickets | severity, waiting reasons, resolution + closure test, reopen history, internal vs client-visible notes |
| CRM10 accountability | Team → Accountability, correction requests, alert challenges (no automatic sanctions) |
| CRM11 reporting | Reports (pipeline vs won vs cash receipts, per currency, drill-down to records) |
| CRM12 AI | `modules/ai` |
| CRM13 portability & recovery | JSON export, `infra/backup.sh`, `infra/restore.sh`, append-only audit log |

**Not in Release 1 (by design, per the brief):** email/calling integrations, outbound sending,
client portal, subscription billing, mobile app (the web app is responsive), attendance/leave
workflows, payroll or any employee monitoring.

---

## 8. Project layout

```
apps/api/                Django project
  config/                settings, urls
  modules/identity       workspace, members, invitations, MFA, audit
  modules/crm            contacts, leads, deals, activities, CSV import
  modules/work           tasks, clients, handovers, projects, milestones
  modules/support        tickets
  modules/automation     rule engine + worker
  modules/reporting      dashboards, receipts, corrections, export
  modules/ai             AI provider adapter, budget, prompts
  tests/                 acceptance tests
apps/web/                React app (src/pages, src/components, src/lib)
infra/                   Caddyfile, backup/restore scripts
docker-compose.yml
```
