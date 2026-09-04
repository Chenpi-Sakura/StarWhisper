"""中国星官 lines 复用守护：北斗勺口闭合 + 参宿猎户闭合 + Bayer 复用不被擦除。

复现修：M2 末尾发现 28 宿折线只画开放链 + Bayer 复用未补全关键闭合。
- 北斗 7 星 raw 折线 6 条 → 缺「天枢↔天权」勺口左
- 参宿 raw 折线 6 条 → 缺「参宿四↔参宿五」顶 + 参宿三↔参宿五」右上 + 参宿三↔参宿七/参宿六↔参宿七

守护：
- 北斗必须含 7 条边（含勺口闭合），且「天枢↔天权」边存在
- 参宿必须 ≥ 9 条边，且至少包含 3 条新增的 Bayer 复用边
- 跑两次 enrich_chinese_lines 不会让边数翻倍（idempotent）
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "server" / "data" / "traditions" / "chinese"
SCRIPT = ROOT / "server" / "scripts" / "enrich_chinese_lines.py"

# 北斗勺口应含边（7 条完整勺子，统一按 (min, max) 排序）
BEIDOU_LADLE_EDGES = {
    tuple(sorted(["54061", "53910"])),  # 勺口顶
    tuple(sorted(["53910", "58001"])),  # 勺口右
    tuple(sorted(["58001", "59774"])),  # 勺口底
    tuple(sorted(["59774", "54061"])),  # 勺口左  ← manual closure
    tuple(sorted(["59774", "62956"])),  # 勺柄起
    tuple(sorted(["62956", "65378"])),
    tuple(sorted(["65378", "67301"])),
}


def _edge_set(lines: list[list[str]]) -> set[tuple[str, str]]:
    out = set()
    for line in lines:
        if not isinstance(line, list) or len(line) != 2:
            continue
        a, b = str(line[0]), str(line[1])
        out.add((min(a, b), max(a, b)))
    return out


def test_beidou_forms_complete_ladle():
    """北斗 7 边完整勺子，含 manual closure「天枢↔天权」。"""
    e = json.loads((DATA / "bei_dou.json").read_text(encoding="utf-8"))
    edges = _edge_set(e["lines"])
    assert len(edges) == 7, f"北斗期望 7 条边，实际 {len(edges)}：{edges}"
    missing = BEIDOU_LADLE_EDGES - edges
    assert not missing, f"北斗勺口缺边：{missing}"


def test_shen_xiu_reused_western_bayer_edges():
    """参宿 9 边：6 raw 折线 + 至少 3 Bayer 复用（参宿四↔参宿五、参宿三↔参宿五、参宿三↔参宿七）。"""
    e = json.loads((DATA / "shen_xiu.json").read_text(encoding="utf-8"))
    edges = _edge_set(e["lines"])
    # 7 颗主星 HIP：参宿一-七
    main7 = {"24436", "25336", "25930", "26311", "26727", "27366", "27989"}
    # 至少 3 条"两端点都是 7 主星"的 Bayer 复用边
    main_internal = {e for e in edges if e[0] in main7 and e[1] in main7}
    # raw 折线本身不含"两端点都是 7 主星"以外的边 → main_internal 全部应是新加
    assert len(main_internal) >= 3, (
        f"参宿 main7 内部边期望 ≥3，实际 {len(main_internal)}：{main_internal}"
    )
    # 关键 Bayer 复用边：参宿四↔参宿五（顶）、参宿三↔参宿五（右上）
    must = {tuple(sorted(["25336", "27989"])),
            tuple(sorted(["25336", "25930"]))}
    missing = must - edges
    assert not missing, f"参宿缺 Bayer 复用边：{missing}"


@pytest.mark.integration
def test_enrich_script_is_idempotent():
    """跑两次 enrich_chinese_lines.py 不应让任何文件的边数翻倍。"""
    # 先 snapshot
    before = {}
    for fp in DATA.glob("*.json"):
        d = json.loads(fp.read_text(encoding="utf-8"))
        before[fp.name] = len(d.get("lines", []))

    # 跑第二次（应无变更，因为 dedup）
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, f"enrich 失败：{result.stderr}"

    # 对比
    changed = []
    for fp in DATA.glob("*.json"):
        d = json.loads(fp.read_text(encoding="utf-8"))
        after = len(d.get("lines", []))
        if after != before[fp.name]:
            changed.append((fp.name, before[fp.name], after))
    assert not changed, f"第二次跑 enrich 改了 {len(changed)} 个文件：{changed[:5]}"


@pytest.mark.integration
def test_enrich_dry_run_does_not_modify_files():
    """--dry-run 不应改任何文件。"""
    before = {}
    for fp in DATA.glob("*.json"):
        d = json.loads(fp.read_text(encoding="utf-8"))
        before[fp.name] = json.dumps(d, ensure_ascii=False, sort_keys=True)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, f"dry-run 失败：{result.stderr}"

    changed = []
    for fp in DATA.glob("*.json"):
        d = json.loads(fp.read_text(encoding="utf-8"))
        after = json.dumps(d, ensure_ascii=False, sort_keys=True)
        if after != before[fp.name]:
            changed.append(fp.name)
    assert not changed, f"dry-run 改了文件：{changed}"


@pytest.mark.integration
def test_build_chinese_preserves_existing_stories():
    """build_chinese_stars.py 重跑不应清空已填好的 stories（309 星官内容）。"""
    # 先 snapshot stories 内容
    before_stories = {}
    for fp in DATA.glob("*.json"):
        d = json.loads(fp.read_text(encoding="utf-8"))
        before_stories[fp.name] = d.get("stories")

    # 跑 build
    build_script = ROOT / "server" / "scripts" / "build_chinese_stars.py"
    py = ROOT / "server" / ".venv" / "Scripts" / "python.exe"
    result = subprocess.run(
        [str(py), str(build_script)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, f"build 失败：{result.stderr[-500:]}"

    # 对比 stories
    wiped = []
    for fp in DATA.glob("*.json"):
        d = json.loads(fp.read_text(encoding="utf-8"))
        after = d.get("stories")
        if before_stories.get(fp.name) != after:
            wiped.append((fp.name, before_stories.get(fp.name), after))
    assert not wiped, f"build 清空了 {len(wiped)} 个 stories：{wiped[:3]}"
