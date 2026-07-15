"""本地网页应用。

单机单用户，无状态，不联网。数据全程留在本机。

四步向导：① 选 Excel → ② 复核数据（可编辑）→ ③ 挑附件、排序 → ④ 生成下载。
复核界面的修改只影响本次生成，不回写 Excel——Excel 是一张公式网，
回写单个值会打断公式链、把计算结果变成死数（见 docs/使用说明.md）。
"""

import json
import logging
import shutil
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask

from src.attachments.collector import AttachmentPage, collect
from src.extractor.project import load_project
from src.model import Category, Project, Subject
from src.renderer.render import render
from src.validator.checks import validate

logger = logging.getLogger(__name__)

__all__ = ["create_app"]

_STATIC = Path(__file__).with_name("static")

# 未打包成生成 docx 文件名的非法字符（Windows 文件系统禁用字符）。
_UNSAFE_FILENAME_CHARS = frozenset('/\\:*?"<>|')


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

    @app.post("/api/extract")
    async def extract(file: UploadFile) -> dict[str, object]:
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="只接受 .xlsx 文件")
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(await file.read())
            path = Path(tmp.name)
        try:
            project = load_project(path)
            warnings = validate(project, path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            path.unlink(missing_ok=True)

        payload = asdict(project)
        payload["category"] = project.category.value
        payload["subjects"] = [asdict(s) for s in project.subjects]
        return {"project": payload, "warnings": [asdict(w) for w in warnings]}

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
