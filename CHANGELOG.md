# Changelog

## 0.1.0 (2026-08-06) — Windows port, published

Initial GitHub release of DanusWin (based on upstream Danus 0.1.0).

### Fixed in this release

- **mcp compatibility (P0):** pinned `mcp>=1.2,<2` in `pyproject.toml` and `启动Danus.bat`. mcp 2.x removed `mcp.server.fastmcp`, which broke `python -m danus.gateway` (the role-gated MCP server behind `fact_submit` / `gm_add`). Added regression tests (`danus/tests/test_gateway_import.py`) and verified the stdio MCP server end-to-end.
- **Relocatable install:** the editable install is refreshed on move (`pip install -e .`), and `runtime/` worker configs no longer hard-code absolute paths.
- **Windows process supervision:** CLI `stop --force` now terminates the whole process tree via psutil (no `SIGKILL`/`killpg` on Windows; `signal.SIGKILL` does not exist there); `spawn_loop` records the real interpreter pid (Windows venv `python.exe` is a redirector); `_alive` uses psutil on Windows.
- **Cross-platform test suite:** `pytest` now passes on Windows (491 tests). POSIX-only semantics (flock, killpg, /proc zombies, `os.geteuid`, `fork`, chmod(0)) are either adapted or explicitly skipped on Windows; fakes are `.py`/`.cmd` on Windows.
- **Chinese-path robustness:** config reads use explicit UTF-8 (paths may contain non-ASCII, e.g. `E:\Desktop\数学`).
- **Restored renderer assets:** `.claude/skills/{human-summary,write-paper}` (needed by the write-paper / human-summary renderers and their tests).
- **Secrets hygiene:** `config/settings.json` is gitignored (contains the API key); `config/settings.example.json` is the committed template.

### Known issues

- DeepSeek API **balance must be topped up** before workers can run (codex CLI returns `402 Insufficient Balance` otherwise).
- Verify service can return connection resets under heavy concurrent load from 4 workers (see 复盘报告).
- OpenCode Go provider option depends on provider/codex-CLI wire compatibility.

See [PATCHES.md](PATCHES.md), [docs/复盘报告.md](docs/复盘报告.md) for the full retrospective.