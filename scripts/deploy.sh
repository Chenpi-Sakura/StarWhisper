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

# 按端口清理残留进程。
# 背景：历史上用 `setsid` 启动 uvicorn / vite preview 让它们脱离 tmux 进程树
# （防 SIGHUP 挂死），但副作用是 `tmux kill-session` 杀不掉它们，端口仍被占，
# 新进程静默启动失败（Errno 98 address already in use）并继续跑旧代码——
# 线上表现为"改了代码但行为没变 + 500 难排查"。这里在起新 session 前
# 按端口兜底清理：先 SIGTERM，2s 后仍在则 SIGKILL。
kill_port_owners() {
    local port="$1"
    local pids
    # ⚠️ || true 不能省：本脚本第 15 行是 `set -euo pipefail`，端口已释放时
    #    grep 无匹配返回 1，pipefail 会把整个管道判失败，赋值语句非 0 触发 set-e
    #    让**整个脚本在函数内部静默退出**——实测会让 kill 之后的新进程根本没
    #    起来，端口空窗、线上 502，而退出码被下游管道掩盖成 0。
    pids=$(ss -tlnp 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K[0-9]+' | sort -u || true)
    [[ -z "$pids" ]] && return 0
    warn "端口 $port 仍被占用（tmux 外的孤儿进程），清理: $pids"
    kill -TERM $pids 2>/dev/null || true
    for _ in 1 2 3 4; do
        sleep 1
        pids=$(ss -tlnp 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K[0-9]+' | sort -u || true)
        [[ -z "$pids" ]] && { info "端口 $port 已释放"; return 0; }
    done
    warn "端口 $port 仍占用，SIGKILL: $pids"
    kill -KILL $pids 2>/dev/null || true
    sleep 1
}

cd "$REPO"

# ---- 0. 预检 ----
[[ "$(git branch --show-current)" == "main" ]] || fail "当前不在 main 分支（请先 git checkout main）"
if ! git diff --quiet HEAD 2>/dev/null; then
    warn "有未提交改动："
    git status --short
    fail "请先 commit 或 git stash 后再部署"
fi
[[ -f .env ]] || fail ".env 不存在（ASTROMETRY_SERVICE_URL 等配置丢失）"

# 外部依赖体检：识图主链路依赖自建 astrometry 求解服务（不在本仓库，见 docs/EXTERNAL_DEPS.md）。
# 这里必须 fail 而不是 warn —— 依赖不通还把 StarWhisper 部上去，等于交付一个
# "页面能开、拍照没反应" 的版本，用户侧才发现，比部署失败难查得多。
echo "▶ 外部依赖体检"
if ! bash scripts/check_deps.sh --quiet; then
    echo
    fail "外部依赖未就绪（识图会 502 ASTROMETRY_DOWN）。完整报告：bash scripts/check_deps.sh"
fi
info "外部依赖就绪"

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
kill_port_owners 8000
tmux new-session -d -s "$API_SESSION" -c "$REPO/server"
tmux send-keys -t "$API_SESSION" \
    "PYTHONUNBUFFERED=1 $CONDA_ENV/bin/uvicorn main:app --host 127.0.0.1 --port 8000 >> .runtime/api.log 2>&1"
tmux send-keys -t "$API_SESSION" Enter
info "后端 session 已启动"

# ---- 5. 重启前端 tmux ----
echo "▶ 重建 tmux session: $PREVIEW_SESSION"
tmux kill-session -t "$PREVIEW_SESSION" 2>/dev/null || true
sleep 1
kill_port_owners 12001
tmux new-session -d -s "$PREVIEW_SESSION" -c "$REPO/web"
tmux send-keys -t "$PREVIEW_SESSION" "pnpm preview --host 0.0.0.0 --port 12001 --strictPort >> ../server/.runtime/preview.log 2>&1"
tmux send-keys -t "$PREVIEW_SESSION" Enter
info "前端 session 已启动"

# ---- 6. 冒烟测试 ----
echo "▶ 等待服务启动..."
sleep 8

# 端口必须在监听：Errno 98 时uvicorn 会静默退出（不报错到终端），
# 页面却还在跑旧代码——这是最难查的一类坑，必须显式断言。
for port in 8000 12001; do
    ss -tln 2>/dev/null | grep -q ":${port} " \
        || fail "端口 $port 未监听（启动失败？看 .runtime/*.log，多半是端口冲突或依赖缺失）"
done

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

# 识图链路真打一次：/api/health 的 astrometry 字段只看配置、不探测上游，
# 所以 health 通过 ≠ 解算可用。这里用仓库自带样图真解一次（见 docs/EXTERNAL_DEPS.md §3）。
# quick-test1.jpg 在 web/public/samples/ 里，克隆即有，实测可解出（D610+50mm，视场 39.9°×26.7°）。
PROBE_IMG="$REPO/web/public/samples/quick-test1.jpg"
if [[ -f "$PROBE_IMG" ]]; then
    SOLVE_CODE=$(curl -s -m 180 -o /tmp/sw_solve_probe.json -w "%{http_code}" \
        -X POST -F "image=@$PROBE_IMG" \
        http://127.0.0.1:8000/api/identify/solve 2>/dev/null || echo "0")
    if [[ "$SOLVE_CODE" != "200" ]]; then
        warn "识图探测返回 HTTP $SOLVE_CODE（这通常意味着解算服务不可达，见 docs/EXTERNAL_DEPS.md）"
    elif python3 -c "
import json,sys
try:
    sys.exit(0 if json.load(open('/tmp/sw_solve_probe.json')).get('solved') else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        info "识图链路真解通过（solved=true）"
    else
        warn "识图链路未解出（服务通但没解出星：多为视场超索引范围或样图不合适，不阻断部署）"
    fi
else
    warn "缺少探测样图 $PROBE_IMG，跳过识图链路探测"
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

# 部署后额外探测 /api/index：它依赖 astropy IERS 表，是典型的
# "平时绿、满30 天突然 500" 的时间炸弹（见 8625fa7 修复）。
INDEX_CODE=$(curl -s -m 20 -o /dev/null -w "%{http_code}" \
    "http://127.0.0.1:8000/api/index?lat=30.5838&lon=103.9873&hours=24" || echo "0")
if [[ "$INDEX_CODE" == "200" ]]; then
    info "观星指数 /api/index 200"
else
    warn "观星指数 /api/index 返回 $INDEX_CODE（若为 500，多半又是 astropy IERS 超龄）"
fi
