"""地方性法规的地区：名称、在国家法律法规数据库里的制定机关编号，以及命令行里的写法。"""
import re

# 顺序是命令行和 make shell 里的编号，从 1（北京）到 31（新疆）
REGION_CODE_MAP = {
    "北京": 170,
    "天津": 180,
    "河北": 190,
    "山西": 200,
    "内蒙古": 210,
    "辽宁": 220,
    "吉林": 230,
    "黑龙江": 240,
    "上海": 250,
    "江苏": 260,
    "浙江": 270,
    "安徽": 280,
    "福建": 290,
    "江西": 300,
    "山东": 310,
    "河南": 320,
    "湖北": 330,
    "湖南": 340,
    "广东": 350,
    "广西": 360,
    "海南": 370,
    "重庆": 380,
    "四川": 390,
    "贵州": 400,
    "云南": 410,
    "西藏": 420,
    "陕西": 430,
    "甘肃": 440,
    "青海": 450,
    "宁夏": 460,
    "新疆": 470,
}


def dlc_name(region: str) -> str:
    """DLC 目录名：「北京」→「北京地方法规」。"""
    return f"{region}地方法规"


def parse_regions(spec: str) -> list[str]:
    """「7-31」「北京 3,5-8」→ 地区名，去重并保持顺序。编号从 1 开始，顺序同 REGION_CODE_MAP。"""
    names = list(REGION_CODE_MAP)
    spec = re.sub(r"\s*[-~～—]\s*", "-", spec.strip())
    result: list[str] = []
    for part in re.split(r"[,，、\s]+", spec):
        if not part:
            continue
        if part in REGION_CODE_MAP:
            picked = [part]
        elif m := re.fullmatch(r"(\d+)-(\d+)", part):
            start, end = int(m.group(1)), int(m.group(2))
            if not 1 <= start <= end <= len(names):
                raise ValueError(f"范围要在 1-{len(names)} 之间，且从小到大：{part}")
            picked = names[start - 1:end]
        elif part.isdigit() and 1 <= int(part) <= len(names):
            picked = [names[int(part) - 1]]
        else:
            raise ValueError(f"不支持的地区：{part}")
        result += [n for n in picked if n not in result]
    if not result:
        raise ValueError("没有选择地区")
    return result
