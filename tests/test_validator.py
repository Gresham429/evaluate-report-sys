"""校验器测试。校验只提示，不阻断——是否为问题由估价师判断。"""

from src.extractor.project import load_project
from src.validator.checks import validate
from tests.conftest import CASES


def test_all_real_cases_produce_no_blocking_error() -> None:
    """三份真实素材都应能通过（可以有警告，但绝不抛异常）。"""
    for path in CASES.values():
        warnings = validate(load_project(path), path)
        assert isinstance(warnings, tuple)


def test_dispersion_within_threshold_no_warning() -> None:
    project = load_project(CASES["农用"])  # 离散度 0.01
    codes = {w.code for w in validate(project, CASES["农用"])}
    assert "DISPERSION_HIGH" not in codes


def test_external_reference_detected_in_office() -> None:
    """办公表 I33 引用他人机器绝对路径，应被检出。"""
    codes = {w.code for w in validate(load_project(CASES["办公"]), CASES["办公"])}
    assert "EXTERNAL_REF" in codes


def test_agricultural_result_table_consistency() -> None:
    """农用 L=K*J（不乘365）：1400*50=70000。"""
    codes = {w.code for w in validate(load_project(CASES["农用"]), CASES["农用"])}
    assert "TABLE_INCONSISTENT" not in codes


def test_office_result_table_consistency() -> None:
    """办公 L=round(J*K*365)：356.29*2.83*365=368030。"""
    codes = {w.code for w in validate(load_project(CASES["办公"]), CASES["办公"])}
    assert "TABLE_INCONSISTENT" not in codes


def test_missing_report_no_warns() -> None:
    from dataclasses import replace

    project = replace(load_project(CASES["办公"]), report_no="")
    codes = {w.code for w in validate(project, CASES["办公"])}
    assert "MISSING_FIELD" in codes
