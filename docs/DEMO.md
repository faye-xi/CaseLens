# CaseLens Five-Minute Demo

This Demo uses one clearly synthetic case, a deterministic `MockModel`, a local
SQLite database, and a simulated refund. It performs no real payment action and
requires no API key.

## Start the product

In PowerShell terminal 1:

```powershell
Set-Location backend
$env:CASELENS_DB_PATH = "$PWD\caselens-day15-demo.db"
$env:UV_CACHE_DIR = "$PWD\..\.codex\uv-cache"
uv sync
uv run uvicorn main:app --reload
```

Use a new database filename if that file already contains a completed Demo.

In PowerShell terminal 2:

```powershell
Set-Location frontend
$env:npm_config_cache = "$PWD\..\.codex\npm-cache"
npm.cmd ci
npm.cmd run dev
```

Open `http://127.0.0.1:5173`.

## Walkthrough

### 0:00–0:40 — Define the product problem

Open `CASE-DEMO-001`. Explain that a refund dispute cannot be decided from the
customer sentence alone: the system must retrieve business evidence, select the
policy effective when the dispute occurred, ground its recommendation, and stop
before a high-risk action.

### 0:40–1:30 — Run the investigation

Select **Start review**. Point out:

- the customer claim and retrieved refund record are separate evidence sources;
- the displayed evidence comes from the persisted review snapshot;
- the refund is still `processing`, so the evidence is complete and not
  conflicting.

### 1:30–2:10 — Show time-sensitive policy grounding

In the decision panel, show the selected policy version and exact quoted clause.
Explain the half-open policy timeline: a case at a version boundary selects the
new version, while a legitimate gap safely produces no decision packet.

### 2:10–3:15 — Show the safety boundary

The high-risk `approve_refund` recommendation is initially
`waiting_approval`. Enter a reviewer identity and approve it. Only then does the
execution button become available.

Select **Execute approved refund**. The simulated action completes the existing
refund using a resource-scoped idempotency key; it does not create a second
refund. Select **Verify final state**. The verifier independently reads the
stored refund and the workflow reaches `completed_verified` only after the
read-back matches.

### 3:15–3:50 — Show audit replay

Open **View trace**. Show ordered model and read-only tool traces from the durable
replay record. Emphasize that the UI does not invent a confidence score and that
completion is based on stored business state, not model prose.

### 3:50–5:00 — Run the regression evaluation

In terminal 3:

```powershell
Set-Location backend
uv run python -m caselens.evaluation --check
Get-Content evals/results/day15-baseline.md
```

Use three cases to explain the engineering value:

- `processing_refund_v1` demonstrates a grounded normal decision;
- `payment_tool_timeout` becomes an explicit source failure without a packet;
- `verification_mismatch` prevents a successful action receipt from becoming a
  false verified completion.

Close with the measured scope: 12 synthetic cases, one dispute type, a scripted
model-only ablation, and no real provider or payment integration. The result is
a reproducible V0.1 regression baseline, not a production-performance claim.
