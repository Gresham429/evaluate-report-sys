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
        # 房屋安全：办公金样真实句式「已对安全、」→「已对房屋安全、」
        ("已对安全、环境污染等因素", "已对房屋安全、环境污染等因素"),
        # 书名号
        ("委托评估协议书复印件", "《委托评估协议书》复印件"),
        # 缺复印件：仅估价依据清单「》；」结尾处补「复印件」
        ("（1）《委托评估协议书》；", "（1）《委托评估协议书》复印件；"),
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


def test_normalise_is_idempotent_on_real_goldens() -> None:
    """幂等性必须在真实金样文本上成立——合成字符串测不出规则互相喂食。"""
    import html
    import re
    import zipfile
    from pathlib import Path

    materials = Path(__file__).resolve().parents[2] / "案例素材"
    goldens = [
        materials / "农用" / "正恒评报字[2026]第F093号.docx",
        materials / "办公" / "正恒评报字[2026]第F071号.docx",
        materials / "商业" / "正恒评报字[2026]第F098号.docx",
    ]
    if not all(g.exists() for g in goldens):
        pytest.skip("案例素材缺失")

    for golden in goldens:
        with zipfile.ZipFile(golden) as archive:
            xml = archive.read("word/document.xml").decode("utf-8")
        text = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", xml)))
        for line in (raw_line.strip() for raw_line in text.split("\n") if raw_line.strip()):
            once = normalise(line)
            assert normalise(once) == once, f"{golden.name} 不收敛：{line[:60]}"


def test_agreement_reference_in_body_not_given_copy_suffix() -> None:
    """正文「按《委托评估协议书》为准」不得被追加「复印件」——那会让句子不通。"""
    raw = "本次估价对象建筑面积按委托评估协议书为准，委托人确认房屋建筑面积为130平方米"
    result = normalise(raw)
    assert "《委托评估协议书》为准" in result
    assert "复印件为准" not in result


def test_evidence_list_gets_copy_suffix() -> None:
    """估价依据清单的「《委托评估协议书》；」应补为「复印件；」。"""
    assert normalise("（1）《委托评估协议书》；") == "（1）《委托评估协议书》复印件；"


def test_building_safety_rule_matches_real_text() -> None:
    """规则须匹配金样真实句式：办公「已对安全、」→「已对房屋安全、」。"""
    office = "2.注册房地产估价师已对安全、环境污染等影响估价对象价值的重大因素给予了关注"
    assert normalise(office) == (
        "2.注册房地产估价师已对房屋安全、环境污染等影响估价对象价值的重大因素给予了关注"
    )
    # 农用地无房屋，本无「安全」项，不得被改动
    land = "2.注册房地产估价师已对估价对象的环境污染等影响估价对象价值的重大因素给予了关注"
    assert normalise(land) == land
