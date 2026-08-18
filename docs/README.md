# 房地产估价报告生成系统 — 文档总入口

> **换会话、接手改 bug 的人先看这里。** 本文件是全项目的现状与索引，一页看懂
> 「这是什么、代码在哪、怎么跑、什么绝不能碰、还有什么没做」。
> 细节在各专题文档里，本页只给指路。

- 更新：**2026-08-15**（最新现状看 **§1d**，它覆盖下面这几条历史概述）
- 分支：`main`（干净，**782 项 pytest 全绿** + 小程序 harness 136 绿 + mypy/ruff 干净）。
  已交付 **v1.1.3**（GitHub Releases）：办公端 exe + 客户版《使用说明.docx》，开箱内置七类基础表 + 12 实例。
  钉钉同步（多维表承载层）+ 双向同步 + 选共有人 + 硬门禁均已并 main；broker/小程序/多维表**均已真机上线**。
- 历史脉络（细节各专题文档）：第五轮 + 反馈、第六轮（4 新类别 + 协议书 + 下载点选）、钉钉同步（Ledger/BaseTable/Instance
  三个可插拔 Store 后端 + 客户端 + 领号 + 离线待同步/联网对账/统一发号）、审核定稿四态、扫码登录、双向同步、ACL 共有人。
  ⚠️ **交付前（打新 tag `v*`）仍须**：真机点一遍全流程 UI + `/code-review ultra` + 新四类真实案例重锁金样 + 估价师终审（见 §1d「仍待」+ §7）。
- 远端：`git@github.com:Gresham429/evaluate-report-sys.git`（私有）

## 0. 一句话

估价师填表（或导入 Excel 预填）→ 选可比实例 → 系统按市场比较法重算 → 产出符合公司
格式的 Word 估价报告 **+ 委托评估协议书**（出报告页点选下载哪份），并给每次生成留一条
**可复现的台账**。单机运行，不联外网，数据全程留在本机。

支持**七类**：农用 / 办公 / 商业（**报告正文金样锁死**）+ 住宅 / 工业 / 停车场用地 /
建设用地（**第六轮新增**）。新四类走 Approach A：**只锁算术金样**（比较法重算=Excel），
报告正文为**结构渲染**、页脚标「须执业估价师终审」，**交付前须真人估价师终审用词**、
并用真实案例重锁金样（现锁的是对方给的构造样例）。房产 shape（住宅/工业）与土地 shape
（停车场/建设用地）各复用一份通用模板。

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
| **六** | **4 新类别**（住宅/工业/停车场用地/建设用地）+ **委托评估协议书** + 出报告页**下载点选** | [design](superpowers/specs/2026-07-17-新类别与双报告-design.md) / [plan](superpowers/plans/2026-07-17-新类别与双报告.md) |

**端到端已验证**（真浏览器 + Windows exe 冒烟，**限前四轮**）：导入基础表 → 出报告 → 选实例重算 →
应用 → 生成 docx → 台账「照此重算」复现出同一个数。三类金样精确复现。

> ⚠️ **第五轮 + 反馈的 UI 尚未真机点过**（合并时是静态+API+Playwright 部分核验）。已在 main，但
> **交付前（打 tag `v*`）必须真人点一遍**——§5 的 UI 坑单元测试拦不住。逐因素描述 / 系数框+范围软提示 /
> 权重框（分数、和≠1 挡生成）/ 选实例展开看实例档次，都要点到。

## 1b. 进行中：钉钉全公司同步（承载层=**钉钉多维表**，宜搭因专业版弃用）

方向：把知识（基础表/实例/模板）、台账、成品报告都汇到公司钉钉，报告编号全公司统一；钉钉为权威、
本地拉取缓存、改动回写。断网仍能读缓存、出草稿；**出正式报告需联网领号**。设计与决策见
[钉钉同步 design](superpowers/specs/2026-07-17-钉钉全公司同步-design.md)、[宜搭数据模型 design](superpowers/specs/2026-07-17-宜搭数据模型与权限.md)。

**已做（本地地基，均已并 main）**——4 个 Store 里 3 个抽出「可插拔后端」（协议 + 本地后端**行为字节不变** +
内存后端**当宜搭适配器的可执行契约** + 契约测试）：

| Store | 后端模块 | 缝口 |
|---|---|---|
| 台账 LedgerStore | `src/ledger/backend.py` | append 一条 / 读全部（append-only） |
| 基础表 BaseTableStore | `src/knowledge_base/backend.py` | 版本内容不可变 + 台账只追加 |
| 实例库 InstanceStore | `src/library/backend.py` | 整库 load / save |

DraftStore **不做**（草稿是个人临时件、不上云）。

**承载层改定＝钉钉多维表（2026-07-18）**：宜搭 OpenAPI 卡专业版（5988/年起）、公司未订；改用**钉钉多维表**
（2024.04 起基础用量免费、扩容仅 198/人/年，单表约 2 万行），同一企业内部应用鉴权、**读/写实测 200**。设计见
[多维表承载层 design](superpowers/specs/2026-07-18-多维表承载层-design.md) / plan `superpowers/plans/2026-07-18-多维表承载层.md`。

**已实现（工作区，待提交评审）**——三个后端各出一个"打多维表"的实现 + 共享客户端 + env 切换 + 领号：
`src/dingtalk/{notable,config,factory,report_number}.py`、`src/{ledger,knowledge_base,library}/notable_backend.py`。
单测 28 个（`tests/test_notable_*.py`/`test_backend_factory.py`/`test_report_number.py`），**全套 525 项全绿**、mypy/ruff 干净。
**三个后端 + 领号全部真机验通**（`tools/notable_provision.py` 自建实例库/基础表两表 + 台账加 autoNumber『报告序号』字段，跑通
实例 save→load、基础表 write→read、领号=`正恒评报字[2026]第1号`；台账 append→iter 见 `notable_backend_smoke.py`）。三表 sheetId
（台账 hERWDMS / 实例库 SjxzHcU / 基础表 XHRMxps）+ base/operator 存 gitignored `.env`。
切换：env `承载后端=多维表`；**默认不设=走本地、行为一字不变**（工厂 `src/dingtalk/factory.py` 选后端，Store `__init__` 懒加载避免循环导入）。

**已实现并并入 main（544 绿、mypy/ruff 干净）**：**接 app 启动 + 离线待同步/联网对账 + 统一发号**（见
[离线待同步 design](superpowers/specs/2026-07-18-离线待同步与联网对账-design.md) + [plan](superpowers/plans/2026-07-18-离线待同步与联网对账.md)）——
app 启动 load `.env`；`GET /api/online` 三态（本地／多维表在线／离线）；在线出报告由后端向多维表 autoNumber **统一领号**、注入 report_no、
离线则存「待同步」草稿、联网逐条 [同步定稿]／[删除]。**报告编号仍显式存进台账快照、replay 不读它**，快照自洽(#5)不受影响；
整套改动 gate 在 `承载后端=多维表`，**本地模式（默认／交付 exe 无 .env）行为一字不变**。⚠️ 前端单文件改动的真机六项（§5 坑 2/4）
+ `/code-review ultra` **在交付（tag `v*`）前必做**——已在 main，同五/六轮尚未真机点。

**仍待**（各自后续小步，均非承载层核心）：**钉钉登录鉴权 + 按人裁剪缓存**（§7b，须先设计）；
成品 **docx 归档到钉盘**（§3⑥，须钉盘 scope）。

**采集前端：[智能实勘问卷](superpowers/specs/2026-07-19-智能实勘问卷-design.md)**（2026-07-19 设计定案）——
估价师现场手机填（地图预填地理因素事实 + 逐因素校验 + 拍照）→ 提交进钉钉多维表 → 办公端拉「已提交」预填表单 →
**估价师选实例** → 出报告。**平台=钉钉小程序前端 + serverless(阿里云函数计算)broker + 多维表，不维护常驻服务器**（原宜搭版
`2026-07-18-实勘问卷-design.md` 因专业版收费作废、平台被此设计取代）。**分两期**：一期=办公端拉取适配器（现可做可测、不依赖小程序），
二期=小程序 + serverless（须你注册钉钉小程序 / 开阿里云 / 办高德 Key）。采集**实勘表**、不碰基础表；算术留 Python。
**一期办公侧已落地**：`src/questionnaire/`（问卷模型 + 办公预填映射 + 校验抽取 + 多维表读取后端 + 表结构 provision），
可用假「已提交」记录端到端测；二期（钉钉小程序 + serverless + 地图预填）待账号就位。

**#3 审核定稿流程 + 权限「只看自己」+ 批量审核**（[design + 进度](superpowers/specs/2026-07-21-审核定稿+办公端钉钉登录+权限-design.md)）——
四态生命周期：草稿 → 已提交 →（办公端**发起审核**，可批量）→ 待审核 →（**审核通过**，可批量）→ **已定稿（终态·锁定）**。
权限「只看自己」：办公端按登录 userid 过滤（登录 UI 未上前用 `.env NOTABLE_OPERATOR_ID` 过渡取值）；已定稿=小程序整份只读、
**broker 服务端也拒写**（防离线补传把已定稿退回草稿）。**步骤 2–5 已实现全绿**（681 项 + 小程序 harness 103 + 办公端浏览器实测）；
**步骤 6 办公端钉钉扫码登录**用户定「先真机验这批再做」，仍待。交付前须真机点审核全流程 + broker 重部署（含 store.py 锁定）+ 小程序重传。

## 1c. 2026-08 本轮：审核定稿 / 权限 / 扫码登录 / 双向同步（现状 + 待办）

承 §1b 智能实勘问卷，本轮补齐「问卷进来之后」的流程。**权威设计＝统一 spec**：
[`2026-08-13-统一owner-可见性-合并-设计`](superpowers/specs/2026-08-13-统一owner-可见性-合并-设计.md)
（owner/可见性/合并的唯一真相；其它 spec 与它冲突处以它为准）。

**已实现并提交（main 本地未 push、全绿 713 pytest + 小程序 harness 103）：**
- **审核定稿 + 批量**：草稿→已提交→(发起审核)→待审核→(审核通过)→已定稿(终态·锁定)；办公端「审核」页签；
  broker 服务端拒写锁定态。[spec](superpowers/specs/2026-07-21-审核定稿+办公端钉钉登录+权限-design.md)
- **权限（共有人 ACL + 三判定）**：问卷加「共有人」列；**可见=owner/上级/管理员、发起审核=owner、定稿=上级/管理员**；
  `permissions.py`(Viewer) + `session.viewer()` + 后端逐份判 + 端点。[ACL spec](superpowers/specs/2026-08-13-问卷共有人ACL+上级可见-design.md)
- **办公端钉钉扫码登录**（**真机验通**）：纯本机 OAuth2（`127.0.0.1/auth/callback` 已在钉钉后台存上）；
  `src/dingtalk/oauth.py`（登录得 unionId → `getbyunionid` 换 userid，与填报人同源）+ `/auth/*` + 顶栏登录态。
  [spec](superpowers/specs/2026-08-13-办公端钉钉扫码登录-design.md)
- **时区**：办公端时间戳按浏览器本地时区显示（修 UTC 早 8 小时）。

**待办（按依赖/优先排）：**
1. ~~**拉取重复草稿去重**（办公端小改、不依赖部署）：草稿存 `survey_id`、拉取幂等（同一问卷回同一份草稿）~~
   ✅ **已做**（2026-08-14，721 绿 + Playwright 冒烟；本地未 push）：草稿加 `问卷ID`、`DraftStore.find_by_survey`、
   `/api/survey/pull` 回 `existing_draft_id`、前端命中则续填不新建。见 [plan](superpowers/plans/2026-08-14-拉取草稿去重.md)。
   交付前真机：对真实多维表点「拉同一问卷两次=续上同一份」。
2. ~~**小程序「选共有人」UI**~~ ✅ **已做**（2026-08-14）：小程序选人存 owners + saveDraft 带 owners；
   broker `save_draft` owners **并集**（谁都不丢）+ `load` 回 owners（harness 129 通过）。✅ 选人 API 真机验通（2026-08-15，选人→进列表）、broker 已重部署 + 小程序已重传；owners 并集/办公端可见待真机点。[plan](superpowers/plans/2026-08-14-小程序选共有人.md)
3. **双向同步：回写 + 字段级 3-way 合并 + 冲突弹窗** — **Phase 1 办公端✅已做**（2026-08-14，本地未 push）：
   `merge_content`（两侧镜像+契约对拍）、`/api/survey/writeback`、办公端「保存回问卷」+冲突弹窗（Playwright 冒烟通过）。
   **Phase 2✅代码全就绪**（2026-08-14）：broker `save_draft` 合并+`SurveyConflict`；小程序 `sync.js` 带 base+冲突处理+`resolveConflict`、`form.js` 捕获 base、新增 `pages/conflict/`（harness 121 通过）。**仍待：broker 重部署（若尚未）+ 小程序重传 + 真机联调**。
   见 [plan](superpowers/plans/2026-08-14-双向同步.md) + [sync spec](superpowers/specs/2026-08-12-问卷报告双向同步-design.md)。
4. ~~**组织架构上级**~~ ✅ **已做**（2026-08-14，本地未 push）：`src/dingtalk/org.py`（下属集纯算法 + 三端点封装 + TTL 缓存 + **fail-closed**）接进 `session.viewer()`，`config.use_org()` 开关**默认关**（= P1，行为不变）。真机校准三个 topapi 端点后设 `组织架构上级=on` 启用「上级可见/可定稿」。[plan](superpowers/plans/2026-08-14-组织架构上级.md)
5. **实勘编号 自动领号**：⛔ **留空待甲方定机制**。[留空 spec](superpowers/specs/2026-08-14-实勘编号自动领号-留空待甲方.md)
6. **交付前**：broker 重部署（含 store.py 锁定 + listSurveys + owners）+ 小程序重传 + 真机点审核全流程/登录/只看自己 + `/code-review ultra`。

**⚠ 部署现状**：（此条 2026-08-14 旧述，已被 §1d 取代——broker/小程序/多维表均已上线。）

## 1d. 2026-08-15 交付 + 真机 + 门禁（**最新现状，接手先看这段**）

上一轮四特性全部**真机部署上线**并按用户反馈修完一批 bug，出了正式交付。**本段是当前真相，覆盖 §1c 里的「部署现状」。**

**已上线（真机在跑）：**
- **broker**（阿里云 FC）已重部署：含 3-way 合并 + owners 并集 + `list_for_user`(入口按共有人) + 兜底 catch(未预期异常回干净 500)。
- **小程序**已重传：冲突页 `pages/conflict/` + 选共有人 + 时区(北京 +08:00) + 删除竞态修 + 带 base。
- **多维表**：`实勘问卷`表补上了缺失的**「共有人」列**（`provision.py` 建表清单漏了它、真机 saveDraft 全 500，已补 + 加防漂移测试 + 直接给表补列）。

**真机修的 4 个 bug**（[plan](superpowers/plans/2026-08-14-交付初稿清理.md) 附近几篇）：时区、删除竞态、入口列表按共有人、
**提交失败**(根因=多维表缺共有人列)。途中真机校准了 `NotableClient.delete_record` 端点 = `POST .../records/delete`（原 `DELETE .../records` 报 404）。

**交付发版**：`v1.1.1 → v1.1.2 → v1.1.3`（**最新给这个**，GitHub Releases 页）。v1.1.3 亮点：
- **开箱即用**：七类基础表 + 12 条起步实例**打进 exe**（`resources/默认基础表`、`resources/默认实例库.json` +
  `--add-data`），首次运行 `seed_*_if_empty` 解出到本地——中文名文件由程序本机生成、不经解压软件、绝无 §坑7 乱码。
  见 memory [[交付数据内置exe播种]]。
- **客户版《使用说明.docx》**（`tools/build_manual_docx.py` 生成，纯钉钉版，随包发）。

**办公端联钉钉部署配置**（交付 exe 默认本地模式，须配置才连多维表）：
- `_load_dotenv()` 从 `app_dir()`（冻结=exe 目录）读 `.env` → **把配好的 `.env` 放 exe 旁即联多维表**。
- 模板 `deploy/office.env.example`（随包发，非敏感）；填好的 `dist/office部署.env`（gitignored，含 app secret，内部分发、勿进 git/Release）。
- **硬门禁**（钉钉模式）：必须扫码登录 + 授权名单 `OFFICE_ALLOWED_USERS`（空=任何登录者；填=白名单）才能用，
  未授权见全屏遮罩 + 数据接口 403（`src/web/app.py` 中间件 + `session.is_authorized`）。本地单机模式不启用。
  见 [plan](superpowers/plans/2026-08-15-办公端硬门禁.md) + [部署与真机验证指南](superpowers/2026-08-14-部署与真机验证指南.md)。

**当前生产多维表数据**：实勘问卷少量测试记录（曾清空）；实例库 `SjxzHcU` = 12 条干净实例（农用/办公/商业/住宅 各 3）；基础表 `XHRMxps` = 七类各一版。

**仍待**：① 双向同步真机联调（并发合并/同字段冲突两端）；② org 上级真机校准三 topapi 端点后 `组织架构上级=on`；
③ 实勘编号自动领号（待甲方定机制）；④ 新四类真实案例重锁金样 + 执业估价师终审；⑤ 交付前 `/code-review ultra`。

**测试基线**：全套 pytest **782 绿**、小程序 harness **136 绿**、mypy/ruff 干净。仓库 `main` 已推 GitHub（tag 到 `v1.1.3`）；
本地可能领先几个提交（含硬门禁）待 push——`git rev-list --count origin/main..main` 查。

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
   **钉钉方向将改写此条**（见 §1b）：改成「数据留在**公司受控的钉钉** + 本地缓存」——企业自有、非第三方外泄，
   属合规决策。运行时零 AI(#3)、台账只增不改(#4)、快照自洽(#5)、旧版不覆盖(#8) 全保留、还帮上同步的忙。

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
│   ├── store.py        版本管理（指纹校验/旧版不覆盖/缺失补回）
│   └── backend.py      ★钉钉★ 可插拔后端：版本不可变 + 台账只追加（本地/内存，宜搭适配器待接）
├── library/            实例库：存、列、批量导入
│   ├── store.py        内存态 + 去重 + 按类别列
│   └── backend.py      ★钉钉★ 可插拔后端：整库 load/save（本地/内存，宜搭适配器待接）
├── drafts/             草稿：边填边存、一条一文件、原子写（★钉钉★ 不上云，无后端抽象）
├── ledger/             ★第四轮★ 报告生成台账
│   ├── model.py        LedgerEntry 快照（基础表知识/实例/方法/权重/结果 + ★五★资产状况 + 偏离整份存）
│   ├── store.py        只增不改；持久化委托后端
│   ├── backend.py      ★钉钉★ 可插拔后端：append 一条/读全部（本地/内存，宜搭适配器待接）
│   └── replay.py       照台账重算（不碰库；用 entry.实际知识 + 权重，故权重/系数偏离自动复现）
├── validator/          校验：只提示不阻断（含 ★五★ 资产状况描述留空提示）
├── prose/              文案库 copy.yaml + 组句 + 大写金额
├── renderer/           docx 渲染（docxtpl）
│   ├── render.py       估价报告；★六★ 新四类映射两 shape 模板 lease_building/land.docx
│   └── agreement.py    ★六★ 委托评估协议书（四类通用，收费手填、大写用 prose.capital，不进台账）
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
uv run pytest                 # 497 项
uv run mypy src/              # 干净
uv run ruff check .           # 干净
```

**钉钉/宜搭对接冒烟**（需付费组织凭据，见 [宜搭对接配置](宜搭对接配置.md)）：
```bash
# 把 5 个值填进仓库根 .env（已 gitignore），然后：
uv run python tools/yida_smoke.py   # 取 token → 拉表结构 → 写一行 → 读回
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
| **第六轮：4 新类别（住宅/工业/停车场用地/建设用地）+ 委托评估协议书 + 下载点选** | ✅ **已做**（Approach A：只锁算术金样，正文结构渲染） | [design](superpowers/specs/2026-07-17-新类别与双报告-design.md) / [plan](superpowers/plans/2026-07-17-新类别与双报告.md) |
| **新四类用真实案例重锁算术金样** | ⏳ **待对方给真实案例**（现锁的是构造样例，面积/日期指数等疑似占位） | 第六轮 |
| **新四类执业复核**：交易日期修正方向（L8/M8）、X37 离散度口径（少 -1）、报告正文用词 | ⏳ **须执业估价师终审**（§8；两处模板差异见 `adapter._normalize_market`、`test_engine_golden_new`） | 第六轮 |
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
- **钉钉全公司同步**：[总设计](superpowers/specs/2026-07-17-钉钉全公司同步-design.md) /
  [宜搭数据模型与权限](superpowers/specs/2026-07-17-宜搭数据模型与权限.md) /
  [台账可插拔后端 plan](superpowers/plans/2026-07-17-钉钉同步-01-台账可插拔后端.md)
- **宜搭对接怎么配**（凭据从哪拿、填哪、怎么跑）：[`宜搭对接配置.md`](宜搭对接配置.md) + [建台账表清单](宜搭建表清单-台账.md)
- **智能实勘问卷**（现场采集 + 智能预填，钉钉小程序 + serverless）：[**design 2026-07-19**](superpowers/specs/2026-07-19-智能实勘问卷-design.md)
  （现行）+ [地理因素与话术](实勘问卷-地理因素与话术.md)（逐类地理因素清单 + 话术模版，待估价师定稿）+
  [宜搭旧版 design](superpowers/specs/2026-07-18-实勘问卷-design.md)（平台已作废，产品决策仍沿用）
- **过程账本**（逐任务评审逮到什么、怎么修）：`.superpowers/sdd/progress.md`
- **第五轮反馈的逐条决策**（① 因素集全渲染 / #1 权重 / #2 系数偏离=A 自由改 / ④ 编号阻塞钉钉 / ⑤ 实例档次）：
  `.superpowers/sdd/overnight-followups.md`
- **给估价师的使用说明**：[`使用说明.md`](使用说明.md)
- **开发/打包**：根目录 [`README.md`](../README.md)
