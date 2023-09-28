
NUMBER_RE = "[一二三四五六七八九十零百千万1234567890]"

INDENT_RE = [
    "序言",
    f"^第{NUMBER_RE}+编",
    f"^第{NUMBER_RE}+章",
    f"^第{NUMBER_RE}+节",
    "^([一二三四五六七八九十零百千万]+、.{1,15})[^。；：]$",
]

LINE_RE = INDENT_RE + [f"^第{NUMBER_RE}+条"]


DESC_REMOVE_PATTERNS = [
    "^（",
    "^\(",
    "）$",
    "\)$",
    "^根据",
    "^自",
]

LINE_START = f"""^({"|".join(map(lambda x: f"({x})".replace(NUMBER_RE, "一"), filter(lambda x: "节" not in x, LINE_RE)))})"""
