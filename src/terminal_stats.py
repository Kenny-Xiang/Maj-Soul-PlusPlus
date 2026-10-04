"""Terminal formatting shared by the Python monitor; no network or UI operations."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

PHASES = {
    "waiting": "等待对局", "connected": "发现牌局连接，等待动作",
    "playing": "正在对局", "between_rounds": "小局结束，等待下一局",
    "ended": "对局结束", "disconnected": "牌局连接中断", "stopped": "监听已停止",
}
ACTION_NAMES = {
    "ActionNewRound": "开局发牌", "ActionDealTile": "摸牌", "ActionDiscardTile": "出牌",
    "ActionChiPengGang": "吃碰杠", "ActionAnGangAddGang": "暗杠／加杠", "ActionBaBei": "拔北",
    "ActionHule": "和牌结算", "ActionNoTile": "荒牌流局", "ActionLiuJu": "途中流局",
    "ActionMJStart": "对局开始", "GameRestore": "恢复牌局",
}


def clean(value):
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(value or ""))[:500]


def tile(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9][mpsz]", value):
        return clean(value)
    number, suit = value
    if suit == "z":
        return {"1": "东", "2": "南", "3": "西", "4": "北", "5": "白", "6": "发", "7": "中"}.get(number, value)
    return ("赤五" if number == "0" else number) + {"m": "万", "p": "筒", "s": "索"}[suit]


def tiles(values):
    return " ".join(map(tile, values)) or "—"


def format_turn(event):
    state = event["state"]
    known = list(state["hand"]) if state["handComplete"] else []
    known += [d["tile"] for river in state["rivers"] for d in river if not d.get("called")]
    known += [t for melds in state["melds"] for meld in melds for t in meld["tiles"]]
    known += state["doras"] + ["4z"] * sum(state["north"])
    counts = Counter("5" + t[1:] if t.startswith("0") else t for t in known
                     if isinstance(t, str) and re.fullmatch(r"[0-9][mpsz]", t))
    time = datetime.fromisoformat(event["time"].replace("Z", "+00:00"))
    time = time.astimezone(timezone(timedelta(hours=8))).strftime("%Y/%m/%d %H:%M:%S")
    seat = state["selfSeat"] if state["selfSeat"] is not None else "待确认"
    left = state["left"] if state["left"] is not None else "未知"
    action = ACTION_NAMES.get(event['trigger'], clean(event['trigger']))
    actor = event.get('actorSeat')
    action = f"座位{actor} {action}" if actor is not None else action
    lines = ["\n" + "═" * 60,
             f"{time} · 第 {event['turnNumber']} 次更新 · 动作 #{event['step']}",
             f"最新动作：{action}",
             f"状态：{PHASES.get(state['phase'], clean(state['phase']))}",
             f"本机座位：{seat}  剩余牌：{left}"]
    if state.get("round"):
        r = state["round"]
        wind = "东南西北"[r["chang"]] if r["chang"] in range(4) else str(r["chang"])
        lines.append(f"局况：{wind}{r['ju'] + 1}局 {r['ben']}本场")
    if state["handComplete"]:
        lines.append(f"本人手牌：{tiles(state['hand'])}")
    else:
        draw = f"；最近摸牌 {tile(state['lastDraw'])}" if state.get("lastDraw") else ""
        lines.append("本人完整手牌：尚未取得" + draw)
    if state.get("baseline") == "snapshot_unverified":
        lines.append(f"待核对快照：{tiles(state['hand'])}")
    scores = " / ".join("?" if s is None else str(s) for s in state["scores"]) or "未知"
    lines.append(f"宝牌指示：{tiles(state['doras'])}  分数：{scores}")
    for index, river in enumerate(state["rivers"][:state["playerCount"]]):
        discards = " ".join(tile(d["tile"]) + ("[立直]" if d.get("riichi") else "")
                            + ("[被鸣]" if d.get("called") else "") for d in river) or "—"
        melds = " / ".join(tiles(m["tiles"]) for m in state["melds"][index]) or "—"
        riichi = "（已立直）" if index != state["selfSeat"] and state.get("riichi", [None] * 4)[index] is True else ""
        lines += [f"座位{index}{riichi} 弃牌({len(river)})：{discards}",
                  f"      副露：{melds}  拔北：{state['north'][index]}"]
    partial = "" if state["historyComplete"] and state["handComplete"] else "（仅已观察部分）"
    counts_text = " ".join(f"{tile(t)}×{n}" for t, n in sorted(counts.items())) or "—"
    lines.append(f"已知牌计数{partial}：{counts_text}")
    hand = "已取得手牌基线" if state["handComplete"] else "缺少完整手牌"
    history = "本小局动作连续" if state["historyComplete"] else "历史不完整或待核对"
    lines.append(f"完整性：{hand}；{history}")
    if state.get("warning"):
        lines.append(f"说明：{clean(state['warning'])}")
    stats = event["statistics"]
    lines.append(f"触发：{clean(event['trigger'])} · 入站 {stats['received']} 条 · 解析错误 {stats['errors']} 次")
    return "\n".join(lines)


class TerminalLog:
    def __init__(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
        self.text_path = folder / (stamp + ".txt")
        self.json_path = folder / (stamp + ".jsonl")
        self.seen = {}

    def write(self, text):
        with self.text_path.open("a", encoding="utf-8") as file:
            file.write(text + "\n")

    def accept(self, event):
        session, serial = event["session"], event["serial"]
        if serial <= self.seen.get(session, 0):
            return
        kind = event["kind"]
        if kind == "turn":
            self.write(format_turn(event))
        elif kind in ("status", "error"):
            self.write(f"[{PHASES.get(event.get('phase'), kind)}] {clean(event.get('message'))}")
        if kind != "heartbeat":
            with self.json_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.seen[session] = serial
        if len(self.seen) > 100:
            del self.seen[next(iter(self.seen))]
