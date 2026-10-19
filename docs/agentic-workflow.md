# ClaimWeave: current health-claim workflow

This diagram follows the current structured health-claim journey. The application
orchestrates the steps through preparation APIs; Gemini performs document extraction
and answers custom questions. Local rules build the checklist and validate the claim.
Human review and approval remain explicit.

```mermaid
flowchart TD
    A([Start a new claim]) --> B[User enters patient, treatment and hospital details]
    B --> C{Claim route?}
    C -->|Cashless| D[Show insurer guidance; contact hospital insurance desk]
    C -->|Reimbursement| E{Policy PDF available?}
    E -->|Yes| F[Read policy text locally; OCR scanned pages]
    F --> G[Gemini extracts policy facts and cited requirements]
    G --> H{Insurer and product match?}
    H -->|Yes| I[Combine verified policy requirements with insurer guidance]
    H -->|No| J[Flag policy mismatch; use provisional insurer guidance]
    E -->|Add later| J
    I --> K[Show document checklist, upload instructions and deadline guidance]
    J --> K
    K --> L[User answers applicability questions and uploads under checklist items]
    L --> M[Read uploaded records locally; OCR scans and photos]
    M --> N[Gemini extracts document types, values and page evidence]
    N --> O[Check extracted evidence against source text]
    O --> P[User reviews and corrects values, categories and page quality]
    P --> Q[Prefill insurer form; user checks form and policy applicability]
    Q --> R{Local validation passes?}
    R -->|No| S[Show missing items, mismatches or unanswered questions]
    S -->|Correct values or form| P
    S -->|Add or replace records| L
    S -->|Add or correct policy| E
    R -->|Yes| T[User explicitly approves the current revision]
    T --> U{Approval and source snapshot still current?}
    U -->|No; claim changed| R
    U -->|Yes| V[Generate and download submission ZIP]
    V --> W([User completes signatures and submits to insurer manually])

    K -. Ask a question .-> X{Routine question or cached answer?}
    X -->|Yes| Y[Answer from saved claim data and insurer guidance]
    X -->|No| Z[Gemini answers using claim context and chat history]
    Y -. Guidance only .-> L
    Z -. Guidance only .-> L

    classDef ai fill:#ede9fe,stroke:#7c3aed,color:#3b0764;
    classDef human fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e;
    classDef rules fill:#ecfdf5,stroke:#059669,color:#064e3b;
    classDef decision fill:#fff7ed,stroke:#ea580c,color:#7c2d12;
    class G,N,Z ai;
    class B,L,P,Q,T,W human;
    class D,F,I,J,K,M,O,S,V,Y rules;
    class C,E,H,R,U,X decision;
```

Purple nodes use Gemini. Blue nodes involve user input or confirmation. Green
nodes represent application logic, local document tools, or displayed guidance.
Orange diamonds are decisions or checks.

## Implementation details

- **Planning precedes supporting-document analysis.**
  `POST /api/v1/claims/{id}/preparation/plan` reads only the optional policy.
  Without a policy, it builds a provisional insurer checklist without an extraction call.
  Requirements extracted from a mismatched policy are excluded.
- **Extraction uses a cache.** The Gemini extraction nodes run only for new or
  changed documents without a valid reusable extraction. Existing results reuse an
  owner-scoped cache; user corrections never transfer between claims.
- **Errors require recovery.** Unreadable or over-limit files remain blocking issues.
  If extraction fails, the user can retry explicitly; successful earlier batches stay
  cached. There is no automatic paid retry loop.
- **Chat assists but does not operate the claim.** Routine questions use local
  responses; custom questions require the configured Gemini key. Chat cannot upload,
  change claim data, approve a draft, or submit a claim.
- **Validation uses rules.** Checks include required documents, conditional answers,
  policy identity and applicability, field confirmations, name/date consistency,
  amounts, duplicates, bank details, and form acknowledgments. Saved corrections
  rerun checks without another Gemini call.
- **State is persisted.** PostgreSQL stores claim state, revisions, extraction
  metadata and user reviews. Documents remain in configured local storage.
  Uploads, edits and deletions invalidate earlier approval. Policy or intake changes
  also require the document plan to be refreshed.
- **Approval is preparation approval.** ZIP export rechecks the current revision
  and source snapshot. Signatures, hospital sections, insurer filing and the insurer's
  coverage decision remain outside automatic submission.

## Code map

| Responsibility | Source |
| --- | --- |
| Guided claim journey and uploads | `frontend/src/ClaimJourney.tsx` |
| Chat interface | `frontend/src/ClaimAssistant.tsx` |
| Document/form review and approval controls | `frontend/src/PreparationWorkspace.tsx` |
| Planning, analysis, reviews, approval and export APIs | `app/api/preparation.py` |
| Local document reading, quality checks and OCR | `app/documents.py` |
| Cached Gemini extraction and evidence grounding | `app/extraction.py` |
| Checklist construction, validation and revision invalidation | `app/preparation.py` |
| Local and Gemini chat responses | `app/health_chat.py` |
| Official form prefilling and submission ZIP generation | `app/forms.py`, `app/submission.py` |

Older claims without structured health intake still use the separate LangGraph
workflow in `app/agent/workflow.py`. That legacy graph includes claim classification
and a checkpointed human-review interrupt. It is not the execution engine for the
current guided health-claim journey shown above.
