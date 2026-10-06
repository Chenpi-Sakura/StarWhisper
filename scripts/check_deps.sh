#!/usr/bin/env bash
#
# StarWhisper 外部依赖体检
#
#   StarWhisper 的识图主链路强依赖自建的 astrometry 求解服务（不在本仓库内）。
#   /api/health 的 astrometry 字段只看配置、不探测上游，所以**不能**用它判断依赖是否活着。
#   这个脚本做真实探测：服务通不通、跑的是哪份代码、解算器是不是 0.98、索引齐不齐。
#
#   用法：
#     bash scripts/check_deps.sh          # 体检，识图依赖缺任一项则 exit 1
#     bash scripts/check_deps.sh --quiet  # 只输出失败项（给 CI / deploy 用）
#
#   退出码：0 = 识图链路依赖全部就绪；1 = 有必需依赖不可用
#
set -uo pipefail   # 故意不用 -e：单项检查失败要继续跑完其余项，最后统一汇总

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---- 依赖位置（默认值可用环境变量覆盖，便于测试）----
ASTROM_DIR="${ASTROM_DIR:-/root/Projects/astrometry}"
ASTRO_PREFIX="${ASTRO_PREFIX:-/opt/astrometry/0.98}"
INDEX_DIR="${ASTRO_INDEX_DIR:-/root/.astrom/4100}"
TMUX_SESSION="${ASTROM_TMUX_SESSION:-astrometry-api}"

# ---- 解算服务地址：与 server/config.py / .env 保持一致 ----
SERVICE_URL="${ASTROMETRY_SERVICE_URL:-}"
if [[ -z "$SERVICE_URL" && -f "$REPO/.env" ]]; then
    SERVICE_URL=$(grep -E '^ASTROMETRY_SERVICE_URL=' "$REPO/.env" | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')
fi
SERVICE_URL="${SERVICE_URL:-http://127.0.0.1:8010}"

# ---- 颜色 ----
if [[ -t 1 ]]; then
    C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_RED='\033[0;31m'; C_RESET='\033[0m'
else
    C_GREEN=''; C_YELLOW=''; C_RED=''; C_RESET=''
fi
ok()   { echo -e "${C_GREEN}[✓]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}[!]${C_RESET} $*"; }
bad()  { echo -e "${C_RED}[✗]${C_RESET} $*" >&2; FAILURES=$((FAILURES + 1)); }

quiet=0
[[ "${1:-}" == "--quiet" ]] && quiet=1
FAILURES=0

say() { [[ $quiet -eq 1 ]] || echo "$*"; }
say_ok()   { [[ $quiet -eq 1 ]] || ok "$@"; }
say_warn() { [[ $quiet -eq 1 ]] || warn "$@"; }

say "===== StarWhisper 外部依赖体检 ====="
say "解算服务地址: $SERVICE_URL"
say

# ================= ① astrometry 服务（必需）=================
say "--- ① astrometry 求解服务（识图必需）---"

HEALTH=$(curl -fsS -m 5 "${SERVICE_URL}/health" 2>/dev/null || echo "")
if [[ -z "$HEALTH" ]]; then
    bad "服务不可达：${SERVICE_URL}/health"
    say "      → StarWhisper 的 POST /api/identify/solve 会返回 502 ASTROMETRY_DOWN"
    say "      → 启动：cd $ASTROM_DIR && ./astrom_service.sh start"
else
    say_ok "服务健康  ${SERVICE_URL}/health"

    # 细化字段：status / commit / reaper / zombies / pid（注意是 5 个，顺序别搞错）
    read -r A_STATUS A_COMMIT A_REAPER A_ZOMBIES A_PID <<<"$(printf '%s' "$HEALTH" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print("- - - - -"); raise SystemExit
print(d.get("status","?"), d.get("commit","?"), d.get("reaper","?"),
      d.get("zombies","?"), d.get("pid","?"))
' 2>/dev/null)"

    SERVER_COMMIT=$(curl -fsS -m 5 "${SERVICE_URL}/version" 2>/dev/null \
        | python3 -c 'import sys,json; print(json.load(sys.stdin).get("version","?"))' 2>/dev/null || echo "?")

    [[ -n "$A_COMMIT" && "$A_COMMIT" != "-" ]] \
        && say_ok "  ├ 服务端 commit        ${A_COMMIT}  pid=${A_PID} zombies=${A_ZOMBIES}" \
        || say_warn "  ├ commit 字段解析失败"
    [[ -n "$A_REAPER" && "$A_REAPER" != "-" ]] \
        && say_ok "  ├ 收割者 reaper         ${A_REAPER}（宿主机 PID 1 负责收割孤儿进程）" \
        || say_warn "  ├ reaper 字段缺失"

    if [[ "$SERVER_COMMIT" == "0.98"* ]]; then
        say_ok "  └ 解算器 solve-field   ${SERVER_COMMIT} ✅"
    elif [[ "$SERVER_COMMIT" == "0.93"* ]]; then
        bad "  └ 解算器 solve-field   ${SERVER_COMMIT} ← 是 apt 的 0.93，不是 0.98！"
        say "      → 会静默降级（不报错但质量/耗时可能变化）。PATH 必须前置 $ASTRO_PREFIX/bin"
    else
        say_warn "  └ 解算器 solve-field   ${SERVER_COMMIT}（期望 0.98-*）"
    fi
fi
say

# ================= ②③ 两个仓库（必需）=================
say "--- ②③ 自建仓库（编译/排查必需）---"

check_repo() {
    local name="$1" dir="$2"
    if [[ ! -d "$dir/.git" ]]; then
        bad "${name} 仓库缺失：${dir}"
        say "      → 两个仓库必须同级放置（go.mod 用相对路径 replace ../astrometry-go-client）"
        return
    fi
    local branch head
    branch=$(git -C "$dir" branch --show-current 2>/dev/null || echo "?")
    head=$(git -C "$dir" rev-parse --short HEAD 2>/dev/null || echo "?")
    local dirty
    dirty=$(git -C "$dir" status --porcelain 2>/dev/null | head -1)
    say_ok "${name}  ${dir}（分支 ${branch} @ ${head}）"
    [[ -n "$dirty" ]] && say_warn "      有未提交改动"
    return 0
}

check_repo "astrometry-api-server" "$ASTROM_DIR/astrometry-api-server"
check_repo "astrometry-go-client " "$ASTROM_DIR/astrometry-go-client"
say

# ================= ④ 解算器运行时（必需）=================
say "--- ④ astrometry.net 运行时（必需）---"

if [[ -x "$ASTRO_PREFIX/bin/solve-field" ]]; then
    VER=$("$ASTRO_PREFIX/bin/solve-field" --version 2>/dev/null | head -1)
    if [[ "$VER" == 0.98* ]]; then
        say_ok "解算器 prefix  $ASTRO_PREFIX（solve-field ${VER}）"
    else
        bad "解算器 prefix  $ASTRO_PREFIX（solve-field ${VER}，期望 0.98-*）"
    fi
    NTOOLS=$(ls "$ASTRO_PREFIX/bin" 2>/dev/null | wc -l | tr -d ' ')
    [[ -d "$ASTRO_PREFIX/lib/python/astrometry" ]] \
        && say_ok "  ├ python 模块   在位（image2pnm 依赖它）" \
        || bad "  ├ python 模块缺失  → solve-field 会报 ModuleNotFoundError: astrometry"
    say_ok "  └ 工具数       ${NTOOLS}"
else
    bad "解算器缺失：$ASTRO_PREFIX/bin/solve-field"
fi
say

# ================= ⑤ 索引（必需）=================
say "--- ⑤ 4100 系列索引（必需）---"
IDX_COUNT=0
IDX_SIZE=$(du -sh "$INDEX_DIR" 2>/dev/null | cut -f1)
for s in 7 8 9 10 11 12 13 14 15 16 17 18; do
    [[ -s "$INDEX_DIR/index-41$(printf '%02d' "$s").fits" ]] && IDX_COUNT=$((IDX_COUNT + 1))
done
if [[ "$IDX_COUNT" -eq 12 ]]; then
    say_ok "索引  ${IDX_COUNT} / 12 个（${IDX_SIZE}，覆盖视场 1.1°~70°）"
else
    bad "索引  ${IDX_COUNT} / 12 个（缺 $((12 - IDX_COUNT)) 个，${IDX_SIZE}）"
    say "      → 缺索引不影响服务启动，但对应视场段会解不出来（SOLVE_FAILED）"
    say "      → 下载：http://data.astrometry.net/4100/"
fi
say

# ================= ⑥ 托管状态（提示）=================
say "--- ⑥ 进程托管（提示）---"
if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    say_ok "tmux 会话  ${TMUX_SESSION} 存活"
else
    say_warn "tmux 会话  ${TMUX_SESSION} 不存在（服务可能仍是活的，但失去托管/无法 stop）"
fi
say

# ================= ⑦ 其他外部依赖（非必需）=================
say "--- ⑦ 其他外部依赖（不影响识图）---"
if [[ -f "$REPO/.env" ]]; then
    if grep -qE '^(AGENTARTS_API_KEY|OPENAI_API_KEY|AI_API_KEY)=' "$REPO/.env" 2>/dev/null; then
        say_warn "AI provider  已配置（AgentArts/OpenAI）—— 它挂了故事会降级到离线预设，识图不受影响"
    else
        say_warn "AI provider  未配置 —— 故事走离线预设 story_fallback.py"
    fi
else
    say_warn ".env 不存在 —— 无法核对 AI provider 配置"
fi
say

# ================= 汇总 =================
say "================================"
if [[ $FAILURES -eq 0 ]]; then
    say_ok "✓ 识图链路依赖全部就绪（StarWhisper 可正常解算）"
else
    bad "✗ $FAILURES 项必需依赖不可用 —— StarWhisper 识图会失败"
    say "  排查见 docs/EXTERNAL_DEPS.md"
fi
exit $((FAILURES > 0 ? 1 : 0))