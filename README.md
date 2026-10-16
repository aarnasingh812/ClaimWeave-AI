# ClaimWeave — Health claim preparation

## Health intake and insurer guidance

New reimbursement claims follow **Claim details → Policy → Documents & help →
Review & download**. Start with patient, treatment and hospital details in one form;
policy name, number and PDF are collected afterwards and can be added later.
Star Health, HDFC ERGO, Niva Bupa and Care Health are supported. **Save draft**
persists an unfinished intake. Cashless claims lead to hospital/insurer guidance.

The document checklist is prepared before hospital records are uploaded. Planning
reads only an attached policy; without one, it uses clearly labelled provisional
insurer guidance without an extraction call. Each checklist item has instructions
and its own upload control, with a chat assistant beside the checklist. Additional
questions determine which conditional documents apply. Duplicate requests for the
same document share one upload card. Uploaded files remain pending review.

Users can upload what they have, then review extracted values against page previews.
Final approval still requires a verified matching policy, complete requirements,
confirmed values and form acknowledgments. Changes invalidate previous approval.
Missing policy identity may be filled in after uploads; changing an established
identity requires removing attached documents first.

Apply the additive schema migration before using this release:

```powershell
env/Scripts/python.exe -m alembic upgrade head
```

`GET /api/v1/health/insurers` returns the authenticated, versioned guidance registry.
`PATCH /api/v1/claims/{id}` saves a full intake replacement for an owned draft.
Existing claims without structured intake retain the previous analysis behavior.
The new details accompany preparation, chat context and approved drafts.

## Document review and claim pack

Open **Documents & help** to gather files, then **Review uploaded documents**:

1. Upload policy wording and supporting PDFs or JPG/PNG/TIFF photos. Native PDF
   text is read locally; scanned pages and photos use local RapidOCR. Page previews,
   low-quality warnings and a confirmed document category support review. The first
   OCR run may download model weights. Uploads are limited to 10 MB and PDF reading
   to 120 pages; unreadable or over-limit files block preparation.
2. Read new supporting documents when entering review, then check values beside the original.
   Each suggested value has a page, source quote and confidence. Correct or add
   missed fields and explicitly confirm values, category and page quality.
3. Answer conditional checklist questions. Published insurer guidance is distinct
   from requirements quoted from the uploaded policy. Unrecognized policy document
   types require an explicit attachment link, rather than matching every Other file.
4. Confirm policy applicability and the official form template, edit form values,
   then resolve deterministic validation issues. Names, dates, bills, receipts,
   bank details, duplicate documents and missing requirements are checked locally.
5. Use **Approve & download claim pack** for the current draft's ZIP: editable official
   claim form, submission guide, index/checklist, confirmed field review, manifest,
   attachment PDFs and untouched originals. Every edit, upload or deletion invalidates
   approval; outdated browser revisions cannot overwrite newer work.

Star Health, Care Health, Niva Bupa and HDFC ERGO templates are installed. HDFC has
separate hospitalization and myOptima Secure templates. Templates are pinned by
SHA-256 and carry official source URLs and review dates in
`app/assets/forms/manifest.json`; update them using `tools/fetch_claim_forms.py`
only after reviewing the official sources and field mapping. Unknown answers,
claimant signatures and hospital/doctor declarations remain for manual completion.
The pack is prepared for manual submission; it does not submit a claim or determine
coverage. Attachment copies use a conservative 5 MB limit; verify current portal
rules and inspect copies before uploading. Originals are retained in the ZIP.

### Gemini cost and token use

The health pipeline makes one structured extraction call per batch of **new or
changed** documents (up to 8 documents / 240,000 text characters). It allows
**16,384 output tokens** rather than truncating extraction to a small answer.
Raw extraction and local OCR are persisted and keyed by content hash, reader/
extractor version and model. Identical files reuse an owner-scoped cache; user
corrections never transfer between claims. Successful batches survive later failures.
Retries require an explicit user action; automatic SDK retries are disabled.

There are **zero Gemini calls** for unchanged reanalysis, corrections, checklist
answers, validation, approval, previews, PDF generation or ZIP export. Routine chat
questions use saved data locally. A custom question uses compact saved claim context
and up to 4,096 output tokens, with repeated answers cached by claim revision and
model. Extraction request and token counts remain available in the API. Legacy claims without
health intake retain the older LangGraph workflow and its separate call pattern.
Configuration defaults live in `app/core/config.py`; changing the Gemini model
intentionally invalidates its extraction cache.

Guidance is maintained in `app/health_guidance.json`. It records official source
URLs, source references per instruction, scope, version and last-checked date.
This is a reviewed snapshot, not a continuously refreshed feed. The UI warns when
sources are older than 90 days or a saved claim used an earlier guidance version.
Before updating the registry, open every official source, verify current forms and
submission instructions, resolve or explicitly flag conflicts, then increment the
version and date. Do not treat general guidance as the user's policy wording or
calculate an authoritative deadline without confirming policy applicability.
The current Star Health guidance explicitly flags its claims-page/form conflict
(15 versus 30 days after discharge). Other uncertain deadlines remain unspecified.

FastAPI + React/TypeScript + LangGraph + **PostgreSQL for both application tables and workflow checkpoints**.

## Scope

1. Claim CRUD and private PDF uploads (Phase 1).
2. Source-grounded LangGraph policy extraction, claim classification, requirements,
   document extraction, validation, interrupt-based human review, JSON export (Phase 2).
3. React dashboard, create claim, upload documents, checklist, review and export (Phase 3).
4. PostgreSQL checkpoints, JWT sign-in, user-scoped claims and workflow endpoints,
   audit events, database migration, test suite, Docker development setup (Phase 4).

**Not a production insurance platform.** No insurer integration, no claim filing, no
eligibility decision. Never use actual personal or medical
records in this demonstration. Gemini receives uploaded document text.

## Local setup (Windows PowerShell)

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`: set `JWT_SECRET` to a **random 32+ character secret** (e.g. generate
with `python -c "import secrets; print(secrets.token_urlsafe(48))"`), and add your
`GOOGLE_API_KEY` if running the agent. Gemini usage may cost money.

```powershell
docker compose up -d db
alembic upgrade head
python -m app.db.checkpoints
uvicorn app.main:app --reload
```

Start frontend in a separate terminal:

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

- Frontend: http://localhost:5173
- Swagger API: http://127.0.0.1:8000/docs

Register in the UI, complete health intake, upload policy wording and supporting
PDFs/photos, analyze changed documents, review evidence and prepare a submission pack.

Step 3 opens the ClaimWeave assistant chat. Select **Start analysis** or type
“Analyze my claim” to begin. The conversation shows the current checkpoint stage
while analysis runs, summarizes missing documents and validation results, and
answers follow-up questions using the claim details and saved analysis. Review
and approval remain available in **Review & export**. Chat history lasts while
the claim workspace is open; it is not saved to the database.

### Optional Docker Compose full development stack

After configuring `.env`, run:

```powershell
docker compose --profile full up -d --build
# One-time migration and checkpoint setup:
docker compose --profile full exec api alembic upgrade head
docker compose --profile full exec api python -m app.db.checkpoints
```

This Docker profile is **development only**; it uses a local Postgres password,
Vite dev server, and lacks TLS, network hardening and secrets management.

## PostgreSQL: two independent table families

- SQLAlchemy/Alembic: `users`, `claims`, `claim_documents`, `audit_events`.
- LangGraph PostgresSaver: its own `checkpoints`, `checkpoint_blobs`,
  `checkpoint_writes` and migration tracking tables created by `.setup()`.

`DATABASE_URL` is required. `alembic.ini` contains **no SQLite fallback**.
`langgraph-checkpoint-postgres` uses the same PostgreSQL database as the app.

**Upgrading from Phase 3:** `alembic upgrade head` creates user/audit tables and
adds `owner_id`. Existing Phase 3 claims have `owner_id=NULL` and are **not visible
to any account**. For a fresh demo, create new claims. Never automatically assign
legacy records to a new account; a controlled ownership migration would be needed.
Old SQLite LangGraph checkpoints are **not migrated**; restart old workflows as new claims.

## API endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | Create account, receive token |
| POST | `/api/v1/auth/login` | Sign in |
| GET | `/api/v1/auth/me` | Current user |
| POST | `/api/v1/claims` | Create claim |
| GET | `/api/v1/claims` | List own claims |
| GET | `/api/v1/claims/{id}` | View own claim |
| PATCH | `/api/v1/claims/{id}` | Edit structured health intake |
| DELETE | `/api/v1/claims/{id}` | Delete own claim and stored documents |
| POST | `/api/v1/claims/{id}/documents` | Upload PDF/photo |
| DELETE | `/api/v1/claims/{id}/documents/{doc}` | Remove document and invalidate approval |
| GET | `/api/v1/claims/{id}/documents/{doc}/preview?page=1` | Protected PNG page preview |
| GET | `/api/v1/claims/{id}/preparation` | Saved health preparation |
| POST | `/api/v1/claims/{id}/preparation/analyze` | Extract changed files and validate |
| PATCH | `/api/v1/claims/{id}/documents/{doc}/review` | Save field/category/quality confirmations |
| PATCH | `/api/v1/claims/{id}/preparation` | Save conditions, attachment links and form values |
| POST | `/api/v1/claims/{id}/preparation/approve` | Approve current validated revision |
| GET | `/api/v1/claims/{id}/preparation/form` | Download editable official form draft |
| GET | `/api/v1/claims/{id}/preparation/pack` | Download current approved ZIP |
| POST | `/api/v1/claims/{id}/workflow/start` | Run workflow |
| GET | `/api/v1/claims/{id}/workflow` | View workflow |
| POST | `/api/v1/claims/{id}/workflow/review` | Resume human approval |
| GET | `/api/v1/claims/{id}/workflow/export` | Download approved JSON |

Except registration, login and health, routes require a Bearer token.
The frontend keeps the token in **sessionStorage** (cleared when the tab session ends).
This is a development choice; production should use hardened session handling.

## Known limitations / next hardening work

- Agent runs synchronously in the HTTP request; use a job queue for long runs.
- PDF validation only checks extension and header, not malware or PDF parser safety.
- Local document storage and PostgreSQL checkpoint payloads are **not encrypted**;
  they can contain document text, PII and medical details.
- No password reset, email verification, MFA, rate limiting, audit retention or
  automated deletion; add these before public deployment.
- The workflow is source-grounded but not clinically/legally reliable; manual review
  remains essential. Conditional requirements need human confirmation.
- Tests are limited and do not establish accuracy, fairness or production readiness.
- Requires a Gemini API key; no free-tier availability is guaranteed.

## New: three policy-source modes

The frontend **Documents** tab now offers:

1. **Upload PDF** (recommended): Upload the actual policy schedule/wording. The agent extracts cited requirements and checks policy identity.
2. **Find online**: Search for PDF candidates on configured official insurer domains. Open and inspect a candidate, confirm exact policy product/version/dates/endorsements, then the backend downloads the selected official PDF and runs the usual verification. The search provider is best-effort and may return no results. Unknown insurers are intentionally unsupported until their domains are vetted and added to `app/agent/policy_discovery.py`.
3. **Skip for now**: Start the LangGraph workflow without any policy. The agent classifies the claim, extracts uploaded supporting-document fields and creates **provisional suggestions**. These suggestions are **not** claimed as policy requirements. Validation deliberately blocks human approval and final JSON export until a verified policy is attached.

You can upload/confirm a policy after a provisional run (`provisional_ready`) and run the workflow again. This reuses the claim's PostgreSQL checkpoint thread and re-executes the graph with the updated inputs. It does not submit anything to an insurer.

If a workflow fails or the policy identity check reports a mismatch, the claim remains recoverable: retry the workflow, and replace the policy PDF if needed. A policy mismatch requires uploading or confirming the corrected source before retrying.

### New endpoints

- `GET /api/v1/claims/{id}/policy/discover` — official PDF candidates for supported insurer.
- `POST /api/v1/claims/{id}/workflow/chat` — contextual chat with the claim assistant.
- `POST /api/v1/claims/{id}/policy/confirm` — `{"url":"https://...pdf","confirmed_policy_match":true}`. This is an explicit user confirmation, not proof that the policy applies.

**Online discovery security note:** This demo uses a fixed insurer domain allowlist, HTTPS-only URLs, no redirects, public DNS address checks, a PDF signature check, and a 10 MB streaming limit. It is **not** a fully hardened remote-fetch service: DNS rebinding, untrusted PDFs, and network egress controls require additional production defenses. Use an isolated egress proxy or fetch verified documents through a controlled browser/download service before deployment. No arbitrary URL fetching is exposed. Some insurer sites may block automated downloads; use the upload mode in that case.

**Source trust:** A public insurer PDF is not necessarily the policy actually purchased. Confirm policy number, issue date, applicable endorsements, waiting periods and policy wording. LLM-extracted requirements are evidence-assisted drafts, not legal or insurance determinations.
