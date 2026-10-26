# Windows AMD64, one-file console build; stdlib application needs no hidden imports.
a = Analysis(['CKSingleMonitorFix.py'], pathex=[], binaries=[], datas=[],
             hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='CKSingleMonitorFix',
          debug=False, strip=False, upx=False, console=True)
