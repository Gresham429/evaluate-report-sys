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

保持 `from src.dingtalk.notable import NotableClient` 可解析：zip 里 `serverless/`、`src/` 目录结构照原样。
一键打包：`uv run python serverless/package.py` → 产 `serverless/dist/survey_broker_fc.zip`。

### 两种入口，二选一（按 FC 创建函数时选的运行时）
- **自定义运行时（Web Server 模式，推荐、已按此走）**：用 `server.py` 起一个标准库 HTTP Server。
  - 启动命令：`python3 -m serverless.survey_broker.server`
  - 监听端口：`9000`（`server.py` 读 `FC_SERVER_PORT`/`PORT`，缺省 9000，与控制台「监听端口」一致）
  - 请求：`POST` body `{"action":"saveDraft|loadDraft|submit|prefillGeo","payload":{...}}` → JSON；`GET /` 健康检查回 200。
  - 客户端在进程启动时建一次（`build_context`），warm 容器复用、token 缓存复用。
- **官方运行时（事件函数）**：用 `handler.py::handler`，处理程序填 `serverless.survey_broker.handler.handler` + 挂 HTTP 触发器。
  两个入口共用同一个纯 `dispatch`，逻辑一致，选一个即可。

## 真机校准状态（2026-07-19 打线上 FC 全部验通 ✅）
本包逻辑先用假 transport/假客户端全测，三处外部接口形状随后**已在线上 FC 真机验通**：

1. ✅ **钉钉换 token / 读 / 写 / 更新**：`loadDraft`/`saveDraft`/`submit` 打真库全 200；`update_record`（`PUT .../records` body `{records:[{id,fields}]}`）经 `submit` 把状态 草稿→已提交 成功——端点形状正确。
2. ✅ **高德**：逆地理 `regeocode.formatted_address`、周边 `pois[].name/.type/.distance` 实测无误。POI 分类关键字**已按真机放宽**为「公交」「地铁」（高德实际是「XX公交车站」「地铁E口(1/4号线)」，卡死「公交站/地铁站」会漏）。
3. ✅ **FC 入口**：自定义运行时 + `server.py`，`GET /` 探活 200、`python3 -m serverless.survey_broker.server` + 端口 9000 起服正常。
4. ✅ **token 缓存**：`server.py` 进程启动建一次客户端，warm 容器复用。

> 走官方运行时 + `handler.py`（事件函数，本项目未用）那条路，event/response 形状仍按 API-Gateway 代理风格假定、未真机验。

**上线前仍要做的一件事（非校准，是鉴权）**：给 broker 加钉钉 authCode 校验（现触发器 anonymous、接口开放），见项目待办。

校准完各处删掉对应 `待校准` 注释。

## 本地测试
```
uv run python -m pytest tests/test_survey_broker_*.py tests/test_notable_client.py -q
uv run ruff check serverless/
uv run mypy serverless/
```
`dispatch` 是纯函数，路由/状态码（未知 action→400、缺字段→400、问卷不存在→404、payload 非对象→400）全可离线测；`handler` 的 FC 协议层待真机。
