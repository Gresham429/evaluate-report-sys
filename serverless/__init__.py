"""Serverless 函数集合的容器包（阿里云函数计算部署单元按子包划分）。

本包本身不导出任何符号——各函数是独立部署单元，见 `survey_broker/`。
显式声明为常规包（而非隐式命名空间包），避免 mypy 把
`serverless.survey_broker.*` 和裸模块路径 `survey_broker.*` 判成同一份
源文件的两个不同模块名（"Source file found twice under different module
names"）。
"""

__all__: list[str] = []
