#!/usr/bin/env bash
#
# StarWhisper 一键部署脚本
#   - 拉取 main 分支最新代码
#   - 后端：按需重装 pip 依赖
#   - 前端：按需 pnpm install + 强制 pnpm build
#   - 重建 tmux session（starwhisper-api / starwhisper-preview）
#   - 冒烟测试（health + 前端 200）
#
# 用法：bash scripts/deploy.sh
# 设计原则：
#   * build 失败时保留旧服务（先 build 再 kill session）
#   * 用 `tmux kill-session` 而非 `Ctrl+C`（避免带走整个 window）
#   * 启动参数遵循"已提交的部署形态"：后端绑 127.0.0.1:8000，前端绑 0.0.0.0:12001

set -euo pipefail

# ---- 配置 ----
REPO="/root/Projects/StarWhisper"
API_SESSION="starwhisper-api"
PREVIEW_SESSION="starwhisper-preview"
CONDA_ENV="/root/miniforge3/envs/starwhisper"

# 状态文件放项目外，避免污染仓库、避免被 .gitignore 反复过滤
STATE_DIR="${HOME}/.cache/starwhisper-deploy"
mkdir -p "$STATE_DIR"

# 颜色（终端可用时）
if [[ -t 1 ]]; then
    C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_RED='\033[0;31m'; C_RESET='\033[0m'
else
    C_GREEN=''; C_YELLOW=''; C_RED=''; C_RESET=''
fi
info()  { echo -e "${C_GREEN}[✓]${C_RESET} $*"; }
warn()  { echo -e "${C_YELLOW}[!]${C_RESET} $*"; }
fail()  { echo -e "${C_RED}[✗]${C_RESET} $*" >&2; exit 1; }

cd "$REPO"

# ---- 0. 预检 ----
[[ "$(git branch --show-current)" == "main" ]] || fail "当前不在 main 分支（请先 git checkout main）"
if ! git diff --quiet HEAD 2>/dev/null; then
    warn "有未提交改动："
    git status --short
    fail "请先 commit 或 git stash 后再部署"
fi
[[ -f .env ]] || fail ".env 不存在（ASTROMETRY_SERVICE_URL 等配置丢失）"

# ---- 1. 拉取 main ----
echo "▶ git pull origin main"
if ! git pull --ff-only origin main; then
    fail "git pull --ff-only 失败（main 分支可能落后或被强推，请手动 rebase）"
fi
NEW_COMMIT=$(git rev-parse --short HEAD)
info "代码已更新到 $NEW_COMMIT"

# ---- 2. 后端依赖（requirements.txt 变了才装）----
REQ_HASH=$(md5sum server/requirements.txt | awk '{print $1}')
LAST_HASH=$(cat "$STATE_DIR/requirements.md5" 2>/dev/null || echo "")
if [[ "$REQ_HASH" != "$LAST_HASH" ]]; then
    echo "▶ requirements.txt 变化，安装后端依赖"
    "$CONDA_ENV/bin/pip" install -q -r server/requirements.txt \
        || fail "pip install 失败（环境：$CONDA_ENV）"
    echo "$REQ_HASH" > "$STATE_DIR/requirements.md5"
    info "后端依赖已更新"
else
    info "后端依赖未变，跳过 pip install"
fi

# ---- 3. 前端依赖 + 构建 ----
cd web

LOCK_HASH=$(md5sum pnpm-lock.yaml | awk '{print $1}')
LAST_LOCK=$(cat "$STATE_DIR/pnpm-lock.md5" 2>/dev/null || echo "")
if [[ "$LOCK_HASH" != "$LAST_LOCK" ]]; then
    echo "▶ pnpm-lock.yaml 变化，安装前端依赖"
    pnpm install --frozen-lockfile || fail "pnpm install 失败"
    echo "$LOCK_HASH" > "$STATE_DIR/pnpm-lock.md5"
    info "前端依赖已更新"
else
    info "前端依赖未变，跳过 pnpm install"
fi

echo "▶ pnpm build"
pnpm build || {
    warn "构建失败！**老服务继续运行**，新代码未生效"
    fail "请检查上方 vue-tsc / vite build 错误"
}
info "前端构建完成"

cd "$REPO"

# ---- 4. 重启后端 tmux ----
echo "▶ 重建 tmux session: $API_SESSION"
tmux kill-session -t "$API_SESSION" 2>/dev/null || true
sleep 1
tmux new-session -d -s "$API_SESSION" -c "$REPO/server"
tmux send-keys -t "$API_SESSION" \
    "PYTHONUNBUFFERED=1 $CONDA_ENV/bin/uvicorn main:app --host 127.0.0.1 --port 8000 2>&1 | tee .runtime/api.log"
tmux send-keys -t "$API_SESSION" Enter
info "后端 session 已启动"

# ---- 5. 重启前端 tmux ----
echo "▶ 重建 tmux session: $PREVIEW_SESSION"
tmux kill-session -t "$PREVIEW_SESSION" 2>/dev/null || true
sleep 1
tmux new-session -d -s "$PREVIEW_SESSION" -c "$REPO/web"
tmux send-keys -t "$PREVIEW_SESSION" "pnpm preview --host 0.0.0.0 --port 12001 --strictPort 2>&1 | tee ../server/.runtime/preview.log"
tmux send-keys -t "$PREVIEW_SESSION" Enter
info "前端 session 已启动"

# ---- 6. 冒烟测试 ----
echo "▶ 等待服务启动..."
sleep 8

HEALTH=$(curl -s -m 5 http://127.0.0.1:8000/api/health || echo "")
if echo "$HEALTH" | grep -q '"ok":true'; then
    info "后端 health: $HEALTH"
else
    fail "后端 health 失败: ${HEALTH:-无响应}（查看 tmux attach -t $API_SESSION）"
fi

PREVIEW_CODE=$(curl -s -m 5 -o /dev/null -w "%{http_code}" http://127.0.0.1:12001/ || echo "0")
if [[ "$PREVIEW_CODE" == "200" ]]; then
    info "前端 preview: HTTP 200"
else
    fail "前端 preview 失败: HTTP $PREVIEW_CODE（查看 tmux attach -t $PREVIEW_SESSION）"
fi

# ---- 7. 完成 ----
echo
echo "================================="
info "部署完成 @ $NEW_COMMIT"
echo "  后端日志: tail -f $REPO/server/.runtime/api.log"
echo "  前端日志: tail -f $REPO/server/.runtime/preview.log"
echo "  进入会话: tmux attach -t $API_SESSION  (Ctrl+B D 退出)"
echo "  域名地址: https://starwhisper.caipiischenpi.top/"
echo "================================="
