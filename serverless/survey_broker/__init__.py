"""实勘问卷 serverless broker（二期）：钉钉小程序写草稿/提交、高德预填地理事实。

自包含、仅用标准库 + `src.dingtalk.notable.NotableClient`（同为纯 stdlib）；
**不** import `src.questionnaire`——那条链经 `src.questionnaire.model` →
`src.extractor.field_map` → `src.model` 拉到 PyYAML，与本包"部署到阿里云
函数计算、免第三方依赖"的目标冲突。行契约（列名/「问卷内容」JSON 结构）是
`src.questionnaire.backend` 那份的独立副本，见 `record.py` 顶部注释；两侧
靠 `tests/test_survey_broker_record.py` 的契约测试对拍，不能各自漂移。

部署时把本目录（`serverless/survey_broker/`）整个打包上传，入口填
`handler.handler`（阿里云 FC 3.0 事件处理程序，形状见 `handler.py` 里的
`# 待部署校准` 注释）。
"""

from serverless.survey_broker.amap import AmapClient
from serverless.survey_broker.handler import dispatch, handler
from serverless.survey_broker.record import (
    COL_CATEGORY,
    COL_CONTENT,
    COL_ID,
    COL_MTIME,
    COL_STATUS,
    COL_USER,
    CONTENT_KEYS,
    STATUS_DRAFT,
    STATUS_SUBMITTED,
    content_to_fields,
    fields_to_content,
    new_survey_id,
)
from serverless.survey_broker.store import SurveyBrokerStore

__all__ = [
    "AmapClient",
    "COL_CATEGORY",
    "COL_CONTENT",
    "COL_ID",
    "COL_MTIME",
    "COL_STATUS",
    "COL_USER",
    "CONTENT_KEYS",
    "STATUS_DRAFT",
    "STATUS_SUBMITTED",
    "SurveyBrokerStore",
    "content_to_fields",
    "dispatch",
    "fields_to_content",
    "handler",
    "new_survey_id",
]
