# atlas-cn-lines 修复记录（260829）

> 修复"星座互动（PLATE Ⅲ）"看不到中国星官连线的问题。
> branch：`fix-260829-atlas-cn-lines` · 4 commits · 全量 187 passed。

## 症状

`server/data/traditions/chinese/*.json` 大量星官 `lines: []`，
前端 `StarCanvas` 画不出连线，PLATE Ⅲ 仅显示空网格。

## 根因（三层 + 一类不可修）

| 类别 | 数量（修前） | 根因 | 可代码修 |
|---|---|---|---|
| A1 | 4 | 独立古名型（成员名与星官名无关） | ✅ |
| A2 | 16 | 括号双 key 归组失败（柱@毕宿 vs 柱@危宿） | ✅ |
| C1 | 5 | 源端点 0.000° 命中，但 `strip_suffix` 不剥 `*` 增星名 | ✅ |
| C2 | 5 | 附官连线延伸到主宿成员（参宿二、室宿二等） | ✅ |
| D | 3 | 源数据/starnames 缺暗星 HIP 的中文名 | ❌ |

## 修复

1. `server/scripts/atlas_data/coords.py`
   - `asterism_key(name)`：主名去序号 + `*` + @归属区分
   - `split_constellation_name(name)`：(主名, 归属) 拆分
   - `strip_suffix` 增加 `[*★]+$` 剥离

2. `server/scripts/atlas_data/cn_members.py`
   - `group_members` 用 `asterism_key` 归组
   - 新增 `EXPLICIT_MEMBERS`（北斗/北极/三台/十二国，HIP 显式）
   - 北极补 HIP 62572 纽星（lines.cn 末端点名）

3. `server/scripts/build_chinese_stars.py`
   - `MATCH_THRESHOLD_DEG = 0.05 → 2.0`（源数据 0.1°-7° 漂移）
   - 端点失配打 WARN（不静默丢线）
   - 附官 fallback 池：本星官成员 + 显式 `EXPLICIT_OWNER` 映射的主宿成员

## 不可修的 3 个 C 类（源数据问题）

- **海山**：line 端点 (161.19, -59.57) → HIP 52558（无名暗星 mag 7.35），`starnames.cn.csv` 未收录
- **螣蛇**：line 端点 (-17.11, 53.83) → HIP 112760（无名暗星 mag 7.93），`starnames.cn.csv` 未收录
- **玉井**：line 端点 (79.40, -6.84) → HIP 24674（参宿增卅八，Orion）—— 源数据把参宿主宿星画入玉井连线，疑似源数据笔误

依据：Wikipedia "Flying serpent (asterism)"（22 颗在室宿/蝎虎座附近）未列 112760；
Wikipedia "List of Chinese star names" 玉井 4 颗全在 Eridanus，无参宿成员。

## 验收

- A 类 20→0；C 类 20→3（不可修的源数据问题）
- 后端 `pytest -q` 187 passed
- 新增 9 个回归测试（`test_atlas_data.py` 8 + `test_chinese_atlas_members.py` 5，去重后 13）
- 北斗完整勺形 7 星 + 6 条线已正确生成