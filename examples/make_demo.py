#!/usr/bin/env python3
"""生成示例文件 examples/demo.pxcp（合成数据，不含任何真实项目内容）。

用法：  uv run python examples/make_demo.py
产物：  examples/demo.pxcp
"""

from __future__ import annotations

import io
import json
import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pxpull

W, H = 1280, 720
ICON_ID = "5f0c2f1e-1111-4a2b-9d3e-000000000001"


# --------------------------------------------------------------------------- #
# 元素构造
# --------------------------------------------------------------------------- #
def el(eid, name, x, y, w, h, *, fill=None, radius=None, stroke=None,
       text="", size=14, color=0xFFE2E8F0, opacity=1.0, bold=False, align="left"):
    colors = []
    if fill is not None:
        colors = [{"type": 1, "solidColor": {"color": fill, "version": 1},
                   "gradientColor": {"colorPos": [], "colors": [], "type": "",
                                     "angle": 90, "scale": 100, "version": 1},
                   "blendMode": "normal", "version": 1}]
    styles = []
    if stroke is not None:
        styles = [{"color": {"solidColor": {"color": stroke, "version": 1}, "type": 1,
                             "gradientColor": {"colorPos": [], "colors": [], "type": "",
                                               "angle": 90, "scale": 100, "version": 1},
                             "blendMode": "", "version": 1},
                   "position": "inside", "thickness": 1, "version": 1}]
    fonts = []
    if text:
        fonts = [{"lineHeight": size * 1.25, "name": "Noto Sans CJK SC", "text": text,
                  "underline": False, "bold": bold, "start": 0, "color": color,
                  "italic": False, "letterSpacing": 0, "size": size,
                  "alignment": align, "end": len(text), "version": 2}]
    return {
        "baseInfo": {"opacity": opacity, "id": eid, "name": name, "root": False, "version": 1},
        "vectored": fill is not None or bool(stroke),
        "rectInfo": {"version": 1, "x": x, "y": y, "width": w, "height": h},
        "fontInfo": {"version": 1, "text": text, "fonts": fonts},
        "vectorInfo": {"stroke": {"dashSet": [], "styles": styles, "version": 1},
                       "stroked": bool(stroke), "filled": fill is not None,
                       "fill": {"colors": colors, "version": 1},
                       "radius": radius or [], "version": 1},
        "effectInfo": {"shadows": [], "version": 1},
        "fonted": bool(text), "effected": False,
        "oldInfo": {"strokeColored": bool(stroke), "isText": bool(text),
                    "vectorStrokeWidth": -1, "version": 1, "fontSizes": [size] if text else [],
                    "fillColor": fill or 0, "fillColored": fill is not None,
                    "fontColors": [color] if text else [], "fontAlignments": [align] if text else [],
                    "strokeColor": stroke or 0, "isVectorRect": fill is not None,
                    "radiu": 0, "fontFamily": ["Noto Sans CJK SC"] if text else []},
        "version": 1,
    }


def build_elements():
    bg, panel, line = 0xFF0B1220, 0xFF111A2E, 0xFF1E293B
    fg, dim, accent = 0xFFE2E8F0, 0xFF94A3B8, 0xFF38BDF8
    els = [
        el("e000", "背景", 0, 0, W, H, fill=bg),
        el("e001", "顶栏", 0, 0, W, 64, fill=0xFF0F172A),
        el("e002", "分隔线", 0, 63, W, 1, fill=line),
        el("e003", "标题", 32, 16, 260, 30, text="示例设计稿", size=22, color=fg, bold=True),
        el("e004", "副标题", 250, 26, 420, 20, text="PxCook .pxcp 解析示例 · 1280×720",
           size=13, color=0xFF64748B),
        el(ICON_ID, "示例图标", W - 56, 20, 24, 24),
    ]
    cards = [("卡片 A", "1,284", "较昨日 +12%"), ("卡片 B", "96.4", "较昨日 +3.1%"),
             ("卡片 C", "24.60", "较昨日 -1.8%")]
    for i, (title, metric, sub) in enumerate(cards):
        x = 32 + i * 416
        els += [
            el(f"c{i}a", f"{title} 背景", x, 96, 384, 200, fill=panel,
               radius=[12, 12, 12, 12], stroke=line),
            el(f"c{i}b", f"{title} 标题", x + 24, 116, 200, 26, text=title, size=17, color=accent),
            el(f"c{i}c", f"{title} 文本", x + 24, 152, 320, 20,
               text="示例说明文本，用于演示图层点选与取色。", size=13, color=dim),
            el(f"c{i}d", f"{title} 指标", x + 24, 186, 240, 46, text=metric, size=36, color=fg),
            el(f"c{i}e", f"{title} 注释", x + 24, 240, 160, 18, text=sub, size=12,
               color=0xFF64748B),
        ]
    # 柱状图
    els += [
        el("chart0", "图表背景", 32, 320, 832, 368, fill=panel,
           radius=[12, 12, 12, 12], stroke=line),
        el("chart1", "图表标题", 56, 340, 240, 24, text="柱状图示例", size=16, color=fg),
    ]
    heights = [86, 132, 64, 158, 104, 186, 142, 96]
    for i, hh in enumerate(heights):
        x = 80 + i * 94
        els += [
            el(f"bar{i}", f"柱子 {i + 1}", x, 640 - hh, 58, hh, fill=0xFF38BDF8, opacity=0.85,
               radius=[6, 6, 0, 0]),
            el(f"bar{i}t", f"柱子标签 {i + 1}", x, 650, 58, 18, text=f"Q{i + 1}",
               size=12, color=dim, align="center"),
        ]
    for i in range(4):
        y = 400 + i * 60
        els.append(el(f"grid{i}", f"网格线 {i + 1}", 72, y, 760, 1, fill=0xFF1B2A44))
    # 右侧列表
    els += [
        el("list0", "列表面板", 888, 320, 360, 368, fill=panel,
           radius=[12, 12, 12, 12], stroke=line),
        el("list1", "列表标题", 912, 340, 200, 24, text="列表示例", size=16, color=fg),
    ]
    for i in range(5):
        y = 386 + i * 56
        els += [
            el(f"row{i}a", f"列表项 {i + 1}", 912, y, 200, 20, text=f"列表项 {i + 1}",
               size=13, color=dim),
            el(f"row{i}b", f"列表值 {i + 1}", 1120, y, 100, 20, text=f"{120 + i * 37}",
               size=13, color=accent, align="right"),
            el(f"row{i}l", f"列表分隔 {i + 1}", 912, y + 34, 312, 1, fill=0xFF18233A),
        ]
    return els


# --------------------------------------------------------------------------- #
# 写 .pxcp
# --------------------------------------------------------------------------- #
def u16(n): return struct.pack("<H", n)
def u32(n): return struct.pack("<I", n)
def s16(t):
    b = t.encode()
    return u16(len(b)) + b
def s32(t):
    b = t.encode()
    return u32(len(b)) + b


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def make_icon() -> tuple[bytes, bytes]:
    img = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 45, 45], radius=12, fill=(56, 189, 248, 255))
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/google-noto-sans-cjk-fonts/NotoSansCJK-Bold.ttc", 26, index=2)
    except OSError:
        font = ImageFont.load_default()
    d.text((24, 24), "P", font=font, fill=(11, 18, 32, 255), anchor="mm")
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">'
           b'<rect x="2" y="2" width="43" height="43" rx="12" fill="#38bdf8"/></svg>')
    return png_bytes(img), svg


def write_pxcp(path: str, doc: dict, art: bytes, thumb: bytes, icon_png: bytes, icon_svg: bytes):
    aid = doc["artboardId"]
    js = json.dumps(doc, ensure_ascii=False).encode()
    child_png = u32(0) + b"\x01" + s16("d120") + s16("png") + u32(len(icon_png)) + icon_png
    child_svg = u32(0) + b"\x01" + s16("d160") + s16("svg") + u32(len(icon_svg)) + icon_svg
    gp = b"\x01" + u16(36) + ICON_ID.encode() + s16("示例图标") + u16(2) + child_png + child_svg
    lib_p = b"\x01" + s16("demo0001") + u16(1) + u32(len(gp)) + gp

    blob = b"PXCP" + u32(399)
    for s in ("示例项目", "D:/demo/demo.pxcp", "Web", "1x", "pxv", "auto"):
        blob += s32(s)
    blob += b"\x00" * 20 + u32(36) + aid.encode()
    blob += u32(len(js)) + js
    blob += u32(len(thumb)) + thumb
    blob += u32(len(art)) + art
    blob += u32(len(lib_p)) + lib_p
    blob += u32(0)
    with open(path, "wb") as fh:
        fh.write(blob)


def main() -> int:
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo.pxcp")
    doc = {"artboardId": "00000000-0000-4000-8000-000000000001",
           "name": "示例设计稿", "filePath": "D:/demo/demo.xd",
           "sourceGuid": "00000000-0000-4000-8000-000000000001",
           "width": W, "height": H, "retinaScale": 2, "marks": [], "cacheMarks": [],
           "stampCreated": 0, "stampModified": 0, "version": 3,
           "elements": build_elements()}
    icon_png, icon_svg = make_icon()
    # 先写一份占位整图，解析后再用真实渲染结果重写，保证图像与元素框对齐
    blank = png_bytes(Image.new("RGBA", (W * 2, H * 2), (11, 18, 32, 255)))
    thumb = png_bytes(Image.new("RGBA", (W // 4, H // 4), (11, 18, 32, 255)))
    write_pxcp(out, doc, blank, thumb, icon_png, icon_svg)

    parsed = pxpull.parse_file(out)
    art_img = pxpull.render_document(parsed, 2.0)
    thumb_img = pxpull.render_document(parsed, 0.25)
    write_pxcp(out, doc, png_bytes(art_img), png_bytes(thumb_img), icon_png, icon_svg)

    size = os.path.getsize(out)
    print(f"已生成 {out}（{size / 1024:.1f} KB，{len(doc['elements'])} 个图层）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
