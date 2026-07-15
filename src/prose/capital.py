"""人民币金额中文大写转换。

中国财务规范：数码用大写汉字（零壹贰叁肆伍陆柒捌玖），组内用拾佰仟，
节权位用万/亿。估价报告的年租赁价值均为整数元，故只处理整数金额，
末尾统一加"元整"。纯函数、无副作用、不调用任何 AI（约束 C2）——
同一输入永远产出同一输出。
"""

__all__ = ["to_capital"]

_DIGITS = "零壹贰叁肆伍陆柒捌玖"
# 组内单位，从高位到低位；个位不加单位
_SMALL_UNITS: tuple[str, ...] = ("仟", "佰", "拾", "")
# 节权位，从低到高：个位组不加、第二组"万"、第三组"亿"
_BIG_UNITS: tuple[str, ...] = ("", "万", "亿")


def _convert_group(number: int) -> str:
    """把 0-9999 的整数转为大写数码（不含节权位）。

    组内连续的零合并为一个「零」，组末尾的零不读出。

    Args:
        number: 0 到 9999 之间的整数。

    Returns:
        大写数字字符串；number 为 0 时返回空字符串，供上层据此省略节权位。
    """
    digits = [int(ch) for ch in f"{number:04d}"]
    parts: list[str] = []
    pending_zero = False
    for digit, unit in zip(digits, _SMALL_UNITS):
        if digit == 0:
            pending_zero = True
            continue
        if pending_zero and parts:
            parts.append("零")
        parts.append(_DIGITS[digit] + unit)
        pending_zero = False
    return "".join(parts)


def _split_groups(amount: int) -> list[str]:
    """把整数金额按 4 位一组、从个位起切分，返回从高位到低位的组字符串列表。

    Args:
        amount: 非负整数金额。

    Returns:
        每组最多 4 位数字的字符串列表，最高位组在前。
    """
    groups: list[str] = []
    remaining = str(amount)
    while remaining:
        groups.insert(0, remaining[-4:])
        remaining = remaining[:-4]
    return groups


def to_capital(amount: int) -> str:
    """整数人民币金额转中文大写（含"元整"）。

    中文法律文书里大写金额是作准的那一份，阿拉伯数字只是辅助——
    这个函数不得算错，四舍五入、负数、越界均视为调用方传参错误。

    Args:
        amount: 非负整数金额，单位元。

    Returns:
        中文大写金额字符串，如 747536 → "柒拾肆万柒仟伍佰叁拾陆元整"。

    Raises:
        ValueError: amount 为负数，或超出本函数支持的最大节权位（亿）。
    """
    if amount < 0:
        raise ValueError(f"金额不能为负数：{amount}")
    if amount == 0:
        return "零元整"

    groups = _split_groups(amount)
    if len(groups) > len(_BIG_UNITS):
        raise ValueError(f"金额超出大写转换支持范围（最大到亿位）：{amount}")

    result = ""
    pending_zero = False
    for i, group in enumerate(groups):
        big_unit = _BIG_UNITS[len(groups) - 1 - i]
        text = _convert_group(int(group))
        if not text:
            if result:
                pending_zero = True
            continue
        if pending_zero:
            result += "零"
            pending_zero = False
        result += text + big_unit
    return result + "元整"
