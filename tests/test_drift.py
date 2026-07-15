"""漂移归一化测试。规则源自设计文档第 8 节，共 25 处。"""

import pytest

from src.prose.drift import DRIFT_RULES, normalise


def test_rule_count() -> None:
    """设计文档第 8 节确认 25 处漂移点。"""
    assert sum(r.weight for r in DRIFT_RULES) == 25


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 序号：阿拉伯数字后用点号（GB/T 15834-2011 §4.5.3.5）
        ("1、注册房地产估价师在本估价报告中陈述的事实是真实的", "1.注册房地产估价师在本估价报告中陈述的事实是真实的"),
        ("5、遵循最高最佳利用原则", "5.遵循最高最佳利用原则"),
        # 汉字数字序号仍用顿号，不得误改
        ("一、一般性假设", "一、一般性假设"),
        ("十三、估价作业期", "十三、估价作业期"),
        # 冒号全角
        ("注册号:3320130071", "注册号：3320130071"),
        # 见诸于 → 见诸
        ("也不得见诸于任何公开的媒体", "也不得见诸任何公开的媒体"),
        # 房屋安全
        ("已对估价对象的安全、环境污染等因素", "已对估价对象的房屋安全、环境污染等因素"),
        # 书名号
        ("委托评估协议书复印件", "《委托评估协议书》复印件"),
        # 方法别名
        ("收益法（价值折算法）是选取适宜方法", "价值折算法是选取适宜方法"),
        ("假设开发法（剩余法）是根据房地产", "剩余法是根据房地产"),
        # 括号全角
        ("(1)", "（1）"),
    ],
)
def test_normalise(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_normalise_is_idempotent() -> None:
    text = "1、注册号:3320130071，不得见诸于媒体"
    once = normalise(text)
    assert normalise(once) == once


def test_already_correct_text_unchanged() -> None:
    text = "1.注册房地产估价师依照中华人民共和国国家标准《房地产估价规范》"
    assert normalise(text) == text
