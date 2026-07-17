"""校验器测试。校验只提示，不阻断——是否为问题由估价师判断。"""

from dataclasses import replace

from src.extractor.project import load_project
from src.model import ConditionFactor, ConditionGroup
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


# ── 规模字段一致性（表单输入的「替他核」）──────────────────────────

def test_scale_matches_in_all_three_goldens() -> None:
    """三份金样三种写法，一条都不许误报。

    农用/办公写合计，商业逐对象列（60、70，合计 130 从没写出来）。
    一个总在喊狼来了的提示，比没有提示更糟。

    只覆盖三份有签发报告的金样：新四类是对方给的构造样例，规模文字与一览表本就
    不自洽（如住宅规模写 1342.59㎡、一览表 342.59），SCALE_MISMATCH 是**正确的
    提示**（校验只提示不阻断），不该在这里当误报断。新类别不炸校验器由
    test_all_real_cases_produce_no_blocking_error 兜。
    """
    for case in ("农用", "办公", "商业"):
        path = CASES[case]
        codes = {w.code for w in validate(load_project(path), path)}
        assert "SCALE_MISMATCH" not in codes, f"{case} 被误报"


def test_scale_typo_is_caught() -> None:
    """把 723.69 手滑打成 732.69——正是这条检查存在的理由。"""
    from dataclasses import replace

    project = load_project(CASES["办公"])
    typo = replace(project, scale="房屋建筑面积732.69平方米及其分摊的土地使用权")
    warnings = [w for w in validate(typo) if w.code == "SCALE_MISMATCH"]
    assert len(warnings) == 1
    assert "732.69" in warnings[0].message
    assert "723.69" in warnings[0].message


def test_scale_accepts_per_subject_listing() -> None:
    """商业那种逐对象列的写法：60 + 70 = 130 对得上合计，不报。"""
    codes = {w.code for w in validate(load_project(CASES["商业"]))}
    assert "SCALE_MISMATCH" not in codes


def test_scale_without_recognisable_area_stays_quiet() -> None:
    """找不到按该类别单位计的数就不吭声——没把握就别喊。"""
    from dataclasses import replace

    project = replace(load_project(CASES["办公"]), scale="详见附件清单")
    codes = {w.code for w in validate(project)}
    assert "SCALE_MISMATCH" not in codes


def test_validate_works_without_excel() -> None:
    """表单路径没有源文件：不传 path 也要能校验，只是跳过外部引用那一项。"""
    project = load_project(CASES["办公"])
    codes = {w.code for w in validate(project)}
    assert "EXTERNAL_REF" not in codes
    assert isinstance(validate(project), tuple)


# ── 资产状况──────────────────────────────────────────────────

def test_warns_empty_description_but_does_not_block() -> None:
    """资产状况因素描述留空应提示，但不阻断校验。"""
    project = load_project(CASES["办公"])
    # 创建一个因素描述为空的资产状况
    project_with_empty_desc = replace(
        project,
        asset_condition_groups=(
            ConditionGroup(
                name="区位状况",
                factors=(
                    ConditionFactor(name="楼层", description=""),
                    ConditionFactor(name="位置", description="良好的位置"),
                ),
            ),
        ),
    )
    warnings = validate(project_with_empty_desc)
    assert any(w.code == "ASSET_CONDITION_INCOMPLETE" for w in warnings)
    # 只提示，不阻断
    assert isinstance(warnings, tuple)
