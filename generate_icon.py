"""Generate the ClearShot application icon as PNG and ICO."""

import sys
import os

# Add the project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen, QBrush, QRadialGradient, QFont

def generate_icon():
    app = QApplication.instance() or QApplication(sys.argv)
    
    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    # Background gradient circle
    gradient = QRadialGradient(size / 2, size / 2, size / 2)
    gradient.setColorAt(0, QColor(0, 150, 255))   # Bright blue center
    gradient.setColorAt(0.7, QColor(0, 100, 212))  # Medium blue
    gradient.setColorAt(1, QColor(40, 60, 150))    # Darker blue edge
    
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(gradient))
    margin = 8
    painter.drawRoundedRect(margin, margin, size - margin * 2, size - margin * 2, 40, 40)
    
    # Crosshair elements
    cx, cy = size // 2, size // 2
    
    # Outer ring
    ring_pen = QPen(QColor(255, 255, 255, 220), 8)
    painter.setPen(ring_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    r_outer = 60
    painter.drawEllipse(cx - r_outer, cy - r_outer, r_outer * 2, r_outer * 2)
    
    # Inner dot
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(255, 255, 255, 240)))
    r_inner = 10
    painter.drawEllipse(cx - r_inner, cy - r_inner, r_inner * 2, r_inner * 2)
    
    # Crosshair lines (extending beyond the circle)
    line_pen = QPen(QColor(255, 255, 255, 220), 6)
    line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(line_pen)
    
    gap = 18  # Gap around center dot
    line_ext = 38  # How far lines extend beyond circle
    
    # Top
    painter.drawLine(cx, cy - r_outer - line_ext, cx, cy - gap)
    # Bottom
    painter.drawLine(cx, cy + gap, cx, cy + r_outer + line_ext)
    # Left
    painter.drawLine(cx - r_outer - line_ext, cy, cx - gap, cy)
    # Right
    painter.drawLine(cx + gap, cy, cx + r_outer + line_ext, cy)
    
    painter.end()
    
    # Save as PNG
    os.makedirs("resources", exist_ok=True)
    pixmap.save("resources/icon.png")
    print("Saved resources/icon.png")
    
    # Generate ICO from the saved PNG using Pillow
    try:
        from PIL import Image
        img = Image.open("resources/icon.png")
        
        # Create ICO with multiple sizes
        icon_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        img.save("resources/icon.ico", format="ICO", sizes=icon_sizes)
        print("Saved resources/icon.ico")
    except Exception as e:
        print(f"ICO generation failed (you can convert PNG to ICO manually): {e}")
    
    print("Done!")

if __name__ == "__main__":
    generate_icon()
