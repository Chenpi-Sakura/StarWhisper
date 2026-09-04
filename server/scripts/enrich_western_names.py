"""一次性 enrich：给西方传统 JSON 的 stars 补 name_zh。

背景：starnames.csv 在西方 88 星座里只有 ~30% 的星有中文名（小星座暗星基本
都是 NA），导致 vul / sge / equ / cvn 等小星座 view 出现大片无 label 的星点。
但这些星在中国传统 28 宿 / 三垣 / 12 星官里通常是有归属的（同名星会同时属
于西方 88 星座 + 中国某星官）。

算法：先聚合 chinese tradition 全部 stars → dict[hip] = name_zh；再扫每个
western/{abbr}.json 的 stars 字典，若 name/name_zh 都为空，从 chinese dict
回填 name_zh（保留原 cross-tradition 性质）。如果 chinese dict 也查不到，
保留空（不强行兜底，避免假数据）。

写入规则：仅在 name 和 name_zh 都为空时才回填。如果原本有 name 而 name_zh
为空，保持原状——starnames.csv 里少数 case 有 bayer 但 zh='NA'，这种保持
bayer 兜底显示是合理的。

跑法：cd server && .venv/Scripts/python.exe -m scripts.enrich_western_names
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WESTERN_DIR = ROOT / "data" / "traditions" / "western"
CHINESE_DIR = ROOT / "data" / "traditions" / "chinese"


def load_chinese_index() -> dict[str, str]:
    """hip → name_zh，从 chinese tradition 全部 entry 聚合（同名星以首次为准）。"""
    out: dict[str, str] = {}
    for fp in sorted(CHINESE_DIR.glob("*.json")):
        if fp.name == "_meta.json":
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARN skip {fp.name}: {e}", file=sys.stderr)
            continue
        for s in data.get("stars", {}).values():
            hip = str(s.get("hip") or "").strip()
            zh = (s.get("name_zh") or "").strip()
            if not hip or not zh or hip in out:
                continue
            out[hip] = zh
    return out


def enrich_western(zh_index: dict[str, str]) -> tuple[int, int]:
    """返回 (回填数, 仍空数)。"""
    filled = 0
    still_empty = 0
    for fp in sorted(WESTERN_DIR.glob("*.json")):
        if fp.name == "_meta.json":
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARN skip {fp.name}: {e}", file=sys.stderr)
            continue
        changed = False
        for s in data.get("stars", {}).values():
            name = (s.get("name") or "").strip()
            name_zh = (s.get("name_zh") or "").strip()
            if name or name_zh:
                continue  # 已有任一名称，不动
            hip = str(s.get("hip") or "").strip()
            if not hip:
                continue
            zh = zh_index.get(hip, "")
            if zh:
                s["name_zh"] = zh
                filled += 1
                changed = True
            else:
                still_empty += 1
        if changed:
            fp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    return filled, still_empty


def main() -> int:
    print("Step 1/2: loading chinese tradition index…")
    zh_index = load_chinese_index()
    print(f"  loaded {len(zh_index)} hip → name_zh")

    print("Step 2/2: enriching western/{abbr}.json…")
    filled, still_empty = enrich_western(zh_index)
    print(f"  回填 name_zh: {filled} 颗")
    print(f"  仍空（中文传统也没名）: {still_empty} 颗")
    return 0


if __name__ == "__main__":
    sys.exit(main())
