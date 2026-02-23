"""ClearShot — Windows clipboard operations for copying images."""

import io
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import QBuffer, QIODevice


def copy_pixmap_to_clipboard(pixmap: QPixmap) -> bool:
    """Copy a QPixmap to the Windows clipboard in multiple formats.
    
    Sets CF_DIBV5, CF_DIB, and PNG clipboard formats for maximum
    compatibility with all Windows apps including Slack, Discord,
    browsers, Paint, Photoshop, etc.
    
    Returns True on success, False on failure.
    """
    try:
        import win32clipboard
        import ctypes
        import struct

        # Convert QPixmap to QImage (RGBA)
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        
        width = image.width()
        height = image.height()
        
        # ── PNG data (for Slack, Discord, browsers) ──
        png_buffer = QBuffer()
        png_buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(png_buffer, "PNG")
        png_buffer.close()
        png_data = bytes(png_buffer.data())
        
        # ── DIB data (for native Windows apps) ──
        header_size = 124  # BITMAPV5HEADER size
        bits_per_pixel = 32
        image_size = width * height * 4
        
        header = struct.pack(
            '<IiiHHIIiiIIIIIIIIIIIIII',
            header_size,          # biSize
            width,                # biWidth
            -height,              # biHeight (negative = top-down)
            1,                    # biPlanes
            bits_per_pixel,       # biBitCount
            3,                    # biCompression = BI_BITFIELDS
            image_size,           # biSizeImage
            0,                    # biXPelsPerMeter
            0,                    # biYPelsPerMeter
            0,                    # biClrUsed
            0,                    # biClrImportant
            0x00FF0000,           # bV5RedMask
            0x0000FF00,           # bV5GreenMask
            0x000000FF,           # bV5BlueMask
            0xFF000000,           # bV5AlphaMask
            0x73524742,           # bV5CSType = 'sRGB'
            0, 0, 0,              # bV5Endpoints (unused for sRGB)
            0, 0, 0,              # bV5GammaRed/Green/Blue
            0,                    # bV5Intent
        )
        
        ptr = image.bits()
        ptr.setsize(image_size)
        pixel_data = bytes(ptr)
        
        dib_data = header + pixel_data
        
        bmp_header_size = 40
        bmp_header = struct.pack(
            '<IiiHHIIiiII',
            bmp_header_size,
            width,
            -height,
            1,
            bits_per_pixel,
            0,  # BI_RGB
            image_size,
            0, 0, 0, 0,
        )
        bmp_data = bmp_header + pixel_data
        
        # ── Set all formats on clipboard ──
        # Register PNG clipboard format (used by Slack, Discord, Chrome, etc.)
        CF_PNG = win32clipboard.RegisterClipboardFormat("PNG")
        
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            # CF_DIBV5 = 17 (alpha-aware apps like Photoshop)
            win32clipboard.SetClipboardData(17, dib_data)
            # CF_DIB = 8 (standard Windows apps like Paint)
            win32clipboard.SetClipboardData(8, bmp_data)
            # PNG format (Slack, Discord, browsers)
            win32clipboard.SetClipboardData(CF_PNG, png_data)
        finally:
            win32clipboard.CloseClipboard()
        
        return True
        
    except ImportError:
        # Fallback to Qt clipboard
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setPixmap(pixmap)
            return True
        return False
    except Exception as e:
        print(f"Clipboard error: {e}")
        try:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setPixmap(pixmap)
                return True
        except Exception:
            pass
        return False
