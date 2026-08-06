#!/usr/bin/env python3
"""
fix-hermes-desktop-message-loss.py
==================================
一键修复 Hermes Agent 桌面版的「消息发出后休眠/关机就丢失」问题。

问题背景
--------
桌面版 Hermes 的消息默认要等一轮对话的 build_turn_context 走完才写入
state.db。如果在这之前电脑休眠/关机、图片分析失败、或 provider 卡死，
用户刚发出去的消息只存在于内存，重启后消失（界面显示"发出去了"，但
第二天打开就不见了）。

本脚本做两件事：
1. tui_gateway/server.py —— 在调用 run_conversation 之前，把用户消息
   立即写入 state.db（持久化用户原文而非图片占位符），并通过
   _pending_cli_user_message + _db_persisted 标记让 agent 的 flush 跳过，
   不产生重复行。
2. run_agent.py —— 当 _session_db 不可用时不再静默跳过，输出明确警告，
   让"消息未持久化"的原因可见。

特性
----
- 幂等：重复运行安全，已修复的文件会自动跳过。
- 自动定位：支持 git 安装 (~/.hermes/hermes-agent) 与 pip 安装。
- 安全：修改前自动备份 (.bak.时间戳)，语法校验失败不落盘。
- 无第三方依赖：仅用 Python 标准库。

用法
----
    python3 fix-hermes-desktop-message-loss.py [Hermes安装目录]

不带参数时自动探测安装目录。修复后需重启 Hermes 桌面 app 生效。
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ───────────────────────────── 补丁定义 ─────────────────────────────
# 每个补丁: (文件名, 旧串, 新串, 幂等标记串)
# 幂等标记串已存在于文件中 → 跳过该补丁

PATCH_RUN_AGENT_LOG = (
    "run_agent.py",
    # old: 静默返回
    """        if getattr(self, "_persist_disabled", False):
            return
        if not self._session_db:
            return
        # Persist user-message override (#48677 chokepoint): historically this""",
    # new: 加 warning
    """        if getattr(self, "_persist_disabled", False):
            return
        if not self._session_db:
            logger.warning(
                "Session DB unavailable for message flush (session=%s) — "
                "inbound user message is NOT persisted. This is the silent-loss "
                "path behind \\"message sent but gone after reboot\\": the agent "
                "was built without a session_db (or state.db failed to open), so "
                "turn-start persistence no-ops. Fix by passing session_db into "
                "AIAgent construction.",
                getattr(self, "session_id", None) or "none",
            )
            return
        # Persist user-message override (#48677 chokepoint): historically this""",
    'Session DB unavailable for message flush',
)

PATCH_TUI_CALLSITE = (
    "tui_gateway/server.py",
    # old: 直接调用 run_conversation
    """            result = agent.run_conversation(run_message, **run_kwargs)""",
    # new: 先立即持久化
    """            # ── 立即持久化用户消息（防断连/关机/休眠丢失）──────────────
            # 默认路径下，用户消息要等 build_turn_context 末尾的
            # _ensure_and_persist 才写库——中间任何一步（系统提示构建、
            # 预压缩、插件 hook、memory prefetch、图片分析）异常或进程被
            # 休眠/断电打断，消息就只悬在内存里，重启后消失。这里在调用
            # run_conversation 之前就把本条用户消息写入 state.db，并通过
            # _pending_cli_user_message 复用同一 dict（带 _db_persisted
            # 标记），让 agent 的 _flush_messages_to_session_db 因 marker
            # 跳过它——既保证立即落盘，又不产生重复行。
            # persist_user_message 必须与 staged content 一致，turn_context
            # 才会复用该 dict（见 turn_context.py expected_persist_content）。
            _persist_user_message_immediately(session, agent, prompt, run_message)
            staged_content = getattr(agent, "_pending_cli_user_message", None)
            if isinstance(staged_content, dict):
                run_kwargs["persist_user_message"] = staged_content.get("content")
            result = agent.run_conversation(run_message, **run_kwargs)""",
    "_persist_user_message_immediately(session, agent, prompt, run_message)",
)

PATCH_TUI_FUNC = (
    "tui_gateway/server.py",
    # old: 在第二个 _content_display_text 定义前插入
    """    return history


def _content_display_text(content: Any) -> str:
    if content is None:
        return """,
    # new: 新函数 + 原定义
    """    return history


def _persist_user_message_immediately(session: dict, agent, prompt: Any, run_message: Any) -> None:
    \"\"\"Persist the inbound user message to state.db BEFORE the turn runs.

    This is the guard against the "message sent but gone after reboot"
    class of loss: normally the user message only lands in state.db at the
    end of ``build_turn_context`` (the crash-resilience persist), so any
    interruption before that point — sleep/shutdown mid-turn, a vision
    analysis failure, a hung provider call, a plugin hook error — leaves the
    message dangling in memory only. Writing it here, before
    ``run_conversation`` is even called, makes the user's own words durable
    the instant they are accepted.

    Deduplication: the staged dict is handed to the agent as
    ``_pending_cli_user_message`` with the ``_db_persisted`` marker, so the
    agent's own flush skips it (``_flush_messages_to_session_db`` checks the
    marker) — no duplicate row, no role-alternation break.
    \"\"\"
    try:
        if getattr(agent, "_persist_disabled", False):
            return
        db = getattr(agent, "_session_db", None) or _get_db()
        if db is None:
            return
        key = session.get("session_key")
        if not key:
            return
        # The content we persist is the user's message as accepted by the
        # gateway: the plain prompt (or the multimodal parts flattened to
        # text). If image analysis failed earlier, the original prompt text
        # is still what the user actually typed — persist that, not the
        # "[The user attached an image but analysis failed.]" placeholder.
        persist_content = prompt if isinstance(prompt, str) else None
        if persist_content is None:
            # Multimodal list content: keep text parts, mark images.
            txt_parts = []
            if isinstance(run_message, list):
                for p in run_message:
                    if isinstance(p, dict) and p.get("type") == "text":
                        txt_parts.append(str(p.get("text", "")))
            persist_content = "\\n".join(txt_parts) if txt_parts else None
        if not persist_content or not persist_content.strip():
            # Nothing user-typed (image-only turn): persist a minimal marker
            # so the turn itself is still durable.
            persist_content = "[image attachment]"
        staged = {"role": "user", "content": persist_content, "_db_persisted": True}
        db.append_message(
            session_id=getattr(agent, "session_id", None) or key,
            role="user",
            content=persist_content,
        )
        # Hand the same dict to the turn so its flush skips it (marker), and
        # the loop's api_messages build finds the user message where it
        # expects it.
        agent._pending_cli_user_message = staged
        agent._persist_user_message_idx = None
        agent._persist_user_message_override = persist_content
        agent._persist_user_message_timestamp = None
    except Exception as exc:
        logger.warning(
            "Immediate user-message persist failed for session=%s: %s",
            session.get("session_key"),
            exc,
        )


def _content_display_text(content: Any) -> str:
    if content is None:
        return """,
    "def _persist_user_message_immediately(session: dict, agent, prompt: Any, run_message: Any) -> None:",
)


PATCHES = [PATCH_RUN_AGENT_LOG, PATCH_TUI_CALLSITE, PATCH_TUI_FUNC]


# ───────────────────────────── 工具函数 ─────────────────────────────

def find_hermes_root(argv):  # -> Optional[Path]
    """定位 Hermes 安装目录：显式参数 > 环境变量 > 常见路径 > hermes 命令。"""
    # 1. 命令行参数
    for arg in argv[1:]:
        p = Path(arg).expanduser()
        if (p / "run_agent.py").exists():
            return p
    # 2. 环境变量
    home = Path.home() / ".hermes"
    candidates = [
        home / "hermes-agent",          # git 安装
        Path("/opt/hermes-agent"),      # 常见自定义位置
    ]
    # 3. hermes 命令报告安装目录
    try:
        out = subprocess.run(
            ["hermes", "--version"], capture_output=True, text=True, timeout=15
        ).stdout
        for line in out.splitlines():
            if "Install directory:" in line:
                p = Path(line.split(":", 1)[1].strip())
                if (p / "run_agent.py").exists():
                    return p
    except Exception:
        pass
    for c in candidates:
        if (c / "run_agent.py").exists():
            return c
    return None


def apply_patch(path: Path, old: str, new: str, idempotent_marker: str) -> str:
    """对单个文件应用一个补丁。返回状态描述。"""
    text = path.read_text(encoding="utf-8")
    if idempotent_marker in text:
        return f"SKIP  已修复（幂等标记存在）"
    if old not in text:
        return f"SKIP  未匹配旧代码（版本可能不同，跳过）"
    backup = path.with_name(path.name + f".bak.{tempfile.mktemp(suffix='').split('/')[-1]}")
    shutil.copy2(path, backup)
    text = text.replace(old, new, 1)
    # 语法校验：失败则回滚
    tmp = Path(tempfile.mktemp(suffix=".py"))
    try:
        tmp.write_text(text, encoding="utf-8")
        import py_compile

        py_compile.compile(str(tmp), doraise=True)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        return f"FAIL  语法校验失败，已回滚: {exc}"
    tmp.unlink(missing_ok=True)
    path.write_text(text, encoding="utf-8")
    return f"OK    已打补丁（备份: {backup.name}）"


# ───────────────────────────── 主流程 ─────────────────────────────

def main() -> int:
    root = find_hermes_root(sys.argv)
    if root is None:
        print("❌ 找不到 Hermes 安装目录。")
        print("   请手动指定：python3 fix-hermes-desktop-message-loss.py /path/to/hermes-agent")
        return 1

    print(f"📂 Hermes 安装目录: {root}")
    results = []
    for fname, old, new, marker in PATCHES:
        fpath = root / fname
        if not fpath.exists():
            results.append((fname, "SKIP  文件不存在"))
            continue
        print(f"   {fname} ...")
        results.append((fname, apply_patch(fpath, old, new, marker)))

    print()
    print("─" * 60)
    for fname, status in results:
        print(f"  {fname:<28} {status}")

    n_ok = sum(1 for _, s in results if s.startswith("OK"))
    n_skip = sum(1 for _, s in results if s.startswith("SKIP"))
    n_fail = sum(1 for _, s in results if s.startswith("FAIL"))

    print("─" * 60)
    if n_fail == 0 and n_ok >= 0:
        print(f"✅ 完成：{n_ok} 个补丁应用，{n_skip} 个跳过，{n_fail} 个失败。")
        if n_ok > 0:
            print("🚀 请重启 Hermes 桌面 app（完全退出再打开）使修复生效。")
            print("   验证：重启后发一条消息，然后休眠/关机，重开后消息应仍在。")
        else:
            print("ℹ️  所有补丁均已应用或无需修改，重启即可。")
    else:
        print(f"⚠️  有 {n_fail} 个补丁失败，请检查输出或手动修复。")
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
