"""星纹配图 prompt 模板（定稿）。

结构来自 2026-10-10 的五臂对照实验。判读口径两条：画面里是否出现
「星座连线」、是否出现「伪文字」。同 seed 换 prompt 不构成严格对照
（改文本条件的同时隐向量也变了），所以每臂按 n=3 重复采样再看。

结论：
- **A1「故事在前、规则在后」**是唯一在两项上都优于基线的臂。模型对**最后
  读到**的内容权重最高，而故事正文点名了十几个星名，把它压在生成端之前会
  持续把画面拽向"带标注的星图"。
- A2 的【画面性质】正面表述**单独用会退化**（删掉禁令后连线反而更多），但
  作为禁令之外的加法能换来卷草纹边框，所以两者都留。
- 措辞不是主杠杆，方差才是：最优臂单张干净率仍只有约 2/3，因此按
  `IMAGE_GEN_N` 一次出多张候选做拒绝采样，由用户挑，而不是继续调提示词。
"""
from __future__ import annotations

from config import IMAGE_STORY_MAX_CHARS

# MiniMax /v1/image_generation 的 prompt 硬上限。
PROMPT_LIMIT = 1500

_LEAD = "为下面这段星空神话故事绘制一幅插画配图：\n```\n"

_STYLE = (
    "\n```\n\n【画风】中世纪羊皮纸手抄本插画风格；做旧米黄纸底与墨蓝夜空并置；"
    "烫金细线描边；钢笔与毛笔混合的手绘线条；雕版印刷的斑驳颗粒质感；"
    "史诗、庄重、带古老传说的氛围；构图语言参考古代星象图鉴与航海图版画。\n\n"
    "【画面性质】这是一幅纯粹的手绘传说插画：画面上只有形象与装饰纹样——"
    "生物、人物、云气、地形、光束，四周以卷草纹边框收边。"
    "它没有图表结构，没有版面文字，没有任何需要被读出来的符号。\n\n"
    "【严禁】\n"
    "- 严禁出现星座连线、星点之间连成的线、任何星官或星座的图形。\n"
    "- 严禁出现星名、星座名、编号、坐标、刻度。\n"
    "- 严禁出现任何文字、字母、数字、签名、水印、标注。\n"
    "- 严禁把画面画成天文示意图、科学图表或摄影照片。\n"
)

# 固定外壳的实测长度：首尾两段加起来，故事为空时的模板长度。
_OVERHEAD = len(_LEAD) + len(_STYLE) + 2  # +2：故事为空时围栏内的换行


def fit_story(story: str, budget: int) -> str:
    """把故事压进 budget 字符内。

    优先**整段丢弃尾部**而不是从中间截断：故事第三段通常是"观星指引/升华"，
    可视意象最少，砍它比砍前两段损失小。段落数不变时再退化为硬截断。
    """
    text = story.strip()
    if budget <= 0 or len(text) <= budget:
        return text
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    kept: list[str] = []
    used = 0
    for para in paragraphs:
        extra = len(para) + (2 if kept else 0)
        if used + extra > budget:
            break
        kept.append(para)
        used += extra
    if kept:
        return "\n\n".join(kept)
    # 单段就超预算：硬截断并留省略号，避免整张图没有故事依据
    return text[: max(0, budget - 1)].rstrip() + "…"


def build_prompt(story: str, budget: int = IMAGE_STORY_MAX_CHARS) -> str:
    """组装最终 prompt，保证不超过接口 1500 字符上限。"""
    story_budget = min(budget, PROMPT_LIMIT - _OVERHEAD)
    return f"{_LEAD}{fit_story(story, story_budget)}{_STYLE}"
