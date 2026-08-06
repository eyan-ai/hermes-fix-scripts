# Hermes Agent 一键修复脚本集

面向 Hermes Agent（尤其桌面版）常见问题的幂等修复脚本。
所有脚本：**自动备份原文件、幂等（可重复运行）、语法校验失败自动回滚**。

## 使用方法

```bash
# 一键执行（自动探测 Hermes 安装目录）
bash <(curl -fsSL https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.sh) fix-message-loss

# 或指定安装目录
bash <(curl -fsSL https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.sh) fix-message-loss /path/to/hermes-agent
```

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

## 手动执行（不经网络）

```bash
# 下载脚本到本地后
python3 fix-hermes-desktop-message-loss.py                # 自动探测
python3 fix-hermes-desktop-message-loss.py ~/.hermes/hermes-agent  # 指定目录
```

## 验证

```bash
# 重启后发一条消息 → 休眠/关机 → 重开，消息应仍在
```
