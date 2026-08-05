# DanusWin 相对上游 Danus-0.1.0 的改动（截至 2026-08-06）

## 核心引擎（danus/）——最小 Windows 适配

1. `danus/codex.py` — `exec_cmd()`：Windows 下 codex CLI 是 Node 程序，自动改为 `node <codex.js> exec ...`（无需 shell）；新增 `_node_bin()`（`DANUS_NODE` 或 PATH）；支持 `.py` / `.cmd` 包装脚本作为 codex 可执行文件（测试与自定义后端）。
2. `danus/execution/scaffold.py` —
   - worker 的 `.codex/config.toml` 中 MCP 网关命令由 `"python3"` 改为当前解释器绝对路径（Windows 无 python3）；
   - `symlink()` 在符号链接不可用时降级为复制（Windows 常见）；
   - `spawn_loop()` 在 Windows 使用 `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`，并解析 venv 重定向器后的**真实解释器 pid**（否则 .pid 记账与 loop 自清理对不上）。
3. `danus/verify/launcher.py` — 验证器 MCP 注入命令同样改为当前解释器绝对路径；symlink 降级复制；verification.json 按 UTF-8-SIG 读取（兼容 Windows 工具写 BOM）。
4. `danus/execution/loop.py` — `FileNotFoundError` 放宽为 `OSError`；轮次成功后清空旧 error（Windows 上 codex 启动失败的报错更准确）。
5. `danus/orchestration/cli.py` — Windows 适配：`_alive` 改用 psutil（无 signal-0 / /proc）；`stop --force` 用 psutil 进程树终止（Windows 无 `killpg`，且 `signal.SIGKILL` 不存在）；`fcntl` 仅在 POSIX 生效。

## 依赖（重要）

- `mcp` 钉死为 `mcp>=1.2,<2`：**mcp 2.x 移除了 `mcp.server.fastmcp`**，会导致 `python -m danus.gateway`（角色权限网关，`fact_submit`/`gm_add` 唯一入口）启动即报 `ModuleNotFoundError`。已新增回归测试 `danus/tests/test_gateway_import.py`。
- codex CLI 使用 npm `@openai/codex@latest`（实测 0.146.1），DeepSeek 直连走 `wire_api = "responses"`。此前文档中"钉死 0.93.0 / chat 接口"的说法已过期，见 CHANGELOG。
- 新增 `desktop` extra（启动Danus.bat 实际安装的依赖：fastapi/uvicorn/pydantic/openai/psutil/mcp<2）；`dev` extra 补齐 pytest 与 psutil。

## 新增（app/ 目录，Windows 桌面层）

- `app/settings.py` — 设置存取、环境注入、DeepSeek codex provider 生成、连通性测试、Codex CLI 一键安装。
- `app/supervisor.py` — Windows 原生进程管理（psutil）：验证服务启停、worker 启停（替换 bash services.sh / setsid / killpg）。
- `app/engine.py` — 项目/事实图/全局记忆操作（app 侧对真相存储只读，facts 仍由验证器把关）。
- `app/consult.py` — 策略环：elaboration → DeepSeek 咨询 → 记录 master_guidance（替代 Claude Code 主代理）。
- `app/server.py` + `app/static/` — 中文点击式网页界面（FastAPI + 原生 JS）。
- `启动Danus.bat` — 双击启动；`使用说明.md` 见 docs/。

## 已知取舍

- 未包含上游的 write-paper（LaTeX 论文生成）与 human-summary（PDF 报告）渲染器**脚本**（bin/、docs/），但代码与 `.claude/skills` 资产已补齐，测试全绿；需要时可在 Linux 侧使用上游脚本。
- 主代理由 Python/UI 替代 Claude Code：保留"主代理不能提交事实"的边界（app 无 fact_submit，只能读取/撤销）。
- 策略咨询走 DeepSeek Chat API（v4-flash / v4-pro 均可）；worker/验证器走 codex CLI 的 Responses API（DeepSeek 直连）。
- OpenCode Go 套餐选项依赖提供商与 codex CLI 的 wire 兼容性（最新 codex 统一 Responses wire），以实际连通性为准。

## 测试

- Windows 本机 `pytest -q`：491 passed（2026-08-06）。
- CI（GitHub Actions）：ubuntu-latest + windows-latest × Python 3.10/3.12。
- POSIX 专属语义（flock、killpg、/proc zombie、os.geteuid、fork、chmod(0)）在 Windows 上跳过或改用等价实现；fake codex 在 Windows 上用 .py/.cmd。