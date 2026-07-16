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

Task 13: complete (commit 23f09e5 + 修复 eaf5d79 + 白名单) — 金样回归【验收判据】
  🎯 农用金样 132 段 100% 复现，缺 0 段
  ⚠️ Task 13 在真实数据上暴露了 field_map 的 H3/H4 错位：
     控制者据「整理前的旧素材」建的映射，换文件后从未复核。
     原映射会让报告印出「估价作业期：46139」裸序列号。
     Task 4 的测试只断言坐标字符串、没断言取出的真实值，故一路溜过。
     → eaf5d79 修正 + 补带真实值的断言
  另修：issue_date 缺中文格式化、有效期截止日写死、日期替换未按长串优先
  剩余差异（KNOWN_DEVIATIONS 白名单，均非系统缺陷）：
   - 办公 3 段：用户 Excel(H3=4月7日) 与其金样(6月5日) 自相矛盾，须用户订正素材
   - 办公1+商业3 段：参数化措辞差异，事实无误，句式取舍待用户裁决
  最终: 146 passed, mypy clean, ruff clean, 0 xfail, 0 skip

进度: 15/15 全部完成

═══════════════════════════════════════════════════════
第二轮：比较法引擎与实例库
计划：docs/superpowers/plans/2026-07-16-比较法引擎与实例库.md（6 个任务）
分支：feat/comparison-engine（从 feat/report-generator 起）
基线：146 passed

Pre-flight：
- 用户确认「输入抽象本轮不做」（设计 §5，YAGNI，钉钉立项时一并做）
- 第一等测试 = test_swapping_instance_changes_result，非复现 12 个数字。
  上一轮教训：拿金样自己的数据算当然能复现，验不出「换了输入还算不算得对」。

## 任务进度

Task 1: complete (commit 2fa7538, 11 项测试, 全量 157) — 知识提取器
  ✅ 三类实测吻合: 农用27/办公28/商业28 个因素, 分值(2,1,0,-1,-2), 系数各不相同
  ⚠️ 代理逮到计划的实质 bug 并改对了:
     农用基础表第23行是模板残留幽灵行（无因素名，D~H 残留'好/较好/一般/较差/差'，I=0）。
     计划的跳过条件 `not name and not levels` 会把它误算成第28个因素。
     → 改为 `not name`。控制者与审查者各自独立用单元格转储复核属实。
  🔍 审查者挖出更深证据: 农用比较法表第29行(=23+6) 也是幽灵行（B列=数字0）。
     幽灵行成对出现 → 该修正不只是计数问题，是 read_subject_levels 正确性的前提。
  - Minor 待后续对齐: knowledge.py 的 coefficient 转换未像 comparison.py 的 _as_float
    那样显式排除 bool（bool 是 int 子类）。当前三份素材未触发，属风险敞口。

Task 2: complete (commit 5ea0def, 5 项测试, 全量 162) — 公式声明 YAML + 策略
  ✅ 公式完整显式声明在 knowledge/比较法-市场比较法-2026版.yaml，供估价师核对
     （直接回应用户异议：「估价知识是他们总结出来的函数形式，请完整表达出来」）
  ✅ YAML 含对照基准（12 个数字），算歪即红
  ✅ 权重条目写明不可调的理由，将来想开放的人会先撞见它
  ✅ 控制者独立复核: 策略 vs Excel，三类 12 个数字全部精确复现
  - Minor: brief 的 Interfaces 摘要漏列 MethodSpec.weights 字段（文档疏漏，代码正确）

Task 3: complete (commit ad8b08a, 13 项测试, 全量 175) — 引擎验收【关键一战已过】
  ✅ 12 个金样数字全部精确命中，未放宽容差
  ✅ 第一等测试通过: 换实例A(2.52→5.00) → 评估结果 2.83→3.79，引擎在真算
  ✅ 第二等: 只改市场状况指数 98→110 → 2.83→2.95
  ✅ 控制者独立复核上述三项
  这一条正是上一轮「模板写死金样数据却全绿」的解药——
  假引擎能骗过「复现12个数字」，骗不过「换了输入必须变」。
  - 代理修正一处 mypy 类型收窄（`or 100` 不收窄 openpyxl 宽联合），语义未变

Task 4: complete (commit 507dffa, 13 项测试) — 实例模型与日期精度
  ⚠️ 代理逮到计划的第二个实质 bug：日期正则 [.\-/] 把区间连字符当成日期内分隔符
     '2025.7-2026.7' → 误解析为 date(2025,7,20)（把"2026"头两位当"日"）
     '2025-2026'     → month=20 → ValueError 直接崩，农用导入必炸
     → 收窄为 [./] 修复，断言值未改一字
Task 5: complete (commit c26abbb, 8 项测试, 全量 196) — 实例库存储与批量导入
  ✅ 9 条种子实例全部导入，编号无冲突
  ✅ 控制者独立复核：分类/排序(新→旧)/编号/日期标记 全部正确
     农用两条标「仅年」，一条「仅年月」，原文 '2025-2026' 原样保留
  ✅ 方案丙价值兑现：界面能显示「⚠日期仅年」，用的人立刻知道时间信息靠不住

Task 6: complete (commit 0d2b2a7, 5 项测试, 全量 201) — 界面选实例（全中文）
  ✅ 接口不返回任何推荐/评分字段（测试锁死）
  ✅ 前端 collectSelectedInstances() 在 input/change 上重读 DOM，
     并用「已选 X/3 · 已填指数 Y/X」提示把取值路径真正跑起来——
     不重蹈上一轮「input 渲染了却从不监听、用户改的字直接蒸发」的覆辙
  ⚠️ 代理指出计划缺口且处置正确：brief 的 Interfaces 段列了
     /api/import、/api/library、/api/compute，但 7 个步骤里无测试无代码。
     它只做了步骤写明的 /api/instances，未凭空发明未测接口，并明确标出缺口。

【计划缺口 P0】功能未闭环 —— 控制者独立复核证实：
  引擎 ✅（12数字+换实例会变）、实例库 ✅（9条种子）、界面能列实例 ✅
  但选完实例后无任何接口接住：/api/compute 不存在，评估结果不会重算。
  三个零件都在，没接上。→ 追加 Task 7 闭环。

Task 7: complete (9 项测试, 全量 210) —— 闭环：/api/import、/api/library、/api/compute
  ✅ tools/seed_library.py 种库：data/实例库.json 9 条（幂等，重跑全部跳过不重复）
  ✅ 关键一战：从库里选办公三条原始实例 + 原始市场状况指数(98/95/95)，
     POST /api/compute 精确复现 2.83（比准价格 [2.92,2.77,2.8]，离散度 0.05）
  ✅ 第一等测试 test_swapping_selection_changes_result：换选中的实例A为
     成交价翻倍的替身 → 2.83 → 3.8，与 test_engine_golden.py 同一扰动
     同一数学关系（3.8 = round(2.83 + 2.92/3, 2)）—— 证明真穿透引擎
  ⚠️ 代理发现并修复模型缺口：StoredInstance 原来没存"交易情况指数"
     （引擎公式必需的数字），只存了文字描述"交易情况"（如"正常"）——
     两者在 Excel 里位于不同单元格。补字段，importer 复用
     read_instances() 已读出的值，未重复读表。因库文件此前不存在，
     无历史数据兼容负担。
  ⚠️ 自审揪出：市场状况指数=0 会让引擎除零崩 500——已在 compute.py 外层
     转 400（未改 Task 3 已验收的 market_2026.py）；类别错配主动加固
     （选农用实例进办公项目会 400，非 brief 明文要求）。
  ⚠️ 明确标出范围外：src/web/static/index.html 未接 /api/compute——
     前端选完实例后仍不显示结果，这是浏览器体感上的"未闭环"，
     四件事清单与验证命令均只要求后端，未列入本任务。
  - /api/library 设计取舍：收完整可序列化实例对象（与 /api/import 的
    返回同形状，同一套 to_dict/from_dict），不收编号列表——无状态架构下
    编号列表无处可查。
  - /api/compute 采用重传 xlsx（Form+File）而非计划草稿的 {file_id}，
    延续"输入抽象本轮不做"的既定决定，与 /api/extract、/api/render
    的既有无状态风格一致。
  当前全量: 210 passed, mypy clean（src）, ruff clean

进度: 第二轮 7/7 完成，功能环已闭合（细节与自审见 r2-task-7-report.md）

---

## 第四轮：报告生成台账（分支 feat/ledger）

计划：docs/superpowers/plans/2026-07-16-报告生成台账.md
设计：docs/superpowers/specs/2026-07-16-报告生成台账与知识权威-design.md
起点：main @ ad69562，基线 320 项测试全绿

Pre-flight：
- 原在 main 上开工 → 已建分支 feat/ledger
- 计划自相矛盾：Task 3 的 __init__.py 代码块 import 了 Task 4 才建的 store，
  注记却说只写空的。照代码块写会直接 ImportError → 已修（33bed03）

- [x] Task 1 版本号单一来源            完成（af68234..3714ec0，评审 规格✅/质量通过）
      实施者与评审各自独立逮到同一个计划 bug：Step 1 的测试
      `assert "importlib.metadata" not in source` 是裸文本扫描，与 Step 3 要求
      docstring 解释「为什么不用它」逐字冲突——测试在惩罚文档写得清楚。
      评审多找到一层：这条隐形约束只记在被 gitignore 的报告里，将来 CI 莫名变红
      没人知道为什么。用户定：改查 AST。已修代码 + 修计划配方（8dfab8a）。
      控制者独立复验：两种 import 写法都判红，docstring 提名不误伤。
- [x] Task 2 拆开「取实例」与「算」  完成（06d0406，评审 规格✅/质量通过）
      评审逮到一个我在设计里漏掉的真缺口：compute() 只把「权重」参数化了，
      METHOD_NAME 仍写死。而存权重的理由（日后可调则重放须用当时那组）原样适用于
      方法本身——将来有人加「市场比较法-2027」并改掉默认，重放旧台账会拿新算法算
      旧数据，静默算出另一个数。用户定：加。已改设计 + 计划 + Task 3 的模型与测试
      （3e0f7f4、c5e3b5d），brief 重新生成后才派 Task 3。
- [ ] Task 3 台账数据模型            实施中（base 7c53b7d 之后）
- [ ] Task 4 台账存储
- [ ] Task 5 照台账重算
- [ ] Task 6 生成报告时落台账
- [ ] Task 7 台账界面 + 导入警告
- [ ] Task 8 文档

### Minor findings（留给最终整体评审分诊）

- T1：AST 守卫只拦 `import importlib.metadata` 与 `from importlib import metadata`
  两种直接写法，拦不住「先 import importlib 再属性访问」的间接引用。修复者判断扫
  属性链会误报，未做。控制者认可。
- T2：日志文案 `重算完成` → `算完`（brief 授意）。评审已 grep 确认全仓库无人依赖
  旧文案，非行为变化。
- T2：实施者报告对该文案变化给的理由与代码不符（说是为区分两种日志语境，但实际
  只有一处 logger.info）。报告措辞有误，代码本身没问题。
- T2：`test_both_entry_points_agree` 两侧实例来自同一次 list_by_category，没测顺序
  被打乱时的等价性。既有测试模式的延伸，非本次引入。
