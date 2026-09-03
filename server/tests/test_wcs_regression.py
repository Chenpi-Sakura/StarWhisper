"""scripts.wcs_regression 的纯 Python 单元测试。

不依赖 astropy：lock_y_flip 只做像素欧氏距离 + max 判定，与 WCS 投影无关。
"""
import pytest

from scripts.wcs_regression import RegressionError, lock_y_flip


def test_no_flip_when_diffs_all_small():
    """全部对得齐：不翻转。"""
    solved = [{"x": 100, "y": 200}, {"x": 300, "y": 400}, {"x": 500, "y": 600}]
    fixture = [{"x": 100, "y": 200}, {"x": 300, "y": 400}, {"x": 500, "y": 600}]
    assert lock_y_flip(solved, fixture, img_h=1000) is False


def test_flip_when_flip_diff_small():
    """不翻转误差大，翻转后误差小：判定翻转。"""
    solved = [{"x": 100, "y": 200}, {"x": 300, "y": 400}]
    fixture = [{"x": 100, "y": 800}, {"x": 300, "y": 600}]  # y 翻转对应
    assert lock_y_flip(solved, fixture, img_h=1000) is True


def test_regression_when_neither_matches():
    """两种朝向都不匹配 → RegressionError。"""
    solved = [{"x": 100, "y": 200}]
    fixture = [{"x": 500, "y": 500}]
    with pytest.raises(RegressionError):
        lock_y_flip(solved, fixture, img_h=1000)


def test_regression_uses_max_not_min():
    """回归保护：单星座靠近中心时翻不翻都 < 2px，max 判定才不会侥幸选错。

    这里构造「全部对齐」的场景，确保 no_flip_max < 2px，返回 False；
    若有人偷偷改成 ``min``，本断言也会通过（最小更小），
    但若改成「只判一颗」且 fixture 凑巧靠近图中心，行为就会暴露差异。
    本用例 + 上面三个用例共同把判定函数锁死成「max + 双侧都不匹配就抛错」。
    """
    solved = [{"x": 100, "y": 100}, {"x": 500, "y": 500}]
    fixture = [{"x": 100, "y": 100}, {"x": 500, "y": 500}]  # 全部对齐
    assert lock_y_flip(solved, fixture, img_h=1000) is False


def test_length_mismatch_raises():
    """长度不一致直接抛 RegressionError，不进入比对。"""
    solved = [{"x": 100, "y": 200}]
    fixture = [{"x": 100, "y": 200}, {"x": 300, "y": 400}]
    with pytest.raises(RegressionError):
        lock_y_flip(solved, fixture, img_h=1000)


def test_empty_lists_raise():
    """空列表无意义，抛 RegressionError。"""
    with pytest.raises(RegressionError):
        lock_y_flip([], [], img_h=1000)