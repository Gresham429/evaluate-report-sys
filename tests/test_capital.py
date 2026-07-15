"""人民币大写转换测试。"""

import pytest

from src.prose.capital import to_capital


def test_to_capital() -> None:
    assert to_capital(747536) == "柒拾肆万柒仟伍佰叁拾陆元整"
    assert to_capital(70000) == "柒万元整"
    assert to_capital(72708) == "柒万贰仟柒佰零捌元整"
    assert to_capital(0) == "零元整"
    assert to_capital(1) == "壹元整"
    assert to_capital(10) == "壹拾元整"
    assert to_capital(100000000) == "壹亿元整"
    assert to_capital(101) == "壹佰零壹元整"
    assert to_capital(1000000) == "壹佰万元整"
    assert to_capital(405147) == "肆拾万伍仟壹佰肆拾柒元整"


def test_to_capital_additional_goldens() -> None:
    """三份金样各自的年租赁价值大写金额（决定性证据，非任意构造）。"""
    assert to_capital(157534) == "壹拾伍万柒仟伍佰叁拾肆元整"
    assert to_capital(72708) == "柒万贰仟柒佰零捌元整"
    assert to_capital(100000001) == "壹亿零壹元整"


def test_to_capital_rejects_negative() -> None:
    with pytest.raises(ValueError):
        to_capital(-1)


def test_to_capital_rejects_overflow() -> None:
    with pytest.raises(ValueError):
        to_capital(1_000_000_000_000)  # 万亿级，超出亿位支持范围
