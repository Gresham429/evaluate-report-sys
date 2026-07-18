"""钉钉多维表（notable / AI 表格）冒烟测试：证明"本地 ↔ 多维表"这条路通、且免费可用。

背景：宜搭 OpenAPI 卡在专业版（5988/年）。钉钉**多维表**是另一个产品，2024.04 起
基础用量**免费**（扩容才需钉钉文档企业版 198/人/年）。本脚本验证：拿现有企业内部
应用凭据能不能读写多维表——通了就等于一个"零服务器、数据留钉钉、几乎零成本"的承载层。

与 `yida_smoke.py` 同套路：**首版草稿**，端点按钉钉 v1.0 notable 接口的当前形状写；
真正调通要拿到 baseId/operatorId + 开表格读写权限后**在本机实跑、按真实报错校准**
（脚本把每步原始响应都打出来）。只用标准库（urllib），拿到即可跑。

凭据从环境变量 / 仓库根 .env 读（.env 已 gitignore，不进仓库）：

    # 复用取 token 的企业内部应用凭据（与宜搭冒烟同一个 AppKey/AppSecret）
    YIDA_APP_KEY=...            # 钉钉企业内部应用 AppKey（Client ID）
    YIDA_APP_SECRET=...         # 钉钉企业内部应用 AppSecret（Client Secret）
    # 多维表侧（选填；缺了就只跑"零输入探针"，靠报错判断接口是否可用/是否卡套餐）
    NOTABLE_BASE_ID=...         # 多维表 baseId：打开多维表→右上角设置→API文档，那页给全
    NOTABLE_SHEET=Sheet1        # 工作表名或 sheetId（默认 Sheet1）
    NOTABLE_OPERATOR_ID=...     # 操作人 unionId（同在 API文档 页给出）

    uv run python tools/notable_smoke.py

跑完把整段输出发我，我据真实报错把端点/参数/字段标识钉死。
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

# 零输入探针用的占位 baseId：故意用一个不存在的值。作用同宜搭冒烟里"用错 formUuid
# 也能撞出权限/套餐错误"——只要拿到的不是"免费版不支持 openApi"、也不是"接口不存在"，
# 就证明多维表 OpenAPI 对本组织可用（免费）、只差开权限/给真 baseId。
_PROBE_BASE_ID = "PROBE_NONEXISTENT_BASE"


def _load_dotenv() -> None:
    """把仓库根 .env 的 KEY=VALUE 读进环境（不覆盖已设的），免装 python-dotenv。"""
    env_file = REPO / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"缺环境变量 {name}——填进仓库根 .env 或 export，见本文件顶部说明。")
    return value


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


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
    """企业内部应用 accessToken（v1.0）。多维表与宜搭共用同一套鉴权。"""
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


def list_records(token: str, base_id: str, sheet: str, operator_id: str) -> tuple[int, str]:
    """列多维表某工作表的记录。端点按 v1.0 notable 当前形状；operatorId 作查询参数。"""
    query = urllib.parse.urlencode({"operatorId": operator_id}) if operator_id else ""
    url = f"{BASE}/v1.0/notable/bases/{base_id}/sheets/{sheet}/records/list"
    if query:
        url = f"{url}?{query}"
    code, text = _request("POST", url, headers=_auth(token), body={"maxResults": 5})
    print("[list] HTTP", code, text[:600])
    return code, text


def insert_record(token: str, base_id: str, sheet: str, operator_id: str) -> None:
    """往多维表写一行。fields 用字段名占位；真 baseId 到手后按 API文档 换字段标识。"""
    query = urllib.parse.urlencode({"operatorId": operator_id}) if operator_id else ""
    url = f"{BASE}/v1.0/notable/bases/{base_id}/sheets/{sheet}/records"
    if query:
        url = f"{url}?{query}"
    code, text = _request(
        "POST", url, headers=_auth(token),
        body={"records": [{"fields": {"标题": "notable-smoke-0001"}}]},
    )
    print("[insert] HTTP", code, text[:600])


def _classify(code: int, text: str) -> str:
    """把探针响应翻译成人话结论。"""
    low = text.lower()
    if "openapi" in low and ("免费" in text or "not support" in low or "暂不支持" in text):
        return "❌ 卡套餐：该组织不支持多维表 OpenAPI（与研究结论矛盾，需复核组织/产品）。"
    if "permissiondenied" in low or "requiredscopes" in low or "尚未开通" in text or code == 403:
        return "✅ 接口对本组织可用（未被套餐拦），只差开『表格读/写』权限——按报错里的申请链接开即可。"
    if "notfound" in low or code == 404:
        return "⚠️ 端点或 baseId 不对（占位 baseId 本就不存在）。若是 baseId 不存在=接口通、给真 baseId 即可；若是 api not found=端点要校准。"
    if code == 200:
        return "✅ 直接读通（权限已在），给真 baseId/operatorId 即可跑完整写读。"
    return "❓ 未归类，把原始响应发我。"


def main() -> None:
    _load_dotenv()
    app_key = _env("YIDA_APP_KEY")
    app_secret = _env("YIDA_APP_SECRET")
    base_id = _opt("NOTABLE_BASE_ID")
    sheet = _opt("NOTABLE_SHEET", "Sheet1")
    operator_id = _opt("NOTABLE_OPERATOR_ID")

    print("=== 1) 取 accessToken ===")
    token = get_access_token(app_key, app_secret)
    print("拿到 token：", token[:10], "…\n")

    if not base_id:
        print("=== 2) 零输入探针（未给 NOTABLE_BASE_ID，用占位 base 撞错误判可用性）===")
        code, text = list_records(token, _PROBE_BASE_ID, sheet, operator_id or "PROBE")
        print("\n>>> 结论：", _classify(code, text))
        print("\n下一步：打开你新组织的多维表 → 右上角设置 → API文档，把 baseId / sheetId /")
        print("operatorId 填进 .env（NOTABLE_BASE_ID/NOTABLE_SHEET/NOTABLE_OPERATOR_ID），")
        print("并按上面报错的申请链接开『表格读/写』权限，再跑一次即可写读全流程。")
        return

    print("=== 2) 列记录（读）===")
    list_records(token, base_id, sheet, operator_id)
    print()
    print("=== 3) 写一行 ===")
    insert_record(token, base_id, sheet, operator_id)
    print()
    print("=== 4) 再列一次核对 ===")
    list_records(token, base_id, sheet, operator_id)


if __name__ == "__main__":
    main()
