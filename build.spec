# -*- mode: python ; coding: utf-8 -*-
"""ClearShot PyInstaller build spec."""

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Qt's standard hooks collect only the modules and plugins actually imported.
ffmpeg_datas, ffmpeg_binaries, ffmpeg_hiddenimports = collect_all('imageio_ffmpeg')
# SoundCard supplies its own data hook; collecting every submodule also bundles
# its PyInstaller tests and their unrelated test-framework dependencies.

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=ffmpeg_binaries,
    datas=[
        ('assets/icon.ico', 'assets'),
        ('assets/icon.png', 'assets'),
        ('THIRD_PARTY_NOTICES.md', '.'),
    ] + ffmpeg_datas,
    hiddenimports=[
        'win32clipboard',
        'win32con',
        'pywintypes',
        'mss',
        'imageio_ffmpeg',
        'soundcard',
        'cffi',
        'numpy',
    ] + ffmpeg_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pydoc'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ClearShot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)

# The installer and portable ZIP run in place, without extracting into TEMP.
installed_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ClearShot',
    console=False,
    strip=False,
    upx=True,
    icon='assets/icon.ico',
)
installed = COLLECT(
    installed_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='ClearShot',
)
