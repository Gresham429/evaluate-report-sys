"""DingtalkIdentity.whoami：authCode → userid。注入假 token_provider + 假 transport。"""

import json

import pytest

from serverless.survey_broker.identity import DingtalkIdentity


def _transport_ok(_method: str, _url: str, _headers: dict, _body: bytes | None) -> tuple[int, str]:
    return 200, json.dumps({"errcode": 0, "result": {"userid": "u-42", "name": "张三"}})


def test_whoami_returns_userid_and_name() -> None:
    idy = DingtalkIdentity(lambda: "tok", transport=_transport_ok)
    assert idy.whoami("code-abc") == {"userid": "u-42", "name": "张三"}


def test_whoami_bad_code_raises_valueerror() -> None:
    def _transport_bad(_m: str, _u: str, _h: dict, _b: bytes | None) -> tuple[int, str]:
        return 200, json.dumps({"errcode": 40078, "errmsg": "invalid code"})

    idy = DingtalkIdentity(lambda: "tok", transport=_transport_bad)
    with pytest.raises(ValueError):
        idy.whoami("bad")


def test_whoami_http_error_raises_valueerror() -> None:
    def _transport_500(_m: str, _u: str, _h: dict, _b: bytes | None) -> tuple[int, str]:
        return 500, "oops"

    idy = DingtalkIdentity(lambda: "tok", transport=_transport_500)
    with pytest.raises(ValueError):
        idy.whoami("x")
