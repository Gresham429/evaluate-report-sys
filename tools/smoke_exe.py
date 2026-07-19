"""冻结产物冒烟测试——**验的是「打出来能用」，不是「打出来了」**。

`tests/test_paths.py` 靠 monkeypatch 假装冻结，能挡住路径写法的回归，但挡不住
「PyInstaller 没把某个文件收进包」「hidden import 漏了」这类只有真跑才暴露的事。
合并前那个 bug 正是这么溜过去的：开发环境一切正常、测试全绿，而 exe 一份报告
也生成不了、数据每次关闭清零。

故本脚本**只对真产物下手**：启动它，打几个真请求，然后回头看磁盘。

    ① GET  /                 服务起得来（uvicorn 的 hidden import 齐不齐）
    ② POST /api/drafts       写一份草稿 → 落盘位置必须在产物旁边，不在临时解压目录
    ③ POST /api/render       出一份真报告 → 同时验 templates/ 与 copy.yaml 都找得到

②③ 各自对应一类真实事故：②不过 = 估价师录的数据关掉就没；③不过 = 一份报告
也出不来。

用法：
    uv run python tools/smoke_exe.py dist/appraisal-report-system.exe
"""

import json
import logging
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

BASE = "http://127.0.0.1:8765"
STARTUP_TIMEOUT = 60

# 一份最小可渲染的办公项目。字段值不重要——此处验的是「找得到模板与文案库」，
# 数字对不对由 tests/ 里的金样回归盯着。
_PROJECT = {
    "category": "办公",
    "report_no": "冒烟测试",
    "project_name": "冒烟测试",
    "client": "", "client_address": "", "legal_rep": "", "purpose": "",
    "survey_date": "2026-03-26", "value_date": "2026-03-26",
    "materials": "", "certificate_status": "估价对象已取得《不动产权证》",
    "owner": "", "address": "", "usage": "办公", "scale": "", "scope": "",
    "current_status": "", "work_period": "", "issue_date": "2026-04-07", "surveyor": "",
    "unit_price": 2.83, "dispersion": 0.05,
    "subjects": [{
        "index": 1, "owner": "甲", "address": "某处", "usage": "办公",
        "area": 100.0, "unit_price": 2.83, "annual_value": 103295,
    }],
}


def _wait_until_up() -> None:
    """等服务起来。起不来就是包缺东西，直接失败。"""
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/", timeout=2) as r:
                if r.status == 200:
                    logger.info("① 服务起来了")
                    return
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(1)
    raise SystemExit(f"✗ {STARTUP_TIMEOUT} 秒内服务没起来")


def _post(path: str, payload: dict[str, object] | None = None, form: bytes | None = None,
          content_type: str = "application/json") -> tuple[int, bytes]:
    data = form if form is not None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _check_draft_lands_beside_the_exe(app_dir: Path) -> None:
    """②：写一份草稿，看它落在哪。

    落进临时解压目录 = 估价师填的东西关掉程序就没。这是本脚本最要紧的一条。
    """
    status, body = _post("/api/drafts", {"数据": {"报告编号": "冒烟测试", "类别": "办公"}})
    if status != 200:
        raise SystemExit(f"✗ 存草稿失败 {status}：{body[:300]!r}")

    drafts = list((app_dir / "data" / "草稿").glob("*.json"))
    if not drafts:
        # 趁进程还活着（_MEIPASS 未删）问它自己把路径解析成了啥——直指真凶。
        try:
            with urllib.request.urlopen(BASE + "/api/_diag", timeout=5) as r:
                diag = r.read().decode("utf-8")
        except (urllib.error.URLError, OSError) as exc:
            diag = f"(取 /api/_diag 失败：{exc})"
        raise SystemExit(
            f"✗ 草稿没落在产物旁边（找的是 {app_dir / 'data' / '草稿'}）。\n"
            f"  应用自报路径：{diag}\n"
            f"  冻结后 Path(__file__) 指向退出即删的临时目录——数据每次关闭会清零。\n"
            f"  见 src/paths.py。"
        )
    logger.info("② 草稿落在产物旁边：%s", drafts[0].relative_to(app_dir))


def _check_report_renders(app_dir: Path) -> None:
    """③：出一份真报告。同时验 templates/ 与 copy.yaml 都找得到。

    copy.yaml 曾压根没被打进包，此时 load_copy() 抛 FileNotFoundError——
    exe 一份报告也生成不了，而开发环境毫无征兆。
    """
    boundary = "----smoke"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="project"\r\n\r\n'
        f"{json.dumps(_PROJECT, ensure_ascii=False)}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    status, payload = _post(
        "/api/render", form=body, content_type=f"multipart/form-data; boundary={boundary}"
    )
    if status != 200:
        raise SystemExit(f"✗ 生成报告失败 {status}：{payload[:400]!r}")
    if not payload.startswith(b"PK"):
        raise SystemExit(f"✗ 返回的不是 docx（zip 应以 PK 开头）：{payload[:40]!r}")
    logger.info("③ 报告生成成功，%d 字节（templates/ 与 copy.yaml 都找得到）", len(payload))


def main(exe: Path) -> int:
    if not exe.exists():
        raise SystemExit(f"✗ 产物不存在：{exe}")
    app_dir = exe.parent

    # 先清掉上一次冒烟留下的 data/，否则「草稿落在这里」可能是上次的残留。
    shutil.rmtree(app_dir / "data", ignore_errors=True)

    logger.info("冒烟测试 %s", exe)
    process = subprocess.Popen(
        [str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=app_dir
    )
    try:
        _wait_until_up()
        _check_draft_lands_beside_the_exe(app_dir)
        _check_report_renders(app_dir)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(app_dir / "data", ignore_errors=True)

    logger.info("✓ 冒烟测试全过")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：python tools/smoke_exe.py <产物路径>")
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
