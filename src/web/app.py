"""本地网页应用。

单机单用户，不联网。数据全程留在本机。

三个页签：出报告（七步向导）、实例库、基础表。

**表单是主，Excel 导入只是把表单一次填好。** 出一份报告可以全程不开 Excel：
引擎要的三样——类别、基础表知识、估价对象档次——分别来自请求、基础表版本库、
表单的 28 个下拉框（见 src/engine/inputs.py）。

表单里的修改只影响本次生成，不回写 Excel——Excel 是一张公式网，回写单个值会
打断公式链、把计算结果变成死数（见 docs/使用说明.md）。
"""

import json
import logging
import os
import secrets
import shutil
import tempfile
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.background import BackgroundTask

from src.dingtalk import config
from src.dingtalk.report_number import draw_report_number
from src.attachments.collector import AttachmentPage, collect
from src.drafts.model import Draft
from src.drafts.store import DEFAULT_DRAFT_DIR, DraftStore
from src.engine.annual import annual_value
from src.engine.compute import (
    METHOD_NAME,
    SELECTION_SIZE,
    compute_from_selection,
    default_weights,
)
from src.engine.inputs import ComparisonInput, from_excel
from src.engine.knowledge import Knowledge, apply_coefficient_overrides
from src.engine.methods import get_method
from src.engine.methods.base import Instance, Result
from src.extractor.condition import GROUP_PREFIXES, read_survey_conditions
from src.extractor.project import load_project
from src.questionnaire.backend import SurveyPullBackend, response_content
from src.questionnaire.prefill import survey_to_prefill
from src.web import session
from src.knowledge_base.store import (
    DEFAULT_STORE_DIR as DEFAULT_BASE_TABLE_DIR,
)
from src.knowledge_base.store import (
    BaseTableStore,
    VersionInfo,
)
from src.knowledge_base.active import ActiveVersions, active_fingerprint
from src.knowledge_base.backend import LocalFileBaseTableBackend
from src.knowledge_base.sync import pull as pull_base_tables
from src.knowledge_base.sync import push_version as push_base_table
from src.version import __version__
from src.web.heartbeat import Heartbeat
from src.dingtalk.factory import notable_base_table_backend
from src.ledger.model import BaseTableUse, Deviation, InstanceUse, LedgerEntry, MethodUse
from src.ledger.model import to_dict as ledger_to_dict
from src.ledger.replay import replay
from src.ledger.store import DEFAULT_LEDGER_DIR, LedgerStore
from src.library.importer import import_from_excel
from src.library.model import StoredInstance, make_id, parse_lease_start
from src.library.store import DEFAULT_STORE_PATH, InstanceStore
from src.model import Category, ConditionFactor, ConditionGroup, Project, Subject
from src.prose.composer import area_unit, price_unit
from src.renderer.agreement import render_agreement
from src.renderer.render import render
from src.validator.checks import check_coefficient_overrides, check_dispersion, validate

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


def _ledger_dir() -> Path:
    """台账目录。测试通过环境变量覆盖。"""
    return Path(os.environ.get("台账目录", str(DEFAULT_LEDGER_DIR)))


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


def _base_table_fingerprint(store: BaseTableStore, cat: Category, explicit: object) -> str | None:
    """出报告/取因素用哪一版基础表：请求显式给了 `base_table` 指纹用之；否则用该类别
    本地**生效版本**（D2，缺省回落最新导入版）。返回 None 表示该类别尚无任何版本。"""
    if explicit:
        return str(explicit)
    return active_fingerprint(store, ActiveVersions(_base_table_dir()), cat)


def _push_base_table_if_online(store: BaseTableStore, cat: Category, fingerprint: str) -> None:
    """导入后把该版推一份进多维表（D4）；多维表未配/离线则静默跳过，绝不拖累本地导入。"""
    remote = notable_base_table_backend()
    if remote is None:
        return
    try:
        push_base_table(remote, LocalFileBaseTableBackend(_base_table_dir()), cat, fingerprint)
    except Exception:  # noqa: BLE001  推送失败（离线/多维表抖动）不该让本地导入失败
        logger.exception("基础表 %s/%s 推送多维表失败（本地导入已成功）", cat.value, fingerprint)


def _to_float(value: object) -> float:
    """把 JSON 数值字段转成 float；缺失或 None 时按 0 处理。"""
    if value is None:
        return 0.0
    if isinstance(value, int | float | str):
        return float(value)
    raise ValueError(f"数值字段类型不对：{value!r}")


_WEIGHT_SUM_TOLERANCE = 1e-6


def _parse_weights(raw: object) -> tuple[float, ...] | None:
    """解析请求里的权重列表；字段缺失（`None`）返回 `None`，交调用方取默认权重。

    可调权重上线后的唯一入口：**和必须为 1**，数量须与选中实例数一致
    （今天恒为 `SELECTION_SIZE`）。不合法一律 400，不静默夹紧或归一化——
    权重是估价师的专业判断，系统不替他改。

    Raises:
        HTTPException: 数量不对、某项不是数字，或总和偏离 1 超过容差。
    """
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) != SELECTION_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"权重须为 {SELECTION_SIZE} 个数字，实收：{raw!r}",
        )
    try:
        weights = tuple(float(w) for w in raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"权重不是有效数字：{raw!r}") from exc
    total = sum(weights)
    if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
        raise HTTPException(status_code=400, detail=f"权重之和必须为 1，实收：{total}")
    return weights


def _parse_coefficient_overrides(raw: object) -> dict[str, float]:
    """解析请求里的逐因素系数覆盖；字段缺失（`None`）返回空字典，不覆盖任何因素。

    单份偏离是「自由覆盖」——不设审批门槛，改哪个因素、改成多少全由估价师
    决定，本函数只管接住、转成合法类型，不做范围校验（范围提示见
    `check_coefficient_overrides`，只提示不阻断）。未知因素名同样不在这里挡：
    留给 `apply_coefficient_overrides` 去报错，理由见该函数 docstring——
    键入错误理应在真正应用覆盖时被截住。

    Raises:
        HTTPException: raw 不是字典，或某项系数不是有效数字。
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=400,
            detail=f"coefficient_overrides 须为 {{因素名: 系数}} 字典：{raw!r}",
        )
    try:
        return {str(k): float(v) for k, v in raw.items()}
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"coefficient_overrides 系数不是有效数字：{raw!r}"
        ) from exc


def _asset_condition_groups_from_form(
    knowledge: Knowledge, descriptions: dict[str, str]
) -> tuple[ConditionGroup, ...]:
    """按基础表因素的分组 + 表单逐因素描述，组装资产状况三组。

    组顺序区位→实物→权益（`GROUP_PREFIXES`），组内按基础表因素序（而非表单
    `descriptions` 的字典序——那是用户填写顺序，不代表基础表行序）。因素没有
    分组（`f.group == ""`，如实勘表未覆盖到的因素）不进任何组，避免臆造归属。
    因素在但描述缺失时给空串而不是丢弃该因素——校验层要靠「因素在、描述空」
    才能提示「未填写」。

    Args:
        knowledge: 该类别当前使用的基础表知识（含每因素 `group`）。
        descriptions: 表单提交的 `{因素名: 描述}`。

    Returns:
        按组聚合的 ConditionGroup 元组，空组丢弃。
    """
    ordered: dict[str, list[ConditionFactor]] = {g: [] for g in GROUP_PREFIXES}
    for f in knowledge.factors:
        if f.group not in ordered:
            continue
        ordered[f.group].append(ConditionFactor(f.name, descriptions.get(f.name, "")))
    return tuple(
        ConditionGroup(name=g, factors=tuple(fs)) for g, fs in ordered.items() if fs
    )


def _project_from_payload(data: dict[str, object]) -> Project:
    """把 /api/render 收到的（可能经用户编辑的）JSON 还原为 Project。

    Args:
        data: 前端提交的项目字段字典，形状与 /api/extract 返回的 project 一致，
            另可带 `asset_conditions`（`{因素名: 描述}`，来自表单或实勘表预填）。

    Returns:
        还原后的 Project。`asset_conditions` 非空时，据当前类别的基础表知识
        （分组、因素序）组装 `asset_condition_groups`；未带该字段则保持默认空，
        不强求已导入基础表——描述是报告增量，不该拖累既有的无描述渲染路径。

    Raises:
        ValueError: 字段缺失、类型不对，category 不是合法枚举值，或带了
            `asset_conditions` 却尚未导入过该类别的基础表。
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
    category = Category(str(data.get("category", "")))
    raw_conditions = data.get("asset_conditions")
    descriptions = (
        {str(k): str(v) for k, v in raw_conditions.items()}
        if isinstance(raw_conditions, dict)
        else {}
    )
    asset_condition_groups: tuple[ConditionGroup, ...] = ()
    if descriptions:
        try:
            _bt_store = BaseTableStore(_base_table_dir())
            knowledge = _bt_store.load(
                category, _base_table_fingerprint(_bt_store, category, None)
            )
        except FileNotFoundError as exc:
            raise ValueError(
                f"带资产状况描述渲染但尚未导入过 {category.value} 类基础表：{exc}"
            ) from exc
        asset_condition_groups = _asset_condition_groups_from_form(knowledge, descriptions)
    return Project(
        category=category,
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
        asset_condition_groups=asset_condition_groups,
    )


def _safe_filename(name: str) -> str:
    """把报告编号整理成合法文件名，为空时兜底。"""
    cleaned = "".join(c for c in name if c not in _UNSAFE_FILENAME_CHARS).strip()
    return cleaned or "估价报告"


def _asset_conditions_to_ledger(
    groups: tuple[ConditionGroup, ...],
) -> tuple[dict[str, object], ...]:
    """把 `Project.asset_condition_groups` 序列化成台账「资产状况」字段的形状。

    独立可选字段，跟「经引擎重算」无关（不参与六者同生同灭）——导入 Excel 直接
    生成的报告一样可能带手写描述。空分组序列化为空元组而非 None：这里已经
    过手组装过（哪怕结果为空），跟「压根没有这个字段」的旧台账不是一回事。
    """
    return tuple(
        {
            "组": g.name,
            "因素": [{"名称": f.name, "描述": f.description} for f in g.factors],
        }
        for g in groups
    )


def _validate_weights(weights: object, num_instances: int) -> None:
    """验证台账权重的有效性。

    权重必须是浮点数序列，长度与实例数一致，和为 1（容差 1e-6）。
    缺失或为空时使用默认权重，无须验证。

    Args:
        weights: 来自 raw["weights"] 的权重值
        num_instances: 实际实例数（uses 列表长度）

    Raises:
        ValueError: 权重数量不对、非数字，或总和偏离 1。
    """
    if weights is None:
        return
    if not isinstance(weights, list):
        raise ValueError(f"台账权重非法：须为数字列表，实收：{weights!r}")
    if len(weights) != num_instances:
        raise ValueError(f"台账权重非法：需 {num_instances} 个，实收 {len(weights)} 个")
    try:
        weight_floats = tuple(float(w) for w in weights)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"台账权重非法：包含非数字：{weights!r}") from exc
    total = sum(weight_floats)
    if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
        raise ValueError(f"台账权重非法：和需为 1，实收 {total}")


def _apply_ledger_coefficient_overrides(
    raw: dict[str, Any], knowledge: Knowledge
) -> tuple[Knowledge, tuple[Deviation, ...]]:
    """把台账 payload 里的逐因素系数覆盖应用到基础知识，产出「实际知识」+「偏离」。

    这是台账落盘侧的坑：单份偏离必须存成「基线版本 + 差异」（`Deviation` 的
    docstring），而不是悄悄换一个基础表版本——`基线版本`/`实际指纹` 不变，
    差异单独记进 `偏离`。`实际知识` 才是重放要用的那份（`replay.py` 读的正是
    `entry.基础表.实际知识`），必须是覆盖后的版本，否则重放会悄悄用回基础表
    原系数，算出另一个数，且看不出哪里错了。

    未知因素名不在本函数里挡：`apply_coefficient_overrides` 自己会报
    `ValueError`，且**必须让它原样炸出去**——写入路径宁可让这次生成的台账
    记不上（`/api/render` 外层广播 except 兜底：报告照常出、只是台账跳过），
    也不能把一条覆盖了根本不存在的因素的记录悄悄写进永久台账。

    Args:
        raw: `/api/render` 收到的台账 payload，可能带 `coefficient_overrides`
            （`{因素名: 新系数}`）、`偏离理由`（全局理由）、
            `coefficient_override_reasons`（`{因素名: 理由}`，逐因素理由，
            命中时优先于全局理由）。
        knowledge: 该类别当前使用的基础 Knowledge（覆盖前）。

    Returns:
        (实际知识, 偏离)：无覆盖时原样返回 `knowledge` 与空元组。

    Raises:
        ValueError: `coefficient_overrides` 里出现 `knowledge` 中不存在的因素名。
    """
    raw_overrides = raw.get("coefficient_overrides")
    if not isinstance(raw_overrides, dict) or not raw_overrides:
        return knowledge, ()

    overrides = {str(k): float(v) for k, v in raw_overrides.items()}
    base_by_name = {f.name: f for f in knowledge.factors}
    overridden = apply_coefficient_overrides(knowledge, overrides)  # 未知因素名在此报错

    global_reason = str(raw.get("偏离理由", ""))
    raw_reasons = raw.get("coefficient_override_reasons")
    per_factor_reasons = (
        {str(k): str(v) for k, v in raw_reasons.items()}
        if isinstance(raw_reasons, dict)
        else {}
    )
    偏离 = tuple(
        Deviation(
            因素=name,
            字段="每差1档修正系数",
            原值=str(base_by_name[name].coefficient),
            现值=str(value),
            审批单号="",  # 自由偏离：本版不设审批门槛，见类头注释
            理由=per_factor_reasons.get(name, global_reason),
        )
        for name, value in overrides.items()
    )
    return overridden, 偏离


def _build_ledger_entry(project: Project, raw: dict[str, Any] | None) -> LedgerEntry:
    """按一次生成攒出台账记录。

    `raw` 为 None（或缺关键字段）即视为**未经系统重算**——导入 Excel 直接生成的
    老路正是如此。此时基础表/档次/实例/方法/权重/结果全为 None，`经引擎重算` 为 False。
    这不是缺失，恰恰是复核最想知道的事：这份报告的数字不是引擎算的。

    `资产状况` 与上述六者无关，两条路径都照样序列化——描述只进报告、不进算术，
    没有引擎重算也可以有手写描述。
    """
    一览表 = tuple(
        {
            "index": s.index, "owner": s.owner, "address": s.address, "usage": s.usage,
            "area": s.area, "unit_price": s.unit_price, "annual_value": s.annual_value,
        }
        for s in project.subjects
    )
    资产状况 = _asset_conditions_to_ledger(project.asset_condition_groups)
    if not raw or not raw.get("result"):
        return LedgerEntry.new(
            报告编号=project.report_no, 类别=project.category,
            基础表=None, 估价对象档次=None, 实例=None, 方法=None, 权重=None, 结果=None,
            一览表=一览表,
            资产状况=资产状况,
        )

    category = Category(str(raw.get("category", project.category.value)))
    fingerprint_raw = raw.get("base_table")
    base_store = BaseTableStore(_base_table_dir())
    fp = _base_table_fingerprint(base_store, category, fingerprint_raw)
    knowledge = base_store.load(category, fp)
    baseline = fp or ""

    # 单份偏离：覆盖为空即原样返回 knowledge 与空元组，旧 payload（没有
    # coefficient_overrides 字段）行为不变，向后兼容。
    knowledge, 偏离 = _apply_ledger_coefficient_overrides(raw, knowledge)

    levels = {str(k): str(v) for k, v in dict(raw["subject_levels"]).items()}
    inst_store = InstanceStore(_store_path())
    inst_store.load()
    uses: list[InstanceUse] = []
    for item in raw["selected"]:
        stored = inst_store.get(str(item["编号"]))
        if stored is None:
            raise ValueError(f"编号不在库中，无法记入台账：{item['编号']}")
        uses.append(
            InstanceUse(
                实例=Instance(
                    位置=stored.位置,
                    成交价=stored.成交价,
                    交易情况指数=stored.交易情况指数,
                    市场状况指数=_to_float(item["市场状况指数"]),
                    因素档次=dict(stored.因素档次),
                ),
                编号=stored.编号,
                判断依据=str(item.get("备注", "")),
            )
        )

    result_raw = dict(raw["result"])
    # 验证并构建权重
    raw_weights = raw.get("weights")
    _validate_weights(raw_weights, len(uses))
    weights = (
        tuple(float(w) for w in raw_weights)
        if raw_weights is not None
        else default_weights()
    )
    return LedgerEntry.new(
        报告编号=project.report_no,
        类别=category,
        基础表=BaseTableUse(
            基线版本=baseline,
            偏离=偏离,
            # 有覆盖时 knowledge 已被 _apply_ledger_coefficient_overrides 换成
            # 覆盖后的那份——重放读的正是这里，不是基础表库里的原始版本。
            实际知识=knowledge,
            # 偏离是「基线版本 + 差异」，不是「另一个版本」：实际指纹仍等于
            # 基线版本，差异单独记在偏离里（Deviation 的 docstring）。
            实际指纹=baseline,
        ),
        估价对象档次=levels,
        实例=tuple(uses),
        方法=MethodUse(名称=METHOD_NAME, 版本=get_method(METHOD_NAME).version),
        # **台账要记「当时实际用的那组」，不是「今天的默认」**——否则哪天权重
        # 开放可调，用户填了非默认权重算出报告，台账却记着 ⅓⅓⅓，重放会用错
        # 权重、悄悄算出另一个数，还看不出错在哪。`raw.get("weights")` 缺失
        # （老 payload，前端还没送这个字段）或为空，才退回默认——向后兼容。
        权重=weights,
        结果=Result(
            比准价格=tuple(float(p) for p in result_raw["比准价格"]),
            评估结果=float(result_raw["评估结果"]),
            离散度=float(result_raw["离散度"]),
        ),
        一览表=一览表,
        资产状况=资产状况,
    )


def _survey_backend() -> SurveyPullBackend:
    """按 env 造「实勘问卷」表读取后端；未接入多维表或配置不全则抛 409。

    问卷源只存在于多维表——本地模式没有问卷可拉，故显式挡回而非静默返回空。
    """
    if not config.use_notable():
        raise HTTPException(
            status_code=409, detail="实勘问卷拉取需 承载后端=多维表（本地模式无问卷源）"
        )
    client = config.build_client()
    sheet = config.survey_sheet()
    if client is None or not sheet:
        raise HTTPException(
            status_code=409, detail="多维表凭据或 NOTABLE_SURVEY_SHEET 未配全，检查 .env"
        )
    return SurveyPullBackend(client, sheet)


def create_app() -> FastAPI:
    """构建 FastAPI 应用。"""
    app = FastAPI(title="房地产估价报告生成系统", docs_url=None, redoc_url=None)
    heartbeat = Heartbeat()          # 浏览器心跳：关网页 → __main__ 看门狗自动停服
    app.state.heartbeat = heartbeat

    # 硬门禁（仅钉钉模式）：未登录/未授权者只能访问「首页壳 + 登录 + 状态查询」，其余数据接口 403。
    # 前端会据 /api/me 显示门禁遮罩；本中间件是服务端兜底，防绕过前端直连接口。本地单机模式不启用。
    _gate_exempt = frozenset({
        "/", "/api/me", "/api/online", "/api/ping", "/api/heartbeat",
        "/auth/login", "/auth/callback", "/auth/logout", "/favicon.ico",
    })

    @app.middleware("http")
    async def _authorization_gate(request: Request, call_next):  # type: ignore[no-untyped-def]
        if (
            config.use_notable()
            and request.url.path not in _gate_exempt
            and not session.is_authorized()
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "请先扫码登录，且需被授权方可使用本软件"},
            )
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((_STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/heartbeat")
    def heartbeat_beat() -> dict[str, bool]:
        """前端页面每几秒打一次；关掉网页后心跳停，__main__ 看门狗宽限后自动停服。

        免登豁免（在 `_gate_exempt` 里），钉钉模式登录页也要能续命，否则登录中被误停。
        """
        heartbeat.beat()
        return {"ok": True}

    @app.get("/api/ping")
    def ping() -> dict[str, str]:
        """单实例守卫探活：回本程序身份 + 版本，让再次双击的 exe 认出「我已在跑」而复用。

        免登豁免（在 `_gate_exempt` 里），钉钉模式也可达——否则守卫探不到 gated 的在跑实例。
        """
        return {"app": "appraisal-report-system", "version": __version__}

    @app.get("/api/online")
    def online_status() -> dict[str, object]:
        """探当前是否联多维表。前端点「出报告」前先问它决定走哪支（§5）。

        local 模式（承载后端≠多维表）：恒离线、恒走本地渲染，不进待同步流程。
        notable 模式：短超时探一次，成功＝在线可领号，失败/缺凭据＝离线转待同步。
        """
        if not config.use_notable():
            return {"online": False, "mode": "local"}
        client = config.build_client(timeout=5.0)
        online = client is not None and client.online()
        return {"online": online, "mode": "notable"}

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
                    "因素档次": dict(i.因素档次),
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

    @app.post("/api/instances")
    def create_instance(payload: dict[str, Any]) -> dict[str, object]:
        """手工录入一条比较实例。

        表单落地后新实例也得能不开 Excel 就录进来，否则「输入不是 Excel」只
        兑现了一半：出报告不用 Excel 了，录实例还得开 Excel。

        **编号、起始日、日期精度由服务端派生**，不让界面自己算：`parse_lease_start`
        认得出「2025.7-2026.7」是仅年月、「2025-2026」是仅年，这段正则有真逻辑
        （见 `src/library/model.py` 的注释），抄一份进 JS 迟早两边解出两个日期。
        日期不精确的照实打标记，不强制补全，不假造月份。
        """
        try:
            category = Category(str(payload.get("类别", "")))
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"未知类别：{payload.get('类别')!r}"
            ) from exc
        location = str(payload.get("位置", "")).strip()
        if not location:
            raise HTTPException(status_code=400, detail="位置不能为空——编号要用它")

        raw_lease = str(payload.get("租期原文", ""))
        start, precision = parse_lease_start(raw_lease)
        levels = payload.get("因素档次")
        try:
            instance = StoredInstance(
                编号=make_id(category, start, precision, location),
                类别=category,
                位置=location,
                成交价=_to_float(payload.get("成交价")),
                面积=_to_float(payload.get("面积")),
                出租用途=str(payload.get("出租用途", "")),
                交易情况=str(payload.get("交易情况", "")),
                交易情况指数=_to_float(payload.get("交易情况指数")),
                租期原文=raw_lease,
                起始日=start,
                日期精度=precision,
                因素档次={str(k): str(v) for k, v in (levels or {}).items()}
                if isinstance(levels, dict)
                else {},
                备注=str(payload.get("备注", "")),
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"实例数据不合法：{exc}") from exc

        store = InstanceStore(_store_path())
        store.load()
        added = store.add(instance)
        store.save()
        return {
            "instance": InstanceStore.to_dict(instance),
            # 重复编号不覆盖——与 /api/library 一致。同位置同起始月的两条实例
            # 会撞编号，那多半是重复录入，如实报告而不是静默顶掉已有的。
            "added": added,
        }

    @app.post("/api/compute")
    def compute(payload: dict[str, Any]) -> dict[str, object]:
        """选中的库内实例接入市场比较法引擎重算。

        **不收文件。** 引擎要的三样——类别、基础表知识、估价对象档次——分别
        来自请求、基础表库、表单的 28 个下拉框（见 `src.engine.inputs`）。
        Excel 导入只是一次性预填表单，之后全程没有 xlsx。

        不做推荐；市场状况指数须逐条现填，系统不推算、不给默认值——
        缺失时 400，不得静默取默认值继续算。

        `coefficient_overrides`（`{因素名: 新系数}`）是单份报告的自由覆盖：
        不设审批门槛，缺省不传即维持基础表原系数不变。覆盖后若某因素落在
        基础表调整范围外，只在 `提示` 里软警告，不阻断——是否合理由估价师
        判断。未知因素名仍是硬错误（400），键入错误不该被悄悄吞掉。
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
        _bt = BaseTableStore(_base_table_dir())
        try:
            knowledge = _bt.load(
                category, _base_table_fingerprint(_bt, category, raw_fingerprint)
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        weights = _parse_weights(payload.get("weights"))
        coefficient_overrides = _parse_coefficient_overrides(
            payload.get("coefficient_overrides")
        )

        try:
            store = InstanceStore(_store_path())
            store.load()
            # 覆盖为空即维持原样——不新建一份等价的 Knowledge，省一次分配，
            # 也让「没传 coefficient_overrides」与旧行为字节级一致。
            computed_knowledge = (
                apply_coefficient_overrides(knowledge, coefficient_overrides)
                if coefficient_overrides
                else knowledge
            )
            result = compute_from_selection(
                ComparisonInput(
                    category=category,
                    knowledge=computed_knowledge,
                    subject_levels={str(k): str(v) for k, v in raw_levels.items()},
                ),
                raw_selected,
                store,
                weights=weights,
            )
        except ValueError as exc:
            # 未知因素名（apply_coefficient_overrides 报的）与选实例/档次相关的
            # 错误走同一条 400 路径——都是「请求给的东西系统接不住」。
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # 重算出的离散度同样要过校验——它会跟着结果进报告，而 /api/extract
        # 那次校验查的是 Excel 里的旧值。**只提示，不阻断**：换不换实例是
        # 估价师的判断。系数越界提示同理，且只在真有覆盖时才查——用基础表
        # 原始 knowledge 查范围（调整范围字段覆盖前后一致，用哪份都一样）。
        提示 = list(check_dispersion(result.离散度))
        if coefficient_overrides:
            提示 += check_coefficient_overrides(knowledge, coefficient_overrides)

        return {
            "比准价格": list(result.比准价格),
            "评估结果": result.评估结果,
            "离散度": result.离散度,
            # 单位随数字一起走：农用 1399.26 与办公 2.83 差 500 倍，
            # 让界面自己去配单位，早晚配错一次。
            "单价单位": price_unit(category),
            "提示": [asdict(w) for w in 提示],
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

    @app.post("/api/validate")
    def validate_project(payload: dict[str, Any]) -> dict[str, object]:
        """校验表单里的项目数据。**只提示，不阻断。**

        表单路径没有源 Excel，故不查外部引用；其余各项与数据从哪来无关，照查。
        19 项基本字段全部人工填、系统不拼凑（用户明确要求），但手填会手滑——
        **不替他填，但替他核**。
        """
        raw = payload.get("project")
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="project 字段缺失或格式错误")
        try:
            project = _project_from_payload(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"项目数据解析失败：{exc}") from exc
        return {"warnings": [asdict(w) for w in validate(project)]}

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
                    "待同步": i.待同步,
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
        待同步 = bool(payload.get("待同步", False))
        # 拉取问卷预填时前端带上来源问卷ID，给这份草稿打标供再拉判重；手建草稿留空。
        问卷ID = str(payload.get("问卷ID", "") or "")
        try:
            saved = DraftStore(_draft_dir()).save(
                Draft.new(raw, draft_id=draft_id, 待同步=待同步, 问卷ID=问卷ID)
            )
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
            # 实勘表逐因素手写描述，读一次收进预填 payload——文件在 finally 里
            # 就会被删，须在此处（workdir 还在）取完。
            conditions = read_survey_conditions(path)
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
            # 资产状况逐因素描述（{因素名: 描述}），供表单预填每因素描述框。
            # 与 subject_levels 同级——不进 Project 数据类，表单收口后随
            # project.asset_conditions 一并提交，由 _project_from_payload 组装。
            "asset_conditions": {c.factor: c.description for c in conditions},
            # 界面据此给一览表的表头标单位，不在 JS 里另写一份农用/房屋的判断。
            "单价单位": price_unit(project.category),
            "面积单位": area_unit(project.category),
        }

    @app.get("/api/me")
    def whoami() -> dict[str, object]:
        """当前办公端操作人：会话优先、否则 .env 过渡值（供前端显示登录态、做「只看自己」）。"""
        return {
            "operator": session.current_operator(),
            "operator_name": session.operator_name(),
            "logged_in": session.is_logged_in(),
            "is_admin": session.is_admin(),
            # 硬门禁：gated=是否启用（钉钉模式才启用）；authorized=当前用户是否被许可使用本软件。
            "gated": config.use_notable(),
            "authorized": session.is_authorized(),
        }

    # ── 钉钉扫码登录（纯本机 OAuth2；见 spec 2026-08-13-办公端钉钉扫码登录）──
    @app.get("/auth/login")
    def auth_login() -> RedirectResponse:
        """跳钉钉扫码授权页。生成一次性 state 存会话防 CSRF。"""
        oauth = config.build_oauth()
        if oauth is None:
            raise HTTPException(status_code=409, detail="未配应用凭据（YIDA_APP_KEY/SECRET），无法登录")
        state = secrets.token_urlsafe(16)
        session.begin_login(state)
        return RedirectResponse(oauth.build_auth_url(config.login_redirect_uri(), state))

    @app.get("/auth/callback")
    def auth_callback(authCode: str = "", code: str = "", state: str = "") -> RedirectResponse:  # noqa: N803  钉钉回调参数名 authCode
        """钉钉回调：校 state → 换 token → 取 unionId → 换 userid → 记会话。

        userid 与问卷「填报人」同源（免登 userid），故必须走 unionId→userid 那步。
        """
        if not session.consume_login_state(state):
            raise HTTPException(status_code=400, detail="登录态校验失败（state 不符），请重新登录")
        auth_code = authCode or code
        if not auth_code:
            raise HTTPException(status_code=400, detail="回调缺 authCode")
        oauth = config.build_oauth()
        client = config.build_client()
        if oauth is None or client is None:
            raise HTTPException(status_code=409, detail="未配应用凭据，无法登录")
        try:
            user_token = oauth.exchange(auth_code)
            info = oauth.me(user_token)
            userid = oauth.userid_by_union(client.access_token(), info["unionid"])
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=f"登录失败：{exc}") from exc
        session.set_operator(userid, info.get("name", ""))
        return RedirectResponse("/")

    @app.get("/auth/logout")
    def auth_logout() -> RedirectResponse:
        """登出：清会话（之后回退 .env 过渡身份）。"""
        session.clear_operator()
        return RedirectResponse("/")

    @app.get("/api/survey/list")
    def survey_list() -> dict[str, object]:
        """列出「实勘问卷」表里的「已提交」问卷（办公端出报告用）。

        可见范围＝`session.viewer()`：普通估价师只看自己、管理员看全部。
        """
        backend = _survey_backend()
        return {"surveys": [asdict(i) for i in backend.list_submitted(session.viewer())]}

    @app.get("/api/survey/review/list")
    def survey_review_list() -> dict[str, object]:
        """列出「待审核」问卷（办公端审核列表用）。普通只看自己、管理员看全部。"""
        backend = _survey_backend()
        return {"surveys": [asdict(i) for i in backend.list_pending(session.viewer())]}

    @app.get("/api/survey/pull")
    def survey_pull(id: str) -> dict[str, object]:
        """拉取一份**本人**的「已提交」问卷，返回与 /api/extract 同形状的预填 payload。

        估价师据此免二次录入；比较法输出留空，仍由其选实例后重算（铁律 #7）。
        非本人问卷按「不存在」处理（404，不泄露他人问卷是否存在）。

        判重：若已为这份问卷建过草稿，payload 带上 `existing_draft_id`（那份草稿 id），
        前端据此续填那份、不再新建，免得「拉 N 次 = N 份失联草稿」。本端点仍只**读**，
        不建草稿；建草稿照旧走 `POST /api/drafts`（带 `问卷ID` 打标）。
        """
        backend = _survey_backend()
        try:
            response = backend.load(id, session.viewer())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = survey_to_prefill(response)
        existing = DraftStore(_draft_dir()).find_by_survey(response.问卷ID)
        payload["existing_draft_id"] = existing.id if existing else None
        # 底版快照 + 底版时间：办公端草稿存下，回写时作 3-way 合并的 base（双向同步 §4）。
        payload["survey_base"] = response_content(response)
        payload["survey_base_mtime"] = response.更新时间
        return payload

    @app.post("/api/survey/review")
    def survey_review(payload: dict[str, Any]) -> dict[str, object]:
        """批量发起审核：把本人选中的若干「已提交」问卷改为「待审核」。

        body: {"survey_ids": [...]}。逐条给结果（ok / 原因），只有 ok 的真改了状态；
        非本人 / 非「已提交」/ 不存在 的都跳过、不动库。
        """
        ids = [s for s in (str(i) for i in (payload.get("survey_ids") or [])) if s]
        backend = _survey_backend()
        results = backend.review(ids, session.viewer())
        return {"results": results, "ok": [k for k, v in results.items() if v == "ok"]}

    @app.post("/api/survey/finalize")
    def survey_finalize(payload: dict[str, Any]) -> dict[str, object]:
        """批量审核通过：把本人选中的若干「待审核」问卷改为「已定稿」（终态·锁定）。

        body: {"survey_ids": [...]}。本期「审核通过」不做角色鉴权——谁登录谁能点（占位，
        引入组织架构后限部门领导，见设计 §2/§5）。逐条给结果，非「待审核」的跳过。
        """
        ids = [s for s in (str(i) for i in (payload.get("survey_ids") or [])) if s]
        backend = _survey_backend()
        results = backend.finalize(ids, session.viewer())
        return {"results": results, "ok": [k for k, v in results.items() if v == "ok"]}

    @app.post("/api/survey/writeback")
    def survey_writeback(payload: dict[str, Any]) -> dict[str, object]:
        """办公端「保存回问卷」：读线上→3-way 合并→冲突返回或写回（双向同步 §5）。

        body：`{survey_id, base, mine, resolutions?}`。无冲突则写「问卷内容」+「更新时间」，
        不改状态/共有人；同字段冲突不写、回 `conflicts` 供前端逐字段选后带 `resolutions` 重提。
        权限=可编辑(owner/管理员)，否则 404；待审核/已定稿锁态 400；本地模式（无问卷源）409。
        """
        survey_id = str(payload.get("survey_id", "") or "")
        base = payload.get("base")
        mine = payload.get("mine")
        if not survey_id or not isinstance(base, dict) or not isinstance(mine, dict):
            raise HTTPException(status_code=400, detail="survey_id/base/mine 缺失或格式错误")
        resolutions = payload.get("resolutions")
        if resolutions is not None and not isinstance(resolutions, dict):
            raise HTTPException(status_code=400, detail="resolutions 须为对象")
        backend = _survey_backend()
        try:
            return backend.writeback(
                survey_id,
                base=base,
                mine=mine,
                viewer=session.viewer(),
                now=datetime.now().isoformat(timespec="seconds"),
                resolutions=resolutions,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        fp = _base_table_fingerprint(store, cat, fingerprint)
        try:
            knowledge = store.load(cat, fp)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        info = next((v for v in store.list_versions(cat) if v.指纹 == fp), None)
        return {
            "factors": [
                {
                    "名称": f.name,
                    # 资产状况分组（区位状况/实物状况/权益状况），来自实勘表导入。
                    # 表单据此把 28 个因素按组分节展示，不在 JS 里另编一份分组规则。
                    "分组": f.group,
                    "系数": f.coefficient,
                    # 调整范围（J 列，如 "2-4"）：单份偏离表单据此给系数输入框一个
                    # 只读软边界提示，越界不阻断（check_coefficient_overrides 同理）。
                    "调整范围": f.调整范围,
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

    def _versions_view(
        store: BaseTableStore, active: ActiveVersions, cat: Category
    ) -> dict[str, object]:
        """某类别版本视图：版本列表（新→旧，各带 latest/active 标）+ 生效指纹。"""
        versions = store.list_versions(cat)
        latest_fp = versions[0].指纹 if versions else None
        active_fp = active_fingerprint(store, active, cat)
        return {
            "类别": cat.value,
            "生效指纹": active_fp,
            "versions": [
                {
                    **_version_payload(v),
                    "latest": v.指纹 == latest_fp,
                    "active": v.指纹 == active_fp,
                }
                for v in versions
            ],
        }

    @app.get("/api/base-tables/all")
    def list_all_base_tables() -> dict[str, object]:
        """全部类别的基础表版本（供基础表页手风琴）：每类别版本 + 生效版 + latest 标。"""
        store = BaseTableStore(_base_table_dir())
        active = ActiveVersions(_base_table_dir())
        return {"categories": [_versions_view(store, active, cat) for cat in Category]}

    @app.get("/api/base-tables")
    def list_base_tables(category: str) -> dict[str, object]:
        """某类别的全部基础表版本，导入时间新→旧。旧版永不覆盖，故都在。"""
        try:
            cat = Category(category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"未知类别：{category}") from exc
        store = BaseTableStore(_base_table_dir())
        return _versions_view(store, ActiveVersions(_base_table_dir()), cat)

    @app.post("/api/base-tables/pull")
    def pull_base_tables_from_notable() -> dict[str, object]:
        """从多维表拉取基础表版本到本地（并集，已有不动）。未配→409；网络异常→502。"""
        remote = notable_base_table_backend()
        if remote is None:
            raise HTTPException(
                status_code=409, detail="从多维表拉取需配好凭据与基础表 sheet（检查 .env）"
            )
        local = LocalFileBaseTableBackend(_base_table_dir())
        try:
            result = pull_base_tables(local, remote)
        except Exception as exc:  # noqa: BLE001  网络/多维表异常兜底回 502，不崩
            logger.exception("从多维表拉取基础表失败")
            raise HTTPException(status_code=502, detail=f"拉取失败：{exc}") from exc
        return {"pulled": result}

    @app.post("/api/base-tables/active")
    def set_active_base_table(payload: dict[str, Any]) -> dict[str, object]:
        """把某类别的生效版本设为某指纹（D2）。指纹须本地已有，否则 400。"""
        try:
            cat = Category(str(payload.get("category", "")))
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"未知类别：{payload.get('category')!r}"
            ) from exc
        fingerprint = str(payload.get("fingerprint", "")).strip()
        store = BaseTableStore(_base_table_dir())
        if not any(v.指纹 == fingerprint for v in store.list_versions(cat)):
            raise HTTPException(status_code=400, detail=f"{cat.value} 类无版本 {fingerprint}")
        ActiveVersions(_base_table_dir()).set(cat, fingerprint)
        return {"category": cat.value, "生效指纹": fingerprint}

    @app.post("/api/base-tables")
    async def import_base_table(file: UploadFile) -> dict[str, object]:
        """导入基础表（方案乙：Excel 是权威，系统存副本，改了重导一次）。

        指纹相同即空操作——「估价师没改基础表就又导了一次」是常态，不是错误。
        导入后若配了多维表，把该版推一份上去（D4）。
        """
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="只接受 .xlsx 文件")
        workdir = Path(tempfile.mkdtemp(prefix="基础表_"))
        path = workdir / (file.filename or "基础表.xlsx")
        path.write_bytes(await file.read())
        try:
            store = BaseTableStore(_base_table_dir())
            imported = store.import_from_excel(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        _push_base_table_if_online(store, imported.版本.类别, imported.版本.指纹)
        return {"base_table": _version_payload(imported.版本), "是否新版": imported.是否新版}

    @app.get("/api/ledger")
    def list_ledger() -> dict[str, object]:
        """台账列表，生成时间新→旧。**不含整份基础表知识**——列表不必背着它走。"""
        return {
            "entries": [
                {
                    "记录号": e.记录号,
                    "报告编号": e.报告编号,
                    "生成时间": e.生成时间.isoformat(),
                    "经手人": e.经手人,
                    "程序版本": e.程序版本,
                    "类别": e.类别.value,
                    "经引擎重算": e.经引擎重算,
                    "基础表版本": e.基础表.实际指纹 if e.基础表 else None,
                    "评估结果": e.结果.评估结果 if e.结果 else None,
                }
                for e in LedgerStore(_ledger_dir()).list_all()
            ]
        }

    @app.get("/api/ledger/{record_id}")
    def get_ledger(record_id: str) -> dict[str, object]:
        """一条台账的完整快照。

        **路径参数名用 ASCII**（`record_id`，仿 `/api/drafts/{draft_id}`）——Starlette
        的 `PARAM_REGEX` 只认 `[a-zA-Z_][a-zA-Z0-9_]*`，`{记录号}` 这种非 ASCII
        花括号段匹配不到参数名，会被当成路径里的字面文本，导致这条路由永远
        404（已用最小复现验证）。变量到手后仍按本文件惯例改叫「记录号」。
        """
        记录号 = record_id
        entry = LedgerStore(_ledger_dir()).get(记录号)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"台账记录不存在：{记录号}")
        return ledger_to_dict(entry)

    @app.post("/api/ledger/{record_id}/replay")
    def replay_ledger(record_id: str) -> dict[str, object]:
        """照台账重算，当场验证能不能复现出同一个数。

        **把「可复现」从承诺变成事实。** 全程不碰实例库、不碰基础表库。

        路径参数同上一个路由，用 ASCII 的 `record_id`，理由见 `get_ledger` 的 docstring。
        """
        记录号 = record_id
        entry = LedgerStore(_ledger_dir()).get(记录号)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"台账记录不存在：{记录号}")
        try:
            result = replay(entry)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        recorded = entry.结果
        return {
            "台账记的": {
                "比准价格": list(recorded.比准价格),
                "评估结果": recorded.评估结果,
                "离散度": recorded.离散度,
            } if recorded else None,
            "重算得的": {
                "比准价格": list(result.比准价格),
                "评估结果": result.评估结果,
                "离散度": result.离散度,
            },
            "一致": recorded == result,
        }

    @app.post("/api/render")
    async def render_report(
        project: str = Form(...),
        ledger: str | None = Form(default=None),
        files: list[UploadFile] | None = File(default=None),
    ) -> FileResponse:
        try:
            parsed = _project_from_payload(json.loads(project))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"项目数据解析失败：{exc}") from exc

        # —— 多维表在线：领全公司唯一号，替换掉表单里的编号（§6 决策 A）——
        # 本地模式（承载后端≠多维表）此段跳过，report_no 沿用表单手填值，行为不变。
        if config.use_notable():
            notable = config.build_client()
            if notable is None:
                raise HTTPException(
                    status_code=503,
                    detail="承载后端=多维表 但缺凭据，无法领号；请存为待同步草稿，配好凭据后同步。",
                )
            try:
                编号 = draw_report_number(
                    notable, config.ledger_sheet(), year=datetime.now().year
                )
            except Exception as exc:  # noqa: BLE001  离线/领号失败一律转 503，让前端存待同步
                logger.warning("领号失败，转 503：%s", exc)
                raise HTTPException(
                    status_code=503,
                    detail="当前离线或领号失败，请存为待同步草稿，联网后到草稿列表定稿。",
                ) from exc
            parsed = replace(parsed, report_no=编号)
            logger.info("已领报告编号：%s", 编号)

        workdir = Path(tempfile.mkdtemp(prefix="guijia_"))
        attachment_paths: list[Path] = []
        for index, upload in enumerate(files or []):
            dest = workdir / (upload.filename or f"attachment_{index}")
            dest.write_bytes(await upload.read())
            attachment_paths.append(dest)

        try:
            pages: tuple[AttachmentPage, ...] = collect(attachment_paths, workdir / "_pages")
            output = workdir / f"{_safe_filename(parsed.report_no)}.docx"
            # 模板路径由 render() 自己按 paths.templates_dir() 解析——冻结与否只在
            # src/paths.py 判断一次，此处不再重复一份。
            render(parsed, pages, output)
        except (ValueError, FileNotFoundError) as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # 落台账。**记不上不许把报告也搞挂**：报告是估价师要交的东西，台账是我们
        # 要留的账，两者冲突时先保住报告——但要在日志里喊出来，不能静默吞掉。
        try:
            raw_ledger = json.loads(ledger) if ledger else None
            记录号 = LedgerStore(_ledger_dir()).append(
                _build_ledger_entry(parsed, raw_ledger)
            )
            logger.info("台账已记 %s", 记录号)
        except Exception:  # noqa: BLE001
            # 兜住一切——这里的语义就是「无论台账出什么事，报告都得照常出」。
            # 原本手工枚举五种异常，但那是靠自觉维持的白名单：将来任一被调模块
            # 新增一种异常（哪怕笔误引发的 AttributeError），就会冲出 /api/render，
            # 恰恰破坏这段代码的初衷。KeyboardInterrupt/SystemExit 不是 Exception
            # 的子类，仍会正常穿透，不会被误吞。
            logger.exception("台账记录失败，报告照常生成：%s", parsed.report_no)

        logger.info("生成报告：%s", output.name)
        return FileResponse(
            output,
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            filename=output.name,
            background=BackgroundTask(shutil.rmtree, workdir, ignore_errors=True),
        )

    @app.post("/api/agreement")
    async def render_agreement_endpoint(
        project: str = Form(...),
        fee_total: int = Form(...),
    ) -> FileResponse:
        """生成委托评估协议书。与 /api/render 同一份 project 数据、收费手填。

        协议书不进台账（无估价算术），只当场渲染返回。
        """
        try:
            parsed = _project_from_payload(json.loads(project))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"项目数据解析失败：{exc}") from exc
        if fee_total < 0:
            raise HTTPException(status_code=400, detail="收费合计不能为负")

        workdir = Path(tempfile.mkdtemp(prefix="guijia_xy_"))
        try:
            output = workdir / f"{_safe_filename(parsed.report_no)}_委托评估协议书.docx"
            render_agreement(parsed, fee_total, output)
        except (ValueError, FileNotFoundError) as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        logger.info("生成委托评估协议书：%s", output.name)
        return FileResponse(
            output,
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            filename=output.name,
            background=BackgroundTask(shutil.rmtree, workdir, ignore_errors=True),
        )

    return app
