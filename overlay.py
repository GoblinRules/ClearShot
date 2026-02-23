"""ClearShot — Fullscreen transparent overlay for region selection."""

import os
import math
import datetime
from PyQt6.QtCore import Qt, QPoint, QPointF, QRect, QRectF, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPixmap, QCursor, QFont,
    QGuiApplication, QPainterPath, QRegion, QImage,
)
from PyQt6.QtWidgets import QWidget, QApplication, QColorDialog, QLineEdit, QPushButton
from capture import capture_all_monitors
from clipboard_utils import copy_pixmap_to_clipboard
from constants import DEFAULT_SAVE_DIR, IMAGE_FORMATS


class SelectionOverlay(QWidget):
    """Fullscreen transparent overlay for selecting a screen region.
    
    Emits:
        region_selected(QPixmap): The captured region as a pixmap.
        cancelled(): The selection was cancelled.
    """
    
    region_selected = pyqtSignal(QPixmap)
    open_annotator = pyqtSignal(QPixmap)
    cancelled = pyqtSignal()

    # Edge/corner zones for resizing
    HANDLE_SIZE = 8

    def __init__(self):
        super().__init__()
        
        # Window setup: frameless, always on top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        
        # State
        self._screenshot: QPixmap = None
        self._selection: QRect = QRect()
        self._is_selecting = False
        self._is_moving = False
        self._is_resizing = False
        self._resize_edge = None  # which edge/corner
        self._start_point = QPoint()
        self._move_offset = QPoint()
        self._move_old_topleft = QPoint()  # track for annotation offset
        self._origin = QPoint()  # Virtual screen origin
        
        # Magnifier
        self._show_magnifier = True
        self._magnifier_size = 120
        self._magnifier_zoom = 4

        # Inline toolbar state
        self._show_inline_toolbar = False
        self._inline_tool = None  # None, 'pen', 'line', 'arrow', 'rect', 'text', 'blur', 'highlight'
        self._inline_items = []  # list of (type, color, width, ...data)
        self._inline_current = None  # item being drawn
        self._inline_drawing = False
        self._inline_start = QPoint()
        self._inline_color = '#FF0000'
        self._inline_width = 3

        # Button rects (computed in paintEvent)
        self._tool_btn_rects = {}  # tool_name -> QRectF
        self._action_btn_rects = {}  # action_name -> QRectF
        self._hovered_tool = None    # for tooltip display

        # Config reference (set by app)
        self._config = None
        # Tray icon reference (set by app, used for toast notifications)
        self._tray_icon = None

        # Inline text editing widget
        self._text_edit: QLineEdit | None = None
        self._text_edit_rect: QRect | None = None
        self._text_edit_btns: list = []  # confirm/cancel/font buttons
        self._text_font_size = 16  # persistent font size for text tool
        self._text_edit_index = -1  # index of text item being re-edited (-1 = new)
        self._text_box_dragging = False  # True when moving the text box
        self._text_box_resizing = False  # True when resizing the text box
        self._text_box_drag_offset = QPoint()

    def begin_capture(self):
        """Capture the screen and show the overlay."""
        self._screenshot, monitor = capture_all_monitors()
        self._origin = QPoint(monitor["left"], monitor["top"])
        self._selection = QRect()
        self._is_selecting = False
        self._show_inline_toolbar = False
        self._inline_tool = None
        self._inline_items.clear()
        self._show_magnifier = True
        self._hovered_tool = None

        # Load persisted annotation color if available
        if self._config:
            saved_color = self._config.get('annotation_color', '#FF0000')
            self._inline_color = saved_color

        # Position the overlay to cover the entire virtual desktop
        self.setGeometry(
            monitor["left"], monitor["top"],
            monitor["width"], monitor["height"],
        )
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.update()

    def _dim_color(self):
        c = QColor(0, 0, 0, 120)
        return c

    def paintEvent(self, event):
        if self._screenshot is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw the screenshot as background
        painter.drawPixmap(0, 0, self._screenshot)

        # Draw dim overlay everywhere except the selection
        dim = self._dim_color()
        if self._selection.isValid() and not self._selection.isEmpty():
            # Dim outside selection
            full_path = QPainterPath()
            full_path.addRect(QRectF(self.rect()))
            sel_path = QPainterPath()
            sel_path.addRect(QRectF(self._selection.normalized()))
            dim_path = full_path - sel_path
            painter.fillPath(dim_path, dim)

            # Draw inline annotations
            self._draw_inline_items(painter)

            # Selection border
            sel_rect = self._selection.normalized()
            pen = QPen(QColor(0, 174, 255), 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(sel_rect)

            # Draw resize handles
            if not self._show_inline_toolbar:
                self._draw_handles(painter, sel_rect)

            # Draw dimension label
            self._draw_dimensions(painter, sel_rect)

            # Draw inline toolbar buttons
            if self._show_inline_toolbar:
                self._draw_inline_toolbar(painter, sel_rect)

            # Draw text tool hint
            if self._inline_tool == 'text' and not self._inline_drawing and not self._text_edit:
                hint_text = '\u270E  Click and drag to draw a text box'
                hint_font = QFont('Segoe UI', 12, QFont.Weight.Bold)
                painter.setFont(hint_font)
                fm = painter.fontMetrics()
                tw = fm.horizontalAdvance(hint_text) + 24
                th = fm.height() + 14
                cx = sel_rect.center().x() - tw / 2
                cy = sel_rect.center().y() - th / 2
                hint_rect = QRectF(cx, cy, tw, th)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(0, 0, 0, 190)))
                painter.drawRoundedRect(hint_rect, 8, 8)
                painter.setPen(QPen(QColor(self._inline_color), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(hint_rect, 8, 8)
                painter.setPen(QPen(QColor(255, 255, 255)))
                painter.drawText(hint_rect, Qt.AlignmentFlag.AlignCenter, hint_text)
        else:
            # Dim entire screen when no selection
            painter.fillRect(self.rect(), dim)

        # Draw crosshair at cursor position
        cursor_pos = self.mapFromGlobal(QCursor.pos())
        if not self._selection.isValid() or self._selection.isEmpty():
            self._draw_crosshair(painter, cursor_pos)

        # Draw magnifier (hide when inline toolbar is showing)
        if self._show_magnifier and not self._show_inline_toolbar:
            self._draw_magnifier(painter, cursor_pos)

        painter.end()

    def _draw_handles(self, painter: QPainter, rect: QRect):
        """Draw resize handles at corners and edges."""
        hs = self.HANDLE_SIZE
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 174, 255)))

        # Corners
        corners = [
            rect.topLeft(),
            rect.topRight(),
            rect.bottomLeft(),
            rect.bottomRight(),
        ]
        for c in corners:
            painter.drawRect(c.x() - hs // 2, c.y() - hs // 2, hs, hs)

        # Edge midpoints
        mid_points = [
            QPoint(rect.center().x(), rect.top()),
            QPoint(rect.center().x(), rect.bottom()),
            QPoint(rect.left(), rect.center().y()),
            QPoint(rect.right(), rect.center().y()),
        ]
        for m in mid_points:
            painter.drawRect(m.x() - hs // 2, m.y() - hs // 2, hs, hs)

    def _draw_dimensions(self, painter: QPainter, rect: QRect):
        """Draw width×height label near the selection."""
        text = f"{rect.width()} × {rect.height()}"
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)
        
        fm = painter.fontMetrics()
        text_width = fm.horizontalAdvance(text) + 16
        text_height = fm.height() + 8
        
        # Position: above the selection, or below if too close to top
        tx = rect.left()
        ty = rect.top() - text_height - 4
        if ty < 0:
            ty = rect.bottom() + 4
        
        # Background
        bg_rect = QRectF(tx, ty, text_width, text_height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 180)))
        painter.drawRoundedRect(bg_rect, 4, 4)
        
        # Text
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_crosshair(self, painter: QPainter, pos: QPoint):
        """Draw crosshair lines across the entire screen at cursor pos."""
        # Use the annotation color when a tool is active, else default cyan
        if self._inline_tool:
            ch_color = QColor(self._inline_color)
            ch_color.setAlpha(180)
        else:
            ch_color = QColor(0, 174, 255, 150)
        pen = QPen(ch_color, 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(pos.x(), 0, pos.x(), self.height())
        painter.drawLine(0, pos.y(), self.width(), pos.y())

    def _draw_magnifier(self, painter: QPainter, cursor_pos: QPoint):
        """Draw a magnified view near the cursor."""
        if self._screenshot is None:
            return

        zoom = self._magnifier_zoom
        size = self._magnifier_size
        src_size = size // zoom

        # Source region centered on cursor
        sx = cursor_pos.x() - src_size // 2
        sy = cursor_pos.y() - src_size // 2
        src_rect = QRect(sx, sy, src_size, src_size)

        # Clamp to screenshot bounds
        src_rect = src_rect.intersected(self._screenshot.rect())
        if src_rect.isEmpty():
            return

        # Position the magnifier offset from cursor
        mag_x = cursor_pos.x() + 20
        mag_y = cursor_pos.y() + 20
        # Keep on screen
        if mag_x + size + 10 > self.width():
            mag_x = cursor_pos.x() - size - 20
        if mag_y + size + 30 > self.height():
            mag_y = cursor_pos.y() - size - 20

        # Draw magnifier background
        mag_rect = QRectF(mag_x, mag_y, size, size)
        painter.setPen(QPen(QColor(0, 174, 255), 2))
        painter.setBrush(QBrush(QColor(0, 0, 0)))
        painter.drawRect(mag_rect)

        # Draw zoomed content
        zoomed = self._screenshot.copy(src_rect).scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        painter.drawPixmap(int(mag_x), int(mag_y), zoomed)

        # Draw crosshair in magnifier center
        center_x = mag_x + size / 2
        center_y = mag_y + size / 2
        cross_pen = QPen(QColor(255, 0, 0, 200), 1)
        painter.setPen(cross_pen)
        painter.drawLine(int(center_x - 10), int(center_y), int(center_x + 10), int(center_y))
        painter.drawLine(int(center_x), int(center_y - 10), int(center_x), int(center_y + 10))

        # Draw color value under cursor
        if (0 <= cursor_pos.x() < self._screenshot.width() and
                0 <= cursor_pos.y() < self._screenshot.height()):
            pixel_color = self._screenshot.toImage().pixelColor(cursor_pos.x(), cursor_pos.y())
            color_text = pixel_color.name().upper()
            font = QFont("Consolas", 9)
            painter.setFont(font)
            
            label_rect = QRectF(mag_x, mag_y + size + 2, size, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0, 180)))
            painter.drawRoundedRect(label_rect, 3, 3)
            
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, color_text)

    def _edge_at(self, pos: QPoint) -> str | None:
        """Determine if pos is on a resize handle/edge."""
        if not self._selection.isValid():
            return None
        
        rect = self._selection.normalized()
        hs = self.HANDLE_SIZE + 4

        on_left = abs(pos.x() - rect.left()) <= hs
        on_right = abs(pos.x() - rect.right()) <= hs
        on_top = abs(pos.y() - rect.top()) <= hs
        on_bottom = abs(pos.y() - rect.bottom()) <= hs

        if on_top and on_left:
            return "top-left"
        if on_top and on_right:
            return "top-right"
        if on_bottom and on_left:
            return "bottom-left"
        if on_bottom and on_right:
            return "bottom-right"
        if on_top:
            return "top"
        if on_bottom:
            return "bottom"
        if on_left:
            return "left"
        if on_right:
            return "right"
        return None

    def _update_cursor_for_edge(self, edge: str | None):
        """Update cursor shape based on resize edge."""
        cursors = {
            "top-left": Qt.CursorShape.SizeFDiagCursor,
            "bottom-right": Qt.CursorShape.SizeFDiagCursor,
            "top-right": Qt.CursorShape.SizeBDiagCursor,
            "bottom-left": Qt.CursorShape.SizeBDiagCursor,
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
        }
        if edge and edge in cursors:
            self.setCursor(cursors[edge])
        elif (self._selection.isValid() and
              self._selection.normalized().contains(self.mapFromGlobal(QCursor.pos()))):
            # Set IBeam cursor when text tool is active
            if self._inline_tool == 'text':
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        pos = event.pos()

        # Check inline toolbar button clicks first
        if self._show_inline_toolbar:
            # Check tool buttons
            for tool_name, btn_rect in self._tool_btn_rects.items():
                if btn_rect.contains(QPointF(pos)):
                    # Color and undo trigger immediately, no second click needed
                    if tool_name == 'color':
                        self._pick_inline_color()
                        return
                    if tool_name == 'undo':
                        if self._inline_items:
                            self._inline_items.pop()
                        self.update()
                        return
                    # Toggle other tools
                    self._inline_tool = tool_name if self._inline_tool != tool_name else None
                    self.update()
                    return

            # Check action buttons
            for action_name, btn_rect in self._action_btn_rects.items():
                if btn_rect.contains(QPointF(pos)):
                    self._handle_inline_action(action_name)
                    return

            # If an inline tool is active and click is inside selection, start drawing
            if self._inline_tool and self._selection.normalized().contains(pos):
                if self._inline_tool == 'text':
                    # Text tool uses drag-a-box, same as rect/line/etc.
                    pass  # fall through to normal drag start below
                self._inline_drawing = True
                self._inline_start = pos
                if self._inline_tool == 'pen':
                    self._inline_current = ('pen', self._inline_color, self._inline_width, [pos])
                else:
                    self._inline_current = (self._inline_tool, self._inline_color, self._inline_width, pos, pos)
                return

        if self._selection.isValid():
            edge = self._edge_at(pos)
            if edge:
                self._is_resizing = True
                self._resize_edge = edge
                self._start_point = pos
                return

            if self._selection.normalized().contains(pos):
                self._is_moving = True
                self._move_offset = pos - self._selection.normalized().topLeft()
                self._move_old_topleft = self._selection.normalized().topLeft()
                return

            # Click outside selection — start a new one, clear annotations
            self._show_inline_toolbar = False
            self._inline_tool = None
            self._inline_items.clear()
            self._inline_current = None

        # Start new selection
        self._show_inline_toolbar = False
        self._inline_tool = None
        self._is_selecting = True
        self._start_point = pos
        self._selection = QRect(pos, QSize(0, 0))

    def mouseMoveEvent(self, event):
        pos = event.pos()

        # Tooltip hover detection for tool buttons
        if self._show_inline_toolbar:
            old_hovered = self._hovered_tool
            self._hovered_tool = None
            for tool_name, btn_rect in self._tool_btn_rects.items():
                if btn_rect.contains(QPointF(pos)):
                    self._hovered_tool = tool_name
                    break
            if self._hovered_tool != old_hovered:
                self.update()

        # Inline drawing
        if self._inline_drawing and self._inline_current:
            if self._inline_current[0] == 'pen':
                self._inline_current[3].append(pos)
            else:
                # Update end point
                self._inline_current = (
                    self._inline_current[0], self._inline_current[1],
                    self._inline_current[2], self._inline_current[3], pos
                )
            self.update()
            return

        if self._is_selecting:
            self._selection = QRect(self._start_point, pos)
            self.update()
            return

        if self._is_moving:
            new_rect = self._selection.normalized()
            new_pos = pos - self._move_offset
            new_rect.moveTopLeft(new_pos)
            # Clamp to screen
            if new_rect.left() < 0:
                new_rect.moveLeft(0)
            if new_rect.top() < 0:
                new_rect.moveTop(0)
            if new_rect.right() >= self.width():
                new_rect.moveRight(self.width() - 1)
            if new_rect.bottom() >= self.height():
                new_rect.moveBottom(self.height() - 1)
            self._selection = new_rect
            # Move annotations with the selection
            delta = new_rect.topLeft() - self._move_old_topleft
            if delta.x() != 0 or delta.y() != 0:
                moved_items = []
                for item in self._inline_items:
                    t = item[0]
                    if t == 'pen':
                        new_pts = [p + delta for p in item[3]]
                        moved_items.append((t, item[1], item[2], new_pts))
                    elif t == 'text':
                        # text: (type, color, font_size, QRect, text_str)
                        r = item[3]
                        moved_items.append((t, item[1], item[2], QRect(r.topLeft() + delta, r.size()), item[4]))
                    else:
                        moved_items.append((t, item[1], item[2], item[3] + delta, item[4] + delta))
                self._inline_items = moved_items
                self._move_old_topleft = new_rect.topLeft()
            self.update()
            return

        if self._is_resizing:
            rect = self._selection.normalized()
            edge = self._resize_edge

            if "left" in edge:
                rect.setLeft(pos.x())
            if "right" in edge:
                rect.setRight(pos.x())
            if "top" in edge:
                rect.setTop(pos.y())
            if "bottom" in edge:
                rect.setBottom(pos.y())

            self._selection = rect
            self.update()
            return

        # Just hovering — update cursor
        if self._selection.isValid() and not self._show_inline_toolbar:
            edge = self._edge_at(pos)
            self._update_cursor_for_edge(edge)

        self.update()  # For crosshair / magnifier

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # Finish inline drawing
        if self._inline_drawing and self._inline_current:
            tool_type = self._inline_current[0]
            if tool_type == 'text':
                # For text tool, spawn an inline text edit in the drawn rectangle
                start = self._inline_current[3]
                end = self._inline_current[4]
                text_rect = QRect(start, end).normalized()
                if text_rect.width() > 10 and text_rect.height() > 10:
                    self._spawn_inline_text_edit(text_rect)
                self._inline_current = None
                self._inline_drawing = False
                self.update()
                return
            self._inline_items.append(self._inline_current)
            self._inline_current = None
            self._inline_drawing = False
            self.update()
            return

        # Show inline toolbar after finishing a new selection
        was_selecting = self._is_selecting
        self._is_selecting = False
        self._is_moving = False
        self._is_resizing = False
        self._resize_edge = None

        if was_selecting and self._selection.isValid():
            sel = self._selection.normalized()
            if sel.width() > 5 and sel.height() > 5:
                self._show_inline_toolbar = True
                self._show_magnifier = False
                self.setCursor(Qt.CursorShape.ArrowCursor)

        self.update()

    def mouseDoubleClickEvent(self, event):
        """Double-click inside selection to confirm."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._selection.isValid() and not self._selection.isEmpty():
                sel = self._selection.normalized()
                if sel.contains(event.pos()):
                    self._confirm_selection()

    def keyPressEvent(self, event):
        key = event.key()

        if key == Qt.Key.Key_Escape:
            if self._show_inline_toolbar:
                # First escape hides the inline toolbar and resets
                self._show_inline_toolbar = False
                self._inline_tool = None
                self._inline_items.clear()
                self._show_magnifier = True
                self.setCursor(Qt.CursorShape.CrossCursor)
                self.update()
            else:
                self._cancel()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._show_inline_toolbar:
                self._handle_inline_action('edit')
            elif self._selection.isValid() and not self._selection.isEmpty():
                self._confirm_selection()
        elif key == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self._show_inline_toolbar:
                self._handle_inline_action('copy')
        elif key == Qt.Key.Key_S and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self._show_inline_toolbar:
                self._handle_inline_action('save')
        elif key == Qt.Key.Key_Z and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self._show_inline_toolbar and self._inline_items:
                self._inline_items.pop()
                self.update()
        elif key == Qt.Key.Key_A and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Select all
            self._selection = QRect(0, 0, self.width(), self.height())
            self.update()

    def _confirm_selection(self):
        """Crop the selected region and emit the signal."""
        sel = self._selection.normalized()
        if sel.width() < 2 or sel.height() < 2:
            self._cancel()
            return

        cropped = self._get_cropped_with_annotations()
        self.hide()
        self.region_selected.emit(cropped)

    def _cancel(self):
        """Cancel selection and close overlay."""
        self.hide()
        self.cancelled.emit()

    # ── Inline toolbar rendering ─────────────────────────────────────

    def _draw_inline_toolbar(self, painter: QPainter, sel_rect: QRect):
        """Draw Lightshot-style floating tool and action buttons."""
        self._tool_btn_rects.clear()
        self._action_btn_rects.clear()

        btn_size = 24
        btn_gap = 1
        corner_radius = 3

        # ── Right-side vertical tool strip ──
        tools = [
            ('pen',       '\u270E'),   # ✎ pencil
            ('line',      '\u2500'),   # ─ horizontal line
            ('arrow',     '\u2192'),   # → right arrow
            ('rect',      '\u25A1'),   # □ white square
            ('text',      'A'),         # text
            ('blur',      '\u2592'),   # ▒ medium shade
            ('highlight', '\u25AE'),   # ▮ black vertical rectangle
            ('undo',      '\u21B6'),   # ↶ undo
            ('color',     None),        # color swatch (painted below)
        ]
        strip_x = sel_rect.right() + 6
        strip_y = sel_rect.top()

        # If strip would go off-screen right, put it on the left
        if strip_x + btn_size + 4 > self.width():
            strip_x = sel_rect.left() - btn_size - 10

        # If strip would go off-screen bottom, shift it up
        strip_h = len(tools) * (btn_size + btn_gap) - btn_gap
        if strip_y + strip_h > self.height():
            strip_y = max(0, self.height() - strip_h - 4)

        # Tool name → tooltip label
        tool_labels = {
            'pen': 'Pen', 'line': 'Line', 'arrow': 'Arrow',
            'rect': 'Rectangle', 'text': 'Text', 'blur': 'Blur',
            'highlight': 'Highlight', 'undo': 'Undo', 'color': 'Color',
        }

        for i, (tool_name, icon) in enumerate(tools):
            y = strip_y + i * (btn_size + btn_gap)
            btn_rect = QRectF(strip_x, y, btn_size, btn_size)
            self._tool_btn_rects[tool_name] = btn_rect

            # Button background
            is_active = self._inline_tool == tool_name
            bg_color = QColor(0, 120, 212) if is_active else QColor(30, 30, 30, 230)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bg_color))
            painter.drawRoundedRect(btn_rect, corner_radius, corner_radius)

            # Border
            border = QColor(0, 150, 255) if is_active else QColor(70, 70, 70)
            painter.setPen(QPen(border, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(btn_rect, corner_radius, corner_radius)

            if tool_name == 'color':
                # Draw a color swatch instead of text
                swatch = btn_rect.adjusted(6, 6, -6, -6)
                painter.setPen(QPen(QColor(200, 200, 200), 1))
                painter.setBrush(QBrush(QColor(self._inline_color)))
                painter.drawRoundedRect(swatch, 2, 2)
            else:
                # Icon text
                painter.setPen(QPen(QColor(255, 255, 255)))
                font = QFont('Segoe UI Symbol', 10)
                font.setBold(tool_name == 'text')
                painter.setFont(font)
                painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, icon)

        # ── Tooltip for hovered tool ──
        if self._hovered_tool and self._hovered_tool in tool_labels:
            label = tool_labels[self._hovered_tool]
            if self._hovered_tool in self._tool_btn_rects:
                tr = self._tool_btn_rects[self._hovered_tool]
                tip_font = QFont('Segoe UI', 9)
                painter.setFont(tip_font)
                fm = painter.fontMetrics()
                tw = fm.horizontalAdvance(label) + 12
                th = fm.height() + 6
                # Position tooltip to the left of the button
                tx = tr.left() - tw - 4
                ty = tr.top() + (btn_size - th) / 2
                tip_rect = QRectF(tx, ty, tw, th)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(20, 20, 20, 220)))
                painter.drawRoundedRect(tip_rect, 4, 4)
                painter.setPen(QPen(QColor(220, 220, 220)))
                painter.drawText(tip_rect, Qt.AlignmentFlag.AlignCenter, label)

        # ── Bottom horizontal action strip ──
        actions = [
            ('copy',  'Copy',  QColor(0, 120, 212)),
            ('save',  'Save',  QColor(16, 124, 16)),
            ('edit',  'Edit',  QColor(80, 80, 80)),
            ('close', '\u2715', QColor(100, 40, 40)),
        ]

        action_btn_w = 44
        total_w = len(actions) * (action_btn_w + btn_gap) - btn_gap
        action_x = sel_rect.right() - total_w + 1
        action_y = sel_rect.bottom() + 6

        # If strip would go off-screen bottom, put it above
        if action_y + btn_size + 4 > self.height():
            action_y = sel_rect.top() - btn_size - 10

        for i, (action_name, label, bg) in enumerate(actions):
            x = action_x + i * (action_btn_w + btn_gap)
            btn_rect = QRectF(x, action_y, action_btn_w, btn_size)
            self._action_btn_rects[action_name] = btn_rect

            # Button background
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(btn_rect, corner_radius, corner_radius)

            # Border
            painter.setPen(QPen(QColor(70, 70, 70), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(btn_rect, corner_radius, corner_radius)

            # Label text
            painter.setPen(QPen(QColor(255, 255, 255)))
            font = QFont('Segoe UI', 9)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, label)

    # ── Inline drawing rendering ─────────────────────────────────────

    def _draw_inline_items(self, painter: QPainter):
        """Render inline annotation items drawn on the overlay."""
        items = list(self._inline_items)
        if self._inline_current:
            items.append(self._inline_current)

        for item in items:
            self._paint_one_item(painter, item, QPoint(0, 0))

    def _paint_one_item(self, painter: QPainter, item, offset: QPoint):
        """Paint a single inline annotation item with the given offset."""
        item_type = item[0]
        color = QColor(item[1])
        width = item[2]

        if item_type == 'pen':
            points = item[3]
            if len(points) < 2:
                return
            pen = QPen(color, width, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            for j in range(1, len(points)):
                painter.drawLine(points[j - 1] - offset, points[j] - offset)

        elif item_type == 'line':
            start, end = item[3] - offset, item[4] - offset
            pen = QPen(color, width, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(start, end)

        elif item_type == 'arrow':
            start, end = item[3] - offset, item[4] - offset
            pen = QPen(color, width, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawLine(start, end)
            # Arrowhead
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            length = math.hypot(dx, dy)
            if length < 1:
                return
            angle = math.atan2(dy, dx)
            head_len = max(10, width * 4)
            p1x = end.x() - head_len * math.cos(angle - 0.4)
            p1y = end.y() - head_len * math.sin(angle - 0.4)
            p2x = end.x() - head_len * math.cos(angle + 0.4)
            p2y = end.y() - head_len * math.sin(angle + 0.4)
            path = QPainterPath()
            path.moveTo(end.x(), end.y())
            path.lineTo(p1x, p1y)
            path.lineTo(p2x, p2y)
            path.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.fillPath(path, QBrush(color))

        elif item_type == 'rect':
            start, end = item[3] - offset, item[4] - offset
            pen = QPen(color, width, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(QPointF(start), QPointF(end)).normalized())

        elif item_type == 'highlight':
            start, end = item[3] - offset, item[4] - offset
            hc = QColor(color)
            hc.setAlpha(60)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(hc))
            painter.drawRect(QRectF(QPointF(start), QPointF(end)).normalized())

        elif item_type == 'text':
            text_rect = item[3]  # QRect
            text = item[4]
            if not isinstance(text, str):
                return
            # Offset the rect
            r = QRectF(text_rect).translated(-offset.x(), -offset.y())
            font_size = width  # text items store font size in the width field
            font = QFont('Segoe UI', font_size)
            painter.setFont(font)
            painter.setPen(QPen(color))
            painter.drawText(r.adjusted(4, 0, -4, 0),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             text)

        elif item_type == 'blur':
            start, end = item[3] - offset, item[4] - offset
            rect = QRectF(QPointF(start), QPointF(end)).normalized().toAlignedRect()
            # Draw pixelation effect on blur region
            if self._screenshot and rect.width() > 0 and rect.height() > 0:
                sel = self._selection.normalized()
                # When painting on the overlay, offset is (0,0) so rect is in
                # screen coords. When painting on the crop, offset is sel.topLeft().
                # In both cases the source rect in the screenshot is rect + offset.
                src_rect = QRect(rect.x() + offset.x(), rect.y() + offset.y(),
                                 rect.width(), rect.height())
                src_rect = src_rect.intersected(QRect(0, 0, self._screenshot.width(), self._screenshot.height()))
                if src_rect.width() > 0 and src_rect.height() > 0:
                    region_img = self._screenshot.copy(src_rect).toImage()
                    # Strong pixelation: large block size prevents any character recovery
                    # Block=16 means each 16x16 pixel area becomes one solid color
                    block = 16
                    small_w = max(1, region_img.width() // block)
                    small_h = max(1, region_img.height() // block)
                    # First pass: downscale aggressively
                    small = region_img.scaled(
                        small_w, small_h,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                    # Second pass: downscale once more to destroy sub-pixel patterns
                    tiny = small.scaled(
                        max(1, small_w // 2), max(1, small_h // 2),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                    # Upscale back to original size (nearest-neighbor = solid blocks)
                    pixelated = tiny.scaled(
                        region_img.width(), region_img.height(),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                    painter.drawImage(rect, pixelated)

    # ── Special inline tool helpers ──────────────────────────────────

    def _pick_inline_color(self):
        """Open a color picker dialog."""
        # Temporarily hide overlay so the dialog isn't behind it
        self.hide()
        color = QColorDialog.getColor(
            QColor(self._inline_color), None, "Pick annotation color"
        )
        if color.isValid():
            self._inline_color = color.name()
            # Persist the color choice
            if self._config:
                self._config.set('annotation_color', self._inline_color)
        self._inline_tool = None
        self.show()
        self.activateWindow()
        self.raise_()
        self.setFocus()
        self.update()

    def _spawn_inline_text_edit(self, rect: QRect, prefill: str = ''):
        """Create an inline text editor with confirm/cancel and font size buttons."""
        # Remove any existing text edit
        self._cleanup_text_edit_widgets()

        self._text_edit_rect = rect
        font_size = self._text_font_size

        # Create the text input
        edit = QLineEdit(self)
        edit.setGeometry(rect)
        edit.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(0, 0, 0, 120);
                color: {self._inline_color};
                border: 1px dashed {self._inline_color};
                font-size: {font_size}px;
                font-family: 'Segoe UI';
                padding: 2px 4px;
            }}
        """)
        if prefill:
            edit.setText(prefill)
        edit.setFocus()
        edit.returnPressed.connect(self._commit_inline_text)
        edit.show()
        self._text_edit = edit

        # Button style
        btn_style = """
            QPushButton {
                background: rgba(30, 30, 30, 220);
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                font-size: 12px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:hover { background: rgba(60, 60, 60, 230); }
        """

        btn_size = 22
        # Position buttons below the text box
        bx = rect.left()
        by = rect.bottom() + 3

        # ✓ Confirm button
        confirm_btn = QPushButton('\u2713', self)
        confirm_btn.setFixedSize(btn_size, btn_size)
        confirm_btn.move(bx, by)
        confirm_btn.setStyleSheet(btn_style.replace('#555', '#2a7a2a'))
        confirm_btn.setToolTip('Commit text (Enter)')
        confirm_btn.clicked.connect(self._commit_inline_text)
        confirm_btn.show()

        # ✗ Cancel button
        cancel_btn = QPushButton('\u2717', self)
        cancel_btn.setFixedSize(btn_size, btn_size)
        cancel_btn.move(bx + btn_size + 2, by)
        cancel_btn.setStyleSheet(btn_style.replace('#555', '#7a2a2a'))
        cancel_btn.setToolTip('Cancel text')
        cancel_btn.clicked.connect(self._cancel_inline_text)
        cancel_btn.show()

        # A- font decrease
        dec_btn = QPushButton('A-', self)
        dec_btn.setFixedSize(btn_size + 4, btn_size)
        dec_btn.move(bx + 2 * (btn_size + 2), by)
        dec_btn.setStyleSheet(btn_style)
        dec_btn.setToolTip('Decrease font size')
        dec_btn.clicked.connect(self._decrease_text_font)
        dec_btn.show()

        # A+ font increase
        inc_btn = QPushButton('A+', self)
        inc_btn.setFixedSize(btn_size + 4, btn_size)
        inc_btn.move(bx + 2 * (btn_size + 2) + btn_size + 6, by)
        inc_btn.setStyleSheet(btn_style)
        inc_btn.setToolTip('Increase font size')
        inc_btn.clicked.connect(self._increase_text_font)
        inc_btn.show()

        # ⤡ Move handle (above text box, left)
        move_btn = QPushButton('\u2630', self)
        move_btn.setFixedSize(btn_size, btn_size)
        move_btn.move(rect.left(), rect.top() - btn_size - 2)
        move_btn.setStyleSheet(btn_style)
        move_btn.setToolTip('Drag to move text box')
        move_btn.setCursor(Qt.CursorShape.SizeAllCursor)
        move_btn.show()
        move_btn.mousePressEvent = self._text_box_move_press
        move_btn.mouseMoveEvent = self._text_box_move_drag

        # ⤡ Resize grip (bottom-right corner)
        resize_btn = QPushButton('\u2921', self)
        resize_btn.setFixedSize(btn_size, btn_size)
        resize_btn.move(rect.right() - btn_size + 1, rect.top() - btn_size - 2)
        resize_btn.setStyleSheet(btn_style)
        resize_btn.setToolTip('Drag to resize text box')
        resize_btn.setCursor(Qt.CursorShape.SizeFDiagCursor)
        resize_btn.show()
        resize_btn.mousePressEvent = self._text_box_resize_press
        resize_btn.mouseMoveEvent = self._text_box_resize_drag

        self._text_edit_btns = [confirm_btn, cancel_btn, dec_btn, inc_btn, move_btn, resize_btn]

    def _cleanup_text_edit_widgets(self):
        """Remove inline text edit and its buttons."""
        if self._text_edit:
            self._text_edit.deleteLater()
            self._text_edit = None
        for btn in self._text_edit_btns:
            btn.deleteLater()
        self._text_edit_btns = []
        self._text_box_dragging = False
        self._text_box_resizing = False

    def _text_box_move_press(self, event):
        """Start moving the text box."""
        self._text_box_dragging = True
        self._text_box_drag_offset = event.pos()

    def _text_box_move_drag(self, event):
        """Actually move the text box and all its buttons."""
        if not self._text_box_dragging or not self._text_edit:
            return
        # Calculate delta from the move button's parent coords
        sender = self._text_edit_btns[4]  # move button
        global_pos = sender.mapToParent(event.pos()) - self._text_box_drag_offset
        old_rect = self._text_edit.geometry()
        dx = global_pos.x() - old_rect.left()
        dy = global_pos.y() - (old_rect.top() - 24)  # offset for button above

        new_rect = QRect(old_rect)
        new_rect.moveTopLeft(old_rect.topLeft() + QPoint(dx, dy))
        self._text_edit.setGeometry(new_rect)
        self._text_edit_rect = new_rect
        # Reposition all buttons
        self._reposition_text_buttons()

    def _text_box_resize_press(self, event):
        """Start resizing the text box."""
        self._text_box_resizing = True
        self._text_box_drag_offset = event.pos()

    def _text_box_resize_drag(self, event):
        """Resize the text box by dragging the grip."""
        if not self._text_box_resizing or not self._text_edit:
            return
        sender = self._text_edit_btns[5]  # resize button
        global_pos = sender.mapToParent(event.pos())
        rect = self._text_edit.geometry()
        new_w = max(60, global_pos.x() - rect.left() + 11)
        new_h = max(20, global_pos.y() - (rect.top() - 24))
        # Resize keeps top-left fixed
        new_rect = QRect(rect.left(), rect.top(), new_w, new_h)
        self._text_edit.setGeometry(new_rect)
        self._text_edit_rect = new_rect
        self._reposition_text_buttons()

    def _reposition_text_buttons(self):
        """Reposition all text edit buttons based on current text edit geometry."""
        if not self._text_edit:
            return
        rect = self._text_edit.geometry()
        btn_size = 22
        bx, by = rect.left(), rect.bottom() + 3

        if len(self._text_edit_btns) >= 6:
            self._text_edit_btns[0].move(bx, by)  # confirm
            self._text_edit_btns[1].move(bx + btn_size + 2, by)  # cancel
            self._text_edit_btns[2].move(bx + 2 * (btn_size + 2), by)  # A-
            self._text_edit_btns[3].move(bx + 2 * (btn_size + 2) + btn_size + 6, by)  # A+
            self._text_edit_btns[4].move(rect.left(), rect.top() - btn_size - 2)  # move
            self._text_edit_btns[5].move(rect.right() - btn_size + 1, rect.top() - btn_size - 2)  # resize

    def _increase_text_font(self):
        """Increase text font size."""
        self._text_font_size = min(72, self._text_font_size + 2)
        self._update_text_edit_font()

    def _decrease_text_font(self):
        """Decrease text font size."""
        self._text_font_size = max(8, self._text_font_size - 2)
        self._update_text_edit_font()

    def _update_text_edit_font(self):
        """Update the inline text edit font size."""
        if self._text_edit:
            self._text_edit.setStyleSheet(f"""
                QLineEdit {{
                    background: rgba(0, 0, 0, 120);
                    color: {self._inline_color};
                    border: 1px dashed {self._inline_color};
                    font-size: {self._text_font_size}px;
                    font-family: 'Segoe UI';
                    padding: 2px 4px;
                }}
            """)
            self._text_edit.setFocus()

    def _cancel_inline_text(self):
        """Cancel text editing without committing."""
        self._cleanup_text_edit_widgets()
        self._text_edit_rect = None
        self._inline_tool = None
        self.setFocus()
        self.update()

    def _commit_inline_text(self):
        """Commit the inline text edit content as a text annotation."""
        if self._text_edit and self._text_edit.text().strip():
            text = self._text_edit.text()
            rect = QRect(self._text_edit.geometry())  # use actual widget geometry
            if self._text_edit_index >= 0:
                # Re-editing an existing text item — replace it
                self._inline_items[self._text_edit_index] = (
                    'text', self._inline_color, self._text_font_size, rect, text
                )
            else:
                self._inline_items.append(
                    ('text', self._inline_color, self._text_font_size, rect, text)
                )
        elif self._text_edit_index >= 0:
            # Was editing but text is now empty — remove the item
            self._inline_items.pop(self._text_edit_index)
        self._cleanup_text_edit_widgets()
        self._text_edit_rect = None
        self._text_edit_index = -1
        self._inline_tool = None
        self.setFocus()
        self.update()

    def mouseDoubleClickEvent(self, event):
        """Double-click on a text annotation to re-edit it."""
        if not self._show_inline_toolbar:
            return
        pos = event.pos()
        # Search text items in reverse (top-most first)
        for i in range(len(self._inline_items) - 1, -1, -1):
            item = self._inline_items[i]
            if item[0] == 'text' and isinstance(item[4], str):
                r = item[3]  # QRect
                if r.contains(pos):
                    # Re-open editor with this item's data
                    self._text_edit_index = i
                    self._inline_color = item[1]
                    self._text_font_size = item[2]
                    self._spawn_inline_text_edit(r, prefill=item[4])
                    return

    # ── Inline actions ───────────────────────────────────────────────

    def _show_toast(self, message: str):
        """Show a brief notification via the system tray icon."""
        if self._tray_icon:
            self._tray_icon.showMessage("ClearShot", message, self._tray_icon.MessageIcon.Information, 2000)

    def _handle_inline_action(self, action: str):
        """Handle clicks on inline action buttons."""
        if action == 'copy':
            pixmap = self._get_cropped_with_annotations()
            copy_pixmap_to_clipboard(pixmap)
            self.hide()
            self._show_toast("Screenshot copied to clipboard")
            self.cancelled.emit()
        elif action == 'save':
            pixmap = self._get_cropped_with_annotations()
            path = self._quick_save_pixmap(pixmap)
            self.hide()
            self._show_toast(f"Saved to {path}")
            self.cancelled.emit()
        elif action == 'edit':
            pixmap = self._get_cropped_with_annotations()
            self.hide()
            self.open_annotator.emit(pixmap)
        elif action == 'close':
            self._cancel()

    def _get_cropped_with_annotations(self) -> QPixmap:
        """Crop the selection and render inline annotations onto it."""
        sel = self._selection.normalized()
        cropped = self._screenshot.copy(sel)

        if not self._inline_items:
            return cropped

        painter = QPainter(cropped)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        offset = sel.topLeft()

        for item in self._inline_items:
            self._paint_one_item(painter, item, offset)

        painter.end()
        return cropped

    def _quick_save_pixmap(self, pixmap: QPixmap) -> str:
        """Quick-save a pixmap to the default folder. Returns the file path."""
        save_dir = DEFAULT_SAVE_DIR
        fmt = 'PNG'
        if self._config:
            save_dir = self._config.get('save_path', save_dir)
            fmt = self._config.get('image_format', 'PNG')

        os.makedirs(save_dir, exist_ok=True)
        ext = IMAGE_FORMATS.get(fmt, '.png')
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        file_name = f'ClearShot_{timestamp}{ext}'
        file_path = os.path.join(save_dir, file_name)
        pixmap.save(file_path)
        return file_path
