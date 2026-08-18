"""办公端「一次配好、每人解压即用」整包脚本。

**解决什么**：交付 exe 默认本地模式；要联公司钉钉多维表须在 exe 旁放一份填好的 `.env`
（含 AppKey/Secret、baseId、四个 sheetId）。那份 `.env` 全公司同一份、不是每人一份——
本脚本让**一个懂的人填一次**，把它注入交付 zip，产出「解压即用」的整包；估价师只需
解压→双击 exe→手机扫码，全程不碰配置。

**挡两个部署暗坑**（都源自 `src/__main__._load_dotenv` 的解析：只 `partition("=")`+strip）：
① 行内 `#` 注释不被剥离 → 会把注释吞进值里、连不上；
② `承载后端` 必须严格 `=多维表`，否则整包退回本地模式（无同步/无登录/无门禁），白配。
另外还挡 §坑7（中文名松散文件被国产解压软件解成乱码）与「误填 OFFICE_OPERATOR_ID
导致所有人共用一个身份、破坏『只看自己』」。

用法：
    uv run python tools/make_office_bundle.py 交付.zip 填好的.env --out dist/
"""

import argparse
import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["EnvAudit", "audit_office_env", "make_bundle", "parse_env"]

# 交付 zip 顶层的应用目录名 / 整包输出名——一律 ASCII（理由见 build_exe.py 的 §坑7 注释）。
_APP_DIR = "appraisal-report-system"
_OUT_STEM = "appraisal-report-system-office-configured-windows"

# 承载后端总开关须严格等于此值，否则整包退回本地模式。
_SWITCH_KEY = "承载后端"
_SWITCH_ON = "多维表"

# 联多维表必须齐备的键（缺一即连不上）。
_REQUIRED_KEYS = (
    _SWITCH_KEY,
    "YIDA_APP_KEY",
    "YIDA_APP_SECRET",
    "NOTABLE_BASE_ID",
    "NOTABLE_OPERATOR_ID",
    "NOTABLE_SURVEY_SHEET",
    "NOTABLE_INSTANCE_SHEET",
    "NOTABLE_BASETABLE_SHEET",
    "NOTABLE_LEDGER_SHEET",
)

# deploy/office.env.example 里的占位值：值仍是这些＝没填。
_PLACEHOLDERS = frozenset(
    {
        "你的AppKey",
        "你的AppSecret",
        "多维表baseId",
        "操作人unionId",
        "实勘问卷sheetId",
        "实例库sheetId",
        "基础表sheetId",
        "台账sheetId",
    }
)

# §坑7：整包里唯一允许的中文名松散文件（估价师用眼睛打开、非机器按名找）。
_ALLOWED_NON_ASCII = frozenset({"使用说明.docx"})


def parse_env(text: str) -> dict[str, str]:
    """按 `src/__main__._load_dotenv` 的同一规则解析 .env——返回程序真正会读到的值。

    刻意**不**剥离行内 `#`：程序也不剥，照抄才能让校验看到与运行时一致的值，
    从而抓出「行内注释被吞进值」这个暗坑。
    """
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


@dataclass(frozen=True)
class EnvAudit:
    """一次 .env 体检结果：`errors` 阻断注入（strict 下抛），`warnings` 只提醒。"""

    values: dict[str, str]
    errors: list[str]
    warnings: list[str]


def audit_office_env(text: str) -> EnvAudit:
    """体检 IT 填好的办公端 .env，把「注入前必须修」和「要知道但不阻断」分开报。"""
    values = parse_env(text)
    errors: list[str] = []
    warnings: list[str] = []

    if values.get(_SWITCH_KEY, "") != _SWITCH_ON:
        errors.append(
            f"{_SWITCH_KEY} 必须 ={_SWITCH_ON}（当前={values.get(_SWITCH_KEY, '<缺>')!r}）；"
            "否则整包退回本地模式，无公司同步、无登录、无门禁。"
        )

    for key in _REQUIRED_KEYS:
        if key == _SWITCH_KEY:
            continue
        val = values.get(key, "")
        if not val:
            errors.append(f"{key} 未填（联多维表必须齐备）。")
        elif val in _PLACEHOLDERS or val.startswith("你的"):
            errors.append(f"{key} 仍是模板占位值 {val!r}，请填真实值。")

    if values.get("OFFICE_OPERATOR_ID", ""):
        warnings.append(
            "OFFICE_OPERATOR_ID 被设值：会让每台机共用同一身份、破坏「只看自己」。"
            "办公端整包应靠扫码登录识别本人，请删掉此行。"
        )

    for key, val in values.items():
        if "#" in val:
            warnings.append(
                f"{key} 的值里含 `#`（{val!r}）：程序不剥离行内注释、会把注释也当成值，"
                "多半连不上；请删掉行内注释。"
            )

    return EnvAudit(values=values, errors=errors, warnings=warnings)


def _find_app_dir(extract_root: Path) -> Path:
    """在解压根里定位应用目录（含 exe 的那层）。

    真交付 zip 顶层是单个 `appraisal-report-system/`。优先按名找，找不到再退回
    「唯一的顶层目录」；都不成立就报错——宁可炸也不猜错、往错地方塞 .env。
    """
    named = extract_root / _APP_DIR
    if named.is_dir():
        return named
    subdirs = [p for p in extract_root.iterdir() if p.is_dir()]
    if len(subdirs) == 1:
        return subdirs[0]
    raise ValueError(
        f"认不出交付 zip 的应用目录（顶层子目录={[p.name for p in subdirs]}）；"
        f"期望单个 {_APP_DIR}/。"
    )


def make_bundle(
    delivery_zip: Path, env_file: Path, out_dir: Path, *, strict: bool = True
) -> Path:
    """把 `env_file` 注入 `delivery_zip` 的 exe 同层为 `.env`，产出 ASCII 名整包 zip。

    Args:
        delivery_zip: GitHub Actions 出的交付 zip（顶层 appraisal-report-system/）。
        env_file: IT 填好真实值的 .env（原样写进整包，程序启动即读它联多维表）。
        out_dir: 整包输出目录（不存在则建）。
        strict: True（默认）时体检有 error 即抛 ValueError；--force 传 False 强行打包。

    Returns:
        产出的整包 zip 路径。
    """
    delivery_zip = Path(delivery_zip)
    env_file = Path(env_file)
    out_dir = Path(out_dir)

    env_text = env_file.read_text(encoding="utf-8")
    audit = audit_office_env(env_text)
    for w in audit.warnings:
        logger.warning("⚠ %s", w)
    if audit.errors:
        for e in audit.errors:
            logger.error("✗ %s", e)
        if strict:
            raise ValueError("；".join(audit.errors))

    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        extract_root = Path(td)
        with zipfile.ZipFile(delivery_zip) as zf:
            zf.extractall(extract_root)
        app_dir = _find_app_dir(extract_root)

        (app_dir / ".env").write_text(env_text, encoding="utf-8")

        for f in app_dir.rglob("*"):
            if f.is_file() and not f.name.isascii() and f.name not in _ALLOWED_NON_ASCII:
                logger.warning(
                    "⚠ §坑7：整包里有中文名文件 %s，国产解压软件可能解成乱码。", f.name
                )

        bundle = Path(
            shutil.make_archive(str(out_dir / _OUT_STEM), "zip", extract_root, app_dir.name)
        )
    logger.info("已产出整包 %s（%.2f MB）", bundle, bundle.stat().st_size / 1024 / 1024)
    return bundle


def main(argv: list[str] | None = None) -> int:
    """命令行入口：交付 zip + 填好的 .env → 办公端整包。"""
    parser = argparse.ArgumentParser(
        description="把填好的 .env 注入交付 zip，产出「解压即用」的办公端整包"
    )
    parser.add_argument("delivery_zip", type=Path, help="GitHub Actions 出的交付 zip")
    parser.add_argument("env_file", type=Path, help="填好真实值的 .env（含 app secret）")
    parser.add_argument(
        "--out", type=Path, default=Path("dist"), help="整包输出目录（默认 dist/）"
    )
    parser.add_argument(
        "--force", action="store_true", help="体检有 error 也强行打包（不建议）"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        bundle = make_bundle(
            args.delivery_zip, args.env_file, args.out, strict=not args.force
        )
    except (ValueError, FileNotFoundError, zipfile.BadZipFile) as exc:
        logger.error("整包失败：%s", exc)
        return 1

    logger.info(
        "下一步：把 %s 发给每个估价师，他们解压→双击 exe→手机扫码即用。", bundle.name
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
