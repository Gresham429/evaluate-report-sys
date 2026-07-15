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

Task 8: complete (commit 62fe86f, 10 项测试) — 条件组句器
  ✅ 控制者亲自在真实数据上核对三类输出，与金样一致：
     农用 D46=郑伟娜→署名 / 办公 D46=胡柯→不署名（本身是抬头签字人）/ 商业 郑伟娜→署名
     权证条件同时驱动正文资料清单与附件第三项，联动无误
     单位随类别：农用 亩/元·亩·年，房屋类 ㎡/元·㎡·天
  当前全量: 91 passed, mypy clean, ruff clean

进度: 10/15 —— 下一步 Task 11 模板构建（第一个真风险点）

Task 11: complete — 由金样构建三份模板（农用/办公/商业），python-docx 打开验证通过
  模板体积: 农用 65,442B / 办公 68,077B / 商业 67,190B（均 <2MB 阈值，金样 24-40MB）
  发现并修正 brief 骨架代码的三处问题（细节见 task-11-report.md，均未改 drift.py 规则）：
    1. 图片剥离范围过宽——会连页眉司徽 logo 一起删，留悬空引用致 Word 报损坏。
       改为只剥离 document.xml 引用的图片，保留页眉/页脚等骨架部件引用的媒体文件。
    2. normalise() 直接作用于单行原始 XML——「序号点号」规则（权重15/25）的 ^ 锚点
       失效，「方法别名」两条规则因目标短语跨 run 断开而不匹配。改为按 <w:p> 段落
       边界拼接可见文本再整体归一化，与 Task 7 extract_copy.py 的既有做法一致。
    3. normalise() 单遍扫描不收敛（商业金样"缺书名号"+"缺复印件"组合案例实测）。
       调用方加定点迭代至收敛，不改规则本身。
  遗留: drift.py「房屋安全」规则 pattern 与真实金样文本不匹配，25 处漂移点中唯一
        未消除的一处（不在本任务范围，未改 drift.py）。无真实 Word/WPS 环境可用，
        用 python-docx 打开+关系引用零悬空零孤儿+ElementTree 解析作代理验证。
  当前全量: 104 passed, mypy clean, ruff clean

进度: 11/15

Task 11: complete (commit dde5c66 + 修复 f0b27c4, 13 项测试) — 模板构建【风险点已过】
  ✅ 三份模板: 农用65KB/办公68KB/商业67KB（金样 24-40MB，降 99.8%）
     python-docx 可打开，段落218/236/215 表格12/13/12，无悬空引用
  ✅ 代理做了 brief 未指定但正确的判断：区分页眉logo(image1.png，模板固有)
     与项目图片(区位图/照片/权证，14张)，只剥后者。照抄 brief 会连公司抬头一起剥掉。
  ⚠️ 本任务在真实数据上炸出 drift.py 三个缺陷（合成测试全部抓不到）:
     1. 序号规则静默失效: document.xml 是单行XML，(?m)^ 锚点无从触发，
        而该规则占 15/25 = 60% 权重。代理改为按段落重建文本再归一化（调用点修复）
     2. 「房屋安全」pattern 匹配的串金样里根本不存在（控制者从 diff 片段拼错）
        → 修正为 已对安全、环境污染 → 已对房屋安全、环境污染
     3. 「缺复印件」过宽，把正文「按协议书为准」改成「按协议书复印件为准」——
        主动改错，比漏改更危险 → 收窄为只匹配 《委托评估协议书》； （估价依据清单）
     4. 幂等性测试用合成字符串，三条全溜过 → 新增真实金样幂等性测试
  ✅ 控制者独立验证: 931 段金样全量幂等 0 不收敛，权重总和 25
  当前全量: 109 passed, mypy clean, ruff clean

进度: 11/15 —— 下一步 Task 12 渲染器，然后 Task 13 金样回归（验收判据）

Task 12: complete (commit e4489ab, 8 项测试) — docx 渲染器
  - 代理自行解决附件循环缺失：在 build_templates.py 加 _inject_attachment_loop()，
    先在沙盒验证再动真脚本。不是手工改 docx（那样下次构建就丢）
Task 14: complete (commit a2b3b83, 4 项测试) — 本地网页应用
  ⚠️ 代理发现计划两处实质缺陷：
     1. brief 的 JS 渲染 <input value=...> 却不监听编辑事件 → 用户改的字提交时丢失，
        「复核界面可编辑」按计划做出来只是摆设。代理自行接上回写逻辑。
     2. brief 的 app.py 漏了 /api/render 路由（Interfaces 声明了但示例代码没有）
Task 15: complete (commit d00e4de) — 打包脚本与文档
  ⚠️ Mac 上打不出 .exe（PyInstaller 不支持交叉编译），已在 README 与报告中写明；
     用户须在 Windows 机器上跑一次 uv run python build_exe.py

【待修 P0】copy.yaml 外置承诺在打包后不成立：
  render.py 的 build_context 调 compose(project) 未传 copy_path，
  composer 的默认查找 Path(__file__).with_name('copy.yaml') 在 PyInstaller 冻结包里
  会解析到临时解压目录 _MEIPASS，而非 exe 旁边的外置文件。
  → 设计第5节对用户承诺「改 copy.yaml 不用重新编译」，当前实现兑现不了。
【待验】__main__.py 的包相对 import 在冻结包中未经验证（Mac 无法交叉编译测试）

进度: 14/15 已提交，剩 Task 13 金样回归 + 代理1 的一览表参数化修复

代理1 的一览表参数化修复: complete（见 .superpowers/sdd/task-12-fix-report.md，
本地未纳入 git 版本控制，随 .superpowers/sdd/*-report.md 惯例）
  - 估价结果一览表 + 两张摘要表的数据行改为 docxtpl `{%tr for/endfor %}` 行循环
    （新增 tools/table_loop.py），行数随 subjects 实际长度变化，不再写死金样数字
  - 决定性测试 test_template_has_no_hardcoded_golden_data（伪造数据渲染）验出
    并顺手修复了同一 bug 类的第 4 处泄漏：封面标题地址被 WPS 空书签打断跨 run，
    SUBSTITUTIONS 原来的整份文件 str.replace() 对这一处静默失效——已改为按段落
    边界拼接文本再整体替换（复用 Task 11 已有技法）
  ⚠️ 同批发现但未修（超出授权范围，需要设计确认）：
     1. 「实物状况/建筑规模」说明性文字表格——按类别措辞结构不同（办公
        "，...共计.."/商业"其中...、.."/农用无枚举），需要新条件文案设计
     2. "估价范围"/"依据不足假设"两段的 scale 字段从未接上 {{ scale }} 占位符
        （商业类措辞还多包一层"总建筑面积X平方米（...）"）
     3. "年租赁价值为...元，大写：..."句同时硬编码阿拉伯数字与中文大写金额，
        需要新增人民币大写转换能力（代码库目前没有此工具）
     以上 3 处用 test_known_out_of_scope_golden_leaks（xfail strict）记录追踪
  - 协调者中途批准追加需求：render.py build_context 新增 _fmt() 统一千分位
    格式化（area/unit_price/annual_value/total_area/total_value），Task 13
    金样回归会因此报数字不一致，是已确认的预期格式改进
  当前全量: 123 passed + 1 xfailed，mypy clean（src 与 tools），ruff clean

【P0 已解决】模板写死金样数据 —— 本项目最严重的缺陷
  症状: 一览表与正文叙述句全是金样的死数据。任何项目生成的报告都会印着
        金样那个项目的地址/面积/金额/金额大写。所有测试都通过——因为它们
        全都拿金样自己的项目去渲染再跟金样比。
  ⚠️ 控制者设计的验收判据（金样回归）根本验不出这类 bug。
     唯一有效的是「用伪造数据渲染、断言金样数字必须消失」——这条测试
     本该从一开始就在计划里。
  修复链:
    4cf08c1  三张表格参数化（{%tr for s in subjects %}）+ 封面标题跨 run 断裂
    ddffdcc  正文叙述句 + 新建 src/prose/capital.py 数字转中文大写
             （金额大写是法律上作准的那个，写死意味着每份报告都印金样的金额）
    (本次)   农用/商业措辞不同的最后 4 处
  ✅ 控制者独立验证: 三类伪造数据渲染，零金样残留
  当前全量: 127 passed, mypy clean, ruff clean, 0 xfail

进度: 14/15 —— 只剩 Task 13 金样回归
