"""办公端「一次配好、每人解压即用」整包脚本的测试。

被测：`tools/make_office_bundle.py`。它把 IT 填好的 `.env` 注入交付 zip 的 exe 同层，
产出「解压即用」的整包，让不懂电脑的估价师只需解压→双击→扫码，不碰任何配置。

两条部署暗坑必须被脚本挡住（都源自 `src/__main__._load_dotenv` 的解析规则）：
① 行内 `#` 注释不被程序剥离（line 88 只 partition("=")+strip）→ 会把注释吞进值里；
② `承载后端` 必须严格 `=多维表`，否则整包退回本地模式（无同步/无登录/无门禁）。
"""

import zipfile
from pathlib import Path

import pytest

from tools.make_office_bundle import audit_office_env, make_bundle, parse_env

# —— 一份「填好的」办公端 .env（假值，但非占位；结构对齐 deploy/office.env.example）——
FILLED_ENV = """\
承载后端=多维表
YIDA_APP_KEY=dingabc123
YIDA_APP_SECRET=secretXYZ789
NOTABLE_BASE_ID=base_KKK
NOTABLE_OPERATOR_ID=jYDAunion001
NOTABLE_SURVEY_SHEET=SVsheet01
NOTABLE_INSTANCE_SHEET=SjxzHcU
NOTABLE_BASETABLE_SHEET=XHRMxps
NOTABLE_LEDGER_SHEET=hERWDMS
OFFICE_ADMINS=
OFFICE_ALLOWED_USERS=
"""

_APP_DIR = "appraisal-report-system"


def _make_delivery_zip(tmp_path: Path) -> Path:
    """造一个和真交付 zip 同构的合成包：顶层 appraisal-report-system/ 下摆 exe 等。"""
    root = tmp_path / "src_pkg" / _APP_DIR
    (root / "templates").mkdir(parents=True)
    (root / f"{_APP_DIR}.exe").write_bytes(b"MZfake-exe")
    (root / "templates" / "office.docx").write_bytes(b"docx-bytes")
    (root / "copy.yaml").write_text("copy: 文案", encoding="utf-8")
    (root / ".env.example").write_text("承载后端=多维表\n", encoding="utf-8")
    (root / "使用说明.docx").write_bytes(b"manual-bytes")  # 唯一允许的中文名松散文件
    zip_path = tmp_path / f"{_APP_DIR}-windows.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(root.parent))
    return zip_path


# ---------------- parse_env：必须与 _load_dotenv 一字不差 ----------------


def test_parse_env_strips_key_and_value() -> None:
    assert parse_env("承载后端 = 多维表\n") == {"承载后端": "多维表"}


def test_parse_env_skips_comment_and_blank_lines() -> None:
    text = "# 注释\n\nYIDA_APP_KEY=k\n"
    assert parse_env(text) == {"YIDA_APP_KEY": "k"}


def test_parse_env_keeps_inline_hash_in_value_like_the_app_does() -> None:
    # 程序不剥离行内 #，值会连注释一起被读进去——校验必须照抄这个行为才能抓到暗坑。
    assert parse_env("YIDA_APP_SECRET=abc  # 敏感\n") == {"YIDA_APP_SECRET": "abc  # 敏感"}


# ---------------- audit_office_env：填好的过、坑要报 ----------------


def test_audit_clean_env_has_no_errors_or_warnings() -> None:
    audit = audit_office_env(FILLED_ENV)
    assert audit.errors == []
    assert audit.warnings == []


def test_audit_flags_missing_required_key() -> None:
    env = FILLED_ENV.replace("NOTABLE_BASE_ID=base_KKK\n", "")
    audit = audit_office_env(env)
    assert any("NOTABLE_BASE_ID" in e for e in audit.errors)


def test_audit_flags_unfilled_placeholder() -> None:
    env = FILLED_ENV.replace("YIDA_APP_KEY=dingabc123", "YIDA_APP_KEY=你的AppKey")
    audit = audit_office_env(env)
    assert any("YIDA_APP_KEY" in e for e in audit.errors)


def test_audit_errors_when_switch_not_notable() -> None:
    env = FILLED_ENV.replace("承载后端=多维表", "承载后端=")
    audit = audit_office_env(env)
    assert any("承载后端" in e for e in audit.errors)


def test_audit_warns_on_office_operator_id_set() -> None:
    env = FILLED_ENV + "OFFICE_OPERATOR_ID=10076\n"
    audit = audit_office_env(env)
    assert any("OFFICE_OPERATOR_ID" in w for w in audit.warnings)
    assert audit.errors == []  # 只提醒、不阻断


def test_audit_warns_on_inline_comment_in_value() -> None:
    env = FILLED_ENV.replace(
        "YIDA_APP_SECRET=secretXYZ789", "YIDA_APP_SECRET=secretXYZ789  # 别删"
    )
    audit = audit_office_env(env)
    assert any("YIDA_APP_SECRET" in w or "#" in w for w in audit.warnings)


# ---------------- make_bundle：注入 .env、产出 ASCII 整包 ----------------


def test_make_bundle_injects_env_beside_exe(tmp_path: Path) -> None:
    delivery = _make_delivery_zip(tmp_path)
    env_file = tmp_path / "filled.env"
    env_file.write_text(FILLED_ENV, encoding="utf-8")
    out = tmp_path / "out"

    bundle = make_bundle(delivery, env_file, out)

    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
        assert f"{_APP_DIR}/.env" in names
        assert zf.read(f"{_APP_DIR}/.env").decode("utf-8") == FILLED_ENV
        # 原有内容仍在
        assert f"{_APP_DIR}/{_APP_DIR}.exe" in names
        assert f"{_APP_DIR}/copy.yaml" in names


def test_make_bundle_output_name_is_ascii(tmp_path: Path) -> None:
    delivery = _make_delivery_zip(tmp_path)
    env_file = tmp_path / "filled.env"
    env_file.write_text(FILLED_ENV, encoding="utf-8")

    bundle = make_bundle(delivery, env_file, tmp_path / "out")

    assert bundle.name.isascii()
    assert bundle.suffix == ".zip"


def test_make_bundle_raises_on_invalid_env(tmp_path: Path) -> None:
    delivery = _make_delivery_zip(tmp_path)
    env_file = tmp_path / "bad.env"
    env_file.write_text(FILLED_ENV.replace("承载后端=多维表", "承载后端="), encoding="utf-8")

    with pytest.raises(ValueError, match="承载后端"):
        make_bundle(delivery, env_file, tmp_path / "out")
