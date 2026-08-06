# Hermes Agent 一键修复脚本集

面向 Hermes Agent（尤其桌面版）常见问题的幂等修复脚本。
所有脚本：**自动备份原文件、幂等（可重复运行）、语法校验失败自动回滚**。

## 使用方法（macOS / Linux）

```bash
# 一键执行（自动探测 Hermes 安装目录）
bash <(curl -fsSL https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.sh) fix-message-loss

# 或指定安装目录
bash <(curl -fsSL https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.sh) fix-message-loss /path/to/hermes-agent
```

## 使用方法（Windows PowerShell 5.1+ / PowerShell 7）

```powershell
# 一键执行（自动探测 Hermes 安装目录）
iex "& { $(irm https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.ps1) } fix-message-loss"

# 或指定安装目录
iex "& { $(irm https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.ps1) } fix-message-loss C:\Users\you\.hermes\hermes-agent"
```

> Windows 前置要求：已安装 Python 3（`python` 或 `py` 可用）。
> PowerShell 5.1 解析 .ps1 时按 ANSI 处理无 BOM 文件，故 install.ps1 输出为英文，
> 中文说明见本 README。

修复完成后**重启 Hermes 桌面 app** 生效。

## 脚本列表

| 命令 | 解决的问题 |
|---|---|
| `fix-message-loss` | 桌面版消息发出后休眠/关机丢失（用户消息发送瞬间即落库） |

## 脚本详情

### fix-message-loss —— 消息丢失修复

**症状**：桌面版 Hermes 发消息后，电脑休眠/关机，第二天打开消息不见了。

**根因**：用户消息默认要等一轮对话的 `build_turn_context` 走完才写入
state.db。在此之前休眠/关机、图片分析失败、provider 卡死，消息只存在
内存中，重启即失。

**修复**（2 个文件）：
- `tui_gateway/server.py`：`run_conversation` 调用前立即把用户消息写入
  state.db（持久化用户原文，非图片占位符），通过 `_db_persisted` 标记
  防重复写入。
- `run_agent.py`：`_session_db` 不可用时输出明确 warning，不再静默丢失。

**平台兼容性**：脚本本体为纯 Python（pathlib 跨平台），macOS / Linux /
Windows 均可用；入口脚本按平台提供 `install.sh`（bash）与 `install.ps1`
（PowerShell）。

## 手动执行（不经网络）

```bash
# 下载脚本到本地后（macOS / Linux）
python3 fix-hermes-desktop-message-loss.py                # 自动探测
python3 fix-hermes-desktop-message-loss.py ~/.hermes/hermes-agent  # 指定目录

# Windows
python fix-hermes-desktop-message-loss.py
python fix-hermes-desktop-message-loss.py C:\Users\you\.hermes\hermes-agent
```

## 验证

```bash
# 重启后发一条消息 → 休眠/关机 → 重开，消息应仍在
```
