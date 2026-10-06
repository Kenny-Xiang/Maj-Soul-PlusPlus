# Maj-Soul++

[简体中文](README.md) | **English**

A macOS client for Mahjong Soul's Chinese server, built on system WebKit, with live game statistics, a translucent overlay, and action recommendations. The application interface is in Chinese.

## Features

- **Game statistics:** your hand, round, scores, remaining tiles, dora indicators, each player's discards and melds, North extractions, and confirmed riichi status.
- **Statistics overlay:** a responsive, two-column layout with click-through interaction except for the automation buttons at the top, updated as table actions arrive.
- **Action recommendations:** compares discards, calls, riichi, North extraction, a nine-terminals abortive draw, and pass using your hand, public information, and server-authorized operations. Available tsumo or ron takes priority.
- **Automatic play:** an overlay switch, off by default, with four-player (default) or three-player mode and East (default) or South matches. Uses the current Unity client's authenticated connections to select an eligible standard ranked room for the chosen match length, match, follow advice, and continue after each match. Timing depends on the action and game state, with small random variation and deadlines taking priority. Each action requires both server acknowledgement and the corresponding game action. Reconnection preserves the switch and resumes automatically from a verified live state; actual state or operation errors pause automation. See the [usage guide](docs/使用说明.md#自动打牌).
- **Hand analysis and logging:** shows shanten, effective unseen tiles, and estimated hand value between actions; saves text and JSONL logs locally.

## Quick start

Requires an **Apple Silicon Mac running macOS 14 or later**.

If you already have `Maj-Soul++.app`, open it and sign in inside the game window. The app includes Python and its runtime dependencies and runs independently of the source checkout. Later launches can reuse a valid login; opening it again activates the existing window. See the [usage guide](docs/使用说明.md).

Running from source requires **Python 3.12**. Tests also require **Node.js 18 or later**.

```sh
git clone https://github.com/Kenny-Xiang/Maj-Soul-PlusPlus.git
cd Maj-Soul-PlusPlus
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python src/monitor.py
```

Dependencies are pinned in [requirements.txt](requirements.txt) and [requirements-build.txt](requirements-build.txt). The collector is installed before the page loads; no manual script injection is required.

## Test and build

Run these commands from the repository root after completing the setup above.

```sh
# Run the complete test suite
./scripts/test.sh

# Build and open the standalone app
./scripts/build.sh
open 'dist/Maj-Soul++.app'
```

Tests cover protocol and state handling, logging, the advisor, background tasks, native WebKit replay, and overlay layout. Native checks require an active macOS graphical session and use local fixtures without connecting to game servers. See the [offline evaluation guide](docs/advisor-evaluation.md) for advisor version comparisons.

The build produces `dist/Maj-Soul++.app` without replacing apps elsewhere. To update an installed app, rebuild and replace it; pushing source changes does not update the app automatically.

Verify the packaged runtime:

```sh
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-native
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-overlay
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-advisor
```

## Data and limitations

Runtime logs are stored in `~/Library/Application Support/Maj-Soul++/`: `logs/` contains text and JSONL records, and `launcher.log` contains diagnostics. WebKit login data is separate from other browsers. Runtime data is not written into the source checkout or app bundle.

- **Information scope:** the app only uses messages received by its own window and does not read opponents' concealed hands. Known tile counts do not describe the exact remaining wall. Recovery after joining mid-round depends on server data.
- **Advice validity:** analysis pauses without a trusted baseline, during unverified recovery, after disconnection, or at round end. State changes and submitted operations invalidate old recommendations.
- **Model scope:** assumes standard three-player or four-player rules, excluding custom rules and event modes. Probabilities and hand values include estimates that have not been calibrated against real play; recommendations do not guarantee optimal decisions. Offline tests do not validate every live-game scenario.

See the [advisor documentation](docs/出牌建议.md) for metric definitions, calculations, and model assumptions.

## Documentation

The following guides are in Chinese, except for the offline evaluation guide.

- [Usage guide](docs/使用说明.md)
- [Action advisor: metrics, model, and limitations](docs/出牌建议.md)
- [Message collection and game-state completeness](docs/监听方法与完整对局信息获取分析.md)
- [Mahjong Soul rules reference](docs/雀魂规则_Agent参考.md)
- [Offline evaluation guide (English)](docs/advisor-evaluation.md)

The `mahjong` dependency license is included in [mahjong-LICENSE.txt](docs/mahjong-LICENSE.txt).

## Contributing

Source, tests, and documentation are in `src/`, `tests/`, and `docs/`. Work on a feature branch, run the relevant checks, and open a pull request targeting `main`. Use English commit messages, PR titles, and descriptions. Keep environments, logs, and build outputs out of Git.
