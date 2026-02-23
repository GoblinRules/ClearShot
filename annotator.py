"""ClearShot — Annotation editor window with toolbar, canvas, and action bar."""

import os
import datetime
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QSize
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPixmap, QIcon, QFont,
    QAction, QKeySequence, QPainterPath, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QToolButton,
    QLabel, QSlider, QColorDialog, QFileDialog, QInputDialog,
    QSizePolicy, QButtonGroup, QFrame, QApplication, QToolBar,
    QSpacerItem, QMessageBox, QScrollArea,
)
from tools import (
    AnnotationItem, PenItem, LineItem, ArrowItem, RectItem,
    FilledRectItem, EllipseItem, TextItem, BlurItem, CounterItem,
    create_tool_item,
)
from clipboard_utils import copy_pixmap_to_clipboard
from constants import (
    TOOL_PEN, TOOL_LINE, TOOL_ARROW, TOOL_RECT, TOOL_FILLED_RECT,
    TOOL_ELLIPSE, TOOL_TEXT, TOOL_BLUR, TOOL_COUNTER,
    COLOR_PALETTE, DEFAULT_PEN_COLOR, DEFAULT_PEN_WIDTH,
    DEFAULT_FONT_SIZE, IMAGE_FORMATS,
)


class AnnotationCanvas(QWidget):
    """Canvas widget that displays the screenshot and handles drawing."""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._base_pixmap = pixmap  # Original screenshot
        self._items: list[AnnotationItem] = []
        self._current_item: AnnotationItem | None = None
        self._undo_stack: list[AnnotationItem] = []
        self._redo_stack: list[AnnotationItem] = []

        # Tool state
        self.current_tool: str = TOOL_PEN
        self.current_color: str = DEFAULT_PEN_COLOR
        self.current_width: int = DEFAULT_PEN_WIDTH
        self.font_size: int = DEFAULT_FONT_SIZE
        self._counter_value: int = 1

        self.setFixedSize(pixmap.size())
        self.setMouseTracking(True)

    def get_rendered_pixmap(self) -> QPixmap:
        """Render all annotations onto the base pixmap and return it."""
        result = self._base_pixmap.copy()
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for item in self._items:
            if isinstance(item, BlurItem):
                item.render(painter, self._base_pixmap)
            else:
                item.render(painter)
        painter.end()
        return result

    def undo(self):
        if self._items:
            item = self._items.pop()
            self._redo_stack.append(item)
            if isinstance(item, CounterItem):
                self._counter_value = max(1, self._counter_value - 1)
            self.update()

    def redo(self):
        if self._redo_stack:
            item = self._redo_stack.pop()
            self._items.append(item)
            if isinstance(item, CounterItem):
                self._counter_value = item.number + 1
            self.update()

    def clear_all(self):
        self._redo_stack.extend(reversed(self._items))
        self._items.clear()
        self._counter_value = 1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw base screenshot
        painter.drawPixmap(0, 0, self._base_pixmap)

        # Draw committed items
        for item in self._items:
            if isinstance(item, BlurItem):
                item.render(painter, self._base_pixmap)
            else:
                item.render(painter)

        # Draw current (in-progress) item
        if self._current_item is not None:
            if isinstance(self._current_item, BlurItem):
                self._current_item.render(painter, self._base_pixmap)
            else:
                self._current_item.render(painter)

        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        pos = QPointF(event.pos())
        self._redo_stack.clear()  # Clear redo on new action

        if self.current_tool == TOOL_TEXT:
            self._place_text(pos)
            return

        if self.current_tool == TOOL_COUNTER:
            item = CounterItem(color=self.current_color, width=self.current_width)
            item.position = pos
            item.number = self._counter_value
            self._counter_value += 1
            self._items.append(item)
            self.update()
            return

        item = create_tool_item(self.current_tool, self.current_color, self.current_width)

        if isinstance(item, PenItem):
            item.add_point(pos)
        elif hasattr(item, 'start'):
            item.start = pos
            item.end = pos

        self._current_item = item

    def mouseMoveEvent(self, event):
        if self._current_item is None:
            return

        pos = QPointF(event.pos())
        if isinstance(self._current_item, PenItem):
            self._current_item.add_point(pos)
        elif hasattr(self._current_item, 'end'):
            self._current_item.end = pos

        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self._current_item is not None:
            self._items.append(self._current_item)
            self._current_item = None
            self.update()

    def _place_text(self, pos: QPointF):
        """Open a dialog to get text input, then place it."""
        text, ok = QInputDialog.getText(
            self, "Add Text", "Enter text:",
        )
        if ok and text:
            item = TextItem(color=self.current_color, width=self.current_width)
            item.position = pos
            item.text = text
            item.font_size = self.font_size
            self._items.append(item)
            self.update()


class AnnotatorWindow(QWidget):
    """Main annotation editor window."""

    closed = pyqtSignal()

    def __init__(self, pixmap: QPixmap, config=None):
        super().__init__()
        self._config = config
        self.setWindowTitle("ClearShot — Annotate")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        # Create canvas
        self._canvas = AnnotationCanvas(pixmap, self)

        # Build UI
        self._build_ui()

        # Size to fit content
        self.adjustSize()
        self._center_on_screen()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar (fixed height)
        toolbar = self._create_toolbar()
        toolbar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(toolbar)

        # Canvas inside a scroll area so it absorbs all resize space
        scroll_area = QScrollArea()
        scroll_area.setWidget(self._canvas)
        scroll_area.setWidgetResizable(False)
        scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background: #1e1e1e;
                border: none;
            }
        """)
        scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(scroll_area, 1)

        # Action bar (fixed height)
        action_bar = self._create_action_bar()
        action_bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(action_bar)

    def _create_toolbar(self) -> QWidget:
        toolbar = QFrame()
        toolbar.setObjectName("annotatorToolbar")
        toolbar.setStyleSheet("""
            #annotatorToolbar {
                background: #2b2b2b;
                border-bottom: 1px solid #444;
                padding: 4px 8px;
            }
            QToolButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 6px 10px;
                color: #ddd;
                font-size: 12px;
                font-weight: bold;
                min-width: 28px;
            }
            QToolButton:hover {
                background: #3d3d3d;
                border: 1px solid #555;
            }
            QToolButton:checked {
                background: #0078D4;
                border: 1px solid #0078D4;
                color: white;
            }
            QPushButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 6px 10px;
                color: #ddd;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #3d3d3d;
                border: 1px solid #555;
            }
            QLabel {
                color: #aaa;
                font-size: 11px;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #555;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 14px;
                height: 14px;
                margin: -5px 0;
                background: #0078D4;
                border-radius: 7px;
            }
        """)

        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)

        tool_defs = [
            (TOOL_PEN, "✏️", "Pen (P)"),
            (TOOL_LINE, "━", "Line (L)"),
            (TOOL_ARROW, "➜", "Arrow (A)"),
            (TOOL_RECT, "▭", "Rectangle (R)"),
            (TOOL_FILLED_RECT, "▮", "Highlight (H)"),
            (TOOL_ELLIPSE, "⬭", "Ellipse (E)"),
            (TOOL_TEXT, "T", "Text (T)"),
            (TOOL_BLUR, "▦", "Blur (B)"),
            (TOOL_COUNTER, "#", "Counter (N)"),
        ]

        for tool_id, icon_text, tooltip in tool_defs:
            btn = QToolButton()
            btn.setText(icon_text)
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            btn.setProperty("tool_id", tool_id)
            btn.clicked.connect(lambda checked, tid=tool_id: self._set_tool(tid))
            self._tool_group.addButton(btn)
            layout.addWidget(btn)
            if tool_id == TOOL_PEN:
                btn.setChecked(True)

        layout.addWidget(self._separator())

        # Color buttons
        self._color_buttons = []
        for color in COLOR_PALETTE[:6]:
            btn = QPushButton()
            btn.setFixedSize(24, 24)
            btn.setStyleSheet(
                f"QPushButton {{ background: {color}; border: 2px solid #555; border-radius: 4px; }}"
                f"QPushButton:hover {{ border: 2px solid #fff; }}"
            )
            btn.setToolTip(color)
            btn.clicked.connect(lambda checked, c=color: self._set_color(c))
            layout.addWidget(btn)
            self._color_buttons.append(btn)

        # Custom color button
        custom_color_btn = QPushButton("🎨")
        custom_color_btn.setToolTip("Custom color")
        custom_color_btn.clicked.connect(self._pick_custom_color)
        layout.addWidget(custom_color_btn)

        layout.addWidget(self._separator())

        # Width slider
        width_label = QLabel("Size:")
        layout.addWidget(width_label)
        
        self._width_slider = QSlider(Qt.Orientation.Horizontal)
        self._width_slider.setRange(1, 20)
        self._width_slider.setValue(DEFAULT_PEN_WIDTH)
        self._width_slider.setFixedWidth(100)
        self._width_slider.valueChanged.connect(self._set_width)
        layout.addWidget(self._width_slider)

        self._width_value_label = QLabel(str(DEFAULT_PEN_WIDTH))
        self._width_value_label.setFixedWidth(20)
        layout.addWidget(self._width_value_label)

        layout.addStretch()

        # Undo / Redo
        undo_btn = QPushButton("↶ Undo")
        undo_btn.setToolTip("Undo (Ctrl+Z)")
        undo_btn.clicked.connect(self._canvas.undo)
        layout.addWidget(undo_btn)

        redo_btn = QPushButton("↷ Redo")
        redo_btn.setToolTip("Redo (Ctrl+Y)")
        redo_btn.clicked.connect(self._canvas.redo)
        layout.addWidget(redo_btn)

        clear_btn = QPushButton("🗑 Clear")
        clear_btn.setToolTip("Clear all annotations")
        clear_btn.clicked.connect(self._canvas.clear_all)
        layout.addWidget(clear_btn)

        return toolbar

    def _create_action_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("actionBar")
        bar.setStyleSheet("""
            #actionBar {
                background: #2b2b2b;
                border-top: 1px solid #444;
                padding: 6px 12px;
            }
            QPushButton {
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 13px;
                font-weight: bold;
                min-width: 80px;
            }
        """)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 6, 8, 6)

        # Copy to clipboard
        copy_btn = QPushButton("📋 Copy")
        copy_btn.setToolTip("Copy to clipboard (Ctrl+C)")
        copy_btn.setStyleSheet("""
            QPushButton {
                background: #0078D4;
                color: white;
                border: none;
            }
            QPushButton:hover {
                background: #1a8adf;
            }
        """)
        copy_btn.clicked.connect(self._copy_to_clipboard)
        layout.addWidget(copy_btn)

        # Save
        save_btn = QPushButton("💾 Save")
        save_btn.setToolTip("Save to file (Ctrl+S)")
        save_btn.setStyleSheet("""
            QPushButton {
                background: #107C10;
                color: white;
                border: none;
            }
            QPushButton:hover {
                background: #1a8f1a;
            }
        """)
        save_btn.clicked.connect(self._save_file)
        layout.addWidget(save_btn)

        # Quick Save
        qsave_btn = QPushButton("⚡ Quick Save")
        qsave_btn.setToolTip("Quick save (Ctrl+Shift+S)")
        qsave_btn.setStyleSheet("""
            QPushButton {
                background: #444;
                color: white;
                border: 1px solid #555;
            }
            QPushButton:hover {
                background: #555;
            }
        """)
        qsave_btn.clicked.connect(self._quick_save)
        layout.addWidget(qsave_btn)

        layout.addStretch()

        # Close
        close_btn = QPushButton("✕ Close")
        close_btn.setToolTip("Discard and close (Escape)")
        close_btn.setStyleSheet("""
            QPushButton {
                background: #555;
                color: #ddd;
                border: 1px solid #666;
            }
            QPushButton:hover {
                background: #c42b1c;
                color: white;
            }
        """)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        return bar

    def _separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(2)
        sep.setStyleSheet("background: #444;")
        return sep

    def _set_tool(self, tool_id: str):
        self._canvas.current_tool = tool_id

    def _set_color(self, color: str):
        self._canvas.current_color = color

    def _pick_custom_color(self):
        color = QColorDialog.getColor(
            QColor(self._canvas.current_color),
            self,
            "Pick a color",
        )
        if color.isValid():
            self._canvas.current_color = color.name()

    def _set_width(self, value: int):
        self._canvas.current_width = value
        self._canvas.font_size = max(10, value * 3)
        self._width_value_label.setText(str(value))

    def _copy_to_clipboard(self):
        pixmap = self._canvas.get_rendered_pixmap()
        success = copy_pixmap_to_clipboard(pixmap)
        if success:
            self._flash_feedback("Copied to clipboard!")

    def _save_file(self):
        save_dir = ""
        fmt = "PNG"
        if self._config:
            save_dir = self._config.get("save_path", "")
            fmt = self._config.get("image_format", "PNG")

        ext = IMAGE_FORMATS.get(fmt, ".png")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"ClearShot_{timestamp}{ext}"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Screenshot",
            os.path.join(save_dir, default_name),
            "PNG (*.png);;JPEG (*.jpg *.jpeg);;BMP (*.bmp);;All Files (*)",
        )
        if file_path:
            pixmap = self._canvas.get_rendered_pixmap()
            pixmap.save(file_path)
            self._flash_feedback(f"Saved to {os.path.basename(file_path)}")

    def _quick_save(self):
        save_dir = os.path.expanduser("~/Pictures/ClearShot")
        fmt = "PNG"
        if self._config:
            save_dir = self._config.get("save_path", save_dir)
            fmt = self._config.get("image_format", "PNG")

        os.makedirs(save_dir, exist_ok=True)
        ext = IMAGE_FORMATS.get(fmt, ".png")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"ClearShot_{timestamp}{ext}"
        file_path = os.path.join(save_dir, file_name)

        pixmap = self._canvas.get_rendered_pixmap()
        pixmap.save(file_path)
        self._flash_feedback(f"Quick saved: {file_name}")

    def _flash_feedback(self, message: str):
        """Show a brief tooltip-like feedback."""
        from PyQt6.QtWidgets import QToolTip
        QToolTip.showText(QCursor.pos(), message, self, self.rect(), 2000)

    def _center_on_screen(self):
        """Center the window on the primary screen."""
        screen = QApplication.primaryScreen()
        if screen:
            screen_geom = screen.availableGeometry()
            x = screen_geom.x() + (screen_geom.width() - self.width()) // 2
            y = screen_geom.y() + (screen_geom.height() - self.height()) // 2
            self.move(x, y)

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()

        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
            self._canvas.undo()
        elif key == Qt.Key.Key_Y and mods & Qt.KeyboardModifier.ControlModifier:
            self._canvas.redo()
        elif key == Qt.Key.Key_C and mods & Qt.KeyboardModifier.ControlModifier:
            self._copy_to_clipboard()
        elif key == Qt.Key.Key_S and mods & Qt.KeyboardModifier.ControlModifier:
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self._quick_save()
            else:
                self._save_file()
        # Tool shortcuts
        elif key == Qt.Key.Key_P:
            self._set_tool(TOOL_PEN)
            self._check_tool_button(TOOL_PEN)
        elif key == Qt.Key.Key_L:
            self._set_tool(TOOL_LINE)
            self._check_tool_button(TOOL_LINE)
        elif key == Qt.Key.Key_A:
            self._set_tool(TOOL_ARROW)
            self._check_tool_button(TOOL_ARROW)
        elif key == Qt.Key.Key_R:
            self._set_tool(TOOL_RECT)
            self._check_tool_button(TOOL_RECT)
        elif key == Qt.Key.Key_H:
            self._set_tool(TOOL_FILLED_RECT)
            self._check_tool_button(TOOL_FILLED_RECT)
        elif key == Qt.Key.Key_E:
            self._set_tool(TOOL_ELLIPSE)
            self._check_tool_button(TOOL_ELLIPSE)
        elif key == Qt.Key.Key_T:
            self._set_tool(TOOL_TEXT)
            self._check_tool_button(TOOL_TEXT)
        elif key == Qt.Key.Key_B:
            self._set_tool(TOOL_BLUR)
            self._check_tool_button(TOOL_BLUR)
        elif key == Qt.Key.Key_N:
            self._set_tool(TOOL_COUNTER)
            self._check_tool_button(TOOL_COUNTER)
        else:
            super().keyPressEvent(event)

    def _check_tool_button(self, tool_id: str):
        """Check the button matching the given tool."""
        for btn in self._tool_group.buttons():
            if btn.property("tool_id") == tool_id:
                btn.setChecked(True)
                break

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
