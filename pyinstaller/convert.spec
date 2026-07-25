# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for audioconvert CLI binary.

Build with:
    pyinstaller pyinstaller/convert.spec

To bundle ffmpeg, place the static binary at pyinstaller/ffmpeg
before building, or set FFMPEG_PATH env var.
"""
import os
from pathlib import Path

block_cipher = None

spec_dir = Path(SPECPATH)
ffmpeg_path = os.environ.get('FFMPEG_PATH', str(spec_dir / 'ffmpeg'))
has_ffmpeg = Path(ffmpeg_path).exists()

datas = []
binaries = []
if has_ffmpeg:
    binaries.append((ffmpeg_path, '.'))

a = Analysis(
    [str(spec_dir.parent / 'convert.py')],
    pathex=[str(spec_dir.parent)],
    binaries=binaries,
    datas=datas,
    hiddenimports=['src', 'src.convert', 'src.utils', 'src.audio_processing',
                   'src.cover_art', 'src.metadata'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='audioconvert',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='audioconvert',
)
