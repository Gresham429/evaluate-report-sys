"""app 启动加载 .env：读文件、setdefault 不覆盖既有 env、缺文件即 no-op。

只测 _load_dotenv 的纯逻辑，不起 uvicorn。
"""

import pytest

import src.__main__ as m


def test_load_dotenv_sets_missing_keys(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("承载后端=多维表\nNOTABLE_BASE_ID=b123\n", encoding="utf-8")
    monkeypatch.setattr(m, "app_dir", lambda: tmp_path)
    monkeypatch.delenv("承载后端", raising=False)
    monkeypatch.delenv("NOTABLE_BASE_ID", raising=False)
    m._load_dotenv()
    import os
    assert os.environ["承载后端"] == "多维表"
    assert os.environ["NOTABLE_BASE_ID"] == "b123"


def test_load_dotenv_does_not_override_existing_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("承载后端=多维表\n", encoding="utf-8")
    monkeypatch.setattr(m, "app_dir", lambda: tmp_path)
    monkeypatch.setenv("承载后端", "本地既有值")
    m._load_dotenv()
    import os
    assert os.environ["承载后端"] == "本地既有值"  # setdefault：既有的不动


def test_load_dotenv_noop_when_file_absent(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m, "app_dir", lambda: tmp_path)  # 目录空、无 .env
    m._load_dotenv()  # 不抛即可
