"""HTTP 请求分发（serverless broker）：saveDraft/loadDraft/submit/prefillGeo → store/amap。

`dispatch` 是纯函数——只认 `action` + `payload` + 两个协作对象，不碰
`os.environ`/网络/FC 运行时，测试直接灌假 store/amap。真正的阿里云 FC
入口函数放在文件末尾，把 event 解析、env 取凭据、构造真实客户端都聚在
这一层，方便部署时单独按真机校准（# 待部署校准）。
"""

import base64
import binascii
import json
import logging
import os
from typing import Any, Protocol

from serverless.survey_broker.amap import AmapClient
from serverless.survey_broker.identity import DingtalkIdentity
from serverless.survey_broker.media import DingtalkMedia
from serverless.survey_broker.store import SurveyBrokerStore
from src.dingtalk.notable import NotableClient

logger = logging.getLogger(__name__)

__all__ = ["dispatch", "handler"]


class _Store(Protocol):
    """`dispatch` 只需要 store 的这三个方法（`SurveyBrokerStore` 天然满足）。"""

    def save_draft(
        self,
        *,
        survey_id: str | None,
        filler: str,
        category: str,
        updated_at: str,
        content: dict[str, Any],
    ) -> str: ...

    def load(self, survey_id: str) -> dict[str, Any]: ...

    def submit(self, survey_id: str) -> None: ...


class _Amap(Protocol):
    """`dispatch` 只需要 amap 的这一个方法（`AmapClient` 天然满足）。"""

    def prefill_geo(self, lng: float, lat: float) -> dict[str, Any]: ...


class _Identity(Protocol):
    """`dispatch` 只需要 identity 的这一个方法（`DingtalkIdentity` 天然满足）。"""

    def whoami(self, auth_code: str) -> dict[str, Any]: ...


class _Media(Protocol):
    """`dispatch` 只需要 media 的这一个方法（`DingtalkMedia` 天然满足）。"""

    def upload(self, name: str, data: bytes, mime: str = ...) -> dict[str, str]: ...


def _require(payload: dict[str, Any], key: str) -> Any:
    """payload 里必填字段缺失 → ValueError（映射成 400）。

    刻意不让原生 `payload[key]` 的 KeyError 冒泡——那会跟"问卷不存在"的
    KeyError（映射成 404）混在一起，请求本身不合法应该是 400 而不是 404。
    """
    if key not in payload:
        raise ValueError(f"缺少字段：{key}")
    return payload[key]


def dispatch(
    action: str,
    payload: dict[str, Any],
    *,
    store: _Store,
    amap: _Amap,
    identity: _Identity,
    media: _Media | None = None,
) -> tuple[int, dict[str, Any]]:
    """路由一个动作到 store/amap/identity/media。

    `media` 关键字可选（默认 None）——只有 `uploadPhoto` 用到；不传而调 uploadPhoto
    回 500，其余 action 一律不受影响（保持既有调用点零改动）。

    Returns:
        `(http_status, body)`。成功 200；未知 action 400；请求缺字段/内容坏 400；
        问卷不存在 404（KeyError 只从 store 的"找不到"语义产生，见 `_require`）。
    """
    if not isinstance(payload, dict):
        return 400, {"error": "payload 必须是对象"}
    try:
        if action == "whoami":
            return 200, identity.whoami(str(_require(payload, "authCode")))
        if action == "uploadPhoto":
            if media is None:
                return 500, {"error": "media 未配置"}
            name = str(payload.get("name") or "photo.jpg")
            mime = str(payload.get("mime") or "image/jpeg")
            try:
                data = base64.b64decode(str(_require(payload, "dataBase64")), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError(f"dataBase64 不是合法 base64：{exc}") from exc
            return 200, media.upload(name, data, mime)
        if action == "saveDraft":
            content = payload.get("content")
            if not isinstance(content, dict):
                raise ValueError("content 必须是对象")
            survey_id = store.save_draft(
                survey_id=payload.get("survey_id"),
                filler=str(_require(payload, "filler")),
                category=str(_require(payload, "category")),
                updated_at=str(_require(payload, "updated_at")),
                content=content,
            )
            return 200, {"survey_id": survey_id}
        if action == "loadDraft":
            survey_id = str(_require(payload, "survey_id"))
            return 200, store.load(survey_id)
        if action == "submit":
            survey_id = str(_require(payload, "survey_id"))
            store.submit(survey_id)
            return 200, {"survey_id": survey_id}
        if action == "prefillGeo":
            lng = float(_require(payload, "lng"))
            lat = float(_require(payload, "lat"))
            return 200, amap.prefill_geo(lng, lat)
        return 400, {"error": f"未知 action：{action}"}
    except KeyError as exc:
        return 404, {"error": f"未找到：{exc}"}
    except ValueError as exc:
        return 400, {"error": str(exc)}


def handler(event: bytes | dict[str, Any], context: Any) -> dict[str, Any]:
    """阿里云 FC 3.0 HTTP 触发器入口。

    # 待部署校准：以下全部是假定，未打真实 FC 环境验证——
    #   1) 触发器/运行时选"事件处理程序"（非"Web Server 运行时"，两者 event
    #      形状完全不同，不可混用）；
    #   2) event 假定是 API-Gateway-代理风格的 JSON（多数版本给 bytes 编码，
    #      少数给已解好的 dict，故类型标 `bytes | dict`），形如
    #      {"httpMethod": "POST", "path": "...", "body": "<json 字符串>", ...}；
    #   3) 请求体 body 假定是 {"action": "...", "payload": {...}}；
    #   4) 返回值假定 FC 会把 {"statusCode":, "headers":, "body":} 序列化成
    #      HTTP 响应（同 API Gateway 代理集成的约定）。
    # 部署前须对照阿里云 FC 3.0 最新文档核实触发器类型、event/response 精确形状，
    # 必要时改写本函数（不影响 dispatch，dispatch 不碰这层协议）。
    """
    try:
        request: dict[str, Any]
        if isinstance(event, (bytes, bytearray)):
            request = json.loads(event.decode("utf-8"))
        else:
            request = event
        body_raw = request.get("body") or "{}"
        body = json.loads(body_raw) if isinstance(body_raw, str) else (body_raw or {})
    except (json.JSONDecodeError, TypeError, AttributeError) as exc:
        logger.warning("FC event 解析失败：%s", exc, exc_info=True)
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "请求体不是合法 JSON"}, ensure_ascii=False),
        }

    action = str(body.get("action") or "")
    payload = body.get("payload") or {}

    client = NotableClient(
        os.environ["DINGTALK_APP_KEY"],
        os.environ["DINGTALK_APP_SECRET"],
        base_id=os.environ["NOTABLE_BASE_ID"],
        operator_id=os.environ["NOTABLE_OPERATOR_ID"],
    )
    store = SurveyBrokerStore(client, os.environ["NOTABLE_SURVEY_SHEET"])
    amap = AmapClient(os.environ["AMAP_KEY"])
    identity = DingtalkIdentity(client.access_token)
    media = DingtalkMedia(client.access_token)

    status, result = dispatch(
        action, payload, store=store, amap=amap, identity=identity, media=media
    )
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result, ensure_ascii=False),
    }
