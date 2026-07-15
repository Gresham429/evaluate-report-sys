"""基础表内容指纹——当版本号用。

为何用指纹而非人工版本号：内容一变指纹即变，改不了也伪造不了。人工填「v1.2」
会忘、会填错、会复制粘贴时忘改（决策记录 §3.3）。现有三份基础表实测**无任何
版本标记**，版本管理是从零建立的。

## 口径（改它会让全部历史版本号失效，须慎）

指纹 = 规范序列化后 SHA256 取前 12 位十六进制小写。

**覆盖**（即「什么算估价知识」，与 ADR-001 划的知识边界一致）：

- 因素名
- 各档次描述与其分值
- 修正系数
- 分值标尺

**不覆盖 `Factor.row`**：行号是 Excel 的排版细节，不是估价知识。基础表中间插一
个空行，全部因素行号后移，但估价知识一个字没变——那不该是新版本。（row 仍要
**存**，Excel 路径靠它定位比较法表的行，见 `adapter.py`；「存」与「进指纹」是
两回事。）

**因素顺序进指纹**，不按名字重排。顺序变动是否算知识变动，本身可争；此处取
「宁可多出一版」：多一版只是多一个文件（旧版永不覆盖，无损失），少一版却是
「改了系数却不出新版本」的正确性事故。错也要错在安全的那一侧。

## 确定性

同一份 Excel 导十次必须得到同一个指纹，否则每次导入都成「新版本」，版本管理
即失去意义。为此：

- 档次字典按键排序（`sort_keys`），不吃 dict 的插入顺序
- 浮点用 `repr` 转成字符串再入 JSON，绕开浮点格式化的任何余地（`2` 与 `2.0`
  在 JSON 里是两个样子，而 `extract_knowledge` 一律给 float）
- 分隔符固定，不留空白差异
"""

import hashlib
import json

from src.engine.knowledge import Knowledge

__all__ = ["fingerprint", "canonical_form"]

_LENGTH = 12


def canonical_form(knowledge: Knowledge) -> str:
    """规范序列化——指纹的唯一输入。

    单独成函数是为了口径可被直接读到、可被测试盯住；它就是「什么算估价知识」
    这个判断的落地处。

    Args:
        knowledge: 一份基础表承载的比较法知识。

    Returns:
        确定性的 JSON 字符串。同一份知识永远得到同一个字符串。
    """
    payload = {
        "分值标尺": list(knowledge.scores),
        "因素": [
            {
                "名称": factor.name,
                "档次": factor.levels,
                # repr 而非裸 float：JSON 对 int/float 的写法不同，而系数经
                # extract_knowledge 一律成了 float，此处固化成字符串最省心。
                "系数": repr(factor.coefficient),
            }
            # 不含 row：见模块 docstring 的口径说明。
            for factor in knowledge.factors
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(knowledge: Knowledge) -> str:
    """基础表内容指纹。

    Args:
        knowledge: 一份基础表承载的比较法知识。

    Returns:
        12 位十六进制小写，如 `6584dc9bf9d2`。用作版本号与文件名的一部分。
    """
    digest = hashlib.sha256(canonical_form(knowledge).encode("utf-8")).hexdigest()
    return digest[:_LENGTH]
