# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # 打包 logo 图标/图片，供运行时设置窗口/任务栏图标（sys._MEIPASS 解压）
    datas=[('logo.ico', '.'), ('logo.png', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除未使用的大型依赖（PyMuPDF 的 pymupdf.table 会引入 pandas/numpy/matplotlib 等）
    excludes=[
        'pandas', 'numpy', 'matplotlib', 'lxml', 'openpyxl', 'fontTools',
        'bs4', 'beautifulsoup4', 'scipy', 'PIL', 'pyparsing', 'cycler',
        'dateutil', 'six', 'jinja2', 'markupsafe', 'odf', 'xlrd',
        'xlsxwriter', 'pyarrow', 'numba', 'numexpr', 'tables', 'sqlalchemy',
        'IPython', 'traitlets', 'tornado',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PDF阅读翻译器',
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
    icon=['logo.ico'],
)
