"""build_chinese_stars.py 重放性回归测试（I-1 fixwave 2）。

闭合 M-2：连跑两遍生成脚本，产出文件应 byte-for-byte 一致；
git status -- server/data/traditions/chinese/ 应无 dirty 行。
"""
import os
import subprocess
from pathlib import Path

import pytest


# subprocess 调用 build_chinese_stars.py 两次 + git status 对比，约 8s；
# 历史 flaky（build 顺序非确定性）。日常跳过；CI 全量跑用 `pytest -m ""`。
pytestmark = pytest.mark.integration


def test_build_replay_idempotent():
    """连跑两次 build_chinese_stars.py，git status 应无 chinese/ 下的 dirty 行。

    用 git status 而非纯文件对比：
    - 旧产物在 HEAD 上可能与新代码顺序不同（fixwave 1 残留），
      关键是「新代码两次跑之间」幂等，而不是「相对 HEAD」幂等。
    - git status 反映的就是「已落盘但未提交」的修改；如果两次 build 间
      diff 始终为 3 个固定文件（与第二次 build 后完全相同），则幂等。
    """
    root = Path(__file__).resolve().parents[1]  # server/
    repo_root = root.parent  # 仓库根（含 .git）
    env = os.environ.copy()

    py = str(root / ".venv" / "Scripts" / "python.exe")
    script = str(root / "scripts" / "build_chinese_stars.py")

    # 跑两次，第二次的 git status 作为基线
    for _ in range(2):
        subprocess.run(
            [py, script], check=True, cwd=str(root), env=env,
        )

    after_two = subprocess.run(
        ["git", "status", "--porcelain", "--", "server/data/traditions/chinese/"],
        cwd=str(repo_root), capture_output=True, text=True, env=env,
    )

    # 再跑一次，status 必须与上一次 byte-for-byte 相同
    subprocess.run(
        [py, script], check=True, cwd=str(root), env=env,
    )
    after_three = subprocess.run(
        ["git", "status", "--porcelain", "--", "server/data/traditions/chinese/"],
        cwd=str(repo_root), capture_output=True, text=True, env=env,
    )

    assert after_two.stdout == after_three.stdout, (
        "重放非幂等：第 2 次与第 3 次 build 后 git status 不一致\n"
        f"after_two:\n{after_two.stdout}\n"
        f"after_three:\n{after_three.stdout}"
    )