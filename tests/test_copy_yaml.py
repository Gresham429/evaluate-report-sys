"""文案库测试。"""

from pathlib import Path

import yaml

from src.prose.drift import normalise

COPY_PATH = Path(__file__).resolve().parents[1] / "copy.yaml"


def test_copy_yaml_exists() -> None:
    assert COPY_PATH.exists(), "先运行 uv run python tools/extract_copy.py"


def test_copy_yaml_structure() -> None:
    data = yaml.safe_load(COPY_PATH.read_text(encoding="utf-8"))
    assert "boilerplate" in data
    assert "conditional" in data
    assert "registered_appraisers" in data
    assert len(data["boilerplate"]) >= 40, "三类共有段落应不少于 40 段"


def test_registered_appraisers() -> None:
    """本所签字估价师固定两人，配置化以便换人。"""
    data = yaml.safe_load(COPY_PATH.read_text(encoding="utf-8"))
    assert data["registered_appraisers"] == ["韩伟", "胡柯"]


def test_boilerplate_is_normalised() -> None:
    """样板文字必须已消除漂移。"""
    data = yaml.safe_load(COPY_PATH.read_text(encoding="utf-8"))
    for key, text in data["boilerplate"].items():
        assert normalise(text) == text, f"样板 {key} 未归一化"


def test_conditional_keys() -> None:
    data = yaml.safe_load(COPY_PATH.read_text(encoding="utf-8"))
    cond = data["conditional"]
    assert set(cond["估价范围"]) == {"农用", "房屋"}
    assert set(cond["权证"]) == {"已取得", "未取得"}
    assert set(cond["资料清单"]) == {"已取得", "未取得"}
    assert set(cond["查勘人署名"]) == {"有", "无"}
