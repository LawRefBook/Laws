"""中文数字和整数之间的转换：条号「第一百零五条」、Word 自动编号「第十二章」。"""

CN_DIGITS = "〇一二三四五六七八九"
_VALUES = dict(zip("零〇一二三四五六七八九", [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9], strict=True))
_UNITS = {"十": 10, "百": 100, "千": 1000}


def cn_to_int(s: str) -> int:
    """「一百零五」→ 105，「二〇二〇」这样逐位写的 → 2020。"""
    if not any(c in s for c in _UNITS):
        value = 0
        for c in s:
            value = value * 10 + _VALUES[c]
        return value
    total, cur = 0, 0
    for c in s:
        if c in _VALUES:
            cur = _VALUES[c]
        else:
            total += (cur or 1) * _UNITS[c]
            cur = 0
    return total + cur


def int_to_cn(n: int) -> str:
    """1 → 一，10 → 十，21 → 二十一，105 → 一百零五。0 和负数原样返回。"""
    if n <= 0:
        return str(n)
    ret, zero = "", False
    for value, unit in ((1000, "千"), (100, "百"), (10, "十")):
        d, n = divmod(n, value)
        if d:
            if zero:
                ret += "零"
            ret += ("" if d == 1 and unit == "十" and not ret else CN_DIGITS[d]) + unit
            zero = False
        elif ret:
            zero = True
    if n:
        ret += ("零" if zero else "") + CN_DIGITS[n]
    return ret
