"""一次性下载 celestial_data 原始数据到 server/data/raw/。

数据源：https://github.com/dieghernan/celestial_data
许可：开源（见 docs/specs/2026-08-25-atlas-data-completion.md §2.1）。
"""
from pathlib import Path
import urllib.request

BASE = "https://raw.githubusercontent.com/dieghernan/celestial_data/main/data"
FILES = [
    "constellations.csv",
    "constellations.cn.csv",
    "starnames.cn.csv",
    "constellations.lines.cn.geojson",
    "stars.8.min.geojson",
    "starnames.csv",
    "constellations.lines.geojson",
]

OUT = Path(__file__).resolve().parents[1] / "data" / "raw"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        url = f"{BASE}/{name}"
        dest = OUT / name
        print(f"下载 {url} -> {dest}")
        urllib.request.urlretrieve(url, dest)
        print(f"  OK {dest.stat().st_size} bytes")


if __name__ == "__main__":
    main()