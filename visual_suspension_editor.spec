# -*- mode: python ; coding: utf-8 -*-
import os
import sys

# Ensure we can find site-packages for data markers if needed
site_packages = next(p for p in sys.path if 'site-packages' in p)

block_cipher = None

a = Analysis(
    ['visual_suspension_editor.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'vtkmodules',
        'vtkmodules.all',
        'vtkmodules.qt.QVTKRenderWindowInteractor',
        'vtkmodules.util',
        'vtkmodules.util.numpy_support',
        'vtkmodules.numpy_interface',
        'vtkmodules.numpy_interface.dataset_adapter',
        'vtkmodules.io.export',
        'vtkmodules.io.import',
        'pyvistaqt',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='VisualSuspensionEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to False for windowed mode
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)
