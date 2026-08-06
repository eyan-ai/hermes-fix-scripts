# Hermes Agent One-Shot Fix Scripts

Idempotent fix scripts for common Hermes Agent issues (especially the desktop app).
All scripts: **auto-backup the original file, idempotent (safe to re-run), and roll
back automatically if the syntax check fails.**

## Usage (macOS / Linux)

```bash
# One-shot (auto-detect Hermes install directory)
bash <(curl -fsSL https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.sh) fix-message-loss

# Or specify the install directory
bash <(curl -fsSL https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.sh) fix-message-loss /path/to/hermes-agent
```

## Usage (Windows PowerShell 5.1+ / PowerShell 7)

```powershell
# One-shot (auto-detect Hermes install directory)
iex "& { $(irm https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.ps1) } fix-message-loss"

# Or specify the install directory
iex "& { $(irm https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.ps1) } fix-message-loss C:\Users\you\.hermes\hermes-agent"
```

> Windows prerequisites: Python 3 installed (`python` or `py` available).
> PowerShell 5.1 parses .ps1 files without BOM as ANSI, so install.ps1 output is
> English-only on purpose; Chinese docs live in [README.zh-CN.md](./README.zh-CN.md).

**Restart the Hermes desktop app after the fix** for it to take effect.

## Scripts

| Command | Fixes |
|---|---|
| `fix-message-loss` | Desktop message lost after sleep/shutdown (user message persisted the moment it is sent) |

## Script details

### fix-message-loss — message loss fix

**Symptom**: after sending a message in the desktop Hermes, the machine sleeps or
shuts down; the message is gone when reopened the next day.

**Root cause**: the user message is only written to state.db after a full turn of
`build_turn_context` finishes. If the machine sleeps/shuts down before that —
image analysis fails, the provider hangs — the message exists only in memory and
vanishes on reboot.

**Fix** (2 files):
- `tui_gateway/server.py`: persist the user message to state.db BEFORE calling
  `run_conversation` (keeps the user's original text, not the image-failure
  placeholder), marked via `_db_persisted` to prevent duplicate rows.
- `run_agent.py`: emit an explicit warning when `_session_db` is unavailable
  instead of silently skipping persistence.

**Platform compatibility**: the script itself is pure Python (pathlib,
cross-platform) — works on macOS / Linux / Windows. Entry points are provided
per platform: `install.sh` (bash) and `install.ps1` (PowerShell).

## Manual run (no network needed)

```bash
# After downloading the script (macOS / Linux)
python3 fix-hermes-desktop-message-loss.py                          # auto-detect
python3 fix-hermes-desktop-message-loss.py ~/.hermes/hermes-agent   # specify dir

# Windows
python fix-hermes-desktop-message-loss.py
python fix-hermes-desktop-message-loss.py C:\Users\you\.hermes\hermes-agent
```

## Verify

```bash
# After restart: send a message → sleep/shut down → reopen, the message should still be there
```

---

[中文文档](./README.zh-CN.md)
