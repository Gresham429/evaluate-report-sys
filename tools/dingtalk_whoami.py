"""查 unionId：多维表接口的 operatorId 要用它。

多维表 openapi 的 operatorId 是"操作人的 unionId"。个人资料卡上看不到，这里用企业内部
应用 token 走通讯录老接口把它查出来：先拉管理员名单（建应用的人通常是管理员），再逐个
换 unionId + 姓名。需要应用有"通讯录"读权限；没有就按报错去开一个。

只用标准库；凭据从仓库根 .env 读（同 yida_smoke / notable_smoke）。
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

NEW = "https://api.dingtalk.com"       # v1.0 取 token
OLD = "https://oapi.dingtalk.com"      # 老通讯录接口（access_token 走查询参数）
REPO = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
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
        sys.exit(f"缺环境变量 {name}——填进仓库根 .env。")
    return value


def _post(url: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> tuple[int, str]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
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


def get_token(app_key: str, app_secret: str) -> str:
    code, text = _post(f"{NEW}/v1.0/oauth2/accessToken", {"appKey": app_key, "appSecret": app_secret})
    if code != 200:
        sys.exit(f"取 token 失败：HTTP {code} {text}")
    return str(json.loads(text)["accessToken"])


def list_admin(token: str) -> list[dict[str, Any]]:
    code, text = _post(f"{OLD}/topapi/user/listadmin?access_token={token}", {})
    print("[listadmin] HTTP", code, text[:400])
    obj = json.loads(text) if code == 200 else {}
    return list(obj.get("result", [])) if obj.get("errcode") == 0 else []


def user_get(token: str, userid: str) -> dict[str, Any]:
    code, text = _post(f"{OLD}/topapi/v2/user/get?access_token={token}", {"userid": userid, "language": "zh_CN"})
    obj = json.loads(text) if code == 200 else {}
    return dict(obj.get("result", {})) if obj.get("errcode") == 0 else {"_raw": text}


def list_dept_users(token: str, dept_id: int) -> list[dict[str, Any]]:
    """列某部门成员（v2 直接带回 unionid）。管理员名单拿不到时用这个兜底。"""
    code, text = _post(
        f"{OLD}/topapi/v2/user/list?access_token={token}",
        {"dept_id": dept_id, "cursor": 0, "size": 100, "language": "zh_CN"},
    )
    print(f"[dept {dept_id} 成员] HTTP", code, text[:400])
    obj = json.loads(text) if code == 200 else {}
    return list(obj.get("result", {}).get("list", [])) if obj.get("errcode") == 0 else []


def _print_people(people: list[dict[str, Any]]) -> None:
    for p in people:
        print(f"  姓名={p.get('name', '?')}  userid={p.get('userid', '?')}  unionId={p.get('unionid', '?')}")


def main() -> None:
    _load_dotenv()
    token = get_token(_env("YIDA_APP_KEY"), _env("YIDA_APP_SECRET"))
    print("拿到 token：", token[:10], "…\n")

    # 优先：管理员名单（建应用的人通常在里面），逐个换 unionId。
    admins = list_admin(token)
    if admins:
        print(f"\n找到 {len(admins)} 个管理员，逐个换 unionId：\n")
        _print_people([{**a, **user_get(token, str(a.get("userid", "")))} for a in admins])
        print("\n认出『薛焱』那条，把它的 unionId 发我（或我直接用第一条试）。")
        return

    # 兜底：不是管理员/名单空，就列根部门成员（v2 直接带 unionid）。
    print("\n管理员名单空，改列根部门(dept_id=1)成员兜底：\n")
    people = list_dept_users(token, dept_id=1)
    if people:
        print()
        _print_people(people)
        print("\n认出『薛焱』那条，把 unionId 发我。若人在子部门没列全，告诉我部门名我再拉。")
        return

    print("\n还是没拿到——多半是『通讯录』读权限(qyapi_get_member)没开全。")
    print("→ 去开发者后台给这个应用开通讯录读权限再跑；或直接把你的 userId/手机号发我。")


if __name__ == "__main__":
    main()
