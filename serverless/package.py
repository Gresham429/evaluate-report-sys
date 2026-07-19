"""把 survey_broker 打成阿里云函数计算(FC)可上传的 zip。

只装 broker 运行真正要用的文件（保持 import 路径 `serverless.survey_broker.*`
与 `src.dingtalk.notable`），零第三方依赖——故 FC 不必装任何 pip 包。

用法：  uv run python serverless/package.py
产物：  serverless/dist/survey_broker_fc.zip
FC 处理程序（入口）填： serverless.survey_broker.handler.handler
"""

import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# 保持仓库内相对路径入 zip —— import 路径才不变。
FILES = [
    "serverless/__init__.py",
    "serverless/survey_broker/__init__.py",
    "serverless/survey_broker/record.py",
    "serverless/survey_broker/store.py",
    "serverless/survey_broker/amap.py",
    "serverless/survey_broker/identity.py",
    "serverless/survey_broker/handler.py",
    "serverless/survey_broker/server.py",
    "src/__init__.py",
    "src/dingtalk/__init__.py",
    "src/dingtalk/notable.py",
]


def main() -> None:
    dist = REPO / "serverless" / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    out = dist / "survey_broker_fc.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in FILES:
            src = REPO / rel
            if not src.exists():
                raise SystemExit(f"缺文件，打包中止：{rel}")
            archive.write(src, rel)
    print(f"打包完成：{out}")
    print(f"含 {len(FILES)} 个文件，零第三方依赖。")
    print("FC 自定义运行时(Web Server 模式)：")
    print("  启动命令 = python3 -m serverless.survey_broker.server")
    print("  监听端口 = 9000")


if __name__ == "__main__":
    main()
