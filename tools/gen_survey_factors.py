"""从 7 份实勘表 xlsx 抽取每类别的逐因素清单 → 生成 miniprogram/factors.js。

实勘表左列（区位状况/实物状况/权益状况）逐因素，每因素在表里带「描述(D列)+档次(E列)」。
本脚本只抽因素名与分组（不抽样例值），供钉钉小程序现场采集页按类别渲染。
因素清单随实勘表变动就重跑本脚本；生成物勿手改。

用法：uv run python tools/gen_survey_factors.py
"""

from __future__ import annotations

import glob
import json
import os
import re

import openpyxl

# 文件名前缀 → 小程序类别值（对齐 form.js CATEGORIES / src.model.Category 值）
_FILE_TO_CATEGORY = {
    "住宅": "住宅",
    "停车场用地": "停车场用地",
    "农用地": "农用",
    "办公": "办公",
    "商业": "商业",
    "工业": "工业",
    "建设用地": "建设用地",
}

_SRC_GLOB = "../输入7种excel案例+输出两种报告模版/*实勘表、比较法.xlsx"
_OUT = "miniprogram/factors.js"


def _norm_section(text: str) -> str:
    """区位状况/实物状况/权益状况(二) → 去掉「(二)」等序号后缀。"""
    return re.sub(r"[(（].*?[)）]", "", text).strip()


def _extract(path: str) -> list[dict[str, object]]:
    wb = openpyxl.load_workbook(path, data_only=True)
    sheet = next((s for s in wb.sheetnames if "查勘记录" in s or "实地查勘" in s), wb.sheetnames[0])
    ws = wb[sheet]
    groups: list[dict[str, object]] = []
    index: dict[str, list[str]] = {}
    section = ""
    for r in range(17, 46):  # 17 起是资产状况块；46 行是「现场查勘记录人员」不算因素
        a = (str(ws.cell(r, 1).value).strip() if ws.cell(r, 1).value else "")
        name = (str(ws.cell(r, 2).value).strip() if ws.cell(r, 2).value else "") or (
            str(ws.cell(r, 3).value).strip() if ws.cell(r, 3).value else ""
        )
        if a and "状况" in a and not a.startswith("资产"):
            section = _norm_section(a)
            if section not in index:
                index[section] = []
                groups.append({"section": section, "items": index[section]})
        if name and section:
            items = index[section]
            if name not in items:  # 去重（个别表同名因素重复了一行）
                items.append(name)
    return groups


def main() -> None:
    files = sorted(glob.glob(_SRC_GLOB))
    if not files:
        raise SystemExit(f"找不到实勘表：{_SRC_GLOB}")
    out: dict[str, list[dict[str, object]]] = {}
    for path in files:
        base = os.path.basename(path)
        prefix = base.split("实勘")[0]
        category = _FILE_TO_CATEGORY.get(prefix)
        if not category:
            print(f"跳过未识别类别：{base}")
            continue
        out[category] = _extract(path)
        total = sum(len(g["items"]) for g in out[category])  # type: ignore[arg-type]
        print(f"{category}: {total} 因素 / {len(out[category])} 组")

    body = json.dumps(out, ensure_ascii=False, indent=2)
    text = (
        "// 由 tools/gen_survey_factors.py 从 7 份实勘表自动生成，勿手改。\n"
        "// 每类别逐因素清单（区位/实物/权益状况），现场采集页按类别渲染「描述+档次」。\n"
        f"module.exports = {body};\n"
    )
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"已写 {_OUT}")


if __name__ == "__main__":
    main()
