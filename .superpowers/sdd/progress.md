# 进度账本 — 房地产估价报告生成系统

计划：docs/superpowers/plans/2026-07-15-房地产估价报告生成系统.md（15 个任务）
分支：feat/report-generator

## Pre-flight 修正
- 计划原将 surveyor 硬编码为 ""，实为 D46 手工录入字段。已修正。
- 署名规则经用户确认：查勘人若属抬头签字估价师（韩伟/胡柯）则不署名，否则署名。
  证据：农用/商业 D46=郑伟娜→署名；办公 D46=胡柯→不署名。已写入 Task 3/4/5/7/8。

## 任务进度

Task 1: complete (commits 5079106..507b112, 规格✅ 质量批准)
  - 审查发现 .gitignore 缺失（控制者早先的 `cd &&` 短路所致，非实现者问题），已补 (见 git log)
  - Minor 待最终审查裁决：tests/__init__.py 无 __all__（brief 明确要求空文件，规则与 brief 冲突）
  - 流程偏差：Step2 红灯未跑（pyproject 不存在时 uv 跑不起来，理由成立，交付物无碍）

Task 2: complete (commits 00064e6..03212b0, 规格✅ 质量批准)
  Minor 待最终审查裁决：
  - Project 缺 frozen 的直接测试（Subject 有），若有人误删 frozen=True 测试不报警
  - has_certificate 用子串 "已取得" 匹配，遇「已取得受理凭证」类文本会误判（brief 规定的语义，非实现缺陷）
