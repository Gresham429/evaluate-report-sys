"""金样回归——本项目的验收标准。

系统必须能用三份真实 Excel 复现出三份真实报告。比对前对两侧文本做两层
归一化：

1. `normalise()`（`src/prose/drift.py`）：模去 25 处已确认的漂移统一
   （序号点号、全角冒号、"见诸于"等）。这是单一事实源，规则本身不在本
   测试改动。
2. `_strip_thousands_separators()`（本文件）：模去千分位差异。金样金额/
   面积未加千分位（如 70000），系统按用户明确要求统一加千分位输出
   （70,000，见 `src/renderer/render.py::_fmt`）。这是已批准的功能改动，
   drift.py 不处理（千分位不是"漂移"，是有意的格式升级），因此比对时在
   测试层面额外容许——不得反过来在 src/ 里回退千分位功能。

断言：除上述两类已确认改进外，其余一字不差。
"""

import re
from pathlib import Path

import pytest

from src.extractor.project import load_project
from src.prose.compare import diff_report, extract_paragraphs
from src.prose.drift import normalise
from src.renderer.render import render
from tests.conftest import CASES, GOLDENS

CASE_NAMES = ("农用", "办公", "商业")

# 三位一组的千分位逗号，如 "70,000" 中 7 与 0 之间的那个逗号。
# 使用 (?<=\d),(?=\d{3}) 而非贪婪匹配多组，因为 re.sub 会从左到右
# 非重叠扫描，逗号本身不被消费，多组逗号（如 "1,234,567"）仍会逐个命中。
_THOUSANDS_SEP_RE = re.compile(r"(?<=\d),(?=\d{3})")


def _strip_thousands_separators(text: str) -> str:
    """比对专用：去除数字千分位逗号。

    仅供本测试文件在归一化后再做一次比对前处理，不改变 drift.py 的规则
    集合，也不影响 `src/renderer/render.py` 的千分位输出功能——那是用户
    明确要求保留的行为。

    Args:
        text: 归一化后的段落文本。

    Returns:
        千分位逗号被移除后的文本。
    """
    return _THOUSANDS_SEP_RE.sub("", text)


def _normalise_for_diff(text: str) -> str:
    """金样回归比对专用的归一化：漂移统一 + 千分位容差。"""
    return _strip_thousands_separators(normalise(text))


@pytest.mark.parametrize("case", CASE_NAMES)
def test_golden_paragraph_coverage(case: str, tmp_path: Path) -> None:
    """渲染结果应覆盖金样的全部段落（归一化 + 千分位容差后）。"""
    project = load_project(CASES[case])
    output = tmp_path / f"{case}.docx"
    render(project, [], output)

    expected = {_normalise_for_diff(p) for p in extract_paragraphs(GOLDENS[case]) if len(p) > 12}
    actual = {_normalise_for_diff(p) for p in extract_paragraphs(output) if len(p) > 12}

    missing = expected - actual
    assert not missing, diff_report(sorted(missing), sorted(actual))


@pytest.mark.parametrize("case", CASE_NAMES)
def test_golden_key_facts_present(case: str, tmp_path: Path) -> None:
    """关键事实必须出现在报告中。"""
    project = load_project(CASES[case])
    output = tmp_path / f"{case}.docx"
    render(project, [], output)
    text = "\n".join(extract_paragraphs(output))

    assert project.report_no in text
    assert project.owner in text
    for subject in project.subjects:
        assert subject.address in text
        assert f"{subject.annual_value:,}" in text or str(subject.annual_value) in text


@pytest.mark.parametrize("case", CASE_NAMES)
def test_output_has_no_drift(case: str, tmp_path: Path) -> None:
    """输出必须已消除全部漂移。"""
    project = load_project(CASES[case])
    output = tmp_path / f"{case}.docx"
    render(project, [], output)
    for paragraph in extract_paragraphs(output):
        assert normalise(paragraph) == paragraph, f"输出仍含漂移：{paragraph[:60]}"


@pytest.mark.parametrize("case", CASE_NAMES)
def test_no_unrendered_placeholders(case: str, tmp_path: Path) -> None:
    """不得有未渲染的 Jinja 占位符漏进成品。"""
    project = load_project(CASES[case])
    output = tmp_path / f"{case}.docx"
    render(project, [], output)
    text = "\n".join(extract_paragraphs(output))
    assert "{{" not in text
    assert "{%" not in text
