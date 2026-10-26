# Windows AMD64, one-file console build; stdlib application needs no hidden imports.
a = Analysis(['CKSingleMonitorFix.py'], pathex=[], binaries=[], datas=[],
             hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[])
pyz = PYZ(a.pure)
# PyInstaller 6.16 OPTIONS, parsed before interpreter initialization. Unlike
# PYTHONUTF8 in the child environment, this configures the frozen interpreter.
# https://pyinstaller.org/en/v6.16.0/spec-files.html#specifying-python-interpreter-options
options = [('X utf8=1', None, 'OPTION')]
exe = EXE(pyz, a.scripts, a.binaries, a.datas, options, name='CKSingleMonitorFix',
          debug=False, strip=False, upx=False, console=True)
