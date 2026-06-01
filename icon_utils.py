"""Shared vector icons for ClearShot's PyQt UI."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
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
    """Paint one named line icon inside rect."""
    name = _normalize_name(name)
    r = QRectF(rect).adjusted(
        rect.width() * 0.08,
        rect.height() * 0.08,
        -rect.width() * 0.08,
        -rect.height() * 0.08,
    )
    stroke = max(1.6, min(r.width(), r.height()) * 0.12)
    fg = QColor(color)
    ac = QColor(accent)

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(fg, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == "pen":
        _draw_pen(painter, r, fg, stroke)
    elif name == "line":
        painter.drawLine(_pt(r, 0.16, 0.5), _pt(r, 0.84, 0.5))
    elif name == "arrow":
        painter.drawLine(_pt(r, 0.2, 0.72), _pt(r, 0.76, 0.28))
        painter.drawLine(_pt(r, 0.54, 0.24), _pt(r, 0.78, 0.26))
        painter.drawLine(_pt(r, 0.76, 0.28), _pt(r, 0.72, 0.52))
    elif name == "rect":
        painter.drawRoundedRect(_box(r, 0.16, 0.22, 0.68, 0.56), stroke * 0.8, stroke * 0.8)
    elif name == "filled_rect":
        box = _box(r, 0.16, 0.22, 0.68, 0.56)
        fill = QColor(ac)
        fill.setAlpha(120)
        painter.setBrush(QBrush(fill))
        painter.drawRoundedRect(box, stroke * 0.8, stroke * 0.8)
    elif name == "ellipse":
        painter.drawEllipse(_box(r, 0.15, 0.18, 0.7, 0.64))
    elif name == "text":
        _draw_text_glyph(painter, r, "T", fg, 0.76)
    elif name == "blur":
        _draw_blur(painter, r, fg)
    elif name == "counter":
        painter.setBrush(QBrush(ac))
        painter.drawEllipse(_box(r, 0.18, 0.16, 0.64, 0.68))
        _draw_text_glyph(painter, r, "1", QColor("#ffffff"), 0.54)
    elif name == "palette":
        _draw_palette(painter, r, fg, ac)
    elif name == "undo":
        _draw_turn_arrow(painter, r, fg, stroke, reverse=True)
    elif name == "redo":
        _draw_turn_arrow(painter, r, fg, stroke, reverse=False)
    elif name == "trash":
        _draw_trash(painter, r, fg, stroke)
    elif name == "copy":
        _draw_copy(painter, r, fg, stroke)
    elif name == "save":
        _draw_save(painter, r, fg, stroke)
    elif name == "quick_save":
        _draw_bolt(painter, r, fg)
    elif name == "capture_region":
        _draw_crop_corners(painter, r)
    elif name == "fullscreen":
        _draw_monitor(painter, r, fg, stroke)
    elif name == "folder":
        _draw_folder(painter, r, fg, ac, stroke)
    elif name == "settings":
        _draw_sliders(painter, r, fg, stroke)
    elif name == "help":
        painter.drawEllipse(_box(r, 0.16, 0.16, 0.68, 0.68))
        _draw_text_glyph(painter, r, "?", fg, 0.6)
    elif name == "refresh":
        _draw_refresh(painter, r, fg, stroke)
    elif name == "check":
        painter.drawLine(_pt(r, 0.22, 0.54), _pt(r, 0.42, 0.72))
        painter.drawLine(_pt(r, 0.42, 0.72), _pt(r, 0.78, 0.3))
    elif name == "move":
        _draw_move(painter, r)
    elif name == "resize":
        _draw_resize(painter, r)
    elif name == "close":
        painter.drawLine(_pt(r, 0.26, 0.26), _pt(r, 0.74, 0.74))
        painter.drawLine(_pt(r, 0.74, 0.26), _pt(r, 0.26, 0.74))
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
        "edit": "pen",
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


def _draw_pen(painter: QPainter, r: QRectF, color: QColor, stroke: float) -> None:
    painter.drawLine(_pt(r, 0.27, 0.78), _pt(r, 0.75, 0.3))
    painter.drawLine(_pt(r, 0.62, 0.18), _pt(r, 0.86, 0.42))
    nib = QPainterPath(_pt(r, 0.22, 0.84))
    nib.lineTo(_pt(r, 0.32, 0.62))
    nib.lineTo(_pt(r, 0.44, 0.74))
    nib.closeSubpath()
    painter.setBrush(QBrush(color))
    painter.drawPath(nib)


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
