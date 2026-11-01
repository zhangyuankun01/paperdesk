# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('LICENSE', '.'), ('THIRD_PARTY_NOTICES.md', '.'),
           ('tests/fixtures', 'test-fixtures')],
    hiddenimports=['PIL.AvifImagePlugin', 'PIL.Jpeg2KImagePlugin', 'pi_heif'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Qt on Windows uses the operating system's ICU forwarder. An unrelated
# Poppler installation on PATH can cause PyInstaller to collect an incompatible
# versioned ICU instead. Keep those unrelated root-level DLLs out of the app.
a.binaries = [entry for entry in a.binaries
              if not (entry[0].lower().startswith('icu')
                      and entry[0].lower().endswith('.dll')
                      and '/' not in entry[0] and '\\' not in entry[0])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PaperDesk',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/app.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PaperDesk',
)
