# Installation and reproducible verification

Use Python 3.13 (3.13.2 is the original baseline) and Node.js 20 or 22. The
platform uses the existing FastAPI server and browser JavaScript; no Node build
step is required for the workbench.

```powershell
git clone https://github.com/TZUKWAN/dayan-simulation.git
cd dayan-simulation
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pip check
.venv\Scripts\python tests/check_sources.py
.venv\Scripts\python tests/run_all.py
.venv\Scripts\python -m dayan.server
```

On Linux/macOS, replace `.venv\Scripts\python` with `.venv/bin/python`. Open
`http://127.0.0.1:8899/` directly. The local page bootstraps a private HttpOnly
session. APIs require that session or a Bearer capability stored in the selected
data directory's `.workbench-token`; never put it in URLs or a public deployment.
The service remains bound to loopback. The DSH tool bridge reads the same private
capability and must use the same `DAYAN_DATA_DIR` as its backend.

For a separately stored project, set `DAYAN_DATA_DIR` and `DAYAN_REPORTS_DIR` to
writable private directories. Existing runs are immutable; clearing history only
changes visibility. Startup and tests do not rewrite tracked HTML or fixtures.

The opening workspace shows the simulation/research stage and live engine telemetry.
The second page lists historical runs for replay, analysis and reports; modeling uses
the native AI conversation and contextual controls without duplicate mode switches.
The right divider supports drag, arrow keys and double-click reset. Use
`Ctrl/Cmd+K` to find recorded runs, datasets, and workspaces. The data centre
offers the World Bank Data360 annual WDI and TIGERweb 2020 spatial presets.
The integrated workbench runs without a CDN. Three.js is bundled under MIT and
the checked-in Chinese plotting font is under OFL. See
[browser assets](../site/console/vendor/) and [font assets](../assets/fonts/).

DSH uses the project-owned native conversation and its own configured language
model. Install the plugin using `link:/absolute/path/dayan-simulation/plugins/dayan`
and load it in DSH. For a separate project set `DAYAN_PROJECT_ROOT`,
`DAYAN_DATA_DIR`, `DAYAN_REPORTS_DIR`, and `DAYAN_PYTHON` in that DSH host so
the Python service and the plugin agree. If connecting to a separately started
engine, set `DAYAN_BACKEND_URL` to its loopback URL. Reload the plugin in DSH
to activate code changes. The current native session restores its last workbench
record after a page reload.

## External services

The default test command makes no live LLM calls and needs no historical data.
It discovers all `tests/**/test_*.py` and `tests/**/*.test.mjs`, explicitly reports
unselected online/LLM suites as skipped, and retains their real exit status.

Set `DAYAN_API_KEY`, `DAYAN_BASE_URL` (OpenAI-compatible API root), and
`DAYAN_MODEL`, or copy `dayan/config.example.json` to private `dayan/config.json`.
Provider limits are discovered from model metadata or the specific documented
provider profile. Local LM Studio uses its **loaded** context. Unknown limits
remain unverified; no artificial universal maximum is invented. Full input and
history are preserved; an input beyond a known context is explicitly refused.
`DAYAN_CONTEXT_WINDOW` / `DAYAN_MAX_OUTPUT_TOKENS` can tighten deployment limits.

```powershell
python tests/run_all.py --only test_online_sources --online
python tests/run_all.py --only test_live_llm --llm
```

The first command downloads actual World Bank and Census records and checks
the study/report chain and spatial data ports. The second makes a paid call
for each of the five language-model agent entries. The isolated test runner
expects the exported environment settings for that command. It excludes the
private `config.json` from its temporary checkout. Scientific holdout and
pipeline outcomes are recorded separately.

## Budgets, fonts and archives

`dayan/limits.py` defines bounded concurrency, queue length, time/CPU/RSS/disk,
request bytes, total steps, arms, seeds, entities and sampled frames. Individual
positive overrides are `DAYAN_` plus the uppercase field name, for example
`DAYAN_TOTAL_STEPS`. Rejected and interrupted jobs retain terminal status; an
interrupted paid task is never automatically replayed. Metrics retain every
observation while view frames are sampled with first and final states retained.

The bundled Noto Sans CJK SC font makes Matplotlib Chinese plots independent of
system fonts. Its OFL license, source URL and hash are in `assets/fonts/`.
DOCX contains Unicode text and names the font; viewing machines need it or
another Chinese fallback. Linux font installation instructions are in that folder.

A run ZIP contains exact source bytes, file hashes, the dependency/environment
inventory and bound input originals. Verify and optionally execute a trusted ZIP
in a **new** output directory:

```powershell
python -m dayan.replay .\downloaded-run.zip --output .\verified-run
python -m dayan.replay .\downloaded-run.zip --output .\reexecuted-run --execute
```

`--execute` runs archived Python. Use it only for trusted research packages.
External LLM results retain their original actions and audit for replay; the
tool refuses to fabricate an offline LLM rerun. Changed execution source is
rejected rather than silently archived as another version.

GitHub Actions verifies the complete offline entry, Python/JavaScript syntax,
the Python dependency graph, actual local HTTP/model integration, Chinese
rendering and tracked-file cleanliness on Windows and Linux. Online credentials
and private research artifacts are excluded from CI and from Git.

For repeatable headless UI verification, install `requirements-ui.txt` and run
`python -m playwright install firefox`. Start a separate local server with a new
`DAYAN_DATA_DIR`, then run:

```powershell
python tests/browser_acceptance.py --base-url http://127.0.0.1:8918 --output .claude/browser-verification
```

This exercises seven workspaces, the command palette, model discovery, actual
professional runs and paired experiments, linked analytics export, archive
lookup, rendered coordinates, state transitions, playback and resizing.
The 4,000-actor archive checks genuine instance identities and positions with
up to 3,000 rendered at once. Screenshots and render measurements are written
to the supplied output directory for the separate headless browser. The real
provider, WDI and TIGERweb runs have separate records in
[research cases](VNEXT_RESEARCH_CASES.md) and [acceptance](VNEXT_ACCEPTANCE.md).
