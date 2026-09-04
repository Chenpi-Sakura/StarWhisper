"""tradition 数据自动发现 + 加载。

单源：server/data/traditions/{tradition_key}/{abbr}.json
- 一级子目录名 = tradition key
- 文件名 (去 .json) = abbr
- startup event 加载（main.py 调用 _load_all()）
- fail-soft：坏 JSON / abbr 不匹配跳过
"""
from pathlib import Path
from threading import Lock
import json
import logging
import math

logger = logging.getLogger(__name__)

_DATA_ROOT: Path = Path(__file__).parent.parent / "data" / "traditions"
_DATA: dict[str, dict[str, dict]] = {}
_META: dict[str, dict] | None = None
_LOCK = Lock()


def _default_meta(key: str, glob_count: int) -> dict:
    """_meta.json 缺失/坏 JSON 时降级默认值。"""
    return {
        "key": key,
        "label": key,
        "star_count": glob_count,
        "coordinate_system": "equatorial",
    }


def _load_all() -> None:
    """启动时由 main.py 显式调用；内部带 lock 防重复、保持 idempotent。

    加载顺序（每个 tradition）：
    1. 读 _meta.json：缺失 → 降级默认值 + warn；坏 JSON → 降级默认值 + error；星表始终尝试加载
    2. 扫描 traditions/{key}/*.json（除 _meta 外），在读 meta 之前或同时计算 glob_count
    3. 校验 star_count（以 glob 为准），不匹配覆盖 meta + warn
    4. 两个全局变量 _DATA / _META 一起原子赋值（避免半初始化）
       注：去重扁平星表不再缓存为全局变量，`build_star_catalog()` 公开 API
       现读现算（独立从 _DATA 读取 + round(...,2) 去重，详见 spec v3 已实现版）。

    **fail-soft**：单文件 JSON 坏不挂服务；记录错误后跳过该文件。
    严格 fail-fast 由 `scripts/validate_atlas.py` + CI 负责，不在运行时执行。

    **double-check locking**：无锁快速路径检查 `_DATA` + `_META`，避免热路径争锁。
    """
    global _DATA, _META
    if _DATA and _META:  # truthy check：两个全局变量均已加载（非空）
        return  # 缓存命中
    with _LOCK:
        if _DATA and _META:
            return
        new_data: dict[str, dict[str, dict]] = {}
        new_meta: dict[str, dict] = {}
        traditions_dir = _DATA_ROOT
        for trad_dir in sorted(p for p in traditions_dir.iterdir() if p.is_dir()):
            key = trad_dir.name
            # 先 glob（不依赖 meta 状态），用于 star_count
            json_files = [
                p for p in trad_dir.glob("*.json") if p.name != "_meta.json"
            ]
            glob_count = len(json_files)
            # 再读 _meta.json（fail-soft）
            meta_path = trad_dir / "_meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(
                        "tradition %s _meta.json corrupt: %s, using defaults",
                        key, e,
                    )
                    meta = _default_meta(key, glob_count)
            else:
                logger.warning(
                    "tradition %s missing _meta.json, using defaults", key,
                )
                meta = _default_meta(key, glob_count)
            # star_count 以 glob 为准
            if meta.get("star_count") != glob_count:
                logger.warning(
                    "tradition %s star_count mismatch (meta=%d, actual=%d), updating",
                    key, meta.get("star_count", -1), glob_count,
                )
                meta["star_count"] = glob_count
            new_meta[key] = meta
            # 加载星表（保证 key 存在，即使所有 entry 均被跳过）
            new_data.setdefault(key, {})
            for fp in json_files:
                abbr = fp.stem
                try:
                    entry = json.loads(fp.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(
                        "tradition %s/%s entry load failed: %s", key, abbr, e,
                    )
                    continue
                # 保留 spec v3 数据契约校验：entry.abbr 必须等于文件名 stem
                if entry.get("abbr") != abbr:
                    logger.error(
                        "traditions: %s/%s abbr=%r != filename=%r, skipped",
                        key, abbr, entry.get("abbr"), abbr,
                    )
                    continue
                new_data.setdefault(key, {})[abbr] = entry
        # 原子赋值（两个全局变量一起，避免半初始化）
        _DATA = new_data
        _META = new_meta


def get_meta(tradition: str) -> dict | None:
    """返回 _meta.json dict（lowercase tradition key）。"""
    _load_all()
    if _META is None:
        return None
    return _META.get(tradition.lower())


def list_traditions() -> list[dict]:
    _load_all()
    return [
        {"key": k, "label": _label(k), "count": len(v)}
        for k, v in sorted(_DATA.items())
    ]


# 28 宿 pinyin slug → 四象分组（中文显示名）；3 垣 = 各占 1 分组
# 键名采用任务 5 生成的中国 abbr slug（下划线分隔）。
# 任务 5 已按主归属消歧：wei_xiu_1=危(北), wei_xiu_2=尾(东), wei_xiu_3=胃(西);
# bi_xiu_1=毕(西), bi_xiu_2=壁(北)
MANSION_GROUP = {
    **{m: "东方七宿" for m in
       ["jiao_xiu", "kang_xiu", "di_xiu", "fang_xiu", "xin_xiu", "wei_xiu_2", "ji_xiu"]},
    **{m: "北方七宿" for m in
       ["dou_xiu", "niu_xiu", "nu_xiu", "xu_xiu", "shi_xiu", "bi_xiu_2"]},
    **{m: "西方七宿" for m in
       ["kui_xiu", "lou_xiu", "mao_xiu", "wei_xiu_3", "zi_xiu", "shen_xiu", "bi_xiu_1"]},
    **{m: "南方七宿" for m in
       ["jing_xiu", "gui_xiu", "liu_xiu", "xing_xiu", "zhang_xiu", "yi_xiu", "zhen_xiu"]},
}
ENCLOSURE_GROUP = {
    "zi_wei_yuan": "紫微垣",
    "tai_wei_yuan": "太微垣",
    "tian_shi_yuan": "天市垣",
}


def list_constellations(tradition: str) -> list[dict]:
    _load_all()
    out = []
    for c in _DATA.get(tradition, {}).values():
        abbr = c.get("abbr", "")
        group = (
            ENCLOSURE_GROUP.get(abbr)
            or MANSION_GROUP.get(abbr)
            or ("近南极" if c.get("asterism_id") == "nanji" else None)
        )
        out.append({
            "abbr": abbr,
            "name": c.get("name", ""),
            "latin": c.get("latin", ""),
            "season": c.get("season", ""),
            "caption": c.get("caption", ""),
            "tradition": tradition,
            "star_count": len(c.get("stars", {})),
            "has_stories": bool(c.get("stories")),
            "group": group,
        })
    return out


def get_constellation(tradition: str, abbr: str) -> dict | None:
    _load_all()
    trad_key = tradition.lower()
    entry = _DATA.get(trad_key, {}).get(abbr.lower())
    if entry is None:
        return None
    return {**entry, "tradition": trad_key, "ok": True}


def find_nearest(
    ra: float,
    dec: float,
    max_sep_deg: float = 5.0,
    top_k: int | None = None,
    tradition: str | None = None,
) -> list[tuple[str, str, float]]:
    """按 (ra, dec) 反查所有 ≤ max_sep_deg 的候选，按角距升序。

    Args:
        ra, dec: 中心坐标（度）
        max_sep_deg: 最大接受角距
        top_k: 最多返回候选数；None = 全部（不截断）。
            生产路径固定 top_k=3（routers/identify.py 约定），避免不截断的性能回退。
        tradition: 限定只查指定 tradition（None = 不限）。

    Returns:
        [(tradition, abbr, sep_deg), ...] — 空 list = 无命中
    """
    _load_all()
    results = []
    for trad_key, entries in _DATA.items():
        if tradition is not None and trad_key != tradition.lower():
            continue
        for abbr, entry in entries.items():
            ra2 = entry["center"]["ra"]
            dec2 = entry["center"]["dec"]
            sep = _angular_separation(ra, dec, ra2, dec2)
            if sep <= max_sep_deg:
                results.append((trad_key, abbr, sep))
    results.sort(key=lambda x: x[2])
    if top_k is not None:
        results = results[:top_k]
    return results


def find_in_fov(
    ra: float,
    dec: float,
    field_w: float,
    field_h: float,
    tradition: str | None = None,
    top_k: int = 3,
) -> list[tuple[str, str, float]]:
    """FOV 视场矩形反查：找"在 FOV 内有星"的 tradition 星座，按"最亮可见星"排序。

    与 ``find_nearest`` 的差异：
    - ``find_nearest`` 按星座"中心点"圆形距离阈值排序（适合窄视场单星座）。
    - ``find_in_fov`` 按"最亮可见星"亮度 + 距离排序（适合广角多星座同框，
      用户能识别出夏季大三角这种亮星组合）。

    排序优先级（夏季大三角案例驱动）：
    1. 最亮可见星 mag < 3 排第一档（亮星座优先：夏季大三角 / 猎户 / 大熊 等）
    2. mag 3-5 排第二档（中等亮度：狐狸 / 天箭 等）
    3. mag ≥ 5 排第三档（暗星座）
    4. 同一档内按"最亮可见星到 solve 中心"的角距升序

    这样 test2 实测：top3 = lyr / aql / cyg（Vega/Deneb/Altair mag 0-1），
    而不是按"中心点距离"算出的 vul / sge / zuo_qi_1（最近但暗）。

    视场矩形以 ``(ra, dec)`` 为中心、``field_w`` × ``field_h``：
    - RA 方向 cos(dec) 校正
    - DEC 方向直接比
    - 上游解算坐标系有旋转（CD 矩阵），轴对齐矩形近似偏差 < 5°，MVP 接受

    RA 不跨 0°/360° 边界（MVP 跳过 wrap）。

    Returns:
        [(tradition, abbr, sep_deg), ...] — sep 为 solve 中心到"最亮可见星"的角距，top_k 截断。
    """
    _load_all()
    if field_w <= 0 or field_h <= 0:
        return []
    half_w = field_w / 2.0
    half_h = field_h / 2.0
    cos_dec = math.cos(math.radians(dec))
    candidates: list[tuple[str, str, float, float, float, float]] = []
    for trad_key, entries in _DATA.items():
        if tradition is not None and trad_key != tradition.lower():
            continue
        for abbr, entry in entries.items():
            stars = entry.get("stars", {})
            if not stars:
                continue
            # 找 FOV 内最亮的星
            best_mag: float | None = None
            best_sep: float | None = None
            best_ra: float | None = None
            best_dec: float | None = None
            for s in stars.values():
                s_ra = s.get("ra")
                s_dec = s.get("dec")
                if s_ra is None or s_dec is None:
                    continue
                # FOV 矩形筛选
                if abs(s_ra - ra) * cos_dec > half_w:
                    continue
                if abs(s_dec - dec) > half_h:
                    continue
                mag = s.get("magnitude", 99)
                if mag is None:
                    mag = 99
                if best_mag is None or mag < best_mag:
                    best_mag = mag
                    best_sep = _angular_separation(ra, dec, s_ra, s_dec)
                    best_ra = s_ra
                    best_dec = s_dec
            if best_mag is None or best_sep is None:
                continue
            candidates.append(
                (trad_key, abbr, best_sep, best_mag, best_ra, best_dec)
            )

    def _sort_key(
        item: tuple[str, str, float, float, float, float],
    ) -> tuple[int, float, float]:
        _, _, sep, mag, _, _ = item
        if mag < 3:
            return (0, mag, sep)    # 亮星座：先按最亮星 mag 升序（Vega 0.03
                                     # 排在 Altair 0.76 前面），再按距离
        if mag < 5:
            return (1, mag, sep)    # 中等亮度
        return (2, mag, sep)        # 暗星座

    candidates.sort(key=_sort_key)

    # ★ 跨 tradition 去重：同一颗物理星（最亮星 ra/dec 相同）只允许 1 个
    # tradition 进 top_k。Vega 是典型例：lyr + zhi_nu 都把 Vega 当成最亮星；
    # Deneb 是 tian_jin + cyg 都当成最亮星。
    # 算法：按 sort order 遍历，每个候选的最佳星用 star_key = (ra, dec) round 2
    # 作 key。dict[star_key] = (trad_pref, ...)；新候选若 tradition 优先级更高
    # 则替换旧值。最后按 (bucket, mag, sep) 排序已选候选，截 top_k。
    # tradition 优先级：western > chinese（西方 88 星座数据干净、跨图复用率高）。
    TRAD_PREF = {"western": 0, "chinese": 1}
    chosen: dict[tuple[float, float], tuple[int, str, str, float, float, float]] = {}
    for trad_key, abbr, sep, mag, s_ra, s_dec in candidates:
        star_key = (round(s_ra, 2), round(s_dec, 2))
        pref = TRAD_PREF.get(trad_key, 99)
        if star_key not in chosen:
            chosen[star_key] = (pref, trad_key, abbr, sep, mag, s_ra)
            continue
        if pref < chosen[star_key][0]:
            chosen[star_key] = (pref, trad_key, abbr, sep, mag, s_ra)
    # 用 _sort_key 重排：保留 bucket 优先 + mag 升序 + sep 升序
    out: list[tuple[str, str, float]] = []
    for _, trad_key, abbr, sep, mag, _ in sorted(
        chosen.values(), key=lambda v: _sort_key(
            (v[1], v[2], v[3], v[4], 0.0, 0.0),
        ),
    ):
        out.append((trad_key, abbr, sep))
    return out[:top_k]


def build_star_catalog() -> list[dict]:
    """为 identify.py 的 WCS 投影构造标准星表。

    **去重**：同颗物理星可能在多个 tradition 中出现（参宿四 在 western/ori 和 chinese/shen 中 RA/Dec 相同）。
    优先按 Hipparcos/HIP 号去重（精确）；无 HIP 时 fallback `round(ra, 3) / round(dec, 3)`
    约 3.6″ 精度去重。重复时保留首个出现。

    **多归属**（用户反馈：选人马座后人马座内部星点不亮）：去重保留首现条目的
    同时，跨 tradition 聚合该物理星在**所有**星座条目中的归属 abbr 到
    `constellations` 列表。原因：`_load_all()` 按目录序加载（chinese <
    western），重叠区域的星被 chinese 抢注单一 `constellation`（实测
    western/sgr 25 颗星全部归到 ji_xiu/dou_xiu），前端按
    `constellation === activeAbbr` 点亮 western chip 时全部 miss。
    `constellation` / `tradition` 字段保留首现归属，向后兼容。
    """
    _load_all()
    # 第一遍：按去重 key 聚合。key 插入顺序 = 首现顺序（Python 3.7+ dict 保序），
    # 输出 catalog 的顺序与旧的"保留首个出现"语义一致。
    agg: dict[tuple, dict] = {}
    for trad_key, consts in _DATA.items():
        for abbr, c in consts.items():
            for _star_key, star in c.get("stars", {}).items():
                hip_raw = star.get("hip")
                hip = str(hip_raw) if hip_raw is not None else ""
                if hip:
                    key: tuple = ("hip", hip)
                else:
                    key = ("radec", round(star["ra"], 3), round(star["dec"], 3))
                if key not in agg:
                    agg[key] = {
                        "star": star,
                        "trad": trad_key,
                        "abbr": abbr,
                        "hip": hip,
                        "abbrs": [],
                        "_seen_abbrs": set(),
                    }
                bucket = agg[key]
                # 同一 abbr 内多颗同 key 星只记一次归属
                if abbr not in bucket["_seen_abbrs"]:
                    bucket["_seen_abbrs"].add(abbr)
                    bucket["abbrs"].append(abbr)
    # 第二遍：输出 catalog
    catalog: list[dict] = []
    for bucket in agg.values():
        star = bucket["star"]
        catalog.append({
            "bayer": star.get("bayer", ""),
            "name": star.get("name", ""),
            "name_zh": star.get("name_zh", ""),
            "magnitude": star.get("magnitude", 0),
            "ra": star["ra"],
            "dec": star["dec"],
            "constellation": bucket["abbr"],
            "tradition": bucket["trad"],
            "hip": bucket["hip"],
            "constellations": bucket["abbrs"],
        })
    return catalog


def _angular_separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """严格 Haversine 球面角距，返回度数。

    公式：
      a = sin²(Δδ/2) + cos δ₁ · cos δ₂ · sin²(Δα/2)
      θ = 2 · atan2(√a, √(1−a))

    选用 Haversine 而非 acos 版球面余弦的原因：
    - 极小角距 (<0.001°) 时，acos 公式会出现 cos θ ≈ 1 的浮点取消
    - Haversine 通过 half-angle 计算保持数值稳定

    MVP 精度：
    - |Dec| < 45°：偏差 < 0.001°（5 星座均满足）
    - |Dec| > 70°：角距计算仍准；投影失真在 4.3 equirectangular TODO 处理
    """
    ra1_r = math.radians(ra1)
    dec1_r = math.radians(dec1)
    ra2_r = math.radians(ra2)
    dec2_r = math.radians(dec2)
    ddec_r = dec2_r - dec1_r
    dra_r = ra2_r - ra1_r
    a = (
        math.sin(ddec_r / 2) ** 2
        + math.cos(dec1_r) * math.cos(dec2_r) * math.sin(dra_r / 2) ** 2
    )
    a = min(1.0, max(0.0, a))  # 数值保护（避免 sqrt(负数)）
    return math.degrees(2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _label(tradition_key: str) -> str:
    return {
        "western": "西方星座",
        "chinese": "中国古代星空",
    }.get(tradition_key, tradition_key)
