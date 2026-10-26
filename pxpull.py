#!/usr/bin/env python3
"""
pxpull.py -- 在 Linux/macOS 上解析 PxCook (像素大厨) 的 .pxcp 设计文件。

.pxcp 是 PxCook 私有的容器格式，本工具逆向出的结构如下（小端）：

    "PXCP" | u32 version
    u32len + utf8        项目名（如 "示例项目"）
    u32len + utf8        原始设计文件路径（如 D:/xxx.xd）
    u32len + utf8        平台（"Web" / "iOS" / "Android" ...）
    u32len + utf8        缩放（"1x" / "2x"）
    u32len + utf8        标记（"pxv"）
    u32len + utf8        标记（"auto"）
    <opaque header blob> 版本/时间戳等，非必需
    u32 36 + uuid        生成 GUID
    u32len + JSON        画板文档：artboard/宽高/elements[…]
    u32len + PNG         画板缩略图
    u32len + PNG         画板整图（retina，2x）
    u32len + 资源库       所有切图资产（每个资产 7 个密度：d120…d640 + svg）
    u32 0                结束符

资源库内部：
    [u8 1][u16 hashlen][hash][u16 count]
    count 个 group:
        [u32 len][u8 1][u16 36][guid][u16 namelen][name][u16 nchild]
        nchild 个 child:
            [u32 len][u8 1][u16 namelen][name][u16 fmtlen][fmt][u32 size][data]

其中 group.guid == 元素 baseInfo.id，group.name == 元素名，
child.name 是密度（d120=1.2x … d640=6.4x），child.fmt 是 png/svg。

用法见 `python3 pxpull.py --help`。
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import struct
import subprocess
import sys
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from PIL import Image

MAGIC = b"PXCP"
UUID_RE = re.compile(rb"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
DENSITY_RE = re.compile(r"^d(\d+)$")


class PxcpError(Exception):
    pass


# --------------------------------------------------------------------------- #
# low level reader
# --------------------------------------------------------------------------- #
class Reader:
    __slots__ = ("data", "pos")

    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def need(self, n: int) -> None:
        if self.pos + n > len(self.data):
            raise PxcpError(f"文件在偏移 {self.pos} 处意外结束（需要 {n} 字节）")

    def u8(self) -> int:
        self.need(1)
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u16(self) -> int:
        self.need(2)
        v = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return v

    def u32(self) -> int:
        self.need(4)
        v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def raw(self, n: int) -> bytes:
        self.need(n)
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v

    def str16(self) -> str:
        n = self.u16()
        return self.raw(n).decode("utf-8", "replace")


# --------------------------------------------------------------------------- #
# data model
# --------------------------------------------------------------------------- #
class AssetVariant:
    __slots__ = ("data", "fmt", "name")

    def __init__(self, name: str, fmt: str, data: bytes):
        self.name, self.fmt, self.data = name, fmt, data

    @property
    def density(self) -> float | None:
        m = DENSITY_RE.match(self.name)
        return int(m.group(1)) / 100 if m else None

    @property
    def size(self) -> tuple[int, int] | None:
        """像素尺寸（PNG 从 IHDR 读，SVG 从 width/height 读）。"""
        if self.fmt == "png" and self.data[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", self.data[16:24])
            return int(w), int(h)
        if self.fmt == "svg":
            head = self.data[:400].decode("utf-8", "replace")
            m = re.search(r'\bwidth="([\d.]+)"\s+height="([\d.]+)"', head)
            if m:
                return round(float(m.group(1))), round(float(m.group(2)))
            m = re.search(r'viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+) ([\d.]+)"', head)
            if m:
                return round(float(m.group(1))), round(float(m.group(2)))
        return None

    def __repr__(self) -> str:
        sz = self.size
        dim = f" {sz[0]}x{sz[1]}" if sz else ""
        return f"<{self.fmt} {self.name}{dim} {len(self.data)}B>"


class Asset:
    """一个切图资产（按元素分组，含多密度）。"""

    __slots__ = ("guid", "name", "variants")

    def __init__(self, guid: str, name: str, variants: list[AssetVariant]):
        self.guid, self.name, self.variants = guid, name, variants

    def pngs(self) -> list[AssetVariant]:
        return [v for v in self.variants if v.fmt == "png"]

    def svg(self) -> AssetVariant | None:
        for v in self.variants:
            if v.fmt == "svg":
                return v
        return None

    def best_png(self, target_w: float = 0, target_h: float = 0,
                 prefer: float = 1.0, max_density: int | None = None) -> AssetVariant | None:
        """选择最合适的 PNG：优先 ≥ 目标尺寸的最小一张，否则最大一张。"""
        pngs = [v for v in self.pngs()
                if v.size and (max_density is None or (v.density or 0) * 100 <= max_density + 1e-6)]
        if not pngs:
            return self.svg()
        pngs.sort(key=lambda v: v.size[0] * v.size[1])
        if target_w <= 1 and target_h <= 1:
            return pngs[-1]
        want = max(target_w, 1) * max(target_h, 1) * prefer * prefer
        for v in pngs:
            if v.size[0] * v.size[1] >= want:
                return v
        return pngs[-1]

    @property
    def natural_size(self) -> tuple[float, float] | None:
        for v in self.variants:
            d, s = v.density, v.size
            if d and s:
                return s[0] / d, s[1] / d
        return None

    def __repr__(self) -> str:
        n = self.natural_size
        dim = f" {n[0]:.1f}x{n[1]:.1f}" if n else ""
        return f"<Asset {self.name!r}{dim} {len(self.variants)} variants>"


class PxcpDoc:
    """解析后的 .pxcp 文档。"""

    def __init__(self):
        self.path = ""
        self.version = 0
        self.project = ""
        self.source_path = ""
        self.platform = ""
        self.scale = ""
        self.tags: list[str] = []
        self.header_blob = b""
        self.guid = ""
        self.data: dict = {}
        self.thumb_png: bytes = b""
        self.artboard_png: bytes = b""
        self.assets: list[Asset] = []
        self.asset_by_guid: dict[str, Asset] = {}
        self.asset_fingerprint = ""  # 资源库 hash（若存在）

    # -- 便捷属性 ---------------------------------------------------------
    @property
    def name(self) -> str:
        return self.data.get("name", "")

    @property
    def width(self) -> int:
        return int(self.data.get("width", 0))

    @property
    def height(self) -> int:
        return int(self.data.get("height", 0))

    @property
    def elements(self) -> list[dict]:
        return self.data.get("elements", [])

    @property
    def retina_scale(self) -> int:
        return int(self.data.get("retinaScale", 2))

    def thumb_image(self):
        from PIL import Image
        return Image.open(io.BytesIO(self.thumb_png)) if self.thumb_png else None

    def artboard_image(self):
        from PIL import Image
        return Image.open(io.BytesIO(self.artboard_png)) if self.artboard_png else None

    # -- 元素分类 ---------------------------------------------------------
    @staticmethod
    def element_text(el: dict) -> str:
        return (el.get("fontInfo") or {}).get("text", "") or ""

    def element_kind(self, el: dict) -> str:
        """text / image / shape / empty"""
        if self.element_text(el).strip():
            return "text"
        if el.get("baseInfo", {}).get("id") in self.asset_by_guid:
            return "image"
        if _has_visible_fill(el) or (el.get("vectorInfo") or {}).get("stroked"):
            return "shape"
        return "empty"

    def stats(self) -> dict:
        kinds = {"text": 0, "image": 0, "shape": 0, "empty": 0}
        for el in self.elements:
            kinds[self.element_kind(el)] += 1
        fonts, colors, sizes = set(), set(), set()
        for el in self.elements:
            for f in (el.get("fontInfo") or {}).get("fonts", []):
                fonts.add(f.get("name"))
                colors.add(f.get("color"))
                sizes.add(f.get("size"))
        return {"elements": len(self.elements), "kinds": kinds,
                "fonts": sorted(x for x in fonts if x),
                "font_sizes": sorted(x for x in sizes if x),
                "assets": len(self.assets)}

    def __repr__(self) -> str:
        return (f"<PxcpDoc {self.name!r} {self.width}x{self.height} "
                f"elements={len(self.elements)} assets={len(self.assets)}>")


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def _read_u32_string(r: Reader) -> str:
    n = r.u32()
    if n > 1 << 20:
        raise PxcpError(f"字符串长度异常: {n} @ {r.pos - 4}")
    return r.raw(n).decode("utf-8", "replace")


def _find_document(r: Reader) -> tuple[str, dict, int, int]:
    """在头部之后定位 GUID + JSON 文档，返回 (guid, doc, json_start, json_end)。"""
    data = r.data
    start = r.pos
    limit = min(len(data), start + 4096)
    for p in range(start, limit - 4):
        if data[p:p + 4] != b"\x24\x00\x00\x00":  # u32 36
            continue
        if not UUID_RE.match(data[p + 4:p + 40]):
            continue
        guid = data[p + 4:p + 40].decode()
        n = struct.unpack_from("<I", data, p + 40)[0]
        if 0 < n < len(data) and data[p + 44:p + 45] == b"{":
            blob = data[p + 44:p + 44 + n]
            try:
                doc = json.loads(blob)
            except Exception:
                continue
            return guid, doc, p, p + 44 + n
    raise PxcpError("找不到 JSON 文档段（可能不是 PxCook 3.x 的 .pxcp）")


def parse_library(payload: bytes, doc: PxcpDoc) -> None:
    r = Reader(payload)
    flag = r.u8()
    if flag != 1:
        raise PxcpError(f"资源库标志异常: {flag}")
    hash_len = r.u16()
    doc.asset_fingerprint = r.raw(hash_len).decode("ascii", "replace")
    count = r.u16()
    for _ in range(count):
        glen = r.u32()
        gstart = r.pos
        if r.u8() != 1:
            raise PxcpError("资源 group 标志异常")
        gl = r.u16()
        guid = r.raw(gl).decode("utf-8", "replace")
        name = r.str16()
        nchild = r.u16()
        variants: list[AssetVariant] = []
        for _ in range(nchild):
            r.u32()  # child length
            if r.u8() != 1:
                raise PxcpError("资源 child 标志异常")
            cname = r.str16()
            cfmt = r.str16()
            size = r.u32()
            blob = r.raw(size)
            variants.append(AssetVariant(cname, cfmt, blob))
        if r.pos - gstart != glen:
            # 长度字段只作校验，不匹配时以实际解析为准
            pass
        a = Asset(guid, name, variants)
        doc.assets.append(a)
        doc.asset_by_guid[guid] = a


def parse_file(path: str) -> PxcpDoc:
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != MAGIC:
        raise PxcpError(f"不是 .pxcp 文件（magic={data[:4]!r}）")
    doc = PxcpDoc()
    doc.path = os.path.abspath(path)
    r = Reader(data, 4)
    doc.version = r.u32()
    doc.project = _read_u32_string(r)
    doc.source_path = _read_u32_string(r)
    doc.platform = _read_u32_string(r)
    doc.scale = _read_u32_string(r)
    doc.tags.append(_read_u32_string(r))   # pxv
    doc.tags.append(_read_u32_string(r))   # auto
    header_start = r.pos

    doc.guid, doc.data, jstart, pos = _find_document(r)
    doc.header_blob = data[header_start:jstart]

    # 后续记录：[u32 len][payload]
    while pos + 4 <= len(data):
        n = struct.unpack_from("<I", data, pos)[0]
        if n == 0:
            break
        payload = data[pos + 4:pos + 4 + n]
        if payload[:8] == b"\x89PNG\r\n\x1a\n":
            if not doc.thumb_png:
                doc.thumb_png = payload
            elif not doc.artboard_png:
                doc.artboard_png = payload
        elif payload[:1] == b"\x01":
            try:
                parse_library(payload, doc)
            except PxcpError:
                # 资源库结构随版本变化，解析失败时保留文档其余部分
                pass
        pos += 4 + n
    return doc


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _has_visible_fill(el: dict) -> bool:
    """填充是否真的可见（全透明色 / 空渐变视为不可见）。"""
    vi = el.get("vectorInfo") or {}
    if not vi.get("filled"):
        return False
    for c in (vi.get("fill") or {}).get("colors", []):
        if (c.get("gradientColor") or {}).get("colors"):
            return True
        if ((c.get("solidColor") or {}).get("color", 0) >> 24) & 0xFF:
            return True
    return False


def color_of(v: int) -> tuple[int, int, int, int]:
    """0xAARRGGBB -> (r,g,b,a)"""
    v &= 0xFFFFFFFF
    return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF, (v >> 24) & 0xFF)


def simplify_element(doc: PxcpDoc, el: dict) -> dict:
    """把原始元素整理成对前端更友好的结构。"""
    bi = el.get("baseInfo") or {}
    ri = el.get("rectInfo") or {}
    vi = el.get("vectorInfo") or {}
    fi = el.get("fontInfo") or {}
    out = {
        "id": bi.get("id"),
        "name": bi.get("name", ""),
        "kind": doc.element_kind(el),
        "x": ri.get("x", 0), "y": ri.get("y", 0),
        "width": ri.get("width", 0), "height": ri.get("height", 0),
        "opacity": bi.get("opacity", 1),
    }
    fills = []
    for c in (vi.get("fill") or {}).get("colors", []):
        if c.get("type") == 1 or c.get("solidColor"):
            fills.append({"type": "solid", "color": hex(c["solidColor"]["color"] & 0xFFFFFFFF),
                          "argb": color_of(c["solidColor"]["color"])})
        elif c.get("gradientColor", {}).get("colors"):
            g = c["gradientColor"]
            fills.append({"type": "gradient", "kind": g.get("type", "linear"),
                          "angle": g.get("angle", 90), "scale": g.get("scale", 100),
                          "stops": [{"pos": p,
                                     "color": hex(col & 0xFFFFFFFF),
                                     "argb": color_of(col)}
                                    for p, col in zip(g.get("colorPos", []), g.get("colors", []), strict=False)]})
    if fills:
        out["fill"] = fills
    strokes = []
    for s in (vi.get("stroke") or {}).get("styles", []):
        col = ((s.get("color") or {}).get("solidColor") or {}).get("color", 0)
        strokes.append({"width": s.get("thickness", 1), "position": s.get("position", "inside"),
                        "color": hex(col & 0xFFFFFFFF), "argb": color_of(col)})
    if strokes:
        out["stroke"] = strokes
    if vi.get("radius"):
        out["radius"] = vi["radius"]
    shadows = []
    for sh in (el.get("effectInfo") or {}).get("shadows", []):
        shadows.append({"x": sh.get("x", 0), "y": sh.get("y", 0), "blur": sh.get("blur", 0),
                        "spread": sh.get("spread", 0), "inner": sh.get("inner", False),
                        "color": hex(sh.get("color", 0) & 0xFFFFFFFF),
                        "argb": color_of(sh.get("color", 0))})
    if shadows:
        out["shadow"] = shadows
    if fi.get("text"):
        f = (fi.get("fonts") or [{}])[0]
        out["text"] = fi["text"]
        out["font"] = {"family": f.get("name"), "size": f.get("size"),
                       "color": hex(f.get("color", 0) & 0xFFFFFFFF),
                       "argb": color_of(f.get("color", 0)),
                       "line_height": f.get("lineHeight"), "align": f.get("alignment"),
                       "letter_spacing": f.get("letterSpacing", 0),
                       "bold": f.get("bold", False), "italic": f.get("italic", False)}
    return out


# --------------------------------------------------------------------------- #
# CLI: info / assets / elements
# --------------------------------------------------------------------------- #
def cmd_info(doc: PxcpDoc, args) -> int:
    st = doc.stats()
    print(f"文件      : {doc.path}")
    print(f"格式版本  : {doc.version}")
    print(f"项目      : {doc.project}")
    print(f"源文件    : {doc.source_path}")
    print(f"平台/缩放 : {doc.platform} / {doc.scale}   tags={doc.tags}")
    print(f"文档 GUID : {doc.guid}")
    print(f"画板      : {doc.name}  {doc.width}x{doc.height}  (retina {doc.retina_scale}x)")
    print(f"元素      : {st['elements']}  {st['kinds']}")
    print(f"字体      : {', '.join(st['fonts'])}   字号 {st['font_sizes']}")
    print(f"资源      : {len(doc.assets)} 组 / {sum(len(a.variants) for a in doc.assets)} 个文件")
    if doc.thumb_png:
        im = doc.thumb_image()
        print(f"缩略图    : {im.width}x{im.height} {len(doc.thumb_png)}B")
    if doc.artboard_png:
        im = doc.artboard_image()
        print(f"画板整图  : {im.width}x{im.height} {len(doc.artboard_png)}B")
    print(f"资源指纹  : {doc.asset_fingerprint}")
    return 0


def _safe_name(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", s).strip(" .")
    return s or "unnamed"


def cmd_assets(doc: PxcpDoc, args) -> int:
    out = args.output or "assets"
    os.makedirs(out, exist_ok=True)
    for a in doc.assets:
        d = os.path.join(out, _safe_name(f"{a.name}"))
        os.makedirs(d, exist_ok=True)
        for v in a.variants:
            if args.max_density and (v.density or 0) * 100 > args.max_density + 1e-6:
                continue
            ext = v.fmt if v.fmt in ("png", "svg") else "bin"
            fn = os.path.join(d, f"{v.name}.{ext}")
            with open(fn, "wb") as fh:
                fh.write(v.data)
        if args.largest:
            best = a.best_png(max_density=args.max_density)
            if best:
                with open(os.path.join(out, _safe_name(a.name) + ".png"), "wb") as fh:
                    fh.write(best.data)
    if doc.thumb_png:
        with open(os.path.join(out, "0-thumbnail.png"), "wb") as fh:
            fh.write(doc.thumb_png)
    if doc.artboard_png:
        with open(os.path.join(out, f"0-artboard@{doc.retina_scale}x.png"), "wb") as fh:
            fh.write(doc.artboard_png)
    print(f"已导出 {len(doc.assets)} 组资源 + 预览图 -> {out}")
    return 0


def cmd_elements(doc: PxcpDoc, args) -> int:
    items = [simplify_element(doc, el) for el in doc.elements]
    if args.csv:
        print("idx,kind,name,x,y,w,h,fill,text")
        for i, e in enumerate(items):
            fill = e.get("fill", [{}])[0].get("color", "") if e.get("fill") else ""
            txt = (e.get("text") or "").replace('"', "'")
            print(f'{i},{e["kind"]},"{e["name"]}",{e["x"]},{e["y"]},{e["width"]},{e["height"]},{fill},"{txt}"')
        return 0
    out = {"artboard": {"name": doc.name, "width": doc.width, "height": doc.height},
           "elements": items}
    text = json.dumps(out, ensure_ascii=False, indent=1 if args.pretty else None)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"-> {args.output}")
    else:
        print(text)
    return 0



# --------------------------------------------------------------------------- #
# rendering (Pillow)
# --------------------------------------------------------------------------- #
_FAMILY_CACHE: dict[str, set] = {}

SUBSTITUTES = {
    "impact": ["Liberation Sans Narrow", "Nimbus Sans Narrow", "DejaVu Sans Condensed"],
    "din": ["DejaVu Sans Condensed", "Liberation Sans"],
    "helveticaneue": ["Liberation Sans", "DejaVu Sans"],
    "helvetica neue": ["Liberation Sans", "DejaVu Sans"],
    "pingfang sc": ["Noto Sans CJK SC", "Noto Sans SC"],
    "harmonyos sans sc": ["Noto Sans CJK SC", "Noto Sans SC"],
    "微软雅黑": ["Noto Sans CJK SC"],
    "microsoft yahei": ["Noto Sans CJK SC"],
}


def _installed_families() -> set:
    if "fam" in _FAMILY_CACHE:
        return _FAMILY_CACHE["fam"]
    fams = set()
    try:
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True,
                             text=True, timeout=8, check=False).stdout
        for line in out.splitlines():
            for name in line.split(","):
                fams.add(name.strip().lower())
    except Exception:
        pass
    _FAMILY_CACHE["fam"] = fams
    return fams


def _resolve_family(family: str) -> str:
    fams = _installed_families()
    if family and family.lower() in fams:
        return family
    key = (family or "").lower().replace(" ", "")
    for cand, subs in SUBSTITUTES.items():
        if cand in key:
            for s in subs:
                if s.lower() in fams:
                    return s
    return "Noto Sans CJK SC"


@lru_cache(maxsize=512)
def load_font(family: str, px: int, bold: bool = False):
    from PIL import ImageFont
    fam = _resolve_family(family)
    pattern = f"{fam}:weight={'bold' if bold else 'regular'}"
    path, index = None, 0
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}\t%{index}", pattern],
                             capture_output=True, text=True, timeout=5, check=False).stdout
        p, i = out.split("\t")
        path, index = p, int(i or 0)
    except Exception:
        pass
    if not path:
        path, index = "/usr/share/fonts/google-noto-sans-cjk-fonts/NotoSansCJK-Regular.ttc", 2
    try:
        return ImageFont.truetype(path, max(1, int(round(px))), index=index)
    except Exception:
        return ImageFont.load_default()


def _rgba(v: int, alpha_mul: float = 1.0):
    r, g, b, a = color_of(v)
    return (r, g, b, max(0, min(255, int(round(a * alpha_mul)))))


def _fill_color(el):
    """返回 (type, color/gradient) 或 None。"""
    vi = el.get("vectorInfo") or {}
    if not vi.get("filled"):
        return None
    colors = (vi.get("fill") or {}).get("colors") or []
    if not colors:
        return None
    c = colors[0]
    if c.get("gradientColor", {}).get("colors"):
        return ("gradient", c["gradientColor"])
    sc = (c.get("solidColor") or {}).get("color", 0)
    return ("solid", sc)


def _stroke(el):
    styles = ((el.get("vectorInfo") or {}).get("stroke") or {}).get("styles") or []
    if not styles:
        return None
    s = styles[0]
    col = ((s.get("color") or {}).get("solidColor") or {}).get("color", 0)
    return {"color": col, "width": s.get("thickness", 1), "position": s.get("position", "inside"),
            "dash": ((el.get("vectorInfo") or {}).get("stroke") or {}).get("dashSet") or []}


def _corners(el, scale: float):
    r = (el.get("vectorInfo") or {}).get("radius") or []
    if not r:
        return None
    vals = [float(v) * scale for v in (r if len(r) == 4 else [r[0]] * 4)]
    if max(vals) <= 0:
        return None
    return tuple(vals)


def _lerp_color(c1, c2, t):
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2, strict=True))


def _stops(grad) -> list[tuple[float, tuple]]:
    pos = grad.get("colorPos") or []
    cols = grad.get("colors") or []
    out = []
    for i, col in enumerate(cols):
        p = pos[i] if i < len(pos) else (i / max(1, len(cols) - 1))
        out.append((float(p), _rgba(col)))
    out.sort(key=lambda x: x[0])
    if not out:
        out = [(0.0, (0, 0, 0, 255)), (1.0, (0, 0, 0, 255))]
    if out[0][0] > 0:
        out.insert(0, (0.0, out[0][1]))
    if out[-1][0] < 1:
        out.append((1.0, out[-1][1]))
    return out


def _sample(stops, t):
    t = max(0.0, min(1.0, t))
    prev = stops[0]
    for p, c in stops:
        if t <= p:
            if p <= prev[0]:
                return c
            k = (t - prev[0]) / (p - prev[0])
            return _lerp_color(prev[1], c, k)
        prev = (p, c)
    return stops[-1][1]


def gradient_image(w: int, h: int, grad: dict) -> Image.Image:
    """线性渐变（角度按 CSS 约定：0=向上，90=向右）。"""
    from PIL import Image, ImageDraw
    stops = _stops(grad)
    angle = float(grad.get("angle", 90) or 0)
    ang = math.radians(angle)
    dx, dy = math.sin(ang), -math.cos(ang)
    if grad.get("type") not in (None, "", "linear"):
        pass
    cx, cy = w / 2.0, h / 2.0
    half = (abs(w * dx) + abs(h * dy)) / 2.0
    half = max(half, 0.5)
    img = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    n = max(2, min(512, int(half * 2)))
    step = (2 * half) / n
    px, py = -dy, dx
    ext = half * 2 + max(w, h)
    for i in range(n + 1):
        t = i / n
        col = _sample(stops, t)
        s = -half + 2 * half * t
        ax, ay = cx + dx * s, cy + dy * s
        d.line([(ax - px * ext, ay - py * ext), (ax + px * ext, ay + py * ext)],
               fill=col, width=max(1, int(math.ceil(step)) + 2))
    return img


def _tile_from_shape(el, w: int, h: int, scale: float, alpha: float):
    """把元素（填充+描边）画到 w*h 的透明图中。"""
    from PIL import Image, ImageDraw
    layer = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    corners = _corners(el, scale)
    fill = _fill_color(el)
    stroke = _stroke(el)
    box = [0, 0, max(0, w - 1), max(0, h - 1)]
    if fill:
        if fill[0] == "solid":
            col = _rgba(fill[1], alpha)
            if col[3] > 0:
                d = ImageDraw.Draw(layer)
                if corners:
                    d.rounded_rectangle(box, radius=0, fill=col, corners=corners)
                else:
                    d.rectangle(box, fill=col)
        else:
            g = gradient_image(max(1, w), max(1, h), fill[1])
            if alpha < 1:
                a = g.getchannel("A").point(lambda v: int(v * alpha))
                g.putalpha(a)
            mask = Image.new("L", (max(1, w), max(1, h)), 0)
            md = ImageDraw.Draw(mask)
            if corners:
                md.rounded_rectangle(box, radius=0, fill=255, corners=corners)
            else:
                md.rectangle(box, fill=255)
            layer.paste(g, (0, 0), mask)
    if stroke and stroke["width"] > 0:
        sw = max(1, int(round(stroke["width"] * scale)))
        col = _rgba(stroke["color"], alpha)
        d = ImageDraw.Draw(layer)
        if corners:
            d.rounded_rectangle(box, radius=0, outline=col, width=sw, corners=corners)
        else:
            d.rectangle(box, outline=col, width=sw)
    return layer


def _shadow_tiles(el, w: int, h: int, scale: float, alpha: float):
    from PIL import Image, ImageDraw, ImageFilter
    out = []
    for sh in ((el.get("effectInfo") or {}).get("shadows") or []):
        if sh.get("inner"):
            continue
        blur = max(0.0, float(sh.get("blur", 0))) * scale
        spread = float(sh.get("spread", 0)) * scale
        ox = float(sh.get("x", 0)) * scale
        oy = float(sh.get("y", 0)) * scale
        pad = int(math.ceil(blur * 1.6 + abs(spread) + 4))
        tw, th = w + pad * 2, h + pad * 2
        layer = Image.new("RGBA", (max(1, tw), max(1, th)), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        corners = _corners(el, scale)
        box = [pad - spread, pad - spread, pad + w - 1 + spread, pad + h - 1 + spread]
        col = _rgba(sh.get("color", 0), alpha)
        if corners:
            d.rounded_rectangle(box, radius=0, fill=col, corners=corners)
        else:
            d.rectangle(box, fill=col)
        if blur > 0:
            layer = layer.filter(ImageFilter.GaussianBlur(blur / 2.0))
        out.append((layer, -pad + ox, -pad + oy))
    return out


def _draw_line(canvas, el, scale, alpha):
    from PIL import ImageDraw
    ri = el["rectInfo"]
    st = _stroke(el)
    if not st:
        return
    x, y = ri["x"] * scale, ri["y"] * scale
    w, h = ri["width"] * scale, ri["height"] * scale
    sw = max(1, int(round(st["width"] * scale)))
    col = _rgba(st["color"], alpha)
    d = ImageDraw.Draw(canvas)
    if h <= 0.5:
        d.line([(x, y), (x + max(w, 1), y)], fill=col, width=sw)
    elif w <= 0.5:
        d.line([(x, y), (x, y + max(h, 1))], fill=col, width=sw)


def _draw_text(canvas, el, scale, alpha):
    from PIL import Image, ImageDraw
    fi = el.get("fontInfo") or {}
    text = fi.get("text") or ""
    if not text:
        return
    f = (fi.get("fonts") or [{}])[0]
    ri = el["rectInfo"]
    x, y = ri["x"] * scale, ri["y"] * scale
    w, h = ri["width"] * scale, ri["height"] * scale
    size = float(f.get("size") or 14) * scale
    font = load_font(f.get("name") or "", size, bool(f.get("bold")))
    col = _rgba(f.get("color", 0), alpha)
    if col[3] == 0:
        return
    lh = float(f.get("lineHeight") or size) * scale
    align = (f.get("alignment") or "left").lower()
    lines = text.split("\n")
    # 文本可能溢出矩形，画到扩大后的画布上
    pad = int(size * 0.6) + 4
    tw, th = int(w + pad * 2), int(h + pad * 2)
    layer = Image.new("RGBA", (max(1, tw), max(1, th)), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    base_y = pad - size * 0.055
    for i, line in enumerate(lines):
        if align.startswith("center"):
            anchor, tx = "ma", pad + w / 2
        elif align.startswith("right"):
            anchor, tx = "ra", pad + w
        else:
            anchor, tx = "la", pad
        d.text((tx, base_y + i * lh), line, font=font, fill=col, anchor=anchor)
    canvas.alpha_composite(layer, (int(round(x - pad)), int(round(y - pad))))


def _open_image(path_or_bytes):
    from PIL import Image
    if isinstance(path_or_bytes, (bytes, bytearray)):
        return Image.open(io.BytesIO(path_or_bytes))
    return Image.open(path_or_bytes)


def _draw_image(canvas, doc, el, scale, alpha, external):
    from PIL import Image
    ri = el["rectInfo"]
    x, y = ri["x"] * scale, ri["y"] * scale
    w, h = ri["width"] * scale, ri["height"] * scale
    if w < 1 or h < 1:
        return
    eid = (el.get("baseInfo") or {}).get("id")
    src = None
    if external and eid in external:
        src = external[eid]
    else:
        a = doc.asset_by_guid.get(eid)
        if a:
            v = a.best_png(ri["width"], ri["height"], prefer=max(scale, 1.0))
            if v:
                src = v.data
    if not src:
        return
    try:
        im = _open_image(src).convert("RGBA")
    except Exception:
        return
    im = im.resize((max(1, int(round(w))), max(1, int(round(h)))), Image.LANCZOS)
    if alpha < 1:
        a = im.getchannel("A").point(lambda v: int(v * alpha))
        im.putalpha(a)
    canvas.alpha_composite(im, (int(round(x)), int(round(y))))


def _paint_order(doc: PxcpDoc, external: dict) -> list[dict]:
    """决定绘制顺序。

    .pxcp 里画板背景图（整幅、透明、外链）通常排在「背景色矩形」之后，
    若直接按数组顺序绘制会被后面的整幅矩形盖住。这里把「开头连续的整幅元素」
    里的背景图占位元素挪到这些矩形之后、正文之前，符合设计稿的实际层叠。
    """
    els = doc.elements
    # 注意：rectInfo 是设计稿坐标（未乘 scale），这里必须用 doc.width/height
    full = 0.9 * doc.width * doc.height

    def is_full(el):
        r = el.get("rectInfo") or {}
        return (r.get("width", 0) * r.get("height", 0)) >= full

    lead = 0
    while lead < len(els) and is_full(els[lead]):
        lead += 1
    if lead <= 1:
        return els

    def is_bg_ph(el):
        return doc.element_kind(el) == "empty" and el["baseInfo"]["id"] in external

    head = els[:lead]
    phs = [e for e in head if is_bg_ph(e)]
    if not phs:
        return els
    rest = [e for e in head if not is_bg_ph(e)]
    return rest + phs + els[lead:]


def render_document(doc: PxcpDoc, scale: float = 1.0, external: dict | None = None,
                    background=(0, 0, 0, 0), warn=None):
    """把文档渲染为 PIL RGBA 图。"""
    from PIL import Image
    W = max(1, int(round(doc.width * scale)))
    H = max(1, int(round(doc.height * scale)))
    canvas = Image.new("RGBA", (W, H), background)
    external = external or {}
    for el in _paint_order(doc, external):
        ri = el.get("rectInfo") or {}
        w = int(round(ri.get("width", 0) * scale))
        h = int(round(ri.get("height", 0) * scale))
        opacity = float((el.get("baseInfo") or {}).get("opacity", 1) or 0)
        if opacity <= 0:
            continue
        x = int(round(ri.get("x", 0) * scale))
        y = int(round(ri.get("y", 0) * scale))
        if w <= 1 or h <= 1:
            _draw_line(canvas, el, scale, opacity)
            continue
        # 阴影
        for layer, ox, oy in _shadow_tiles(el, w, h, scale, opacity):
            canvas.alpha_composite(layer, (x + int(round(ox)), y + int(round(oy))))
        if doc.element_kind(el) == "text":
            _draw_text(canvas, el, scale, opacity)
        elif doc.element_kind(el) == "image":
            _draw_image(canvas, doc, el, scale, opacity, external)
        else:
            if _has_visible_fill(el) or _stroke(el):
                tile = _tile_from_shape(el, w, h, scale, opacity)
                canvas.alpha_composite(tile, (x, y))
            elif doc.element_kind(el) == "empty":
                _draw_image(canvas, doc, el, scale, opacity, external)
    return canvas


def _find_external_images(doc: PxcpDoc) -> dict:
    """为外链图片占位元素（无填充/无内嵌资源）匹配同目录图片。"""
    from PIL import Image
    folder = os.path.dirname(doc.path)
    cands = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return {}
    for fn in names:
        if not fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
            continue
        p = os.path.join(folder, fn)
        try:
            with Image.open(p) as im:
                cands.append((p, im.size))
        except Exception:
            continue
    out = {}
    used = set()
    for el in doc.elements:
        if doc.element_kind(el) != "empty":
            continue
        if not (el.get("baseInfo") or {}).get("name"):
            continue
        ri = el["rectInfo"]
        w, h = ri["width"], ri["height"]
        if w * h < doc.width * doc.height * 0.05 or h == 0:
            continue
        aria = w / h
        for p, (iw, ih) in cands:
            if ih == 0 or p in used:
                continue
            # 尺寸必须覆盖元素且不过分大（防止小卡片误配整张背景图）
            if iw < w * 0.98 or ih < h * 0.98 or iw > w * 3 or ih > h * 3:
                continue
            if abs(aria - iw / ih) / aria < 0.005:
                out[el["baseInfo"]["id"]] = p
                used.add(p)
                break
    return out


def cmd_render(doc: PxcpDoc, args) -> int:
    from PIL import Image
    external = _find_external_images(doc)
    for spec in args.fill_image or []:
        if "=" not in spec:
            continue
        key, path = spec.split("=", 1)
        key = key.strip()
        path = os.path.expanduser(path.strip())
        if key in doc.asset_by_guid or key in {e["baseInfo"]["id"] for e in doc.elements}:
            external[key] = path
            continue
        # 允许 "1920x1080=bg.png" 或 "元素名=bg.png"
        if "x" in key and key.replace("x", "").isdigit():
            w, h = (int(v) for v in key.split("x"))
            for el in doc.elements:
                ri = el["rectInfo"]
                if abs(ri["width"] - w) < 2 and abs(ri["height"] - h) < 2:
                    external[el["baseInfo"]["id"]] = path
        else:
            for el in doc.elements:
                if el["baseInfo"]["name"] == key:
                    external[el["baseInfo"]["id"]] = path
    img = render_document(doc, args.scale, external,
                          background=(0, 0, 0, 0))
    if args.background:
        bg = Image.open(os.path.expanduser(args.background)).convert("RGB")
        bg = bg.resize(img.size, Image.LANCZOS).convert("RGBA")
        bg.alpha_composite(img)
        img = bg
    out = args.output
    if img.mode == "RGBA":
        img.save(out)
    else:
        img.save(out)
    used = len(external)
    if used:
        names = {el["baseInfo"]["id"]: (el["baseInfo"].get("name") or el["baseInfo"]["id"])
                 for el in doc.elements}
        for eid, path in external.items():
            print(f"外链图片: {path} -> 元素「{names.get(eid, eid)}」")
    print(f"已渲染 {doc.width}x{doc.height} @{args.scale}x -> {out}"
          f"（外链图片 {used} 张）")
    print("提示: .pxcp 不保存矢量路径，渐变文字/曲线/装饰形状只能用外接矩形近似；"
          "看设计原图请用 viewer。")
    return 0


def cmd_viewer(doc: PxcpDoc, args) -> int:
    from pxpull_viewer import build_viewer
    return build_viewer(doc, args.output, max_density=args.max_density,
                        densities=args.densities)



def cmd_slice(doc: PxcpDoc, args) -> int:
    """按元素区域从画板整图上裁切出图片（相当于“切图”）。"""
    if not doc.artboard_png:
        print("错误: 该文件没有内嵌画板整图", file=sys.stderr)
        return 1
    art = doc.artboard_image().convert("RGBA")
    k = art.width / doc.width if doc.width else 1.0
    outdir = args.output or "slices"
    os.makedirs(outdir, exist_ok=True)
    targets = []
    if args.index:
        for part in args.index.split(","):
            part = part.strip()
            if part.isdigit() and int(part) < len(doc.elements):
                targets.append(int(part))
    if args.name:
        needle = args.name.lower()
        for i, el in enumerate(doc.elements):
            nm = (el["baseInfo"].get("name") or "") + " " + (el["fontInfo"].get("text") or "")
            if needle in nm.lower():
                targets.append(i)
    if not targets and not args.all and (args.name or args.index):
        cond = f"--name {args.name!r}" if args.name else f"--index {args.index!r}"
        print(f"错误: 没有匹配的图层（{cond}）；要用全部元素请加 --all", file=sys.stderr)
        return 1
    if args.all or not targets:
        for i, el in enumerate(doc.elements):
            ri = el["rectInfo"]
            if ri["width"] * ri["height"] >= args.min_area:
                targets.append(i)
    seen = set()
    n = 0
    for i in sorted(set(targets)):
        el = doc.elements[i]
        ri = el["rectInfo"]
        x, y, w, h = ri["x"], ri["y"], ri["width"], ri["height"]
        pad = args.pad
        box = (max(0, int(round((x - pad) * k))), max(0, int(round((y - pad) * k))),
               min(art.width, int(round((x + w + pad) * k))),
               min(art.height, int(round((y + h + pad) * k))))
        if box[2] - box[0] < 1 or box[3] - box[1] < 1:
            continue
        name = el["baseInfo"].get("name") or el["fontInfo"].get("text") or "slice"
        fn = f"{i:03d}-{_safe_name(name)[:40]}.png"
        base, ext = os.path.splitext(fn)
        j = 2
        while fn in seen:
            fn = f"{base}-{j}{ext}"
            j += 1
        seen.add(fn)
        art.crop(box).save(os.path.join(outdir, fn))
        n += 1
    print(f"已裁切 {n} 张 -> {outdir}（源图 {art.width}x{art.height}，{k:g}x）")
    return 0


def cmd_export(doc: PxcpDoc, args) -> int:
    """一次性导出：画板图 + 元素 JSON + 切图 + 查看器。"""
    from pxpull_viewer import build_viewer
    out = args.output or "pxpull-export"
    os.makedirs(out, exist_ok=True)
    if doc.artboard_png:
        with open(os.path.join(out, f"artboard@{doc.retina_scale}x.png"), "wb") as fh:
            fh.write(doc.artboard_png)
    if doc.thumb_png:
        with open(os.path.join(out, "thumbnail.png"), "wb") as fh:
            fh.write(doc.thumb_png)
    rc = build_viewer(doc, out, max_density=args.max_density, densities=args.densities)
    print(f"全部导出完成 -> {out}")
    return rc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pxpull",
        description="解析/查看/导出 PxCook .pxcp 设计文件（Linux 原生，无需 Windows）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  pxpull.py info  design.pxcp
  pxpull.py assets design.pxcp -o out/assets --largest
  pxpull.py elements design.pxcp -o out/elements.json --pretty
  pxpull.py render design.pxcp -o out/preview.png --scale 2
  pxpull.py viewer design.pxcp -o out/
""")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("info", help="查看文件概要")
    s.add_argument("file")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("assets", help="导出内嵌切图/图标/整图")
    s.add_argument("file")
    s.add_argument("-o", "--output")
    s.add_argument("--largest", action="store_true", help="为每组资产额外导出一张最大 PNG")
    s.add_argument("--max-density", type=int, choices=[120, 160, 240, 320, 480, 640],
                   help="只导出不高于该密度的变体（默认全部 7 档）")
    s.set_defaults(func=cmd_assets)

    s = sub.add_parser("elements", help="导出元素 JSON / CSV")
    s.add_argument("file")
    s.add_argument("-o", "--output")
    s.add_argument("--pretty", action="store_true")
    s.add_argument("--csv", action="store_true")
    s.set_defaults(func=cmd_elements)

    s = sub.add_parser("render", help="把设计图渲染成 PNG")
    s.add_argument("file")
    s.add_argument("-o", "--output", default="preview.png")
    s.add_argument("--scale", type=float, default=1.0)
    s.add_argument("--fill-image", action="append", default=[], metavar="WxH=PATH",
                   help="为外链图片占位元素指定图片，如 1920x1080=bg.png")
    s.add_argument("--background", metavar="PATH", help="垫一张背景图（如设计稿背景）")
    s.set_defaults(func=cmd_render)

    s = sub.add_parser("viewer", help="导出可在浏览器中查看/点选的 HTML")
    s.add_argument("file")
    s.add_argument("-o", "--output", default="viewer")
    s.add_argument("--max-density", type=int, choices=[120, 160, 240, 320, 480, 640],
                   default=320, help="切图最大密度（默认 320，即 3.2x）")
    s.add_argument("--densities", choices=["best", "all"], default="best",
                   help="切图导出策略：best=每组只留最高可用档（默认），all=保留全部档位")
    s.add_argument("--all-densities", dest="densities", action="store_const", const="all",
                   help="等价于 --densities all")
    s.set_defaults(func=cmd_viewer)

    s = sub.add_parser("slice", help="按元素区域从画板整图裁切图片")
    s.add_argument("file")
    s.add_argument("-o", "--output", default="slices")
    s.add_argument("--all", action="store_true", help="导出所有元素区域")
    s.add_argument("--name", help="按名称/文本子串过滤")
    s.add_argument("--index", help="按元素序号，逗号分隔")
    s.add_argument("--pad", type=float, default=0, help="外扩边距（设计像素）")
    s.add_argument("--min-area", type=float, default=16, help="--all 时的最小面积")
    s.set_defaults(func=cmd_slice)

    s = sub.add_parser("export", help="一次性导出画板图/JSON/切图/查看器")
    s.add_argument("file")
    s.add_argument("-o", "--output", default="pxpull-export")
    s.add_argument("--max-density", type=int, choices=[120, 160, 240, 320, 480, 640],
                   default=320, help="切图最大密度（默认 320；传 640 为最高档）")
    s.add_argument("--densities", choices=["best", "all"], default="best",
                   help="切图导出策略：best=每组只留最高可用档（默认，体积小），all=全部档位")
    s.add_argument("--all-densities", dest="densities", action="store_const", const="all",
                   help="等价于 --densities all")
    s.set_defaults(func=cmd_export)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        doc = parse_file(args.file)
    except (OSError, PxcpError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    if args.cmd in ("render", "viewer"):
        return args.func(doc, args)
    return args.func(doc, args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # 允许 `pxpull.py info ... | head`
        os._exit(0)
