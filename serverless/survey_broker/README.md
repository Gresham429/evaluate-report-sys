# 实勘问卷 serverless broker（阿里云函数计算 · Python）

二期用。钉钉小程序（现场手机）不能持 AppSecret，故由本 broker 代它读写钉钉多维表
「实勘问卷」表：持密钥换 token、写草稿/提交、调高德取地理事实。办公端照旧**直读**
该表「已提交」记录（`src/questionnaire/backend.py`），不经 broker。

**行契约与办公端严格对齐**：broker 写的行由 `record.py::content_to_fields` 生成，
其列名与「问卷内容」JSON 键，跟办公端 `src/questionnaire/backend.py::response_to_fields`
**逐字节一致**（`tests/test_survey_broker_record.py` 用真 office 编码器钉死这条，任一侧改了它就红）。

## 四个接口（小程序 → broker）
| action | payload | 行为 |
|---|---|---|
| `saveDraft` | `{survey_id?, filler, category, updated_at, content}` | 有 survey_id 且行存在→更新该行；否则新插一行。状态=草稿。返回 `{survey_id}` |
| `loadDraft` | `{survey_id}` | 取该行（任意状态），返回 `{survey_id,status,filler,category,updated_at,content}` |
| `submit` | `{survey_id}` | 该行状态→已提交 |
| `prefillGeo` | `{lng, lat}` | 高德逆地理+周边 → `{address,bus_stops,nearest_metro,facilities}`（只事实，不判档次，铁律 #7）|

`content` 内含 `basic/subjects/subject_levels/asset_conditions/photos/gps` 六键——即办公端 `_fields_to_response` 认的那套。

## 环境变量（配进 FC，**绝不进 git**）
| 变量 | 说明 |
|---|---|
| `DINGTALK_APP_KEY` | 钉钉小程序 Client ID（原 AppKey） |
| `DINGTALK_APP_SECRET` | 钉钉小程序 Client Secret（原 AppSecret）——**只在这里** |
| `NOTABLE_BASE_ID` | 多维表 baseId（同承载层那个） |
| `NOTABLE_OPERATOR_ID` | 操作人 unionId（同承载层） |
| `NOTABLE_SURVEY_SHEET` | 「实勘问卷」表 sheetId（`tools/survey_seed.py`/`questionnaire_provision.py` 会打印） |
| `AMAP_KEY` | 高德 **Web 服务** Key |

## 打包范围（部署到 FC 时 zip 进去的）
- `serverless/survey_broker/`（本包，stdlib only）
- `src/dingtalk/notable.py` + `src/dingtalk/__init__.py`（broker 复用的 `NotableClient`，纯标准库）
- **不需要** openpyxl/fastapi/pyyaml 等——broker 不 import `src.questionnaire` 包（那条链会拖第三方进来）。
- `requirements.txt` 为空（无第三方依赖）。

保持 `from src.dingtalk.notable import NotableClient` 可解析：zip 里 `src/` 目录结构照原样，入口按 `serverless.survey_broker.handler.handler` 配。

## 部署前必做的真机校准（`待真机校准`/`待部署校准`）
本包逻辑已用假 transport/假客户端全测（47 项绿），但**三处外部接口形状是按文档假定、未打真机**，部署时逐条核实：

1. **钉钉更新记录端点**（`src/dingtalk/notable.py::update_record`）：现按 `PUT .../records` body `{records:[{id,fields}]}` 假定。对照钉钉多维表 OpenAPI 最新文档核实 method/URL/body，必要时改这一个方法（同承载层当初用 `tools/notable_backend_smoke.py` 打真库校准的做法，可加一个 update 冒烟）。
2. **高德字段路径**（`amap.py`）：逆地理 `regeocode.formatted_address`、周边 `pois[].name/.type/.distance` 按高德文档常见形状假定。真机打一次，若字段名不同，同时改 `amap.py` 与 `tests/test_survey_broker_amap.py` 的 canned JSON（两边一起改）。POI type 里「公交站/地铁站」关键字匹配也按真返回微调。
3. **FC 入口形状**（`handler.py::handler`）：现按「事件处理程序 + API-Gateway 代理风格 event/response」假定。对照阿里云 FC 3.0 文档核实触发器类型与 event/response 精确形状，改 `handler`（不影响 `dispatch`，它是纯函数、不碰协议层）。
4. **token 缓存（性能）**：`handler` 现每次请求新建 `NotableClient`，warm 容器复用不到 token 缓存、每请求多换一次 token。部署时把客户端构造**提到模块级**（或懒加载单例），让 warm 容器复用 token。

校准完各处删掉对应 `待校准` 注释。

## 本地测试
```
uv run python -m pytest tests/test_survey_broker_*.py tests/test_notable_client.py -q
uv run ruff check serverless/
uv run mypy serverless/
```
`dispatch` 是纯函数，路由/状态码（未知 action→400、缺字段→400、问卷不存在→404、payload 非对象→400）全可离线测；`handler` 的 FC 协议层待真机。
