"""隐藏终端后（PyInstaller --noconsole）标准流为 None，日志得安全落到文件。

这是交付 exe 才暴露的一类事：开发环境 stdout 一直是真流，怎么测都绿；只有
冻结无控制台时 stdout 变 None，才会把 uvicorn/logging 炸在 None 上、程序默默
起不来。故此处直接喂 None 盯住这条线。
"""

import io
from pathlib import Path

from src.__main__ import LOG_FILENAME, _resolve_log_stream


def test_returns_none_when_stdout_is_a_real_stream(tmp_path: Path) -> None:
    """开发环境有真 stdout：不改动，返回 None。"""
    assert _resolve_log_stream(tmp_path, io.StringIO()) is None


def test_redirects_to_logfile_when_stdout_is_none(tmp_path: Path) -> None:
    """冻结无控制台（stdout=None）：返回一个写到 exe 旁 运行日志.log 的流。"""
    stream = _resolve_log_stream(tmp_path, None)
    assert stream is not None
    try:
        stream.write("能写就不会炸\n")
        stream.flush()
    finally:
        stream.close()
    log = tmp_path / LOG_FILENAME
    assert log.exists()
    assert "能写就不会炸" in log.read_text(encoding="utf-8")


def test_falls_back_when_dir_unwritable(tmp_path: Path) -> None:
    """目录不可写也不能让程序起不来——退到 devnull，仍返回可写流。"""
    unwritable = tmp_path / "不存在的目录"  # 父目录不存在 → open 追加抛 OSError
    stream = _resolve_log_stream(unwritable, None)
    assert stream is not None
    try:
        stream.write("x")  # 不抛异常即可
    finally:
        stream.close()
