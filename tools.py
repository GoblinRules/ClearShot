"""ClearShot — Drawing tool implementations for the annotation canvas."""

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QFont, QPolygonF, QPainterPath,
    QBrush, QPixmap, QImage,
)
import math
from constants import (
    TOOL_PEN, TOOL_LINE, TOOL_ARROW, TOOL_RECT, TOOL_FILLED_RECT,
    TOOL_ELLIPSE, TOOL_TEXT, TOOL_BLUR, TOOL_COUNTER,
)


class AnnotationItem:
    """Base class for all annotation items that can be drawn on the canvas."""
    
    tool_type = None

    def __init__(self, color: str = "#FF0000", width: int = 3):
        self.color = color
        self.width = width

    def render(self, painter: QPainter):
        raise NotImplementedError


class PenItem(AnnotationItem):
    """Freehand pen stroke."""
    
    tool_type = TOOL_PEN

    def __init__(self, color="#FF0000", width=3):
        super().__init__(color, width)
        self.points: list[QPointF] = []

    def add_point(self, point: QPointF):
        self.points.append(point)

    def render(self, painter: QPainter):
        if len(self.points) < 2:
            return
        pen = QPen(QColor(self.color), self.width, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        path.moveTo(self.points[0])
        for pt in self.points[1:]:
            path.lineTo(pt)
        painter.drawPath(path)


class LineItem(AnnotationItem):
    """Straight line."""
    
    tool_type = TOOL_LINE

    def __init__(self, color="#FF0000", width=3):
        super().__init__(color, width)
        self.start: QPointF = QPointF()
        self.end: QPointF = QPointF()

    def render(self, painter: QPainter):
        pen = QPen(QColor(self.color), self.width, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(self.start, self.end)


class ArrowItem(AnnotationItem):
    """Line with an arrowhead at the end."""
    
    tool_type = TOOL_ARROW

    def __init__(self, color="#FF0000", width=3):
        super().__init__(color, width)
        self.start: QPointF = QPointF()
        self.end: QPointF = QPointF()

    def render(self, painter: QPainter):
        pen = QPen(QColor(self.color), self.width, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(self.color)))

        # Draw the line
        painter.drawLine(self.start, self.end)

        # Draw arrowhead
        dx = self.end.x() - self.start.x()
        dy = self.end.y() - self.start.y()
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1:
            return

        # Arrowhead size proportional to line width
        arrow_size = max(self.width * 4, 14)
        angle = math.atan2(dy, dx)

        # Arrowhead triangle
        p1 = self.end
        p2 = QPointF(
            self.end.x() - arrow_size * math.cos(angle - math.pi / 6),
            self.end.y() - arrow_size * math.sin(angle - math.pi / 6),
        )
        p3 = QPointF(
            self.end.x() - arrow_size * math.cos(angle + math.pi / 6),
            self.end.y() - arrow_size * math.sin(angle + math.pi / 6),
        )

        arrow_head = QPolygonF([p1, p2, p3])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(arrow_head)


class RectItem(AnnotationItem):
    """Rectangle outline."""
    
    tool_type = TOOL_RECT

    def __init__(self, color="#FF0000", width=3):
        super().__init__(color, width)
        self.start: QPointF = QPointF()
        self.end: QPointF = QPointF()

    def get_rect(self) -> QRectF:
        return QRectF(self.start, self.end).normalized()

    def render(self, painter: QPainter):
        pen = QPen(QColor(self.color), self.width, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.get_rect())


class FilledRectItem(AnnotationItem):
    """Semi-transparent filled rectangle (highlighter)."""
    
    tool_type = TOOL_FILLED_RECT

    def __init__(self, color="#FFCC00", width=3):
        super().__init__(color, width)
        self.start: QPointF = QPointF()
        self.end: QPointF = QPointF()

    def get_rect(self) -> QRectF:
        return QRectF(self.start, self.end).normalized()

    def render(self, painter: QPainter):
        color = QColor(self.color)
        color.setAlpha(80)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawRect(self.get_rect())


class EllipseItem(AnnotationItem):
    """Ellipse outline."""
    
    tool_type = TOOL_ELLIPSE

    def __init__(self, color="#FF0000", width=3):
        super().__init__(color, width)
        self.start: QPointF = QPointF()
        self.end: QPointF = QPointF()

    def get_rect(self) -> QRectF:
        return QRectF(self.start, self.end).normalized()

    def render(self, painter: QPainter):
        pen = QPen(QColor(self.color), self.width, Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(self.get_rect())


class TextItem(AnnotationItem):
    """Text annotation."""
    
    tool_type = TOOL_TEXT

    def __init__(self, color="#FF0000", width=3):
        super().__init__(color, width)
        self.position: QPointF = QPointF()
        self.text: str = ""
        self.font_size: int = 16
        self.font_family: str = "Arial"

    def render(self, painter: QPainter):
        if not self.text:
            return
        font = QFont(self.font_family, self.font_size)
        font.setBold(True)
        painter.setFont(font)
        
        # Draw text shadow for readability
        shadow_color = QColor("#000000")
        shadow_color.setAlpha(160)
        painter.setPen(QPen(shadow_color))
        painter.drawText(self.position + QPointF(2, 2), self.text)
        
        # Draw main text
        painter.setPen(QPen(QColor(self.color)))
        painter.drawText(self.position, self.text)


class BlurItem(AnnotationItem):
    """Pixelation/blur region for redacting."""
    
    tool_type = TOOL_BLUR

    def __init__(self, color="#000000", width=3):
        super().__init__(color, width)
        self.start: QPointF = QPointF()
        self.end: QPointF = QPointF()
        self.pixel_size: int = 10

    def get_rect(self) -> QRectF:
        return QRectF(self.start, self.end).normalized()

    def render(self, painter: QPainter, source_pixmap: QPixmap = None):
        rect = self.get_rect()
        if rect.width() < 2 or rect.height() < 2:
            return

        if source_pixmap is not None:
            # Pixelate the selected region
            region = source_pixmap.copy(rect.toAlignedRect())
            small = region.scaled(
                max(1, int(rect.width() / self.pixel_size)),
                max(1, int(rect.height() / self.pixel_size)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            pixelated = small.scaled(
                int(rect.width()),
                int(rect.height()),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            painter.drawPixmap(rect.toAlignedRect(), pixelated)
        else:
            # Fallback: draw a gray block
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(128, 128, 128)))
            painter.drawRect(rect)


class CounterItem(AnnotationItem):
    """Numbered circle marker."""
    
    tool_type = TOOL_COUNTER

    def __init__(self, color="#FF0000", width=3):
        super().__init__(color, width)
        self.position: QPointF = QPointF()
        self.number: int = 1
        self.radius: int = 16

    def render(self, painter: QPainter):
        # Draw filled circle
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(self.color)))
        painter.drawEllipse(self.position, self.radius, self.radius)

        # Draw number in white
        font = QFont("Arial", int(self.radius * 0.9))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#FFFFFF")))
        
        text_rect = QRectF(
            self.position.x() - self.radius,
            self.position.y() - self.radius,
            self.radius * 2,
            self.radius * 2,
        )
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignCenter,
            str(self.number),
        )


# Factory for creating tool items
TOOL_CLASSES = {
    TOOL_PEN: PenItem,
    TOOL_LINE: LineItem,
    TOOL_ARROW: ArrowItem,
    TOOL_RECT: RectItem,
    TOOL_FILLED_RECT: FilledRectItem,
    TOOL_ELLIPSE: EllipseItem,
    TOOL_TEXT: TextItem,
    TOOL_BLUR: BlurItem,
    TOOL_COUNTER: CounterItem,
}


def create_tool_item(tool_type: str, color: str, width: int) -> AnnotationItem:
    """Factory function to create the appropriate annotation item."""
    cls = TOOL_CLASSES.get(tool_type)
    if cls:
        return cls(color=color, width=width)
    raise ValueError(f"Unknown tool type: {tool_type}")
