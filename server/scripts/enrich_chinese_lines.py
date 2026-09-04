# -*- coding: utf-8 -*-
"""为 chinese asterism 复用西方 Bayer 完整闭合边。

28 宿传统折线只画连续链（不闭合），导致北斗/参宿/猎户等"无勺口/无四边形"。
Bayer 体系的西方线条画完整星座（闭合）。本脚本从 western/*.json 抽取
Bayer 边（端点都是亮星 magnitude ≤ 3.5），为每个 chinese asterism 复用
其中"两端点都是其成员"的边，使中文名保留 + 形状完整。

用法：
    python server/scripts/enrich_chinese_lines.py            # 跑全量
    python server/scripts/enrich_chinese_lines.py --dry-run  # 只报告，不写
    python server/scripts/enrich_chinese_lines.py shen_xiu.json bei_dou.json  # 限文件

输出格式：在原 lines 末尾追加新边（保留原 28 宿折线作底），去重。
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CN_DIR = ROOT / "server" / "data" / "traditions" / "chinese"
WEST_DIR = ROOT / "server" / "data" / "traditions" / "western"
BRIGHT_MAG = 3.5  # 肉眼可见亮星上限；北斗 3.32、参旗部分 2-3 都在内

# 已知 28 宿 / 古星官的"形状补全"边：raw 折线只画开放链，缺 1 条闭合
# 不足以让 Western Bayer 复用补回（西方 UMa 也不画北斗勺口），需手工加。
# 键是 chinese 文件 abbr；值是 (hip_a, hip_b) 列表，端点用裸 HIP 字符串。
# 之所以手工：
#   - 西方 Bayer 体系没画北斗"勺口"（UMa 把北斗 7 星看作大熊尾），自动复用帮不上
#   - 这条边是 28 宿传统 7 星折线 → 闭合勺口 的最小补全，画出来中国用户一眼能认
KNOWN_CLOSURES: dict[str, list[tuple[str, str]]] = {
    # 北斗 7 星：raw 折线 6 条连成 7 星开放链；缺「天枢(54061)↔天权(59774)」闭合勺口左
    "bei_dou": [("54061", "59774")],
}


def strip_hip_prefix(key: str) -> str:
    """western key 'HIP_12345' -> '12345'；chinese key '12345' 原样。"""
    if key.startswith("HIP_"):
        return key[4:]
    return key


def collect_western_edges(west_dir: Path) -> set[tuple[str, str]]:
    """所有 western Bayer 边（端点都是 magnitude ≤ 3.5 的亮星），端点用裸 HIP 字符串。"""
    edges: set[tuple[str, str]] = set()
    for path in sorted(west_dir.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            d = json.load(f)
        for line in d.get("lines", []):
            if len(line) != 2:
                continue
            a, b = line
            sa, sb = d.get("stars", {}).get(a), d.get("stars", {}).get(b)
            if not (sa and sb):
                continue
            ma, mb = sa.get("magnitude", 99), sb.get("magnitude", 99)
            if ma > BRIGHT_MAG or mb > BRIGHT_MAG:
                continue
            ha, hb = strip_hip_prefix(a), strip_hip_prefix(b)
            if not (ha and hb):
                continue
            edges.add((min(ha, hb), max(ha, hb)))
    return edges


def enrich_one(
    cn_path: Path,
    west_edges: set[tuple[str, str]],
    dry_run: bool = True,
) -> tuple[int, int, int]:
    """为单个 chinese asterism 复用西方边 + 应用 KNOWN_CLOSURES。

    Returns: (existing_count, new_added, total_after)
    """
    with cn_path.open(encoding="utf-8") as f:
        d = json.load(f)

    bright_hips: set[str] = set()
    for s in d.get("stars", {}).values():
        if not s.get("hip"):
            continue
        if s.get("magnitude", 99) > BRIGHT_MAG:
            continue
        bright_hips.add(s["hip"])

    existing = d.get("lines", [])
    existing_set: set[tuple[str, str]] = set()
    for line in existing:
        if len(line) != 2:
            continue
        a, b = strip_hip_prefix(str(line[0])), strip_hip_prefix(str(line[1]))
        existing_set.add((min(a, b), max(a, b)))

    new_edges: list[list[str]] = []

    # 1) 自动复用西方 Bayer 边（端点都属本 asterism 亮星）
    for a, b in west_edges:
        if a in bright_hips and b in bright_hips:
            e = (min(a, b), max(a, b))
            if e not in existing_set:
                new_edges.append([a, b])
                existing_set.add(e)

    # 2) 应用 KNOWN_CLOSURES（手工补全的形状闭合边，端点必须在本 asterism 亮星内）
    abbr = cn_path.stem
    for a, b in KNOWN_CLOSURES.get(abbr, ()):
        if a not in bright_hips or b not in bright_hips:
            # 端点不在亮星集合 → 跳过并警告（避免把不存在的边塞进数据）
            print(
                f"  WARN {abbr}: KNOWN_CLOSURES 边 {a}↔{b} 端点不在亮星集合，跳过",
                file=sys.stderr,
            )
            continue
        e = (min(a, b), max(a, b))
        if e not in existing_set:
            new_edges.append([a, b])
            existing_set.add(e)

    if new_edges and not dry_run:
        d["lines"] = existing + new_edges
        with cn_path.open("w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
            f.write("\n")

    return len(existing), len(new_edges), len(existing) + len(new_edges)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files",
        nargs="*",
        help="限 chinese 文件名（不含 .json 也可），默认全量",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只报告变更，不写文件",
    )
    args = parser.parse_args()

    west_edges = collect_western_edges(WEST_DIR)
    print(f"Loaded {len(west_edges)} Bayer edges (magnitude ≤ {BRIGHT_MAG})", file=sys.stderr)

    if args.files:
        targets = []
        for name in args.files:
            stem = name[:-5] if name.endswith(".json") else name
            targets.append(CN_DIR / f"{stem}.json")
    else:
        targets = sorted(CN_DIR.glob("*.json"))

    total_added = 0
    for path in targets:
        if not path.exists():
            print(f"SKIP (not found): {path.name}", file=sys.stderr)
            continue
        before, added, after = enrich_one(path, west_edges, dry_run=args.dry_run)
        flag = "DRY " if args.dry_run else "    "
        if added > 0:
            print(f"{flag}{path.name:30}  {before:>2} → {after:>2}  (+{added})")
        total_added += added

    print(f"\n{flag.strip()}Total new edges added: {total_added}  (in {len(targets)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
