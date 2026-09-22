# Maestro LLM Test Platform

Local Android automation platform that turns structured Excel test cases into validated Maestro flows, generates pytest fixtures, executes on an Android Studio emulator, and records repair evidence and results.

M0 through M3 currently provide:

- Frozen technical design, API contract, and Flow IR V1 Schema.
- FastAPI service with health, capability, and schema endpoints.
- Domain models and a guarded run state machine.
- Local probes for Maestro, ADB, Android Emulator, Maestro MCP, devices, AVDs, and the configured Android package.
- Typed Maestro CLI runner and managed MCP stdio/JSON-RPC client.
- React/TypeScript system-baseline console.
- Three-sheet Excel import with exact cell-level validation and immutable source snapshots.
- Stable fixture dependency planning with cycle/missing-dependency blocking.
- Schema-bound LLM Flow IR adapter, deterministic offline translator, and Maestro YAML compiler.
- Maestro `check-syntax`, source-to-command preview, and individual or batch review approval.
- Deterministic pytest packages with one item per Case and dependency-aware setup/teardown fixtures.
- Android emulator selection, boot/package preparation, real Maestro execution, JUnit, trace, logs, and artifacts.
- Persisted Run state/events, cancellation, SSE resume, result aggregation, and a Web run console.
- Process isolation with argument arrays, `shell=False`, timeout phases, output caps, and process-group cleanup.
- Deterministic failure classification, Maestro MCP hierarchy/screenshot diagnostics, evidence-backed text-selector repair, and bounded full-lifecycle retries.
- Immutable attempt/repair artifact ledgers, timestamped Excel result writeback, unified HTML reports, and refresh-safe result deep links.

M0, M1, M2, and M3 are accepted. M3 completed a real locator-repair Run and a separate real assertion-protection Run on the Android Studio emulator. Android credential services were restored to their exact original values after each authorized acceptance transaction. Evidence is tracked in
[`docs/m0-status.md`](docs/m0-status.md), [`docs/m1-status.md`](docs/m1-status.md), [`docs/m2-status.md`](docs/m2-status.md), and [`docs/m3-status.md`](docs/m3-status.md). Milestone gates are frozen in
[`docs/milestone-acceptance-v1.md`](docs/milestone-acceptance-v1.md).

M4 is planned, not yet accepted. Its tasks and release gates are in
[`docs/m4-plan.md`](docs/m4-plan.md); the Chinese environment/setup, operation, and
Excel field guide is [`docs/user-guide-v1.md`](docs/user-guide-v1.md). The guide marks
known M4 contract gaps, including unattended approval of warning-bearing flows.

## Start the local application

After installing backend and frontend dependencies, start both services with one command:

```bash
make dev
```

Do not keep Maestro Studio connected to the same emulator while this platform is using
Maestro CLI or MCP. Maestro Studio 0.9.5 and CLI 2.10.0 can otherwise compete for the
same Android Driver session.

## Backend

```bash
python3 -m pip install -e '.[dev]'
uvicorn maestro_app.main:app --app-dir backend/src --reload
```

Backend URL: `http://127.0.0.1:8000`

Useful endpoints:

- `GET /api/v1/health`
- `GET /api/v1/system/capabilities`
- `GET /api/v1/schema/flow-ir`
- `POST /api/v1/workbooks`
- `GET /api/v1/workbooks/{workbook_id}/validation`
- `POST /api/v1/generations`
- `GET /api/v1/generations/{generation_id}/flows/{flow_id}`
- `POST /api/v1/generations/{generation_id}/approval`
- `POST /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/cases/{case_id}`
- `GET /api/v1/runs/{run_id}/events`
- `GET /api/v1/runs/{run_id}/artifacts/{artifact_id}`
- `GET /api/v1/runs/{run_id}/result-workbook`
- `POST /api/v1/runs/{run_id}/cancel`
- `GET /docs`

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend URL: `http://127.0.0.1:5173`

Vite proxies `/api` to the local backend. Set `VITE_API_BASE_URL` only when the backend uses another origin.

## Tests

```bash
make verify
```

To collect MCP device, hierarchy, and screenshot evidence:

```bash
maestro-app-m0-verify \
  --device-id emulator-5554 \
  --output-dir runtime/m0-mcp-evidence
```

To run the repeatable M1 Excel-to-IR-to-YAML acceptance workflow:

```bash
maestro-app-m1-verify \
  --workbook /absolute/path/to/Maestro_pytest_LLM_APP_测试用例模板.xlsx \
  --output-dir runtime/m1-acceptance-evidence
```

The command imports an immutable copy, verifies entity counts and the fixture plan,
compiles all enabled flows, runs the configured Maestro `check-syntax`, approves all
valid flows, and confirms that the original workbook hash is unchanged.

To execute a `ready` Generation through pytest and Maestro on the configured emulator:

```bash
maestro-app-m2-verify \
  --generation-id <ready-generation-id> \
  --repeat 3 \
  --evidence runtime/m2-acceptance/evidence.json
```

The command exits non-zero unless every Run reaches `COMPLETED`. Before unattended
execution, prepare the dedicated AVD as described in
[`docs/m2-operations.md`](docs/m2-operations.md); in particular, use an English
keyboard input engine for ASCII credentials and prevent password-manager overlays.
On an explicitly authorized, dedicated test AVD, the opt-in
`--temporarily-disable-credential-services` flag snapshots the exact Android values,
temporarily suppresses the services, and restores plus verifies them on completion or
exception. It must be paired with an evidence path and an explicit emulator ID.

To execute the M3 real locator-repair acceptance branch:

```bash
maestro-app-m3-verify \
  --generation-id <ready-generation-with-stable-locator-failure> \
  --evidence runtime/m3-acceptance/locator-evidence.json \
  --temporarily-disable-credential-services \
  --settings-evidence runtime/m3-acceptance/locator-credential-services.json
```

For the assertion-protection branch, pass `--expected-outcome assertion-failure`.
The command succeeds only when the Run ends with one `ASSERTION` Attempt, zero
repairs, and `COMPLETED_WITH_FAILURES`. Result workbooks, `report.html`, manifests,
attempt evidence, and repair evidence are stored under the Run directory.

## Local configuration

Copy `.env.example` to `.env` or export the required variables before starting the backend. The application does not load `.env` automatically; shell or process-manager environment variables are authoritative. Set `LLM_BASE_URL`, `LLM_MODEL`, and optionally `LLM_API_KEY` to use an OpenAI-compatible structured-output endpoint. If they are absent, M1 uses the documented deterministic Chinese-step translator for local/offline acceptance.

When `MAESTRO_COMMAND` or `EMULATOR_COMMAND` is not on `PATH`, the backend also checks the common macOS user installation locations.

Use this application only in a controlled local environment. Excel files, generated YAML, logs, screenshots, and result artifacts may contain test accounts or test data.
