"""services/image_prompt.py 单测：定稿模板的结构契约与长度预算。

这些断言锁的是**实验选出来的结构**（故事在前、规则在后），不是文案细节——
文案还会继续调，但顺序一旦回退，实验里"连线/伪文字"就会重新出现。
"""
from __future__ import annotations

from services.image_prompt import PROMPT_LIMIT, build_prompt, fit_story

STORY = (
    "玉衡引路：大熊座与夏夜星河\n"
    "第一段：北天那头巨大的铁熊从地平线后探出脊背。\n\n"
    "第二段：天鹅座展翅北去，与大熊座遥遥对望。\n\n"
    "第三段：若你在今晚抬头，先寻北斗的玉衡。"
)


def test_story_comes_before_the_rules():
    """A1 结构：故事正文必须排在所有风格/禁令块之前。"""
    out = build_prompt(STORY)
    assert out.index("铁熊") < out.index("【画风】") < out.index("【严禁】")


def test_last_line_is_a_ban_not_the_story():
    """生成端最后读到的必须是禁令，不能是点名星名的故事。"""
    out = build_prompt(STORY)
    assert out.rstrip().endswith("摄影照片。")


def test_prompt_contains_all_three_blocks():
    out = build_prompt(STORY)
    assert "【画风】" in out and "【画面性质】" in out and "【严禁】" in out


def test_story_is_fenced():
    """故事用 ``` 围栏包起来，与指令区隔开。"""
    out = build_prompt(STORY)
    assert out.count("```") == 2
    assert "```\n" + STORY.split("\n")[0] in out


def test_ban_list_keeps_the_four_clauses():
    """A2 实验证明正面表述不能替代禁令，四条严禁必须都在。"""
    out = build_prompt(STORY)
    for clause in ("星座连线", "星名、星座名", "任何文字、字母、数字", "天文示意图"):
        assert clause in out


def test_empty_story_still_yields_a_valid_prompt():
    out = build_prompt("   ")
    assert "【画风】" in out
    assert len(out) <= PROMPT_LIMIT


# ---------- 长度预算 ----------


def test_prompt_never_exceeds_api_limit():
    out = build_prompt("星" * 9000)
    assert len(out) <= PROMPT_LIMIT


def test_story_budget_respected_by_build():
    out = build_prompt("啊" * 5000, budget=200)
    assert out.count("啊") <= 200


# ---------- fit_story ----------


def test_fit_story_returns_unchanged_when_it_fits():
    assert fit_story("短故事一段", 900) == "短故事一段"


def test_fit_story_drops_whole_trailing_paragraphs():
    """优先整段砍尾部，而不是从段落中间截断。"""
    text = "甲" * 100 + "\n\n" + "乙" * 100 + "\n\n" + "丙" * 100
    out = fit_story(text, 210)
    assert "丙" not in out
    assert out == "甲" * 100 + "\n\n" + "乙" * 100
    assert "…" not in out  # 段落级裁剪不该留省略号


def test_fit_story_hard_cuts_when_single_paragraph_too_long():
    out = fit_story("星" * 300, 50)
    assert len(out) == 50
    assert out.endswith("…")


def test_fit_story_zero_budget_is_noop():
    assert fit_story("内容", 0) == "内容"


def test_fit_story_strips_surrounding_whitespace():
    assert fit_story("\n\n  故事  \n\n", 900) == "故事"
