# Build from the repository root using scripts/build.sh.
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH)
datas = [(str(root / 'src' / name), '.') for name in
         ('core.cjs', 'browser.js', 'overlay.js', 'autoplay.js', 'background.js',
          'unity_transport.js', 'unity_actions.js', 'unity_lobby.js')]
datas += copy_metadata('mahjong')
datas += [(str(root / 'docs'), 'docs')]
datas += [(str(root / name), '.') for name in ('README.md', 'README.en.md')]
for folder in ('src', 'tests', 'docs', 'scripts'):
    for path in (root / folder).rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo'):
            datas.append((str(path), str(Path('source') / path.relative_to(root).parent)))
for name in ('README.md', 'README.en.md', '.gitignore', 'requirements.txt', 'requirements-build.txt', 'Maj-Soul++.spec'):
    datas.append((str(root / name), 'source'))

a = Analysis([str(root / 'src/monitor.py')], pathex=[str(root / 'src')], datas=datas,
             hiddenimports=['monitor', 'Foundation', 'AppKit', 'WebKit', 'unittest', 'unittest.mock', 'platform'],
             hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Maj-Soul++',
          debug=False, strip=False, upx=False, console=False,
          argv_emulation=False, target_arch='arm64', codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Maj-Soul++')
app = BUNDLE(coll, name='Maj-Soul++.app', icon=None,
             bundle_identifier='local.kenny.mahjong-monitor',
             info_plist={'CFBundleName': 'Maj-Soul++', 'CFBundleDisplayName': 'Maj-Soul++',
                         'CFBundleShortVersionString': '6.1', 'CFBundleVersion': '8',
                         'LSMinimumSystemVersion': '14.0', 'NSHighResolutionCapable': True})
