# 房地产估价报告生成系统 — 文档总入口

> **换会话、接手改 bug 的人先看这里。** 本文件是全项目的现状与索引，一页看懂
> 「这是什么、代码在哪、怎么跑、什么绝不能碰、还有什么没做」。
> 细节在各专题文档里，本页只给指路。

- 更新：2026-07-17
- 分支：`main`（干净，440 项测试全绿）——第五轮 + 4 条反馈**已合并**（`feat/asset-condition` 已并入）。
  ⚠️ **交付前（打 tag `v*`）须补做**：真机点一遍第五轮/反馈的 UI + 跑 `/code-review ultra`（合并时用户决定先合、未做）。
- 远端：`git@github.com:Gresham429/evaluate-report-sys.git`（私有）

## 0. 一句话

估价师填表（或导入 Excel 预填）→ 选可比实例 → 系统按市场比较法重算 → 产出符合公司
格式的 Word 估价报告，并给每次生成留一条**可复现的台账**。单机运行，不联外网，
数据全程留在本机。支持**农用 / 办公 / 商业**三类。

## 1. 现状：五轮 + 一轮打磨，都在 main

| 轮次 | 做了什么 | 关键文档 |
|---|---|---|
| 一 | Excel → docx 报告 | [design](superpowers/specs/2026-07-15-房地产估价报告生成系统-design.md) |
| 二 | 比较法引擎 + 实例库 + 选实例界面 | [design](superpowers/specs/2026-07-16-比较法引擎与实例库-design.md) |
| 三 | 表单输入 + 基础表版本管理（出报告可全程不开 Excel） | [决策记录](superpowers/specs/2026-07-16-表单输入与基础表版本管理-决策记录.md) |
| 四 | 报告生成台账（存快照、照台账重算） | [design](superpowers/specs/2026-07-16-报告生成台账与知识权威-design.md) |
| 打磨 | 交付 exe（GitHub Actions）、台账分组、草稿/表单折叠、若干实测 bug | §6 + v1.0.2 |
| **五** | **估价对象资产状况**：逐因素手写描述贯通表单→报告三张表→台账 | [design](superpowers/specs/2026-07-16-估价对象资产状况-design.md) / [plan](superpowers/plans/2026-07-16-估价对象资产状况.md) |
| **反馈** | **权重可调**（和=1、分数输入）、**单份偏离**（系数按报告可调）、**实例数据可视化** | §6 末 + `.superpowers/sdd/overnight-followups.md` |

**端到端已验证**（真浏览器 + Windows exe 冒烟，**限前四轮**）：导入基础表 → 出报告 → 选实例重算 →
应用 → 生成 docx → 台账「照此重算」复现出同一个数。三类金样精确复现。

> ⚠️ **第五轮 + 反馈的 UI 尚未真机点过**（合并时是静态+API+Playwright 部分核验）。已在 main，但
> **交付前（打 tag `v*`）必须真人点一遍**——§5 的 UI 坑单元测试拦不住。逐因素描述 / 系数框+范围软提示 /
> 权重框（分数、和≠1 挡生成）/ 选实例展开看实例档次，都要点到。

## 2. 铁律：改任何东西之前必须知道，碰了就是回归

这些是几轮讨论 + 评审沉淀下来的**不可违反的约束**。每一条都有测试或决策记录背书。

1. **金样精确复现**（[ADR-001](decisions/2026-07-15-比较法算术移入-Python.md)）：三份真 Excel 的 12 个数字算歪即红。
   办公 2.83、农用 1399.26、商业 3.32。`tests/test_engine_golden.py` 锁死。
2. **知识在 Excel，算术在 Python**：基础表（28 因素/档次/系数/分值标尺）是估价知识，
   系统只读不改；比较法的三行算术由系统执行。改**基础表版本**的系数 = 改 Excel 重导，不是改代码。
   **例外（第五轮反馈，已上线）**：单份报告可临时改系数 = **单份偏离**——不改基础表版本、不动指纹，
   存成「基线版本 + 偏离」进台账（`BaseTableUse.偏离` + 改后的 `实际知识`），replay 用实际知识复现。
   自由改、不卡审批（用户选 A）。见 §5 坑 1 与 `_apply_ledger_coefficient_overrides`。
3. **运行时零 AI**：同一输入永远同一输出，可复现可审计。渲染、算术全程无模型调用。
4. **台账只增不改**：`LedgerStore` 没有 remove/save/update。能被改写的记录不构成依据。
5. **快照自洽**：一条台账离开实例库/基础表库能独立重算（`replay` 用内嵌快照，不回库）。
6. **存当时那份，不存今天的默认**：台账存了当时的基础表知识 / 方法 / 权重，重放用它们，
   不用今天的默认。**这条栽过两跤**（方法字段先没进模型、后进了没被用），见 §5 的坑。
7. **不替他填，但替他核**：系统不拼凑字段、不给默认值、不做可比性推荐、不推算市场状况
   指数；但会替他核对（规模 vs 一览表面积、离散度阈值等）。校验只提示不阻断。
8. **保留事实，判断交给人**：日期只知年月就标「仅年月」不假造；旧基础表版本永不覆盖；
   重算结果预填单价但可改（取整是估价师的判断）。
9. **数据全程留本机**：不联外网。冻结路径见 `src/paths.py`——用户数据挂 exe 旁边，不是
   `Path(__file__)`（onefile 解压目录退出即删）。

## 3. 代码地图

```
src/
├── paths.py            冻结/非冻结的路径解析，唯一判断 sys.frozen 处
├── version.py          程序版本单一来源（台账记它；CI 校验 tag 一致）
├── model.py            Project / Subject / Category
├── extractor/          读 Excel：实勘表字段、比较法表、一览表
│   └── condition.py    ★五★ 读实勘表逐因素〔组,因素,描述〕（资产状况 + 因素分组）
├── engine/             比较法引擎
│   ├── inputs.py       ComparisonInput：引擎的输入契约（引擎不认识 Excel）
│   ├── compute.py      compute() 纯算（收权重）/ compute_from_selection(weights=) / apply_coefficient_overrides()
│   ├── knowledge.py    从基础表提取 Knowledge（28 因素）；Factor 带 group(分组) + 调整范围(J列)，均不进指纹
│   ├── adapter.py      读估价对象档次、实例
│   └── methods/        市场比较法-2026（策略 + YAML 声明）
├── knowledge_base/     基础表版本库：指纹当版本号，旧版永不覆盖
├── library/            实例库：存、列、批量导入
├── drafts/             草稿：边填边存、一条一文件、原子写
├── ledger/             ★第四轮★ 报告生成台账
│   ├── model.py        LedgerEntry 快照（基础表知识/实例/方法/权重/结果 + ★五★资产状况 + 偏离整份存）
│   ├── store.py        只增不改
│   └── replay.py       照台账重算（不碰库；用 entry.实际知识 + 权重，故权重/系数偏离自动复现）
├── validator/          校验：只提示不阻断（含 ★五★ 资产状况描述留空提示）
├── prose/              文案库 copy.yaml + 组句 + 大写金额
├── renderer/           docx 渲染（docxtpl）；★五★ 资产状况三张表数据驱动，见 tools/condition_tables.py
└── web/
    ├── app.py          FastAPI，全部接口
    └── static/index.html  单文件前端：四页签（出报告/实例库/基础表/台账）
```

`data/`（运行期，已 gitignore；`实例库.json` 是显式跟踪的种子）：
`实例库.json`、`基础表/`（各版 + 台账.json）、`草稿/`、`生成台账/`。

## 4. 怎么跑 / 测 / 打包

```bash
uv sync
uv run python -m src          # 起本地服务，自动开浏览器 http://127.0.0.1:8765
uv run pytest                 # 440 项
uv run mypy src/              # 干净
uv run ruff check .           # 干净
```

**改代码的规矩**（[coding-style](file:///Users/gresham/.claude/rules/coding-style.md)）：TDD、中文注释讲「为什么」、
全类型标注、不裸 except、logger 不用 print。前端是单文件原生 JS（内网 exe，不引外部资源），
改 `index.html` 后**必须自己起服务用浏览器实测**——单元测试测不到 UI（§5 的坑都出在这）。

**Windows exe**：打 tag `v*` → GitHub Actions 出交付 zip（含冒烟测试）。
PyInstaller 不支持交叉编译，只有 windows runner 能出 .exe。见根 README「打包」节。

## 5. 这个项目最容易栽的坑（改 bug 前必读）

1. **台账要存「当时那份」，replay 要用「存的那份」**：台账存了当时的方法/权重/系数，但若
   `replay` 或 `_build_ledger_entry` 用今天的默认（`METHOD_NAME`/`default_weights()`/基线系数），
   字段就白存了。**第五轮反馈两处碰这条、都已按此模式做+配了专门防坑测试**：
   ① 权重可调——`_build_ledger_entry` 存实际权重（不是 `default_weights()`）、`replay` 用 `entry.权重`；
   ② 单份系数偏离——存改后的 `实际知识`、`replay` 用 `entry.基础表.实际知识`；`实际指纹==基线版本`（不另立版本）。
   两条 pitfall 测试在 `tests/test_ledger_replay.py`（改后值 vs 默认值，round-trip 后 replay 复现改后值）。
2. **UI 状态切换后没刷新**：新建/续填/导入切换表单时，顶部草稿列表、「编辑中」标记
   要跟着走。修复统一放在 `openForm()` 末尾 `loadDraftList()`。这类 bug 单元测试拦不住，
   **只有真人乱点或浏览器实测能逼出来**——四轮评审都漏过。
3. **测试写脏真实 data/**：`tests/conftest.py` 的 autouse 夹具把四个存储目录
   （实例库/草稿/基础表/台账）重定向到 tmp_path。**新增用到某存储的 web 测试，确认它被
   兜住**，否则会往真实 data/ 落文件且全绿无人发现。
4. **中文不能做 HTTP 路径参数**：starlette 的 PARAM_REGEX 只认 ASCII，`{记录号}` 永远 404。
   用 `{record_id}`（函数体内再赋给中文变量）。
5. **基础表系数是公式**：I 列指向比较法表 X 列。openpyxl 存盘丢公式缓存值，改系数测试要
   先 `data_only=True` 压平再改，否则 28 系数全塌成 0、测试因无关原因变绿。
6. **冻结路径**：exe 里 `Path(__file__)` 指向退出即删的临时目录。所有用户数据/外置文件走
   `src/paths.py`。`tests/test_paths.py` 假装冻结盯死这条线。
7. **交付 zip 里别放中文文件名**：中文名会被第三方解压软件（WinRAR/360/好压/2345）按
   GBK 解成乱码（`农用.docx`→`鍐滅敤.docx`），render() 便找不到模板、一份报告也出不来
   （v1.0.1 实测）。凡随包发出、要被机器按名字找的标识一律 ASCII（同 Release 资产名、
   HTTP 路径参数那两跤）。模板名与「类别值」解耦见 `render.TEMPLATE_FILENAMES`——类别值
   本身仍是中文，遍布 JSON/台账快照，**不能动**。`tests/test_delivery_ascii.py` 守住这条。
8. **冒烟别只测暂存目录**：`smoke_exe.py` 从前只跑 `dist/_package/`（文件复制，名字完好），
   从没跑过用户真解压的 zip——中文名乱码正好在这个盲区里溜过。workflow 已加「解压交付
   zip 再冒烟」一步，验的是用户真正拿到的形态。
9. **隐藏终端后 stdout 变 None**：`--noconsole` 打包后 PyInstaller 把 `sys.stdout/stderr`
   置 None，logging/uvicorn 的 StreamHandler 会炸、程序默默起不来。`__main__._setup_logging`
   在 uvicorn 启动前把标准流接到 exe 旁的 `运行日志.log`，`tests/test_logging_setup.py` 盯着。
10. **金样测试只查「缺失」、不查「多余」**（第五轮 opus 复核逮到）：`test_golden.py` 断言
    金样每段都出现，但**不拦渲染多出来的内容**——所以资产状况表若混进金样没有的行，43/43 仍绿。
    第五轮据此修过一条名为「0」的 office 垃圾行混进农用报告。改渲染/因素集时，光看金样绿不够，
    要真看报告有没有多东西。（① 因素集用户已定**全渲染**所有真实因素，见 §7。）
11. **实勘表有模板残留行**：`read_survey_conditions` 会读到名为「0」这类非真实因素的残留行
    （描述还可能是别类的样板文字）。`condition.py` 按「因素名不含 CJK 即跳过」滤掉，
    `tests/test_extractor_condition.py` 钉死农用不再出「0」行。

## 6. 打磨轮的实测 bug（都已修，记此备查）

按用户真机试用逐个逼出来的，全是 UI/交付类、单元测试拦不住的：

- 交付 exe 数据每次关闭清零 + copy.yaml 没打进包（冻结路径，`src/paths.py` 收口）
- Release 资产名中文被 GitHub 删空 → 改 ASCII
- 新建表单后草稿列表不刷新、续填后「编辑中」标记不跟随（`openForm` 收口）
- 草稿列表/表单各段可折叠、草稿列表加滚动
- **（v1.0.2）Windows 交付三连**——都是「本地/CI 全绿、用户机上炸」的交付类：
  - 双击 exe 弹出黑终端 → `build_exe.py` 加 `--noconsole`（仅 Windows）
  - 终端里中文乱码 → 隐藏终端即消失；隐藏后 stdout=None，日志改落 exe 旁 `运行日志.log`
  - 中文模板名被第三方解压软件解成乱码 → 找不到模板、出不了报告：模板名改 ASCII
    （`farmland/office/commercial.docx`），交付名（exe/内层目录）一并 ASCII 化；
    补「解压交付 zip 再冒烟」堵住冒烟盲区。见 §5 的坑 7/8/9。

**（第五轮 + 反馈，已合并 main）**——逐个决策由用户拍板：
- **资产状况**：报告（三）三张表从「死金样文字」改成逐因素数据驱动，出实勘表手写描述；
  因素分组从实勘表 A 列读、不硬编码；三张表用 docxtpl `{%tr%}` 行循环（`tools/condition_tables.py`），
  组标签列 vMerge 用 `{% if loop.first %}restart{% else %}continue{% endif %}`（避开 TOC 书签重复）。
- **权重可调**：写死 ⅓ → 可调、和必=1（≠1 挡生成）、支持分数输入「1/3」。坑见 §5-1。
- **单份偏离**：系数按报告可调、Excel J 列「调整范围」当**软提示**（超范围只提醒不拦，因基线系数
  本身有的就在范围外）、默认=基线值、记「理由」留痕、自由改不卡审批。坑见 §5-1 与 §2-2。
- **实例数据可视化**：选实例时每条实例可点击展开详情 + 因素档次（`/api/instances` 加返回 `因素档次`）。
- 全套 440 绿、金样 12 数字全程未动、每任务独立复核（算术红线用对抗式复核）。

## 7. 未决清单（下一步的候选，均未做）

| 事项 | 状态 | 出处 |
|---|---|---|
| **单份偏离**（某报告调某系数、只对该份生效） | ✅ **已做**（第五轮反馈，**自由改不卡审批**——用户选 A；将来要审批再叠 `审批单号` 字段） | §6 末 |
| **权重可调** | ✅ **已做**（和=1、分数输入；台账坑已闭） | §6 末 |
| **报告编号可领取（全公司递增）** | ⏸ **阻塞于钉钉**——全公司唯一序列须中心协调，单机做不了；等 C | 反馈 ④ |
| **C：钉钉审批与同步** | 不碰，须贵司合规先行（报告编号、单份偏离审批都挂在它后面） | 台账 design §6 |
| **实例推荐算法** | 用户提到「后续要做」——选实例详情区已留扩展性 | 反馈 ⑤ |
| **B：知识资产统一维护**（基础表/实例/模板成为公司的，不因离职丢失） | 方向已定，未做 | [台账 design §5](superpowers/specs/2026-07-16-报告生成台账与知识权威-design.md) |
| 报告里写明用了哪三条实例 | 牵涉执业规范，须执业估价师定夺 | 决策记录 §8.5 |
| 台账列表加「基础表版本」列 | 数据没丢（详情有），是否加由用户定 | 整体评审 Minor |

## 8. 谁能拍板什么

用户是建设方，**不是执业估价师**（见 memory `user-not-the-appraiser`）：
- **产品/技术决策**问用户（形态、工作流、性能、依赖）——他判断得准。
- **估价执业准则**不能问用户确认（可比性维度、市场状况指数、法定文书用语）——
  他无从验证，须明说「这需要执业估价师确认」，隔离成可配置/人工输入，不编码进系统。

## 9. 专题文档索引

- **决策为什么**：[`decisions/`](decisions/)（ADR-001 算术移入 Python）
- **各轮设计**：[`superpowers/specs/`](superpowers/specs/)
- **各轮实施计划 + 进度**：[`superpowers/plans/`](superpowers/plans/)
- **过程账本**（逐任务评审逮到什么、怎么修）：`.superpowers/sdd/progress.md`
- **第五轮反馈的逐条决策**（① 因素集全渲染 / #1 权重 / #2 系数偏离=A 自由改 / ④ 编号阻塞钉钉 / ⑤ 实例档次）：
  `.superpowers/sdd/overnight-followups.md`
- **给估价师的使用说明**：[`使用说明.md`](使用说明.md)
- **开发/打包**：根目录 [`README.md`](../README.md)
