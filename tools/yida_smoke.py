"""宜搭「台账」表冒烟测试：本地 → 宜搭 写一行、再读回来。

目的：证明"本地 ↔ 宜搭"这条路通。**这是首版草稿**，按钉钉开放平台 v1.0
接口的当前形状写；真正调通要拿到用户凭据后**在本机实跑、按真实报错校准**
（宜搭老/新接口、参数名可能要微调——所以脚本把每步的原始响应都打出来）。

只用标准库（urllib），不引第三方依赖，拿到就能跑。

凭据一律从环境变量读，**不写进代码、不进仓库**（security 规矩）：

    export YIDA_APP_KEY=...          # 应用 AppKey
    export YIDA_APP_SECRET=...       # 应用 AppSecret
    export YIDA_SYSTEM_TOKEN=...     # 宜搭应用 SystemToken（appType）
    export YIDA_FORM_UUID=FORM-xxxx  # 台账表的表单编号
    export YIDA_USER_ID=...          # 你的钉钉 userId
    uv run python tools/yida_smoke.py

跑完把整段输出发我，我据此把 save/search 的参数名和字段映射钉死。
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://api.dingtalk.com"
REPO = Path(__file__).resolve().parents[1]
SNAPSHOT_SAMPLE = REPO / "台账快照样例_给宜搭测试用.json"


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"缺环境变量 {name}——见本文件顶部说明。")
    return value


def _request(
    method: str, url: str, *, headers: dict[str, str] | None = None, body: dict[str, Any] | None = None
) -> tuple[int, str]:
    """发一个 HTTP 请求，返回 (状态码, 响应文本)。失败也如实返回，不抛。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for key, val in (headers or {}).items():
        req.add_header(key, val)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310  仅访问固定的钉钉域名
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        return 0, f"网络错误：{exc}"


def get_access_token(app_key: str, app_secret: str) -> str:
    """企业内部应用 accessToken（v1.0）。这步最稳，先证明凭据有效。"""
    code, text = _request(
        "POST", f"{BASE}/v1.0/oauth2/accessToken",
        body={"appKey": app_key, "appSecret": app_secret},
    )
    print("[token] HTTP", code, text[:300])
    if code != 200:
        sys.exit("取 token 失败，先把上面这行发我。")
    return str(json.loads(text)["accessToken"])


def _auth(token: str) -> dict[str, str]:
    return {"x-acs-dingtalk-access-token": token}


def list_form_fields(token: str, system_token: str, form_uuid: str, user_id: str) -> None:
    """拉表单结构，拿到每个字段的"字段标识"（textField_xxx）。

    宜搭 formDataJson 按"字段标识"填、不是中文名，先拉结构对上。端点名首跑可能要校准。
    """
    query = urllib.parse.urlencode({"appType": system_token, "userId": user_id})
    code, text = _request(
        "GET", f"{BASE}/v1.0/yida/forms/{form_uuid}/components?{query}", headers=_auth(token)
    )
    print("[schema] HTTP", code, text[:800])


def save_row(
    token: str, system_token: str, form_uuid: str, user_id: str, form_data: dict[str, Any]
) -> None:
    """往台账表写一行。form_data 的 key 是字段标识（首跑后按 schema 替真标识）。"""
    code, text = _request(
        "POST", f"{BASE}/v1.0/yida/forms/instances", headers=_auth(token),
        body={
            "appType": system_token,
            "formUuid": form_uuid,
            "userId": user_id,
            "formDataJson": json.dumps(form_data, ensure_ascii=False),
        },
    )
    print("[save] HTTP", code, text[:500])


def search_rows(token: str, system_token: str, form_uuid: str, user_id: str) -> None:
    code, text = _request(
        "POST", f"{BASE}/v1.0/yida/forms/instances/search", headers=_auth(token),
        body={
            "appType": system_token,
            "formUuid": form_uuid,
            "userId": user_id,
            "pageNumber": 1,
            "pageSize": 5,
        },
    )
    print("[search] HTTP", code, text[:500])


def main() -> None:
    app_key = _env("YIDA_APP_KEY")
    app_secret = _env("YIDA_APP_SECRET")
    system_token = _env("YIDA_SYSTEM_TOKEN")
    form_uuid = _env("YIDA_FORM_UUID")
    user_id = _env("YIDA_USER_ID")

    print("=== 1) 取 accessToken ===")
    token = get_access_token(app_key, app_secret)
    print("拿到 token：", token[:10], "…\n")

    print("=== 2) 拉台账表字段结构（对字段标识）===")
    list_form_fields(token, system_token, form_uuid, user_id)
    print()

    print("=== 3) 写一行（含快照样例）===")
    snapshot = SNAPSHOT_SAMPLE.read_text(encoding="utf-8") if SNAPSHOT_SAMPLE.exists() else "{}"
    # 字段标识首跑从 schema 里对；这里先用中文名占位，schema 打出来后我替成真标识。
    test_row = {
        "记录号": "smoke-0001",
        "报告编号": "正恒评报字[2026]第TEST号",
        "类别": "办公",
        "快照": snapshot,
    }
    save_row(token, system_token, form_uuid, user_id, test_row)
    print()

    print("=== 4) 读回来核对 ===")
    search_rows(token, system_token, form_uuid, user_id)


if __name__ == "__main__":
    main()
