# Maj-Soul++

A standalone macOS window for Mahjong Soul with live tile tracking, a translucent statistics overlay, and discard recommendations based on your hand and public game information.

The app uses the system WebKit engine to load the game, observes messages received by that window, and passes statistics to Python through a native message bridge. The overlay updates after the initial deal and every accepted table action, including other players' actions.

Source repository: [Kenny-Xiang/Maj-Soul-PlusPlus](https://github.com/Kenny-Xiang/Maj-Soul-PlusPlus). The application interface and detailed reference documents are currently in Chinese.

## Features

- **Fixed overlay columns:** game information on the left; recording status, diagnostics, and current discard advice on the right. The overlay stays in the upper half of the window and lets mouse clicks pass through to the game.
- **Live game statistics:** your hand and seat, round information, scores, remaining tile count, dora indicators, each player's discards and melds, extracted North tiles, and known tile counts.
- **Confirmed riichi labels:** opponents' labels indicate confirmed normal or double riichi. A declaration alone is not treated as confirmation. Labels clear when a new round starts or the match ends.
- **Discard recommendations:** when it is your turn and the required information is complete, compare legal discards by shanten, effective unseen tiles, estimated win probability and hand value, and estimated immediate deal-in risk and loss. Recommendations are displayed only; the app does not play moves for you.
- **Clear update boundaries:** duplicate actions do not produce duplicate updates. Statistics remain visible between rounds and clear at the end of a match; historical logs are retained.
- **Local operation:** a dedicated WebKit login profile, one running game window, and text and JSONL logs stored in your user data directory.

The advisor assumes standard three-player or four-player Mahjong Soul rules. Its probability estimates use an uncalibrated public-information model and are not measured win rates or a guarantee of optimal play. See the [discard advisor documentation](docs/出牌建议.md) for the model, metrics, and limitations.

## Using the app

Open `Maj-Soul++.app` and sign in inside its game window on first use. The app keeps its own WebKit website data and can reuse a valid login on later launches. Launching it again activates the existing window. Close the main window or quit the app to exit.

A built app includes Python, its dependencies, and the application resources. It runs independently of the source checkout and does not require an external Python, Node.js, or Xcode installation. See the build instructions below to create the app from source.

## Requirements for development

- Apple Silicon Mac running macOS 14 or later.
- An independently installed **Python 3.12**.
- **Node.js 18 or later** for the JavaScript tests.

Runtime dependencies are pinned in `requirements.txt`: PyObjC 11.1 and `mahjong` 2.0.0. Build dependencies are listed in `requirements-build.txt`, including PyInstaller 6.22.0.

From the repository root, create an isolated environment and install the dependencies:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
```

## Run from source

```sh
.venv/bin/python src/monitor.py
```

The collector is installed before the game page loads. No manual script injection is required.

## Test

Run the complete test suite:

```sh
./scripts/test.sh
```

The script runs JavaScript protocol and state checks, Python formatting and logging checks, advisor and background-worker tests, an isolated native WebKit replay, and overlay layout checks.

The native WebKit and overlay checks require an active macOS graphical session. They use local fixtures and a nonpersistent WebKit data store without connecting to game servers or interacting with a live match.

To save a local overlay preview:

```sh
PYTHONPATH=src .venv/bin/python tests/test_overlay.py --snapshot
```

The image is written to `build/overlay-preview.png`, which is ignored by Git.

## Build a standalone app

```sh
./scripts/build.sh
open 'dist/Maj-Soul++.app'
```

The output is `dist/Maj-Soul++.app`. PyInstaller uses `onedir` and `windowed` mode to package the Python runtime, dependencies, collector scripts, documentation, and source into a macOS app without a console window.

The build writes to the repository's `build/` and `dist/` directories. It does not replace an app already installed elsewhere. Update the source and rebuild rather than editing files inside a signed app bundle.

Verify the packaged runtime with the offline entrypoints:

```sh
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-native
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-overlay
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-advisor
```

## Repository layout

```text
Maj-Soul-PlusPlus/
├── src/
│   ├── monitor.py             macOS window, native message bridge, and startup
│   ├── terminal_stats.py      Statistics formatting and local logs; no console output
│   ├── core.cjs               Protocol decoding and game state
│   ├── browser.js             Passive collection, action updates, and match resets
│   ├── overlay.js             Translucent overlay with click-through behavior
│   ├── advisor.py             Rule calculations and discard evaluation
│   └── advice_worker.py       Background evaluation and stale-result invalidation
├── tests/                     JavaScript, Python, and native WebKit tests
│   └── fixtures/              Recorded replay fixtures
├── docs/                      Usage guide, protocol analysis, and rules references
├── scripts/test.sh            Complete test suite
├── scripts/build.sh           Standalone app build
├── requirements.txt           Runtime dependencies
├── requirements-build.txt     Build dependencies
├── Maj-Soul++.spec            PyInstaller configuration
└── .gitignore                 Excludes environments, runtime data, and build outputs
```

## Local data

Runtime files are stored in:

```text
~/Library/Application Support/Maj-Soul++/
```

- `logs/`: text (`.txt`) and structured (`.jsonl`) records for each run.
- `launcher.log`: startup and runtime diagnostics.
- `monitor.lock`: the single-instance lock.

WebKit stores login data in the user's profile, outside the repository. Statistics are written in the background, with displayed timestamps in Beijing time (UTC+8). Runtime data is not written back into the app bundle.

## Information boundaries

The collector only sees messages delivered to its own game window. A new-round deal can establish a complete baseline; joining mid-round depends on the recovery data supplied by the server. Missing steps, unknown actions, inconsistent updates, and unverified recovery boundaries are reported instead of being presented as complete history.

The app does not infer opponents' concealed hands or reconstruct information that was never received. Known tile counts combine red and ordinary fives and avoid counting a called discard again as part of a meld. These counts are not the exact composition of the remaining live wall: unseen tiles can also be in opponents' hands or the dead wall.

Advice pauses when it is not your turn, the required baseline is missing, recovery is unverified, the connection is lost, or the round has ended. New actions invalidate stale recommendations. Custom room rules and event modes are outside the advisor's standard-rule assumptions.

Offline replay verifies behavior against fixtures; it does not establish that every server recovery scenario or live-game edge case has been validated.

## Contributing

Make changes on a feature branch, run the relevant checks, and open a pull request targeting `main`. Use English commit messages, PR titles, and PR descriptions. Source changes and app builds are separate steps: pushing code to GitHub does not automatically update an installed app.

Git tracks source, tests, fixtures, documentation, dependency lists, and build configuration. Virtual environments, runtime data, caches, generated app bundles, and build outputs are excluded by `.gitignore`.

## Further documentation

The detailed guides below are currently in Chinese:

- [Usage guide](docs/使用说明.md)
- [Discard advisor: metrics, model, and limitations](docs/出牌建议.md)
- [Message collection and game-state completeness analysis](docs/监听方法与完整对局信息获取分析.md)
- [Mahjong Soul rules reference](docs/雀魂规则_Agent参考.md)

The license for the bundled `mahjong` dependency is included in [mahjong-LICENSE.txt](docs/mahjong-LICENSE.txt).
