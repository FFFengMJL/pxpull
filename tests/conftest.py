"""测试夹具：在内存里合成一个最小可用的 .pxcp 文件。

格式依据 README「2. .pxcp 格式」：头部字符串 → GUID → JSON 文档 → 缩略图 →
画板整图 → 资源库 → u32 0 结束符。
"""

from __future__ import annotations

import io
import json
import struct

import pytest
from PIL import Image


def u16(n: int) -> bytes:
    return struct.pack("<H", n)


def u32(n: int) -> bytes:
    return struct.pack("<I", n)


def s16(text: str) -> bytes:
    raw = text.encode("utf-8")
    return u16(len(raw)) + raw


def s32(text: str) -> bytes:
    raw = text.encode("utf-8")
    return u32(len(raw)) + raw


def make_png(width: int, height: int, color=(255, 0, 0, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(buf, "PNG")
    return buf.getvalue()


def make_svg(width: int, height: int) -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><rect width="{width}" height="{height}" fill="#0f0"/></svg>'
    ).encode()


def _vector(fill: int | None = None, radius=None, stroke=None) -> dict:
    colors = []
    if fill is not None:
        colors = [{"type": 1, "solidColor": {"color": fill, "version": 1},
                   "gradientColor": {"colorPos": [], "colors": [], "type": "",
                                     "angle": 90, "scale": 100, "version": 1},
                   "blendMode": "normal", "version": 1}]
    styles = []
    if stroke is not None:
        styles = [{"color": {"solidColor": {"color": stroke, "version": 1}}, "type": 1,
                   "position": "inside", "thickness": 1, "version": 1}]
    return {
        "stroke": {"dashSet": [], "styles": styles, "version": 1},
        "stroked": bool(stroke),
        "filled": fill is not None,
        "fill": {"colors": colors, "version": 1},
        "radius": radius or [],
        "version": 1,
    }


def _element(eid: str, name: str, x: int, y: int, w: int, h: int,
             fill: int | None = None, text: str = "", opacity: float = 1,
             radius=None, stroke=None, font=None) -> dict:
    fonts = []
    if text:
        f = {"name": "Noto Sans CJK SC", "size": 12, "color": 0xFFFFFFFF,
             "lineHeight": 16, "alignment": "left", "letterSpacing": 0,
             "bold": False, "italic": False, "start": 0, "end": len(text),
             "text": text, "underline": False, "version": 2}
        f.update(font or {})
        fonts = [f]
    return {
        "baseInfo": {"opacity": opacity, "id": eid, "name": name, "root": False, "version": 1},
        "vectored": fill is not None or bool(stroke),
        "rectInfo": {"version": 1, "x": x, "y": y, "width": w, "height": h},
        "fontInfo": {"version": 1, "text": text, "fonts": fonts},
        "vectorInfo": _vector(fill, radius, stroke),
        "effectInfo": {"shadows": [], "version": 1},
        "fonted": bool(text),
        "effected": False,
        "oldInfo": {"strokeColored": bool(stroke), "isText": bool(text),
                    "vectorStrokeWidth": -1, "version": 1, "fontSizes": [],
                    "fillColor": fill or 0, "fillColored": fill is not None,
                    "fontColors": [], "fontAlignments": [], "strokeColor": 0,
                    "isVectorRect": True, "radiu": 0, "fontFamily": []},
        "version": 1,
    }


PHOTO_ID = "aaaaaaaa-1111-2222-3333-444444444444"
RECT_B_ID = "bbbbbbbb-1111-2222-3333-444444444444"
TEXT_ID = "cccccccc-1111-2222-3333-444444444444"
IMG_ID = "dddddddd-1111-2222-3333-444444444444"


def build_pxcp(path, *, width: int = 64, height: int = 36) -> str:
    """写一个最小 .pxcp：背景矩形 → 半透明外链图占位 → 第二张整幅矩形 → 文本 → 带切图的图片。"""
    aid = "99999999-1111-2222-3333-444444444444"
    doc = {
        "artboardId": aid, "name": "合成画板", "filePath": "D:/demo/demo.xd",
        "sourceGuid": aid, "width": width, "height": height,
        "marks": [], "cacheMarks": [], "retinaScale": 2,
        "stampCreated": 0, "stampModified": 0, "version": 3,
        "elements": [
            _element("0000", "背景", 0, 0, width, height, fill=0xFF001322),
            _element(PHOTO_ID, "Photo", 0, 0, width, height, fill=0x00000000, opacity=0.5),
            _element(RECT_B_ID, "覆盖矩形", 0, 0, width, height, fill=0xFF001322),
            _element(TEXT_ID, "标题", 4, 4, 40, 16, text="你好"),
            _element(IMG_ID, "图标", 4, 24, 8, 8),
        ],
    }
    js = json.dumps(doc, ensure_ascii=False).encode("utf-8")

    # 资源库：1 组，guid = IMG_ID，含 d120 PNG + d160 SVG
    png = make_png(8, 8, (0, 255, 0, 255))
    svg = make_svg(8, 8)
    child_png = u32(0) + b"\x01" + s16("d120") + s16("png") + u32(len(png)) + png
    child_svg = u32(0) + b"\x01" + s16("d160") + s16("svg") + u32(len(svg)) + svg
    group_payload = (b"\x01" + u16(36) + IMG_ID.encode() + s16("图标")
                     + u16(2) + child_png + child_svg)
    group = u32(len(group_payload)) + group_payload
    lib_payload = b"\x01" + s16("deadbeef") + u16(1) + group
    lib = u32(len(lib_payload)) + lib_payload

    thumb = make_png(width // 4, height // 4, (10, 20, 30, 255))
    artboard = make_png(width * 2, height * 2, (0, 19, 34, 255))

    blob = b"PXCP" + u32(399)
    for text in ("测试项目", "D:/demo/demo.xd", "Web", "1x", "pxv", "auto"):
        blob += s32(text)
    blob += b"\x00" * 20
    blob += u32(36) + aid.encode()
    blob += u32(len(js)) + js
    blob += u32(len(thumb)) + thumb
    blob += u32(len(artboard)) + artboard
    blob += lib
    blob += u32(0)

    with open(path, "wb") as fh:
        fh.write(blob)
    return str(path)


@pytest.fixture()
def sample_pxcp(tmp_path):
    return build_pxcp(tmp_path / "sample.pxcp")


@pytest.fixture()
def photo_png(tmp_path):
    p = tmp_path / "photo.png"
    Image.new("RGBA", (64, 36), (255, 0, 0, 255)).save(p, "PNG")
    return str(p)
