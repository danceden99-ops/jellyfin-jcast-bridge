# -*- mode: python ; coding: utf-8 -*-
# PyInstaller specification for JCastBridge
# Generates a single-file, windowless Windows System Tray executable (.exe)

import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_all

block_cipher = None

# Collect all C-extensions, binaries, and submodules for cryptography and other core packages
crypto_datas, crypto_binaries, crypto_hidden = collect_all('cryptography')
pystray_datas, pystray_binaries, pystray_hidden = collect_all('pystray')
zeroconf_datas, zeroconf_binaries, zeroconf_hidden = collect_all('zeroconf')
aiohttp_datas, aiohttp_binaries, aiohttp_hidden = collect_all('aiohttp')

# Ensure python3.dll and OpenSSL runtime DLLs are explicitly bundled for abi3 C-extensions
py_dir = os.path.dirname(sys.executable)
extra_binaries = []
for candidate_dir in [py_dir, os.path.join(py_dir, 'DLLs')]:
    for dll_name in ['python3.dll', 'libcrypto-3.dll', 'libssl-3.dll', 'libcrypto-3-x64.dll', 'libssl-3-x64.dll']:
        target_path = os.path.join(candidate_dir, dll_name)
        if os.path.isfile(target_path):
            extra_binaries.append((target_path, '.'))

all_datas = crypto_datas + pystray_datas + zeroconf_datas + aiohttp_datas
all_binaries = crypto_binaries + pystray_binaries + zeroconf_binaries + aiohttp_binaries + extra_binaries
all_hiddenimports = (
    crypto_hidden
    + [
        'cryptography.hazmat.bindings._rust',
        'cryptography.hazmat.bindings._rust.x509',
        'cryptography.hazmat.bindings._rust.openssl',
    ]
    + pystray_hidden
    + zeroconf_hidden
    + aiohttp_hidden
    + [
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'yaml',
        'jellyfin_jriver_bridge',
    ]
    + collect_submodules('jellyfin_jriver_bridge')
)

a = Analysis(
    ['run_tray.py'],
    pathex=[],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'pandas', 'unittest', 'test'],
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
    name='JCastBridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Windowless: runs directly in the Windows system tray
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
