from __future__ import annotations

import io
import os
from pathlib import Path
import secrets
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .providers.base import ProviderError

VISION_COLORS = {"红色": "#a6473c", "绿色": "#4f6d50", "蓝色": "#46627a"}
DEFAULT_PAGE_LINES = ["灯亮着，归还便有了方向。", "我把沉默夹进书页。"]


def chinese_font(size: int = 30) -> ImageFont.FreeTypeFont:
    candidates: list[str] = []
    if os.getenv("YUEJI_CHINESE_FONT"):
        candidates.append(os.environ["YUEJI_CHINESE_FONT"])
    candidates.extend([
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
    ])
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    raise ProviderError("font_missing", "系统缺少可用中文字体，无法生成真实中文书页探针；请安装 Noto Sans CJK 或设置 YUEJI_CHINESE_FONT")


def probe_truth() -> dict[str, Any]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return {
        "code": "".join(secrets.choice(alphabet) for _ in range(6)),
        "color": secrets.choice(list(VISION_COLORS)),
        "shape": "圆形",
        "page_lines": DEFAULT_PAGE_LINES.copy(),
        "marker": "页" + "".join(secrets.choice(alphabet) for _ in range(4)),
    }


def vision_png(truth: dict[str, Any]) -> bytes:
    image = Image.new("RGB", (640, 300), "#e8ede4")
    draw = ImageDraw.Draw(image)
    font = chinese_font(30)
    draw.rectangle((0, 0, 639, 299), outline="#7c826f", width=3)
    draw.ellipse((44, 52, 208, 216), fill=VISION_COLORS[truth["color"]], outline="#30352d", width=3)
    draw.text((250, 112), truth["code"], fill="#292d28", font=font)
    draw.text((250, 165), "圆形", fill="#4a5042", font=font)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def page_png(truth: dict[str, Any]) -> bytes:
    font = chinese_font(30)
    small = chinese_font(20)
    image = Image.new("RGB", (900, 420), "#f7f2e7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((28, 24, 871, 395), outline="#6b675f", width=2)
    draw.text((58, 54), truth["marker"], fill="#34342f", font=small)
    y = 145
    for line in truth["page_lines"]:
        # 真实渲染中文；缺字体时直接失败，不用方块冒充。
        draw.text((58, y), line, fill="#292d28", font=font)
        y += 82
    draw.line((58, y + 8, 842, y + 8), fill="#a9a294", width=1)
    draw.text((58, y + 24), "—— 阅迹合成书页探针 ——", fill="#777064", font=small)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
