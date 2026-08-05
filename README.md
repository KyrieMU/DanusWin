# DanusWin — Windows Desktop Shell for Danus

DanusWin turns **[Danus](https://github.com/frenzymath/Danus)** (an automated mathematics proof-search system that orchestrates LLM agents with a verifier-gated fact graph) into a **native Windows application**: a Chinese click-to-use web UI plus Windows-native process management, no WSL / bash required.

> **License:** Apache-2.0 (upstream Danus by Bin Wu). This port keeps the core engine semantics intact and adds a desktop shell on top.

## What it does

Danus runs a swarm of autonomous proof-search workers against a mathematical problem:

1. A **main agent** (here: the web UI + a Python strategy-consult loop) decomposes the problem and assigns directions to workers.
2. Each **worker** (a `codex` CLI session) proves claims — reading the shared memory, searching existing facts, drafting a proof.
3. Every claim goes through **`fact_submit`** → a **cold-start stateless verifier** (a fresh codex session) is the *sole authority* on correctness.
4. Accepted facts accumulate in a **content-addressed fact graph** — the system's only source of truth — and later facts cite them by `fact_id`.
5. The operator can browse the fact graph, revoke wrong facts (cascade), finalize the answer, and generate a Markdown proof report.

The separation of powers is enforced structurally: the app/main agent cannot submit facts; the verifier is read-only; only the role-gated MCP gateway can write verified facts.

## Features

- 🖥️ Double-click `启动Danus.bat` to install deps and open `http://127.0.0.1:8765`
- 🧩 Web UI (Chinese): overview, project/worker management, live worker activity, fact-graph browser, revoke/finalize, proof report
- 🔁 Windows-native process supervision (psutil): verify service + worker loops, no `setsid`/`killpg`
- 🧠 Strategy consult: DeepSeek chat API → `master_guidance` per project
- ✅ Cross-platform test suite: **491 tests passing on Windows** (also runs on Linux CI)

## Quickstart (Windows)

Requirements: **Python 3.10+** (check *Add python.exe to PATH*), **Node.js**, a **DeepSeek API key**.

```bat
:: 1. double-click 启动Danus.bat  (first run creates .venv and installs deps)
:: 2. browser opens http://127.0.0.1:8765
:: 3. Settings -> paste your DeepSeek API Key -> Save
:: 4. 总览 -> 写入 DeepSeek 配置 -> 测试连接 (expect ok)
:: 5. 项目 -> 新建项目 (english name, worker count, paste your problem) -> 创建
:: 6. 工作台 -> assign tasks (or 生成策略指引 -> 按条目分配到 Worker) -> 全部启动
:: 7. watch the fact graph grow; 事实图 -> 结题 -> 生成报告 when done
```

Headless alternative:

```bash
pip install -e .[desktop]
python -m app            # serves http://127.0.0.1:8765
```

## How to run the tests

```bash
pip install -e ".[dev]"
pytest -q                # 491 passed (Windows), full matrix on CI
```

## Configuration

- Settings are stored in `config/settings.json` (created on first run) — **never commit it**: it contains your API key. A template lives at `config/settings.example.json`.
- The app writes a codex provider config + model catalog into `runtime/codex-home/` from the UI (设置 → 写入 DeepSeek 配置).
- Worker/verifier models: `deepseek-v4-flash` via the codex CLI **Responses API** (DeepSeek direct). Strategy consult: `deepseek-v4-pro` via the chat API.

## Architecture (short)

```
app/                    FastAPI backend + static web UI (settings, supervisor, engine, consult)
danus/                  the engine (installable package)
  core/                 content-addressed fact graph + typed memory + BM25 + schema
  gateway/              role-gated MCP server (worker | verifier | main) — the only fact-write door
  verify/               cold-start verifier HTTP service (the sole correctness gate)
  execution/            worker swarm: round loop + scaffolding (Windows-aware spawn)
  orchestration/        the `danus` CLI verbs (POSIX + Windows-safe)
  strategy/             consult transports (DeepSeek / Claude API / Claude Code)
  authoring/ write_paper/ human_summary/   artifact renderers (LaTeX paper, PDF report, HTML)
agents/                 codex agent contracts + worker/verify skills
config/                 settings + templates
```

Every claim enters truth through one cycle:

```
worker → fact_submit (MCP gateway, role=worker)
       → verify service → cold-start codex verifier (stateless)
       → verdict "correct" → content-addressed fact node (with predecessors)
       → later proofs may cite its fact_id
```

## Windows-specific changes vs upstream

- `danus/codex.py` — runs the codex CLI via `node <codex.js> exec …`; supports `.py` / `.cmd` wrapper binaries
- `danus/execution/scaffold.py` — MCP gateway command uses the current interpreter; symlink→copy fallback; `CREATE_NEW_PROCESS_GROUP` spawn; real-interpreter pid bookkeeping (venv redirector)
- `danus/verify/launcher.py` — same interpreter wiring; symlink fallback; UTF-8-SIG verdict reading
- `danus/orchestration/cli.py` — psutil-based liveness / process-tree stop on Windows (no `fcntl`, `killpg`, `/proc`)
- `mcp` is pinned to `>=1.2,<2` (mcp 2.x removed `mcp.server.fastmcp`, which the gateway/renderers use)
- `app/` — new FastAPI UI + supervisor replacing the Claude-Code main agent and the bash service layer

See [PATCHES.md](PATCHES.md) and [CHANGELOG.md](CHANGELOG.md) for the full history.

## Known limitations

- Verification is **LLM-based, not Lean/Coq machine checking** — the generated report says so explicitly; review important results before publishing.
- The strategy consult uses DeepSeek chat API; the OpenCode Go bundle option depends on your provider's codex CLI compatibility (latest codex uses the Responses wire).
- `runtime/` is local-only (gitignored): projects, fact graphs, codex sessions, and logs live there. Back it up if your work matters.

## Security notes

- The app binds `127.0.0.1` only, but has no auth: any local process/page can read settings (including the API key) and start/stop workers. Use it on a trusted machine.
- Stop workers before closing the app, or the worker loops keep running (and keep spending tokens) — the supervisor kills them on `stop`, but a hard app kill can orphan them.
- Never commit `config/settings.json`; rotate the key if the folder is ever shared.