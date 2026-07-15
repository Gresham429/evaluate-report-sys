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

Task 3: complete (commits 11f0175..13e4466, 规格✅ 质量批准 + 修复 Important)
  - 21 个单元格坐标经审查逐一核对无误（含 surveyor=D46, T39, X37）
  - 修复 Important: 测试原只覆盖 19 字段中的 7 个，COMPARISON_FIELDS/RESULT_COLUMNS 零覆盖
    → 13e4466 补全，现 11 项测试全覆盖坐标
  - Minor 待最终审查裁决: RESULT_HEADER_ROW/FIRST_ROW 缺显式 int 标注
  - 实现者报告行数不实（称 185 行，实测 91 行），仅报告问题非代码问题

## 流程优化（用户要求提速）
自 Task 4 起改为合批派发，8 批而非 12 次单派：
  A: 4+5 (extractor)  B: 6+7 (prose)  C: 9+10 (validator+attachments)
  D: 8 (composer)  E: 11 (templates,单独) F: 12 (renderer)
  G: 13 (golden,单独) H: 14+15 (web+packaging)
不做真并行：多个实现代理同时 git commit 必然撞 index.lock，收益抵不上 worktree 复杂度。

Task 4: complete (commit a339fd9, 22 项测试) — 实勘表提取器
Task 5: complete (commit 4cd3b9b + 修复 b2f562d, 10 项测试) — 比较法与一览表提取器
  ✅ C1 铁律测试通过: test_agricultural_price_is_read_not_recomputed
     （农用 K49=1400 手工取整值原样读，不被 T39=1399.26 覆盖）
  - 修复 Important: comparison.py 的 int()/float() 未收窄 Cell.value 宽联合类型，
    mypy 报 4 处 arg-type。这是计划代码的缺陷，非实现者问题。
    → b2f562d 加 _as_int/_as_float/_as_text 辅助函数（显式排除 bool），mypy 归零
  - 实现者自行加了 types-openpyxl 开发依赖（brief 外），加得对——正是它暴露了上述隐患
  - 清除某代理擅建的 .superpowers/sdd/.gitignore（内容为 `*`，会威胁账本存续）
  当前全量: 50 passed, mypy clean, ruff clean
  - 批次A审查: 规格✅ 质量批准。审查者独立打开真实 Excel 复核 C1，确认 K49=1400 与
    T39=1399.26 被分别断言，反重算测试是真锁非摆设。grep 确认全仓 data_only=True，
    无 formulas/eval 重算痕迹。
  - 修复 Important (27d895b): _as_float/_as_int 静默归零无日志。估价报告里的「0元/0㎡」
    看起来像正常数字，比报错更危险。已加 logger.warning（None 属正常空值不告警）。
    同时补 bool 分支单测、统一循环停止条件的 bool 口径。现 52 passed。

Task 6: complete (commit e2df1be, 14 项测试) — 25 处漂移归一化规则
Task 7: complete (commit 66a1081, 5 项测试) — 从金样抽取样板文字生成 copy.yaml
  ✅ 归一化生效验证: len>12 口径下交集 43 → 63（净增 20 段法定套话）
     控制者原设的「>112」门槛是错的（112 为不过滤口径），已修正 (6d1b7f2)
  - copy.yaml: 63 段样板 + registered_appraisers[韩伟,胡柯] + 5 组条件文本
  教训: 代理运行期间不要碰仓库文件——批次B 代理发现计划文件被神秘修改（实为控制者所为），
        正确地拒绝将来源不明的改动入库。
  当前全量: 71 passed, mypy clean, ruff clean

进度: 7/15

Task 9:  complete (commit 57accea) — 数据校验器（只提示不阻断，6 项检查全部源自真实素材的坑）
Task 10: complete (commit 见上) — 附件收集与 PDF 转图（PyMuPDF，非 pdf2image）
  - 用户误触杀掉批次C 代理，Task 10 代码已写完但未提交；代理无法恢复，由控制者接手完成
  - 发现并修复环境损坏: 代理加的 pymupdf-stubs 仅支持 Python>=3.12，与本项目
    requires-python>=3.11 冲突，导致 uv 无法解析、所有命令罢工。
    改为 [[tool.mypy.overrides]] ignore_missing_imports 显式接受 fitz 无存根。
    取舍：类型存根是锦上添花，跨版本兼容是地基。
  当前全量: 81 passed, mypy clean, ruff clean

进度: 9/15
