"""Shared vector icons for ClearShot's PyQt UI."""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QBrush,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtSvg import QSvgRenderer


SVG_PATHS = {
    "pen": """
        <path d="M12 20h9"/>
        <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>
        <path d="m14 6 4 4"/>
    """,
    "line": """<path d="M5 12h14"/>""",
    "arrow": """
        <path d="M7 17 17 7"/>
        <path d="M8 7h9v9"/>
    """,
    "rect": """<rect x="5" y="5" width="14" height="14" rx="2.5"/>""",
    "ellipse": """<ellipse cx="12" cy="12" rx="7.5" ry="6.5"/>""",
    "text": """
        <path d="M4 7V4h16v3"/>
        <path d="M9 20h6"/>
        <path d="M12 4v16"/>
    """,
    "palette": """
        <path d="M12 3a9 9 0 0 0 0 18h1.5a1.5 1.5 0 0 0 1.1-2.5 1.5 1.5 0 0 1 1.1-2.5H18a6 6 0 0 0 0-12z"/>
        <circle cx="7.5" cy="10" r=".8"/>
        <circle cx="10.5" cy="7.5" r=".8"/>
        <circle cx="14" cy="7.5" r=".8"/>
        <circle cx="16.5" cy="10.5" r=".8"/>
    """,
    "undo": """
        <path d="M9 14 4 9l5-5"/>
        <path d="M4 9h10.5a5.5 5.5 0 1 1 0 11H11"/>
    """,
    "redo": """
        <path d="m15 14 5-5-5-5"/>
        <path d="M20 9H9.5a5.5 5.5 0 1 0 0 11H13"/>
    """,
    "trash": """
        <path d="M3 6h18"/>
        <path d="M8 6V4h8v2"/>
        <path d="M19 6 18 20H6L5 6"/>
        <path d="M10 11v5"/>
        <path d="M14 11v5"/>
    """,
    "copy": """
        <rect x="8" y="8" width="12" height="12" rx="2"/>
        <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>
    """,
    "save": """
        <path d="M15.5 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V8.5z"/>
        <path d="M15 3v5H7V3"/>
        <path d="M7 21v-7h10v7"/>
    """,
    "quick_save": """<path d="M13 2 4 14h7l-1 8 10-13h-7z"/>""",
    "capture_region": """
        <path d="M4 8V5a1 1 0 0 1 1-1h3"/>
        <path d="M16 4h3a1 1 0 0 1 1 1v3"/>
        <path d="M20 16v3a1 1 0 0 1-1 1h-3"/>
        <path d="M8 20H5a1 1 0 0 1-1-1v-3"/>
        <path d="M9 12h6"/>
        <path d="M12 9v6"/>
    """,
    "fullscreen": """
        <rect x="4" y="5" width="16" height="11" rx="2"/>
        <path d="M8 20h8"/>
        <path d="M12 16v4"/>
    """,
    "folder": """
        <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1"/>
        <path d="M3 10h18l-2 9H5z"/>
    """,
    "settings": """
        <path d="M4 7h10"/>
        <path d="M18 7h2"/>
        <path d="M4 17h2"/>
        <path d="M10 17h10"/>
        <circle cx="16" cy="7" r="2"/>
        <circle cx="8" cy="17" r="2"/>
    """,
    "help": """
        <circle cx="12" cy="12" r="9"/>
        <path d="M9.5 9a2.7 2.7 0 0 1 5.1 1.3c0 1.9-2.6 2.1-2.6 4"/>
        <path d="M12 18h.01"/>
    """,
    "refresh": """
        <path d="M20 6v5h-5"/>
        <path d="M4 18v-5h5"/>
        <path d="M18.8 10A7 7 0 0 0 6.3 7.3L4 9.5"/>
        <path d="M5.2 14a7 7 0 0 0 12.5 2.7L20 14.5"/>
    """,
    "check": """<path d="m5 12 4 4 10-10"/>""",
    "close": """
        <path d="M6 6l12 12"/>
        <path d="M18 6 6 18"/>
    """,
    "move": """
        <path d="M12 3v18"/>
        <path d="m8 7 4-4 4 4"/>
        <path d="m8 17 4 4 4-4"/>
        <path d="M3 12h18"/>
        <path d="m7 8-4 4 4 4"/>
        <path d="m17 8 4 4-4 4"/>
    """,
    "resize": """
        <path d="M15 3h6v6"/>
        <path d="m21 3-7 7"/>
        <path d="M9 21H3v-6"/>
        <path d="m3 21 7-7"/>
    """,
    "edit": """
        <path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
        <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L11 15l-4 1 1-4Z"/>
        <path d="m15 5 4 4"/>
    """,
    "editor": """
        <rect x="3.5" y="5" width="17" height="14" rx="2"/>
        <path d="M3.5 9h17"/>
        <path d="m6.5 17 3.5-4 3 3 2-2 2.5 3"/>
        <path d="M7.5 7h.01"/>
        <path d="M10.5 7h.01"/>
    """,
}


def ui_icon(
    name: str,
    color: str | QColor = "#f5f7fb",
    accent: str | QColor = "#0099ff",
    sizes: tuple[int, ...] = (16, 20, 24, 32),
) -> QIcon:
    """Build a scalable-looking QIcon from painted pixmaps."""
    icon = QIcon()
    for size in sizes:
        pixmap = QPixmap(QSize(size, size))
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_icon(painter, name, QRectF(0, 0, size, size), color, accent)
        painter.end()

        icon.addPixmap(pixmap)
    return icon


def paint_icon(
    painter: QPainter,
    name: str,
    rect: QRectF,
    color: str | QColor = "#f5f7fb",
    accent: str | QColor = "#0099ff",
) -> None:
    """Paint one named icon inside rect."""
    name = _normalize_name(name)
    r = QRectF(rect).adjusted(
        rect.width() * 0.12,
        rect.height() * 0.12,
        -rect.width() * 0.12,
        -rect.height() * 0.12,
    )
    stroke = max(1.7, min(r.width(), r.height()) * 0.12)
    fg = QColor(color)
    ac = QColor(accent)

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(fg, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name in SVG_PATHS:
        _draw_svg_icon(painter, r, SVG_PATHS[name], fg, stroke)
    elif name == "filled_rect":
        _draw_highlight_icon(painter, r, fg, ac, stroke)
    elif name == "blur":
        _draw_blur(painter, r, fg)
    elif name == "counter":
        painter.setPen(QPen(fg, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QBrush(ac))
        painter.drawEllipse(_box(r, 0.18, 0.16, 0.64, 0.68))
        _draw_text_glyph(painter, r, "1", QColor("#ffffff"), 0.54)
    else:
        _draw_text_glyph(painter, r, name[:1].upper() or "?", fg, 0.62)

    painter.restore()


def _normalize_name(name: str) -> str:
    aliases = {
        "highlight": "filled_rect",
        "filled": "filled_rect",
        "monitor": "fullscreen",
        "open_folder": "folder",
        "exit": "close",
        "color": "palette",
    }
    key = name.lower().strip().replace("-", "_").replace(" ", "_")
    return aliases.get(key, key)


def _pt(rect: QRectF, x: float, y: float) -> QPointF:
    return QPointF(rect.left() + rect.width() * x, rect.top() + rect.height() * y)


def _box(rect: QRectF, x: float, y: float, w: float, h: float) -> QRectF:
    return QRectF(
        rect.left() + rect.width() * x,
        rect.top() + rect.height() * y,
        rect.width() * w,
        rect.height() * h,
    )


def _draw_svg_icon(painter: QPainter, rect: QRectF, body: str, color: QColor, stroke: float) -> None:
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
      <g fill="none" stroke="{color.name()}" stroke-width="2.1"
         stroke-linecap="round" stroke-linejoin="round">
        {body}
      </g>
    </svg>
    """
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    renderer.render(painter, rect)


def _draw_highlight_icon(painter: QPainter, r: QRectF, color: QColor, accent: QColor, stroke: float) -> None:
    body = """
        <path d="M5 15 15 5l4 4-10 10H5z"/>
        <path d="M14 6l4 4"/>
        <path d="M5 19h14"/>
    """
    _draw_svg_icon(painter, r, body, color, stroke)
    fill = QColor(accent)
    fill.setAlpha(105)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(fill))
    painter.drawRoundedRect(_box(r, 0.2, 0.68, 0.6, 0.12), stroke * 0.5, stroke * 0.5)


def _draw_text_glyph(painter: QPainter, r: QRectF, text: str, color: QColor, scale: float) -> None:
    painter.setPen(QPen(color))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    font = QFont("Segoe UI")
    font.setBold(True)
    font.setPixelSize(max(8, int(min(r.width(), r.height()) * scale)))
    painter.setFont(font)
    painter.drawText(r, Qt.AlignmentFlag.AlignCenter, text)


def _draw_blur(painter: QPainter, r: QRectF, color: QColor) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    size = min(r.width(), r.height()) * 0.18
    for row in range(3):
        for col in range(3):
            c = QColor(color)
            c.setAlpha(220 if (row + col) % 2 == 0 else 120)
            painter.setBrush(QBrush(c))
            box = QRectF(
                r.left() + r.width() * (0.18 + col * 0.23),
                r.top() + r.height() * (0.18 + row * 0.23),
                size,
                size,
            )
            painter.drawRoundedRect(box, size * 0.18, size * 0.18)


def _draw_palette(painter: QPainter, r: QRectF, color: QColor, accent: QColor) -> None:
    painter.setPen(QPen(color, max(1.2, min(r.width(), r.height()) * 0.08)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(_box(r, 0.14, 0.18, 0.72, 0.62))
    painter.setPen(Qt.PenStyle.NoPen)
    for x, y, c in [
        (0.34, 0.38, QColor("#ff4d4d")),
        (0.5, 0.3, QColor("#ffd24d")),
        (0.64, 0.42, accent),
    ]:
        painter.setBrush(QBrush(c))
        painter.drawEllipse(_pt(r, x, y), r.width() * 0.055, r.height() * 0.055)
    painter.setBrush(QBrush(color))
    painter.drawEllipse(_pt(r, 0.56, 0.62), r.width() * 0.075, r.height() * 0.075)


def _draw_turn_arrow(painter: QPainter, r: QRectF, color: QColor, stroke: float, reverse: bool) -> None:
    if reverse:
        path = QPainterPath(_pt(r, 0.78, 0.72))
        path.cubicTo(_pt(r, 0.78, 0.38), _pt(r, 0.54, 0.26), _pt(r, 0.3, 0.38))
        painter.drawPath(path)
        painter.drawLine(_pt(r, 0.3, 0.38), _pt(r, 0.46, 0.2))
        painter.drawLine(_pt(r, 0.3, 0.38), _pt(r, 0.5, 0.48))
    else:
        path = QPainterPath(_pt(r, 0.22, 0.72))
        path.cubicTo(_pt(r, 0.22, 0.38), _pt(r, 0.46, 0.26), _pt(r, 0.7, 0.38))
        painter.drawPath(path)
        painter.drawLine(_pt(r, 0.7, 0.38), _pt(r, 0.54, 0.2))
        painter.drawLine(_pt(r, 0.7, 0.38), _pt(r, 0.5, 0.48))


def _draw_trash(painter: QPainter, r: QRectF, color: QColor, stroke: float) -> None:
    painter.drawLine(_pt(r, 0.24, 0.3), _pt(r, 0.76, 0.3))
    painter.drawLine(_pt(r, 0.4, 0.22), _pt(r, 0.6, 0.22))
    painter.drawRoundedRect(_box(r, 0.32, 0.34, 0.36, 0.46), stroke, stroke)
    painter.drawLine(_pt(r, 0.44, 0.43), _pt(r, 0.44, 0.7))
    painter.drawLine(_pt(r, 0.56, 0.43), _pt(r, 0.56, 0.7))


def _draw_copy(painter: QPainter, r: QRectF, color: QColor, stroke: float) -> None:
    painter.setPen(QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawRoundedRect(_box(r, 0.22, 0.28, 0.42, 0.48), stroke, stroke)
    painter.drawRoundedRect(_box(r, 0.36, 0.18, 0.42, 0.48), stroke, stroke)


def _draw_save(painter: QPainter, r: QRectF, color: QColor, stroke: float) -> None:
    painter.drawRoundedRect(_box(r, 0.2, 0.18, 0.6, 0.64), stroke, stroke)
    painter.drawLine(_pt(r, 0.34, 0.18), _pt(r, 0.34, 0.42))
    painter.drawLine(_pt(r, 0.34, 0.42), _pt(r, 0.66, 0.42))
    painter.drawRoundedRect(_box(r, 0.34, 0.58, 0.32, 0.18), stroke * 0.6, stroke * 0.6)


def _draw_bolt(painter: QPainter, r: QRectF, color: QColor) -> None:
    path = QPainterPath(_pt(r, 0.54, 0.12))
    path.lineTo(_pt(r, 0.28, 0.54))
    path.lineTo(_pt(r, 0.48, 0.54))
    path.lineTo(_pt(r, 0.38, 0.88))
    path.lineTo(_pt(r, 0.74, 0.42))
    path.lineTo(_pt(r, 0.52, 0.42))
    path.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawPath(path)


def _draw_crop_corners(painter: QPainter, r: QRectF) -> None:
    for x1, y1, x2, y2 in [
        (0.12, 0.38, 0.12, 0.12), (0.12, 0.12, 0.38, 0.12),
        (0.62, 0.12, 0.88, 0.12), (0.88, 0.12, 0.88, 0.38),
        (0.88, 0.62, 0.88, 0.88), (0.88, 0.88, 0.62, 0.88),
        (0.38, 0.88, 0.12, 0.88), (0.12, 0.88, 0.12, 0.62),
    ]:
        painter.drawLine(_pt(r, x1, y1), _pt(r, x2, y2))


def _draw_monitor(painter: QPainter, r: QRectF, color: QColor, stroke: float) -> None:
    painter.drawRoundedRect(_box(r, 0.14, 0.2, 0.72, 0.48), stroke, stroke)
    painter.drawLine(_pt(r, 0.5, 0.68), _pt(r, 0.5, 0.8))
    painter.drawLine(_pt(r, 0.36, 0.82), _pt(r, 0.64, 0.82))


def _draw_folder(painter: QPainter, r: QRectF, color: QColor, accent: QColor, stroke: float) -> None:
    fill = QColor(accent)
    fill.setAlpha(70)
    path = QPainterPath(_pt(r, 0.14, 0.32))
    path.lineTo(_pt(r, 0.4, 0.32))
    path.lineTo(_pt(r, 0.48, 0.42))
    path.lineTo(_pt(r, 0.86, 0.42))
    path.lineTo(_pt(r, 0.78, 0.8))
    path.lineTo(_pt(r, 0.16, 0.8))
    path.closeSubpath()
    painter.setPen(QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(QBrush(fill))
    painter.drawPath(path)


def _draw_sliders(painter: QPainter, r: QRectF, color: QColor, stroke: float) -> None:
    knob_r = max(2.0, min(r.width(), r.height()) * 0.09)
    rows = [(0.28, 0.34), (0.5, 0.66), (0.72, 0.46)]
    for y, knob_x in rows:
        painter.drawLine(_pt(r, 0.16, y), _pt(r, 0.84, y))
        painter.setBrush(QBrush(color))
        painter.drawEllipse(_pt(r, knob_x, y), knob_r, knob_r)
        painter.setBrush(Qt.BrushStyle.NoBrush)


def _draw_refresh(painter: QPainter, r: QRectF, color: QColor, stroke: float) -> None:
    path = QPainterPath(_pt(r, 0.74, 0.32))
    path.cubicTo(_pt(r, 0.58, 0.16), _pt(r, 0.28, 0.22), _pt(r, 0.24, 0.5))
    path.cubicTo(_pt(r, 0.2, 0.78), _pt(r, 0.56, 0.88), _pt(r, 0.74, 0.66))
    painter.drawPath(path)
    painter.drawLine(_pt(r, 0.74, 0.32), _pt(r, 0.74, 0.14))
    painter.drawLine(_pt(r, 0.74, 0.32), _pt(r, 0.56, 0.32))


def _draw_move(painter: QPainter, r: QRectF) -> None:
    painter.drawLine(_pt(r, 0.5, 0.18), _pt(r, 0.5, 0.82))
    painter.drawLine(_pt(r, 0.18, 0.5), _pt(r, 0.82, 0.5))
    painter.drawLine(_pt(r, 0.5, 0.18), _pt(r, 0.38, 0.3))
    painter.drawLine(_pt(r, 0.5, 0.18), _pt(r, 0.62, 0.3))
    painter.drawLine(_pt(r, 0.5, 0.82), _pt(r, 0.38, 0.7))
    painter.drawLine(_pt(r, 0.5, 0.82), _pt(r, 0.62, 0.7))
    painter.drawLine(_pt(r, 0.18, 0.5), _pt(r, 0.3, 0.38))
    painter.drawLine(_pt(r, 0.18, 0.5), _pt(r, 0.3, 0.62))
    painter.drawLine(_pt(r, 0.82, 0.5), _pt(r, 0.7, 0.38))
    painter.drawLine(_pt(r, 0.82, 0.5), _pt(r, 0.7, 0.62))


def _draw_resize(painter: QPainter, r: QRectF) -> None:
    painter.drawLine(_pt(r, 0.28, 0.72), _pt(r, 0.72, 0.28))
    painter.drawLine(_pt(r, 0.72, 0.28), _pt(r, 0.72, 0.46))
    painter.drawLine(_pt(r, 0.72, 0.28), _pt(r, 0.54, 0.28))
    painter.drawLine(_pt(r, 0.28, 0.72), _pt(r, 0.28, 0.54))
    painter.drawLine(_pt(r, 0.28, 0.72), _pt(r, 0.46, 0.72))
