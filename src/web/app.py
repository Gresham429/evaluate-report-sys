"""本地网页应用。

单机单用户，无状态，不联网。数据全程留在本机。

四步向导：① 选 Excel → ② 复核数据（可编辑）→ ③ 挑附件、排序 → ④ 生成下载。
复核界面的修改只影响本次生成，不回写 Excel——Excel 是一张公式网，
回写单个值会打断公式链、把计算结果变成死数（见 docs/使用说明.md）。
"""

import json
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask

from src.attachments.collector import AttachmentPage, collect
from src.drafts.model import Draft
from src.drafts.store import DEFAULT_DRAFT_DIR, DraftStore
from src.engine.annual import annual_value
from src.engine.compute import compute_from_selection
from src.engine.inputs import ComparisonInput, from_excel
from src.extractor.project import load_project
from src.knowledge_base.store import (
    DEFAULT_STORE_DIR as DEFAULT_BASE_TABLE_DIR,
)
from src.knowledge_base.store import (
    BaseTableStore,
    VersionInfo,
)
from src.library.importer import import_from_excel
from src.library.store import DEFAULT_STORE_PATH, InstanceStore
from src.model import Category, Project, Subject
from src.prose.composer import area_unit, price_unit
from src.renderer.render import render
from src.validator.checks import check_dispersion, validate

logger = logging.getLogger(__name__)

__all__ = ["create_app"]

_STATIC = Path(__file__).with_name("static")

# 未打包成生成 docx 文件名的非法字符（Windows 文件系统禁用字符）。
_UNSAFE_FILENAME_CHARS = frozenset('/\\:*?"<>|')


def _store_path() -> Path:
    """实例库路径。测试通过环境变量覆盖。"""
    return Path(os.environ.get("实例库路径", str(DEFAULT_STORE_PATH)))


def _draft_dir() -> Path:
    """草稿目录。测试通过环境变量覆盖。"""
    return Path(os.environ.get("草稿目录", str(DEFAULT_DRAFT_DIR)))


def _base_table_dir() -> Path:
    """基础表目录。测试通过环境变量覆盖。"""
    return Path(os.environ.get("基础表目录", str(DEFAULT_BASE_TABLE_DIR)))


def _version_payload(info: VersionInfo) -> dict[str, object]:
    """基础表版本信息 → JSON。

    界面要能明示「当前用的是哪一版」（决策记录 §3.4）：**不阻止**使用旧版本
    （万一 Excel 改了没重导，系统照跑），但用户一眼能看到用的是哪一版。
    与本项目一贯立场一致：保留事实，判断交给人。
    """
    return {
        "类别": info.类别.value,
        "指纹": info.指纹,
        "导入时间": info.导入时间.isoformat(),
        "来源文件名": info.来源文件名,
    }


def _to_float(value: object) -> float:
    """把 JSON 数值字段转成 float；缺失或 None 时按 0 处理。"""
    if value is None:
        return 0.0
    if isinstance(value, int | float | str):
        return float(value)
    raise ValueError(f"数值字段类型不对：{value!r}")


def _project_from_payload(data: dict[str, object]) -> Project:
    """把 /api/render 收到的（可能经用户编辑的）JSON 还原为 Project。

    Args:
        data: 前端提交的项目字段字典，形状与 /api/extract 返回的 project 一致。

    Returns:
        还原后的 Project。

    Raises:
        ValueError: 字段缺失、类型不对，或 category 不是合法枚举值。
    """
    raw_subjects = data.get("subjects")
    if not isinstance(raw_subjects, list):
        raise ValueError("subjects 字段缺失或格式错误")
    subjects = tuple(
        Subject(
            index=int(s["index"]),
            owner=str(s["owner"]),
            address=str(s["address"]),
            usage=str(s["usage"]),
            area=float(s["area"]),
            unit_price=float(s["unit_price"]),
            annual_value=int(s["annual_value"]),
        )
        for s in raw_subjects
    )
    return Project(
        category=Category(str(data.get("category", ""))),
        report_no=str(data.get("report_no", "")),
        project_name=str(data.get("project_name", "")),
        client=str(data.get("client", "")),
        client_address=str(data.get("client_address", "")),
        legal_rep=str(data.get("legal_rep", "")),
        purpose=str(data.get("purpose", "")),
        survey_date=str(data.get("survey_date", "")),
        value_date=str(data.get("value_date", "")),
        materials=str(data.get("materials", "")),
        certificate_status=str(data.get("certificate_status", "")),
        owner=str(data.get("owner", "")),
        address=str(data.get("address", "")),
        usage=str(data.get("usage", "")),
        scale=str(data.get("scale", "")),
        scope=str(data.get("scope", "")),
        current_status=str(data.get("current_status", "")),
        work_period=str(data.get("work_period", "")),
        issue_date=str(data.get("issue_date", "")),
        surveyor=str(data.get("surveyor", "")),
        unit_price=_to_float(data.get("unit_price")),
        dispersion=_to_float(data.get("dispersion")),
        subjects=subjects,
    )


def _templates_dir() -> Path | None:
    """打包成 exe 后模板外置于 exe 同目录；开发环境用 render() 自带的仓库内默认路径。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "templates"
    return None


def _safe_filename(name: str) -> str:
    """把报告编号整理成合法文件名，为空时兜底。"""
    cleaned = "".join(c for c in name if c not in _UNSAFE_FILENAME_CHARS).strip()
    return cleaned or "估价报告"


def create_app() -> FastAPI:
    """构建 FastAPI 应用。"""
    app = FastAPI(title="房地产估价报告生成系统", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((_STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/instances")
    def list_instances(category: str) -> dict[str, object]:
        """按类别列出实例，起始日从新到旧。

        **不做推荐、不高亮、不打分、不筛选**——哪条更可比由估价师判断。
        """
        try:
            cat = Category(category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"未知类别：{category}") from exc
        store = InstanceStore(_store_path())
        store.load()
        return {
            "instances": [
                {
                    "编号": i.编号,
                    "类别": i.类别.value,
                    "位置": i.位置,
                    "成交价": i.成交价,
                    "面积": i.面积,
                    "出租用途": i.出租用途,
                    "交易情况": i.交易情况,
                    "租期原文": i.租期原文,
                    "起始日": i.起始日.isoformat() if i.起始日 else None,
                    "日期精度": i.日期精度.value,
                    "备注": i.备注,
                }
                for i in store.list_by_category(cat)
            ]
        }

    @app.post("/api/import")
    async def import_instances(file: UploadFile) -> dict[str, object]:
        """从 xlsx 抽取比较实例，供确认后经 /api/library 入库。**不落库**。"""
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="只接受 .xlsx 文件")
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(await file.read())
            path = Path(tmp.name)
        try:
            instances = import_from_excel(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            path.unlink(missing_ok=True)
        return {"imported": [InstanceStore.to_dict(i) for i in instances]}

    @app.post("/api/library")
    def add_to_library(payload: dict[str, Any]) -> dict[str, object]:
        """把确认过的实例入库。形状与 /api/import 的 `imported` 一致。

        重复编号不覆盖——已在库中的原样保留，判重结果在 `skipped` 中如实报告。
        """
        raw = payload.get("instances")
        if not isinstance(raw, list):
            raise HTTPException(status_code=400, detail="instances 字段缺失或格式错误")
        store = InstanceStore(_store_path())
        store.load()
        added = 0
        skipped: list[str] = []
        for item in raw:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail=f"实例数据格式错误：{item!r}")
            try:
                inst = InstanceStore.from_dict(item)
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"实例数据解析失败：{exc}") from exc
            if store.add(inst):
                added += 1
            else:
                skipped.append(inst.编号)
        store.save()
        return {"added": added, "skipped": skipped}

    @app.post("/api/compute")
    def compute(payload: dict[str, Any]) -> dict[str, object]:
        """选中的库内实例接入市场比较法引擎重算。

        **不收文件。** 引擎要的三样——类别、基础表知识、估价对象档次——分别
        来自请求、基础表库、表单的 28 个下拉框（见 `src.engine.inputs`）。
        Excel 导入只是一次性预填表单，之后全程没有 xlsx。

        不做推荐；市场状况指数须逐条现填，系统不推算、不给默认值——
        缺失时 400，不得静默取默认值继续算。
        """
        raw_selected = payload.get("selected")
        if not isinstance(raw_selected, list):
            raise HTTPException(status_code=400, detail="selected 字段缺失或不是数组")
        raw_levels = payload.get("subject_levels")
        if not isinstance(raw_levels, dict):
            raise HTTPException(status_code=400, detail="subject_levels 字段缺失或格式错误")
        try:
            category = Category(str(payload.get("category", "")))
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"未知类别：{payload.get('category')!r}"
            ) from exc

        raw_fingerprint = payload.get("base_table")
        try:
            knowledge = BaseTableStore(_base_table_dir()).load(
                category, str(raw_fingerprint) if raw_fingerprint else None
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            store = InstanceStore(_store_path())
            store.load()
            result = compute_from_selection(
                ComparisonInput(
                    category=category,
                    knowledge=knowledge,
                    subject_levels={str(k): str(v) for k, v in raw_levels.items()},
                ),
                raw_selected,
                store,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "比准价格": list(result.比准价格),
            "评估结果": result.评估结果,
            "离散度": result.离散度,
            # 单位随数字一起走：农用 1399.26 与办公 2.83 差 500 倍，
            # 让界面自己去配单位，早晚配错一次。
            "单价单位": price_unit(category),
            # 重算出的离散度同样要过校验——它会跟着结果进报告，而 /api/extract
            # 那次校验查的是 Excel 里的旧值。**只提示，不阻断**：换不换实例是
            # 估价师的判断。
            "提示": [asdict(w) for w in check_dispersion(result.离散度)],
        }

    @app.post("/api/annual-values")
    def annual_values(payload: dict[str, Any]) -> dict[str, object]:
        """按单价与面积重算各估价对象的年租赁价值。

        界面上估价师改了一览表的单价，年租赁价值须跟着变。公式（农用 面积×单价、
        房屋类 ROUND(面积×单价×365,0)）**只在 Python 里实现一次**，界面不自己算——
        照抄一份到 JS 里，两份迟早算出两个数。
        """
        try:
            category = Category(str(payload.get("category", "")))
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"未知类别：{payload.get('category')!r}"
            ) from exc
        raw = payload.get("subjects")
        if not isinstance(raw, list):
            raise HTTPException(status_code=400, detail="subjects 字段缺失或格式错误")
        try:
            values = [
                annual_value(category, _to_float(item["area"]), _to_float(item["unit_price"]))
                for item in raw
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"面积或单价不是有效数字：{exc}") from exc
        return {"annual_values": values}

    @app.get("/api/drafts")
    def list_drafts() -> dict[str, object]:
        """列出草稿摘要，更新时间新→旧。不含表单数据本身。"""
        infos = DraftStore(_draft_dir()).list_all()
        return {
            "drafts": [
                {
                    "id": i.id,
                    "报告编号": i.报告编号,
                    "类别": i.类别,
                    "更新时间": i.更新时间.isoformat(),
                }
                for i in infos
            ]
        }

    @app.post("/api/drafts")
    def save_draft(payload: dict[str, Any]) -> dict[str, object]:
        """存草稿。带 id 即续存（覆盖），不带即新建。

        单个估价对象最少 52 项，实地勘察回来填、中途被打断是常态——填一半
        关了浏览器不该全丢。`数据` 原样存，后端不校验其形状。
        """
        raw = payload.get("数据")
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="数据字段缺失或格式错误")
        draft_id = payload.get("id")
        if draft_id is not None and not isinstance(draft_id, str):
            raise HTTPException(status_code=400, detail="id 须为字符串")
        try:
            saved = DraftStore(_draft_dir()).save(Draft.new(raw, draft_id=draft_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": saved}

    @app.get("/api/drafts/{draft_id}")
    def get_draft(draft_id: str) -> dict[str, object]:
        """取一份完整草稿，供续填。"""
        try:
            draft = DraftStore(_draft_dir()).get(draft_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if draft is None:
            raise HTTPException(status_code=404, detail=f"草稿不存在：{draft_id}")
        return DraftStore.to_dict(draft)

    @app.delete("/api/drafts/{draft_id}")
    def delete_draft(draft_id: str) -> dict[str, object]:
        """删一份草稿。"""
        try:
            removed = DraftStore(_draft_dir()).remove(draft_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not removed:
            raise HTTPException(status_code=404, detail=f"草稿不存在：{draft_id}")
        return {"deleted": draft_id}

    @app.post("/api/extract")
    async def extract(file: UploadFile) -> dict[str, object]:
        """导入一份实勘表 Excel，**一次性预填表单**。

        表单是主，Excel 导入是可选便利（决策记录 §1）。故本接口一次交出表单
        需要的全部东西：19 项基本字段、一览表、28 个估价对象档次。之后重算与
        出报告都走表单，不再需要这个文件。

        顺带把这份 Excel 的基础表收进版本库——它是估价知识的来源，进了库表单
        路径才有下拉框可选。指纹已在库中即为空操作，不新增版本。
        """
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="只接受 .xlsx 文件")
        # 落成上传时的原名，不用 NamedTemporaryFile 那串乱码——基础表台账要记
        # 「这版是从哪个文件导进来的」，记一串 tmpXXXX 等于没记。
        workdir = Path(tempfile.mkdtemp(prefix="导入_"))
        path = workdir / (file.filename or "实勘表.xlsx")
        path.write_bytes(await file.read())
        try:
            project = load_project(path)
            warnings = validate(project, path)
            source = from_excel(path)
            imported = BaseTableStore(_base_table_dir()).import_from_excel(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        payload = asdict(project)
        payload["category"] = project.category.value
        payload["subjects"] = [asdict(s) for s in project.subjects]
        return {
            "project": payload,
            "warnings": [asdict(w) for w in warnings],
            # 28 个估价对象档次：Excel 路径从比较法表 D 列读出来预填进表单，
            # 之后 /api/compute 用的就是表单里的这份，不再回头读 Excel。
            "subject_levels": source.subject_levels,
            "base_table": _version_payload(imported.版本),
            # 界面据此给一览表的表头标单位，不在 JS 里另写一份农用/房屋的判断。
            "单价单位": price_unit(project.category),
            "面积单位": area_unit(project.category),
        }

    @app.get("/api/factors")
    def factors(category: str, fingerprint: str | None = None) -> dict[str, object]:
        """某类别的比较因素与各档次选项，供表单的下拉框用。

        选项全部来自基础表——估价师维护基础表即维护选项（ADR-001 的边界：
        知识在 Excel，算术在 Python）。系统不编造档次。
        """
        try:
            cat = Category(category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"未知类别：{category}") from exc
        store = BaseTableStore(_base_table_dir())
        try:
            knowledge = store.load(cat, fingerprint)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        info = store.current(cat)
        return {
            "factors": [
                {
                    "名称": f.name,
                    "系数": f.coefficient,
                    # 档次按分值从高到低给：基础表里 D..H 就是 2/1/0/-1/-2 的排法，
                    # 下拉框顺序跟着它，估价师看到的次序与 Excel 里一致。
                    "档次": [
                        {"描述": desc, "分值": score}
                        for desc, score in sorted(
                            f.levels.items(), key=lambda kv: kv[1], reverse=True
                        )
                    ],
                }
                for f in knowledge.factors
            ],
            "base_table": _version_payload(info) if info else None,
        }

    @app.get("/api/base-tables")
    def list_base_tables(category: str) -> dict[str, object]:
        """某类别的全部基础表版本，导入时间新→旧。旧版永不覆盖，故都在。"""
        try:
            cat = Category(category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"未知类别：{category}") from exc
        store = BaseTableStore(_base_table_dir())
        current = store.current(cat)
        return {
            "versions": [_version_payload(v) for v in store.list_versions(cat)],
            "current": _version_payload(current) if current else None,
        }

    @app.post("/api/base-tables")
    async def import_base_table(file: UploadFile) -> dict[str, object]:
        """导入基础表（方案乙：Excel 是权威，系统存副本，改了重导一次）。

        指纹相同即空操作——「估价师没改基础表就又导了一次」是常态，不是错误。
        """
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="只接受 .xlsx 文件")
        workdir = Path(tempfile.mkdtemp(prefix="基础表_"))
        path = workdir / (file.filename or "基础表.xlsx")
        path.write_bytes(await file.read())
        try:
            imported = BaseTableStore(_base_table_dir()).import_from_excel(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        return {"base_table": _version_payload(imported.版本), "是否新版": imported.是否新版}

    @app.post("/api/render")
    async def render_report(
        project: str = Form(...),
        files: list[UploadFile] | None = File(default=None),
    ) -> FileResponse:
        try:
            parsed = _project_from_payload(json.loads(project))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"项目数据解析失败：{exc}") from exc

        workdir = Path(tempfile.mkdtemp(prefix="guijia_"))
        attachment_paths: list[Path] = []
        for index, upload in enumerate(files or []):
            dest = workdir / (upload.filename or f"attachment_{index}")
            dest.write_bytes(await upload.read())
            attachment_paths.append(dest)

        try:
            pages: tuple[AttachmentPage, ...] = collect(attachment_paths, workdir / "_pages")
            output = workdir / f"{_safe_filename(parsed.report_no)}.docx"
            render(parsed, pages, output, templates_dir=_templates_dir())
        except (ValueError, FileNotFoundError) as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        logger.info("生成报告：%s", output.name)
        return FileResponse(
            output,
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            filename=output.name,
            background=BackgroundTask(shutil.rmtree, workdir, ignore_errors=True),
        )

    return app
