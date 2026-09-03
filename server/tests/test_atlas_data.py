from scripts.atlas_data.coords import (
    normalize_ra, ra_wrap, haversine_deg, main_name, strip_suffix, slugify,
    split_constellation_name, asterism_key,
)
from scripts.atlas_data.cn_members import (
    group_members, match_line_endpoint, EXPLICIT_MEMBERS,
)


def test_normalize_ra_boundaries():
    assert normalize_ra(0) == 0
    assert normalize_ra(83.7137) == 83.7137
    assert normalize_ra(-131.6994) == 228.3006
    assert normalize_ra(180) == 180
    assert normalize_ra(-180) == 180


def test_ra_wrap_shortest_arc():
    assert ra_wrap(359 - 1) == -2          # 跨春分点：取最短弧
    assert ra_wrap(10 - 20) == -10
    assert abs(ra_wrap(200)) == 160        # 200 → -160


def test_haversine_known_pair():
    # 参宿四 (88.7929, 7.4071) vs 猎户中心 (86.0, -2.0)
    sep = haversine_deg(88.7929, 7.4071, 86.0, -2.0)
    assert 9.0 < sep < 10.0


def test_main_name_strips_parens():
    assert main_name("柱(毕宿)") == "柱"
    assert main_name("柱一[毕宿]") == "柱一"
    assert main_name("参宿") == "参宿"


def test_strip_suffix_returns_asterism():
    assert strip_suffix("参宿四") == "参宿"
    assert strip_suffix("参宿增卅八") == "参宿"
    assert strip_suffix("壁宿增廿一") == "壁宿"


def test_strip_suffix_strips_asterisk():
    # 带 * 的增星（波斯四* / 天庾一* / 天社增四*）应剥掉 * 后正确归组
    assert strip_suffix("天庾一*") == "天庾"
    assert strip_suffix("波斯十一*") == "波斯"
    assert strip_suffix("天社增四*") == "天社"
    assert asterism_key("天庾一*") == "天庾"


def test_slugify_ascii():
    assert slugify("Zhu(Bi Xiu)") == "zhu_bi_xiu"
    assert slugify("Shēnxiù") == "shenxiu"


def test_group_members_prefix_rule(tmp_path, monkeypatch):
    constellations = tmp_path / "c.csv"
    starnames = tmp_path / "s.csv"
    constellations.write_text(
        "id,name,en,pinyin,desig,rank,display_ra,display_dec\n"
        "3,参宿,Three Stars,shenxiu,参宿,1,83.7,-1.1\n",
        encoding="utf-8",
    )
    starnames.write_text(
        "id,name,desig,en,pinyin\n"
        "27989,参宿四,α Ori,Three Stars IV,Shēnxiù IV\n"
        "26727,参宿一,ζ Ori,Three Stars I,Shēnxiù I\n"
        "900,无关星,XX,None,None\n",
        encoding="utf-8",
    )
    groups = group_members(str(constellations), str(starnames))
    assert "参宿" in groups
    assert {m["id"] for m in groups["参宿"]} == {"27989", "26727"}


def test_match_line_endpoint_picks_nearest():
    # 端点 (83.0017, -0.2991) = 参宿一; 成员含参宿一
    key = match_line_endpoint(
        (83.0017, -0.2991),
        [{"id": "26727", "ra": 83.0017, "dec": -0.2991},
         {"id": "27989", "ra": 88.7929, "dec": 7.4071}],
    )
    assert key == "26727"


def test_split_constellation_name_parens_and_brackets():
    assert split_constellation_name("柱(毕宿)") == ("柱", "毕宿")
    assert split_constellation_name("柱一[毕宿]") == ("柱一", "毕宿")
    assert split_constellation_name("伐(附官)") == ("伐", "附官")
    assert split_constellation_name("伐一") == ("伐一", "")
    assert split_constellation_name("参宿") == ("参宿", "")


def test_asterism_key_unifies_star_and_constellation_names():
    # 星官名(圆括号) 与 成员名(方括号) 应归到同一 key
    assert asterism_key("柱(毕宿)") == "柱@毕宿"
    assert asterism_key("柱一[毕宿]") == "柱@毕宿"
    # 附官忽略标记：伐(附官) 与 伐一 同为「伐」
    assert asterism_key("伐(附官)") == "伐"
    assert asterism_key("伐一") == "伐"
    # 普通宿：参宿四 归回 参宿
    assert asterism_key("参宿四") == "参宿"


def test_asterism_key_distinguishes_same_name_scopes():
    # 同名星官（不同宿）必须被 @归属 区分，否则成员会串
    assert asterism_key("杵(箕宿)") == "杵@箕宿"
    assert asterism_key("杵(危宿)") == "杵@危宿"
    assert asterism_key("杵(箕宿)") != asterism_key("杵(危宿)")


def test_group_members_scoped_names(tmp_path):
    constellations = tmp_path / "c.csv"
    starnames = tmp_path / "s.csv"
    constellations.write_text(
        "id,name,en,pinyin,desig,rank,display_ra,display_dec\n"
        "54,杵(箕宿),Pestle,chujj,杵(箕宿),3,-60,-32\n"
        "55,杵(危宿),Pestle,chuw,杵(危宿),3,-20,-25\n",
        encoding="utf-8",
    )
    starnames.write_text(
        "id,name,desig,en,pinyin\n"
        "1,杵一[箕宿],σ Ara,Pestle I,Chǔ I\n"
        "2,杵二[箕宿],α Ara,Pestle II,Chǔ II\n"
        "3,杵一[危宿],1 Lac,Pestle I,Chǔ I\n",
        encoding="utf-8",
    )
    groups = group_members(str(constellations), str(starnames))
    assert {m["id"] for m in groups.get("杵@箕宿", [])} == {"1", "2"}
    assert {m["id"] for m in groups.get("杵@危宿", [])} == {"3"}


def test_group_members_explicit_members_inject(tmp_path):
    # 显式映射：北斗成员名(天枢…)与星官名无关，靠 HIP 注入
    constellations = tmp_path / "c.csv"
    starnames = tmp_path / "s.csv"
    constellations.write_text(
        "id,name,en,pinyin,desig,rank,display_ra,display_dec\n"
        "39,北斗,Northern Dipper,beidou,北斗,3,-173,55\n",
        encoding="utf-8",
    )
    starnames.write_text(
        "id,name,desig,en,pinyin\n"
        "54061,天枢,α UMa,The Celestial Pivot,Tiānshū\n"
        "53910,天璇,β UMa,The Celestial Rotating Jade,Tiānxuán\n",
        encoding="utf-8",
    )
    groups = group_members(str(constellations), str(starnames))
    # 北斗七星的显式 HIP 中，只有 54061/53910 在本 fixture 中
    assert {m["id"] for m in groups.get("北斗", [])} == {"54061", "53910"}


def test_explicit_members_cover_known_independent_asterisms():
    # 守护显式映射表：北斗 7 星、北极 6 星（太子/帝/庶子/后宫/北极星/纽星）、
    # 三台 6 星、十二国 12+ 国
    assert len(EXPLICIT_MEMBERS["北斗"]) == 7
    assert len(EXPLICIT_MEMBERS["北极"]) == 6
    assert "62572" in EXPLICIT_MEMBERS["北极"]  # 纽星，lines.cn 末端点名
    assert len(EXPLICIT_MEMBERS["三台"]) == 6
    assert len(EXPLICIT_MEMBERS["十二国"]) >= 12