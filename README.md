# ClaimWeave AI — Health Claim Preparation Platform

ClaimWeave AI is an intelligent, source-grounded health insurance claim preparation assistant designed specifically for reimbursement claims (with pre-configured support for leading Indian insurers like **Star Health**, **HDFC ERGO**, **Care Health**, and **Niva Bupa**).

It assists policyholders in transforming unstructured hospital bills, discharge summaries, payment receipts, and policy wordings into an audit-ready, pre-filled official submission pack.

> [!IMPORTANT]
> **ClaimWeave is a preparation assistant, not an automated submission portal or claim adjudicator.**  
> It does not submit claims to insurance portals, predict underwriting decisions, or offer legal/insurance advice. The generated pack is prepared for **manual submission** with claimant signatures and hospital authorizations.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Core Backend Components](#core-backend-components)
- [End-to-End Processing Flow](#end-to-end-processing-flow)
- [LangGraph Workflow State Machine](#langgraph-workflow-state-machine)
- [Token & Cost Optimization Strategy](#token--cost-optimization-strategy)
- [Technology Stack](#technology-stack)
- [Supported Insurers & Official Templates](#supported-insurers--official-templates)
- [API Reference](#api-reference)
- [Local Setup & Installation](#local-setup--installation)
- [Docker Development Setup](#docker-development-setup)
- [Security, Audit & Limitations](#security-audit--limitations)

---

## Project Overview

Filing a health insurance reimbursement claim is notoriously error-prone:
- Missing mandatory documents lead to claim queries or rejections.
- Inconsistent details (spelling of patient name, dates of admission/discharge, bill numbers) delay payouts.
- Official claim forms from insurers are multi-page, dense, and tedious to complete by hand.
- Sifting through hospital paperwork to cross-verify bills against receipts takes hours.

**ClaimWeave AI** solves this by combining **local OCR and document inspection**, **targeted Google Gemini structured extraction**, **deterministic rule validation**, and **official PDF template pre-filling**.

---

## Key Features

- **Dynamic Checklist & Insurer Guidance**: Formulates customized document requirements using reviewed snapshots of official insurer checklists (`health_guidance.json`).
- **3 Policy Ingestion Modes**:
  1. *Upload Policy PDF*: Ground-truth extraction of policy rules and coverage limits.
  2. *Discover Online*: Search and download official insurer policy wordings from allowlisted domains.
  3. *Provisional Mode*: Begin preparation immediately with provisional checklists before policy upload.
- **Local OCR & Page Quality Inspection**: Local text reading (PyMuPDF) and on-device OCR (`RapidOCR` with ONNX runtime) for scanned documents and mobile photos without sending images to external APIs. Automatic detection of blurry or low-resolution pages.
- **Side-by-Side Provenance Review**: Every extracted field links back to its exact source page, confidence score, and verbatim quote, allowing users to verify values directly against high-resolution page previews.
- **Strict Deterministic Validation**: Non-LLM business rules check for bill arithmetic mismatches, duplicate bills, invalid IFSC codes, date order issues, and KYC requirements (claims $\ge$ ₹1,00,000).
- **Official Form Autofill**: Exact pixel-coordinate pre-filling directly onto authentic insurer claim forms (Star Health, HDFC ERGO Hospitalization & myOptima Secure, Care Health, Niva Bupa).
- **Audit-Ready Submission ZIP**: Bundles the prefilled official claim form, submission guide, checklist, field audit manifest, optimized attachment PDFs, and untouched originals.
- **Approval Invalidation Safeguard**: Any document addition, deletion, or field edit increments the claim revision and immediately revokes previous approvals.

---

## System Architecture

ClaimWeave AI is decoupled into a reactive frontend, a robust FastAPI backend service, local document processing utilities, a dual PostgreSQL database layer, and Google Gemini AI.

```mermaid
graph TD
    subgraph Frontend["Frontend Client (React 19 + TypeScript + Vite)"]
        UI["Web UI Dashboard"]
        Intake["Health Intake Form"]
        DocReview["Side-by-Side Document Reviewer"]
        ChatUI["Claim Assistant Chat"]
    end

    subgraph API["FastAPI REST Services"]
        AuthRouter["Auth API (JWT)"]
        ClaimsRouter["Claims & Documents API"]
        PrepRouter["Preparation & Review API"]
        PolicyRouter["Policy Discovery API"]
        WorkflowRouter["LangGraph Workflow API"]
        ChatRouter["Assistant Chat API"]
    end

    subgraph CoreBackend["Backend Processing Pipeline"]
        DocEngine["Document & OCR Engine<br/>(PyMuPDF, RapidOCR, PIL)"]
        GeminiEngine["Structured Extraction Engine<br/>(Google Gemini + SHA-256 Cache)"]
        ValidationEngine["Deterministic Validation Engine<br/>(Business Rules & Math Checks)"]
        FormOverlay["PDF Form Pre-fill Engine<br/>(PyMuPDF Coordinate Overlays)"]
        PackGenerator["Claim Pack Generator<br/>(ReportLab & ZIP Bundler)"]
        GuidanceRegistry["Insurer Guidance Registry<br/>(app/health_guidance.json)"]
    end

    subgraph Storage["Persistence & External Services"]
        PG_App[("PostgreSQL: App Tables<br/>(users, claims, claim_documents, audit_events)")]
        PG_Checkpoints[("PostgreSQL: LangGraph Checkpoints<br/>(checkpoints, checkpoint_blobs)")]
        LocalFiles[("Protected Local Storage<br/>(Encrypted / Private Uploads)")]
        Gemini[("Google Gemini API<br/>(gemini-2.5-flash)")]
    end

    UI --> AuthRouter
    UI --> ClaimsRouter
    UI --> PrepRouter
    UI --> PolicyRouter
    UI --> WorkflowRouter
    ChatUI --> ChatRouter

    ClaimsRouter --> LocalFiles
    ClaimsRouter --> PG_App
    PrepRouter --> DocEngine
    PrepRouter --> GeminiEngine
    PrepRouter --> ValidationEngine
    PrepRouter --> FormOverlay
    PrepRouter --> PackGenerator
    PrepRouter --> GuidanceRegistry

    WorkflowRouter --> PG_Checkpoints
    DocEngine --> LocalFiles
    GeminiEngine --> Gemini
    GeminiEngine --> PG_App
```

---

## Core Backend Components

### 1. Document & Ingestion Engine (`app/documents.py`, `app/storage.py`)
- **File Validation**: Strict verification of file headers (PDF magic bytes `%PDF-`, allowed extensions `.pdf`, `.jpg`, `.jpeg`, `.png`, `.tif`), 10 MB file size limit, and 120-page PDF ceiling.
- **Local OCR**: When PDFs have no embedded text or when users upload mobile photos, ClaimWeave uses `RapidOCR` powered by ONNX Runtime. Images are converted to grayscale and evaluated for blurriness (via Laplacian variance) and resolution before OCR.
- **Protected Page Previews**: Generates secure, rendered PNG previews for each page (`GET /api/v1/claims/{id}/documents/{doc}/preview?page=N`) to allow users to audit facts visually.

### 2. LLM Extraction Pipeline (`app/extraction.py`)
- **Structured Data Extraction**: Sends extracted document text to Google Gemini using Pydantic schemas (`BatchExtraction`, `ExtractedFile`, `ExtractedField`, `PolicyExtraction`).
- **Prompt Injection Defense**: Uploaded text is treated strictly as untrusted user data. LLM instructions mandate extracting only explicitly supported fields and verbatim evidence quotes.
- **Content-Addressed Cache**: Every document's text and extraction is fingerprinted using SHA-256. If a file was analyzed previously, the result is fetched from the database cache without calling the Gemini API.

### 3. Deterministic Validation Engine (`app/preparation.py`)
Critical financial and regulatory checks are **never delegated to an LLM**. They are executed deterministically in Python:
- **Financial Cross-Checks**: Compares claimed reimbursement amounts against sum of itemized hospital bills and payment receipts.
- **Identity & Account Validation**: Validates Indian IFSC formats (`^[A-Z]{4}0[A-Z0-9]{6}$`), bank account number digits (6–20 digits), and checks if the account holder matches the policyholder/patient.
- **Timeline & Chronology Checks**: Verifies that discharge date $\ge$ admission date and ensures hospital admission fell within the active policy validity period.
- **Duplicate Bill Detection**: Identifies and flags duplicate bill numbers from the same hospital across separate uploaded files.
- **KYC Rules**: Flags missing identity documents when claims exceed ₹1,00,000 for relevant insurers (e.g., HDFC ERGO, Niva Bupa).

### 4. Official PDF Form Pre-fill & ZIP Pack Engine (`app/forms.py`, `app/submission.py`)
- **Pixel-Accurate Coordinate Mapping**: Overlays verified form values directly onto genuine insurer claim form templates (stored in `app/assets/forms/`).
- **Submission Pack Generation**: Using `ReportLab` and Python's `zipfile`, generates:
  - `claim_form_prefilled.pdf`: The official insurer form prefilled with confirmed values.
  - `submission_guide.pdf`: Step-by-step instructions with remaining manual items (e.g., doctor stamps, claimant signatures).
  - `document_checklist.pdf` & `audit_manifest.json`: Complete audit trail of confirmed fields, page numbers, and confidence ratings.
  - `attachments/`: Normalized, legible PDF copies of supporting documents.
  - `originals/`: Untouched original files as uploaded by the user.

### 5. In-Claim Assistant & Contextual Chat (`app/health_chat.py`)
- Answers questions about missing documents, submission deadlines, and portal rejection tips.
- Evaluates routine queries locally using regex matching and versioned guidance; falls back to Gemini only for complex custom questions, caching answers by claim revision.

---

## End-to-End Processing Flow

The following sequence outlines how a claim moves from initial intake to final ZIP pack download:

```mermaid
flowchart TD
    Start([1. Start Claim Intake]) --> Step1[Enter Patient, Hospital, Admission Dates & Treatment]
    Step1 --> Step2{2. Policy Ingestion Mode}

    Step2 -->|Upload PDF| P_Upload[Upload Policy Schedule / Wording]
    Step2 -->|Find Online| P_Find[Search Allowlisted Insurer Domains]
    Step2 -->|Skip Policy| P_Skip[Provisional Checklist Mode]

    P_Upload --> Step3[3. Upload Supporting Documents<br/>Bills, Discharge Summary, Receipts, Cheque]
    P_Find --> Step3
    P_Skip --> Step3

    Step3 --> DocCheck[Local Reading & RapidOCR<br/>Page previews, blur checks, SHA-256 fingerprinting]

    DocCheck --> CacheDecision{Hash Found in Cache?}
    CacheDecision -->|Yes| Hit[Load Cached Extraction]
    CacheDecision -->|No| BatchCall[Batch Gemini Structured Extraction<br/>One call for new/changed documents]

    Hit --> ValStep[4. Run Deterministic Business Rules]
    BatchCall --> ValStep

    ValStep --> ReviewUI[5. Side-by-Side Review Screen<br/>Compare extracted facts with page preview]
    ReviewUI --> UserConfirm[User Confirms Values & Conditional Questions]

    UserConfirm --> ValidCheck{Validation Passed?}
    ValidCheck -->|Issues / Missing Docs| Fix[Flag Errors & Needs Attention]
    Fix --> ReviewUI

    ValidCheck -->|Passed| Prefill[6. Form Template Autofill<br/>Overlays data onto authentic insurer PDF]
    Prefill --> Approve[7. Explicit Human Approval]
    Approve --> PackGen[8. Generate Claim Pack ZIP<br/>Prefilled form, guide, attachments, originals]
    PackGen --> Finish([Ready for Physical / Portal Submission])
```

---

## LangGraph Workflow State Machine

For policy verification, requirements planning, and structured human approval, ClaimWeave provides a notebook-inspired, source-grounded LangGraph workflow (`app/agent/workflow.py`). It utilizes a PostgreSQL checkpointer (`langgraph-checkpoint-postgres`) with human-in-the-loop interrupt:

```mermaid
stateDiagram-v2
    [*] --> acquire : Claim Initialized
    acquire --> extract_policy : Policy Provided
    acquire --> classify : No Policy (Provisional)

    extract_policy --> verify : LLM Extracts Requirements & Quoted Evidence
    verify --> classify : Policy Matches Claim Identity
    verify --> [*] : Policy Mismatch (Halt)

    classify --> requirements : Classify Treatment & Route
    requirements --> extract_documents : Map Insurer / Policy Requirements
    extract_documents --> check_documents : Extract Supporting Document Fields
    check_documents --> draft : Compare Uploaded vs Mandatory Documents
    draft --> validate : Assemble Form Draft

    validate --> review : Validation Passed
    validate --> [*] : Validation Failed (Wait for User Action)

    review --> finalize : Human Review Interrupt (Approved)
    review --> [*] : Human Review Rejected

    finalize --> [*] : Claim Pack Ready for Download
```

---

## Token & Cost Optimization Strategy

ClaimWeave AI is intentionally engineered to minimize LLM token consumption and external API dependency:

| Operation | LLM Call? | Mechanism / Caching Strategy |
|---|---|---|
| Document OCR | **No** | Local PyMuPDF text reader & on-device `RapidOCR` (ONNX) |
| Page quality & blur check | **No** | Local Laplacian variance algorithm via NumPy/Pillow |
| New document extraction | **Yes** | 1 structured call per batch (up to 8 files / 240k characters) |
| Re-analyzing unchanged documents | **No** | Content-addressed SHA-256 cache in PostgreSQL |
| Checklist evaluation | **No** | Evaluated via local `app/health_guidance.json` |
| Field confirmations & edits | **No** | Handled deterministically in application database |
| Arithmetic & cross-validation | **No** | Deterministic Python rules |
| Official PDF Form prefill | **No** | PyMuPDF point-coordinate overlay |
| Claim pack ZIP assembly | **No** | ReportLab PDF generator & Python `zipfile` |
| Routine Chatbot questions | **No** | Local rule/regex matching against saved claim state |

---

## Technology Stack

### Backend
- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.11+ / 3.13) with [Uvicorn](https://www.uvicorn.org/)
- **Database & Migration**: [PostgreSQL 17](https://www.postgresql.org/), [SQLAlchemy 2.0](https://www.sqlalchemy.org/), [psycopg 3](https://www.psycopg.org/), [Alembic](https://alembic.sqlalchemy.org/)
- **Agent & Orchestration**: [LangGraph](https://github.com/langchain-ai/langgraph), `langgraph-checkpoint-postgres`
- **Generative AI**: [Google Gemini](https://ai.google.dev/) (`gemini-2.5-flash`) via `langchain-google-genai` & `google-genai`
- **Document & Image Processing**:
  - [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/): High-performance PDF text parsing, page rendering, and form overlay
  - [RapidOCR](https://github.com/RapidAI/RapidOCR) & [onnxruntime](https://onnxruntime.ai/): Fast on-device OCR
  - [Pillow (PIL)](https://python-pillow.org/) & [NumPy](https://numpy.org/): Image normalization and blur/quality analysis
  - [pypdf](https://pypdf.readthedocs.io/): Fallback PDF reading
  - [ReportLab](https://www.reportlab.com/): Programmatic generation of submission guides and checklists
- **Security & Authentication**: [PyJWT](https://pyjwt.readthedocs.io/), [pwdlib](https://frankie567.github.io/pwdlib/) with Argon2

### Frontend
- **Framework**: [React 19](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/)
- **Bundler & Tooling**: [Vite 6](https://vitejs.dev/)
- **Icons & Styling**: [Lucide React](https://lucide.dev/), Modular Vanilla CSS design system

---

## Supported Insurers & Official Templates

Official claim forms are verified by SHA-256 checksums and source-pinned in `app/assets/forms/manifest.json`:

| Insurer | Supported Policy Forms | Official Source Review Date |
|---|---|---|
| **Star Health** | Health Insurance Claim Form (Part A & B) | 2026-03-24 |
| **HDFC ERGO** | Standard Hospitalization Reimbursement Form | 2026-03-24 |
| **HDFC ERGO** | my:Optima Secure Individual Claim Form | 2026-03-24 |
| **Care Health** | Comprehensive Reimbursement Claim Form | 2026-03-24 |
| **Niva Bupa** | Health Insurance Reimbursement Form | 2026-03-24 |

---

## API Reference

All protected endpoints require an `Authorization: Bearer <token>` header.

### Authentication & Account
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/auth/register` | Register a new account and receive a JWT |
| `POST` | `/api/v1/auth/login` | Sign in with email and password |
| `GET` | `/api/v1/auth/me` | Retrieve the authenticated user profile |

### Claims Management
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/claims` | Create a new claim |
| `GET` | `/api/v1/claims` | List claims belonging to the current user |
| `GET` | `/api/v1/claims/{id}` | Retrieve details of an owned claim |
| `PATCH` | `/api/v1/claims/{id}` | Update structured health intake |
| `DELETE` | `/api/v1/claims/{id}` | Delete a claim and its stored documents |

### Documents & OCR
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/claims/{id}/documents` | Upload a PDF or JPG/PNG/TIFF file (max 10 MB) |
| `DELETE` | `/api/v1/claims/{id}/documents/{doc_id}` | Remove a document (invalidates existing approvals) |
| `GET` | `/api/v1/claims/{id}/documents/{doc_id}/preview?page=N` | View rendered PNG page preview |
| `PATCH` | `/api/v1/claims/{id}/documents/{doc_id}/review` | Save human field confirmations & category reviews |

### Preparation, Validation & Export
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/claims/{id}/preparation` | Get current preparation state and checklist |
| `POST` | `/api/v1/claims/{id}/preparation/analyze` | Trigger batch OCR and Gemini extraction for changed files |
| `PATCH` | `/api/v1/claims/{id}/preparation` | Save checklist answers and manual form values |
| `POST` | `/api/v1/claims/{id}/preparation/approve` | Approve validated revision for export |
| `GET` | `/api/v1/claims/{id}/preparation/form` | Download prefilled official claim form PDF |
| `GET` | `/api/v1/claims/{id}/preparation/pack` | Download complete submission pack ZIP |

### Policy Discovery & Workflow
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/claims/{id}/policy/discover` | Query official insurer domains for policy PDFs |
| `POST` | `/api/v1/claims/{id}/policy/confirm` | Confirm an official web policy candidate |
| `POST` | `/api/v1/claims/{id}/workflow/start` | Launch LangGraph claim preparation workflow |
| `GET` | `/api/v1/claims/{id}/workflow` | Check LangGraph workflow status and checkpoints |
| `POST` | `/api/v1/claims/{id}/workflow/chat` | Send question to the contextual claim assistant |

---

## Local Setup & Installation

### Prerequisites
- **Python 3.11+** (or Python 3.13)
- **Node.js 20+** & **npm**
- **Docker** (for running local PostgreSQL)
- **Google Gemini API Key** (get one at [Google AI Studio](https://aistudio.google.com/))

### 1. Clone & Configure Environment

```powershell
# Clone the repository
git clone https://github.com/aarnasingh812/ClaimWeave-AI.git
cd ClaimWeave-AI

# Create and activate Python virtual environment
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1

# Install backend dependencies
pip install -r requirements.txt

# Copy environment configuration
Copy-Item .env.example .env
```

Edit `.env` and set:
```env
DATABASE_URL=postgresql+psycopg://claimpilot:claimpilot@127.0.0.1:5432/claimpilot
JWT_SECRET=your-secure-random-32-plus-character-secret
GOOGLE_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-2.5-flash
STORAGE_DIR=private_uploads
```

### 2. Start PostgreSQL & Run Migrations

```powershell
# Start local PostgreSQL container
docker compose up -d db

# Run Alembic migrations for application tables
alembic upgrade head

# Initialize LangGraph PostgreSQL checkpoint tables
python -m app.db.checkpoints

# Start the FastAPI development server
uvicorn app.main:app --reload
```

Backend will be available at:
- **API Server**: `http://127.0.0.1:8000`
- **Swagger Docs**: `http://127.0.0.1:8000/docs`

### 3. Start Frontend

Open a separate PowerShell terminal:

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Frontend will be running at `http://localhost:5173`.

---

## Docker Development Setup

You can run the entire stack (PostgreSQL + FastAPI + Vite Frontend) using Docker Compose:

```powershell
# Build and start all services
docker compose --profile full up -d --build

# Run one-time database setup inside the container
docker compose --profile full exec api alembic upgrade head
docker compose --profile full exec api python -m app.db.checkpoints
```

> [!NOTE]
> The Docker full profile is intended for **local development only** (uses local passwords, Vite dev server, and unencrypted local volumes).

---

## Security, Audit & Limitations

- **Source-Grounded, Not Legally Binding**: LLM extractions and checklists are assistive tools. Users must review all extracted numbers and dates against physical hospital documents.
- **Data Protection**: Document storage and LangGraph PostgreSQL checkpoint payloads store clinical information, medical bills, and personal identity numbers. Ensure appropriate volume encryption and access control before deploying to cloud environments.
- **No Direct Portal Submission**: ClaimWeave does not automate insurer portal login, CAPTCHA bypass, or direct API submission. It creates a complete pack ready for manual or portal submission.
- **Signatures & Hospital Stamps**: Claim form sections requiring doctor signatures, medical superintendent declarations, and hospital stamps must be completed manually.
