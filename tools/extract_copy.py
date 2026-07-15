"""开发期工具：从三份金样抽取共有样板文字，生成 copy.yaml。

三份金样的章节结构完全相同（23 个目录项），共有段落即三类通用的
法定套话。求交集前先做漂移归一化，否则「1.」与「1、」会被当成不同段落。

用法：
    uv run python tools/extract_copy.py
"""

import html
import logging
import re
import sys
import zipfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.prose.drift import normalise  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

MATERIALS = Path(__file__).resolve().parents[2] / "案例素材"
GOLDENS = {
    "农用": MATERIALS / "农用" / "正恒评报字[2026]第F093号.docx",
    "办公": MATERIALS / "办公" / "正恒评报字[2026]第F071号.docx",
    "商业": MATERIALS / "商业" / "正恒评报字[2026]第F098号.docx",
}
OUTPUT = Path(__file__).resolve().parents[1] / "src" / "prose" / "copy.yaml"

# 本所签字的注册房地产估价师。固定两人，但配置化——换人只改此处。
# 报告抬头写作「韩  伟」（含空格），而实勘表 D46 录作「韩伟」，
# 比对前须去空格，故此处存无空格形式。
REGISTERED_APPRAISERS: list[str] = ["韩伟", "胡柯"]

# 条件文本：无法由交集得出（各类各异），依设计文档第 7.2 节手工确定
CONDITIONAL: dict[str, dict[str, str]] = {
    "估价范围": {
        "农用": "本次估价范围包含土地使用权，不包含水电费、债权债务、特许经营权等其他权利。",
        "房屋": "本次估价范围包含房屋及其分摊建设用地使用权，不包含水电费、网费、物业费、"
                "债权债务、特许经营权等其他权利。",
    },
    "权证": {
        "已取得": "估价对象已取得《不动产权证》",
        "未取得": "估价对象未取得《不动产权证》",
    },
    "资料清单": {
        "已取得": "《委托评估协议书》、《不动产权证》复印件；",
        "未取得": "《委托评估协议书》复印件；",
    },
    # 查勘人若本身就是抬头署名的注册估价师（如办公类 D46=胡柯），
    # 抬头已署其名，正文不再单独提。否则（如农用/商业 D46=郑伟娜）须署名。
    "查勘人署名": {
        "有": "5.注册房地产估价师及现场查勘记录人员{{ surveyor }}已对本报告中的估价对象"
              "进行了实地查勘。",
        "无": "5.注册房地产估价师已对本报告中的估价对象进行了实地查勘。",
    },
    "附件清单第三项": {
        "已取得": "三、《委托评估协议书》、《不动产权证》复印件",
        "未取得": "三、《委托评估协议书》复印件",
    },
}


def paragraphs(path: Path) -> list[str]:
    """抽取 docx 的段落文本。"""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    xml = re.sub(r"</w:p>", "\n", xml)
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    return [line.strip() for line in text.split("\n") if line.strip()]


def main() -> int:
    missing = [str(p) for p in GOLDENS.values() if not p.exists()]
    if missing:
        logger.error("金样缺失：%s", missing)
        return 1

    normalised = {
        tag: {normalise(p) for p in paragraphs(path) if len(p) > 12}
        for tag, path in GOLDENS.items()
    }
    common = normalised["农用"] & normalised["办公"] & normalised["商业"]
    logger.info("三类共有段落（归一化后）：%d 段", len(common))

    boilerplate = {
        f"para_{i:03d}": text for i, text in enumerate(sorted(common, key=len, reverse=True), 1)
    }
    data = {
        "registered_appraisers": REGISTERED_APPRAISERS,
        "boilerplate": boilerplate,
        "conditional": CONDITIONAL,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=200),
        encoding="utf-8",
    )
    logger.info("已写出 %s（%d 段样板 + %d 组条件文本）", OUTPUT, len(boilerplate), len(CONDITIONAL))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
