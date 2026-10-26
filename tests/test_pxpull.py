"""pxpull 解析器与渲染器的单元测试。"""

from __future__ import annotations

import json

import pytest
from conftest import IMG_ID, PHOTO_ID

import pxpull


def test_parse_header_and_doc(sample_pxcp):
    doc = pxpull.parse_file(sample_pxcp)
    assert doc.version == 399
    assert doc.project == "测试项目"
    assert doc.platform == "Web"
    assert doc.name == "合成画板"
    assert (doc.width, doc.height, doc.retina_scale) == (64, 36, 2)
    assert len(doc.elements) == 5
    assert doc.thumb_png.startswith(b"\x89PNG")
    assert doc.artboard_png.startswith(b"\x89PNG")


def test_assets(sample_pxcp):
    doc = pxpull.parse_file(sample_pxcp)
    assert len(doc.assets) == 1
    asset = doc.asset_by_guid[IMG_ID]
    assert asset.name == "图标"
    assert [v.name for v in asset.variants] == ["d120", "d160"]
    assert asset.svg().fmt == "svg"
    assert asset.best_png().fmt == "png"
    # 8px / 1.2 = 6.67 设计像素
    nw, nh = asset.natural_size
    assert nw == pytest.approx(8 / 1.2) and nh == pytest.approx(8 / 1.2)


def test_element_kind(sample_pxcp):
    doc = pxpull.parse_file(sample_pxcp)
    kinds = [doc.element_kind(el) for el in doc.elements]
    assert kinds == ["shape", "empty", "shape", "text", "image"]


def test_paint_order_moves_background_placeholder(sample_pxcp):
    doc = pxpull.parse_file(sample_pxcp)
    external = {PHOTO_ID: "photo.png"}
    order = pxpull._paint_order(doc, external)
    ids = [el["baseInfo"]["id"] for el in order]
    # 占位元素原本在 index 1，必须被挪到两张整幅矩形之后
    assert ids.index(PHOTO_ID) == 2
    assert ids[0] == "0000" and ids[1] != PHOTO_ID


def test_paint_order_independent_of_scale(sample_pxcp):
    """回归：_paint_order 只接收 doc 尺寸，不得再传画布像素尺寸。"""
    doc = pxpull.parse_file(sample_pxcp)
    order = pxpull._paint_order(doc, {PHOTO_ID: "photo.png"})
    assert [e["baseInfo"]["id"] for e in order].index(PHOTO_ID) == 2


def test_color_of():
    assert pxpull.color_of(0xFF001322) == (0, 0x13, 0x22, 0xFF)
    assert pxpull.color_of(0x80010203) == (1, 2, 3, 0x80)


def test_has_visible_fill(sample_pxcp):
    doc = pxpull.parse_file(sample_pxcp)
    bg, photo, rect_b = doc.elements[0], doc.elements[1], doc.elements[2]
    assert pxpull._has_visible_fill(bg)
    assert not pxpull._has_visible_fill(photo)
    assert pxpull._has_visible_fill(rect_b)


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_render_applies_external_background(sample_pxcp, photo_png, scale):
    """有/无外链背景图，渲染结果必须不同（1x 与 2x 都要成立）。"""
    doc = pxpull.parse_file(sample_pxcp)
    probe = (int(32 * scale), int(18 * scale))
    plain = pxpull.render_document(doc, scale, {}).convert("RGB")
    with_bg = pxpull.render_document(doc, scale, {PHOTO_ID: photo_png}).convert("RGB")

    r_plain = plain.getpixel(probe)[0]
    r_with = with_bg.getpixel(probe)[0]
    # 红色照片以 50% 叠在深蓝底上，红通道应显著升高
    assert r_plain < 16, f"无背景时不该有红色: {plain.getpixel(probe)}"
    assert r_with > 60, f"{scale}x 下背景图未生效: {with_bg.getpixel(probe)}"
    assert with_bg.getpixel(probe) != plain.getpixel(probe)


def test_simplify_element(sample_pxcp):
    doc = pxpull.parse_file(sample_pxcp)
    s = pxpull.simplify_element(doc, doc.elements[3])
    assert s["kind"] == "text"
    assert s["text"] == "你好"
    assert s["font"]["size"] == 12
    assert s["width"] == 40


def test_rejects_non_pxcp(tmp_path):
    bad = tmp_path / "bad.pxcp"
    bad.write_bytes(b"NOPE" + b"\x00" * 64)
    with pytest.raises(pxpull.PxcpError):
        pxpull.parse_file(str(bad))


def test_info_command(sample_pxcp, capsys):
    doc = pxpull.parse_file(sample_pxcp)
    args = type("A", (), {})()
    assert pxpull.cmd_info(doc, args) == 0
    out = capsys.readouterr().out
    assert "合成画板" in out and "64x36" in out


def test_elements_json_roundtrip(sample_pxcp, tmp_path):
    doc = pxpull.parse_file(sample_pxcp)
    out = tmp_path / "elements.json"
    args = type("A", (), {"csv": False, "pretty": True, "output": str(out)})()
    assert pxpull.cmd_elements(doc, args) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["artboard"]["width"] == 64
    assert len(data["elements"]) == 5
    assert data["elements"][3]["text"] == "你好"


def test_slice_by_name(sample_pxcp, tmp_path):
    doc = pxpull.parse_file(sample_pxcp)
    out = tmp_path / "slices"
    args = type("A", (), {"output": str(out), "index": None, "name": "图标",
                          "all": False, "min_area": 0, "pad": 0})()
    assert pxpull.cmd_slice(doc, args) == 0
    files = sorted(p.name for p in out.iterdir())
    assert len(files) == 1 and files[0].endswith("图标.png")


def test_slice_unknown_name_errors(sample_pxcp, tmp_path, capsys):
    doc = pxpull.parse_file(sample_pxcp)
    out = tmp_path / "slices"
    args = type("A", (), {"output": str(out), "index": None, "name": "不存在的名字",
                          "all": False, "min_area": 0, "pad": 0})()
    assert pxpull.cmd_slice(doc, args) == 1
    assert "没有匹配的图层" in capsys.readouterr().err
    assert list(out.iterdir()) == []
