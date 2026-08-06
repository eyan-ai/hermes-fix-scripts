#!/usr/bin/env bash
#
# Hermes Agent 一键修复入口
#
# 用法:
#   bash <(curl -fsSL https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.sh) <script-name> [hermes-dir]
#
# 示例:
#   bash <(curl -fsSL https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.sh) fix-message-loss
#
# 所有脚本均为幂等设计: 可重复运行, 自动备份, 语法校验失败自动回滚。
# 兼容 bash 3.2 (macOS 默认) 与 bash 4+。

set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main"

# 解析脚本名 -> 文件名。用 case 而非关联数组（macOS bash 3.2 不支持）。
resolve_filename() {
  case "${1:-}" in
    fix-message-loss) echo "fix-hermes-desktop-message-loss.py" ;;
    *) echo "" ;;
  esac
}

usage() {
  echo "用法: bash <(curl -fsSL $REPO_RAW/install.sh) <script-name> [hermes-dir]"
  echo ""
  echo "可用脚本:"
  echo "  fix-message-loss  ->  修复桌面版消息休眠/关机丢失"
  echo ""
  echo "示例:"
  echo "  bash <(curl -fsSL $REPO_RAW/install.sh) fix-message-loss"
  echo "  bash <(curl -fsSL $REPO_RAW/install.sh) fix-message-loss ~/.hermes/hermes-agent"
  exit 1
}

main() {
  local name="${1:-}"
  local filename
  filename="$(resolve_filename "$name")"
  if [[ -z "$filename" ]]; then
    usage
  fi

  local hermes_dir="${2:-}"

  echo "📦 下载 $name ($filename) ..."
  local tmp
  tmp="$(mktemp -d)"
  local script_path="$tmp/$filename"

  if ! curl -fsSL "$REPO_RAW/$filename" -o "$script_path"; then
    echo "❌ 下载失败: $REPO_RAW/$filename"
    rm -rf "$tmp"
    exit 1
  fi

  echo "✅ 下载完成，开始执行 ..."
  echo ""
  if [[ -n "$hermes_dir" ]]; then
    python3 "$script_path" "$hermes_dir"
  else
    python3 "$script_path"
  fi
  local rc=$?

  rm -rf "$tmp"
  echo ""
  echo "🚀 完成后请重启 Hermes 桌面 app（完全退出再打开）使修复生效。"
  exit $rc
}

main "$@"
