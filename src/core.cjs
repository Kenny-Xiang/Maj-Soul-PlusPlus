// Liqi fields and action-data transform were checked against majsoulrpa
// revision 13698e226eace210ff8772fcabacfd2916299c4e and local live samples.
const textDecoder = new TextDecoder();
const KEYS = [132, 94, 78, 66, 57, 162, 31, 96, 28];

function fields(bytes) {
  let pos = 0;
  const result = new Map();
  function integer() {
    let value = 0n;
    for (let shift = 0n; shift < 70n && pos < bytes.length; shift += 7n) {
      const byte = bytes[pos++];
      value |= BigInt(byte & 127) << shift;
      if (!(byte & 128)) return value <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(value) : value;
    }
    throw new Error('Protobuf 整数不完整');
  }
  while (pos < bytes.length) {
    const tag = integer();
    if (typeof tag !== 'number' || tag < 8) throw new Error('Protobuf 字段编号无效');
    const id = Math.floor(tag / 8), wire = tag % 8;
    let value;
    if (wire === 0) value = integer();
    else if ([1, 2, 5].includes(wire)) {
      const size = wire === 2 ? integer() : wire === 1 ? 8 : 4;
      if (typeof size !== 'number' || pos + size > bytes.length) throw new Error('Protobuf 字段不完整');
      value = bytes.slice(pos, pos + size);
      pos += size;
    } else throw new Error(`不支持的 Protobuf wire ${wire}`);
    if (!result.has(id)) result.set(id, []);
    result.get(id).push(value);
  }
  return result;
}
const first = (f, n, fallback = 0) => f.get(n)?.[0] ?? fallback;
const str = (f, n) => f.has(n) ? textDecoder.decode(first(f, n)) : null;
const strings = (f, n) => (f.get(n) || []).map(b => textDecoder.decode(b));
const signed32 = n => Number(BigInt.asIntN(32, BigInt(n)));
function integers(f, n) {
  return (f.get(n) || []).flatMap(value => {
    if (!(value instanceof Uint8Array)) return [signed32(value)];
    const output = [];
    let current = 0n, shift = 0n;
    for (const b of value) {
      current |= BigInt(b & 127) << shift;
      if (b & 128) { shift += 7n; if (shift >= 70n) throw new Error('packed 整数过长'); }
      else { output.push(signed32(current)); current = shift = 0n; }
    }
    if (shift) throw new Error('packed 整数不完整');
    return output;
  });
}

function envelope(bytes) {
  const kind = bytes[0];
  if (![1, 2, 3].includes(kind) || bytes.length < (kind === 1 ? 2 : 4)) return null;
  const f = fields(bytes.slice(kind === 1 ? 1 : 3));
  return {kind, id: kind === 1 ? null : bytes[1] | bytes[2] << 8,
    name: str(f, 1), data: first(f, 2, new Uint8Array())};
}

function action(bytes, obfuscated = true) {
  const a = fields(bytes), name = str(a, 2);
  let data = first(a, 3, new Uint8Array());
  if (obfuscated) data = data.map((b, i) => b ^ (((23 ^ data.length) + 5 * i + KEYS[i % 9]) & 255));
  const f = fields(data), e = {name, step: first(a, 1)};
  const operationField = {ActionNewRound: 7, ActionDealTile: 4, ActionDiscardTile: 4,
    ActionChiPengGang: 6, ActionAnGangAddGang: 4, ActionBaBei: 4}[name];
  if (operationField && f.has(operationField)) {
    const op = fields(first(f, operationField));
    e.selfSeat = first(op, 1);
    e.operationDetails = (op.get(2) || []).map(b => {
      const detail = fields(b);
      return {type: first(detail, 1), combination: strings(detail, 2)};
    });
    e.operations = e.operationDetails.map(op => op.type);
    e.canDiscard = e.operations.includes(1);
  }
  const furitenField = {ActionDealTile: 7, ActionDiscardTile: 6, ActionChiPengGang: 7,
    ActionAnGangAddGang: 7, ActionBaBei: 7}[name];
  if (furitenField) e.furiten = Boolean(first(f, furitenField));
  if (['ActionDealTile','ActionChiPengGang','ActionLiuJu'].includes(name) && f.has(5)) {
    const l = fields(first(f, 5));
    e.liqiSuccess = {seat:first(l, 1), score:signed32(first(l, 2)), failed:Boolean(first(l, 4))};
    if (l.has(3)) e.liqiSuccess.riichiSticks = first(l, 3);
  }
  if (name === 'ActionNewRound') {
    Object.assign(e, {hand: strings(f, 4), scores: integers(f, 6), chang: first(f, 1),
      ju: first(f, 2), ben: first(f, 3), left: first(f, 13), riichiSticks: first(f, 8),
      doras: f.has(14) ? strings(f, 14) : strings(f, 5)});
  } else if (['ActionDealTile', 'ActionDiscardTile'].includes(name)) {
    Object.assign(e, {seat: first(f, 1), tile: str(f, 2)});
    if (name === 'ActionDealTile') Object.assign(e, {left: first(f, 3), doras: strings(f, 6)});
    else Object.assign(e, {moqie: Boolean(first(f, 5)), riichi: Boolean(first(f, 3) || first(f, 9)),
      doubleRiichi: Boolean(first(f, 9)), doras: strings(f, 8)});
  } else if (name === 'ActionChiPengGang') {
    Object.assign(e, {seat: first(f, 1), type: first(f, 2), tiles: strings(f, 3), froms: integers(f, 4)});
  } else if (name === 'ActionAnGangAddGang') {
    Object.assign(e, {seat: first(f, 1), type: first(f, 2), tile: str(f, 3), doras: strings(f, 6)});
  } else if (name === 'ActionBaBei') Object.assign(e, {seat: first(f, 1), moqie: Boolean(first(f, 9)), doras: strings(f, 6)});
  else if (name === 'ActionHule') Object.assign(e, {matchEnd: f.has(6), scores: integers(f, 5)});
  else if (name === 'ActionNoTile') e.matchEnd = Boolean(first(f, 4));
  else if (name === 'ActionLiuJu') e.matchEnd = f.has(2);
  else if (name !== 'ActionMJStart') e.unsupported = true;
  return e;
}

function restore(bytes) {
  const response = fields(bytes);
  if (response.has(1)) {
    const error = fields(first(response, 1));
    if (first(error, 1)) throw new Error(`游戏响应错误 ${first(error, 1)}`);
  }
  const result = {step: first(response, 3), ended: Boolean(first(response, 2)), actions: [], snapshot: null};
  if (!response.has(4)) return result;
  const f = fields(first(response, 4));
  result.actions = (f.get(2) || []).map(b => action(b, false));
  if (f.has(1)) {
    const s = fields(first(f, 1));
    result.snapshot = {selfSeat: first(s, 4), hand: strings(s, 6), doras: strings(s, 7),
      chang: first(s, 1), ju: first(s, 2), ben: first(s, 3), left: first(s, 5),
      players: (s.get(9) || []).map(b => {
        const p = fields(b);
        return {score: signed32(first(p, 1)), discards: strings(p, 4),
          melds: (p.get(5) || []).map(m => {const q = fields(m);
            return {type: first(q, 1), tiles: strings(q, 2), froms: integers(q, 3)};})};
      })};
  }
  return result;
}

function emptyState() {
  return {phase: 'waiting', selfSeat: null, hand: [], handComplete: false, historyComplete: false,
    baseline: null, lastStep: null, lastDraw: null, lastAction: null, left: null, doras: [], scores: [],
    rivers: [[], [], [], []], melds: [[], [], [], []], north: [0, 0, 0, 0],
    riichi: [null, null, null, null], riichiPending: [false, false, false, false],
    doubleRiichi: [null, null, null, null], doubleRiichiPending: [false, false, false, false],
    riichiStep: [null, null, null, null], riichiSticks: null, furiten: null,
    canAct: false, canDiscard: false, noCallsYet: false, canDoubleRiichi: false,
    operations: [], operationDetails: [], forbiddenDiscards: [],
    playerCount: 4, warning: '尚未取得开局或恢复基线', round: null};
}
const tileFamily = t => t?.replace(/^0/, '5');
function setOperations(state, e) {
  state.operations = [...(e.operations || [])];
  state.operationDetails = (e.operationDetails || []).map(op => ({...op, combination: [...op.combination]}));
  // The offered tile belongs to this exact action, never a previous river entry.
  state.lastAction = e.name && state.phase === 'playing' && !e.unsupported ? {
    name: e.name, seat: e.seat ?? (e.name === 'ActionNewRound' ? e.ju ?? null : null),
    tile: e.tile ?? (e.name === 'ActionBaBei' ? '4z' : e.name === 'ActionNewRound' ? state.lastDraw : null),
    type: e.type ?? null, step: e.step,
  } : null;
  // In type 1, combination lists forbidden kuikae discards, not legal candidates.
  // See majsoulrpa screens/match/operation/_decode.py at the revision above.
  state.forbiddenDiscards = state.operationDetails.filter(op => op.type === 1).flatMap(op => op.combination);
  state.canAct = state.phase === 'playing' && state.handComplete && state.historyComplete &&
    Number.isInteger(state.selfSeat) && state.selfSeat >= 0 && state.selfSeat < state.playerCount &&
    e.selfSeat === state.selfSeat && state.operations.some(type => Number.isInteger(type) && type >= 1 && type <= 11);
  state.canDiscard = state.canAct && state.operations.includes(1);
  state.canDoubleRiichi = state.canAct && state.noCallsYet && state.rivers[state.selfSeat].length === 0;
}
function apply(state, e) {
  if (e.name === 'ActionNewRound') {
    if (state.phase === 'playing' && state.baseline === 'new_round' &&
        state.lastStep !== null && e.step <= state.lastStep &&
        ['chang', 'ju', 'ben'].every(key => state.round?.[key] === e[key])) return false;
    const seat = e.selfSeat ?? (e.hand.length === 14 ? e.ju : state.selfSeat);
    Object.assign(state, emptyState(), {phase: 'playing', selfSeat: seat, hand: [...e.hand],
      handComplete: e.hand.length > 0, historyComplete: true, baseline: 'new_round',
      riichi: [false, false, false, false], doubleRiichi: [false, false, false, false],
      riichiSticks: e.riichiSticks ?? 0, furiten: false, noCallsYet: true,
      lastDraw: e.hand.length === 14 && seat === e.ju ? e.hand.at(-1) : null,
      warning: '', lastStep: e.step, left: e.left, doras: e.doras, scores: e.scores,
      playerCount: e.scores.length || 4, round: {chang: e.chang, ju: e.ju, ben: e.ben}});
    setOperations(state, e);
    return true;
  }
  if (state.lastStep !== null && e.step <= state.lastStep) return false;
  if (state.lastStep !== null && e.step !== state.lastStep + 1) {
    state.handComplete = state.historyComplete = false;
    state.warning = `动作缺口：${state.lastStep} → ${e.step}，等待新基线`;
  }
  state.lastStep = e.step;
  state.phase = 'playing';
  const localSeat = e.name === 'ActionDealTile' && e.tile ? e.seat : e.selfSeat;
  if (localSeat !== undefined) {
    if (state.selfSeat !== null && state.selfSeat !== localSeat) invalidate('本人座位与基线不一致，等待新基线');
    else state.selfSeat = localSeat;
  }
  if (e.doras?.length) state.doras = e.doras;
  if (e.scores?.length) state.scores = e.scores;
  if (e.furiten !== undefined) state.furiten = e.furiten;
  if (e.liqiSuccess) {
    const confirmation = e.liqiSuccess, seat = confirmation.seat;
    if (!Number.isInteger(seat) || seat < 0 || seat >= state.playerCount) throw new Error('立直座位编号无效');
    if (!confirmation.failed) {
      if (confirmation.riichiSticks !== undefined) state.riichiSticks = confirmation.riichiSticks;
      else if (state.riichi[seat] !== true && state.riichiSticks !== null) state.riichiSticks++;
      state.scores[seat] = confirmation.score;
      state.riichiStep[seat] ??= e.step;
      if (state.riichiPending[seat]) state.doubleRiichi[seat] = state.doubleRiichiPending[seat];
    } else {state.riichiStep[seat] = null; state.doubleRiichi[seat] = false;}
    state.riichi[seat] = !confirmation.failed;
    state.riichiPending[seat] = false;
    state.doubleRiichiPending[seat] = false;
  }
  function invalidate(reason) {
    state.handComplete = state.historyComplete = false;
    state.warning = reason;
  }
  function remove(tile, family = false) {
    if (!state.handComplete) return;
    const index = state.hand.findIndex(t => family ? tileFamily(t) === tileFamily(tile) : t === tile);
    if (index < 0) invalidate('手牌更新与基线不一致，等待新基线');
    else state.hand.splice(index, 1);
  }
  if (e.seat !== undefined && (!Number.isInteger(e.seat) || e.seat < 0 || e.seat > 3)) throw new Error('座位编号无效');
  if (e.unsupported) { invalidate(`未支持动作 ${e.name}，完整性待核对`); setOperations(state, {}); return true; }
  if (e.name === 'ActionDealTile') {
    state.left = e.left;
    if (e.tile) {
      state.lastDraw = e.tile;
      if (state.handComplete) state.hand.push(e.tile);
    }
  } else if (e.name === 'ActionDiscardTile') {
    state.rivers[e.seat].push({tile: e.tile, moqie: e.moqie, riichi: e.riichi, called: false, step: e.step});
    if (e.riichi) {
      state.riichiPending[e.seat] = true;
      state.doubleRiichiPending[e.seat] = Boolean(e.doubleRiichi);
      state.riichiStep[e.seat] = e.step;
    }
    if (e.seat === state.selfSeat) { remove(e.tile); state.lastDraw = null; }
  } else if (e.name === 'ActionChiPengGang') {
    state.noCallsYet = false;
    state.melds[e.seat].push({type: e.type, tiles: e.tiles, froms: e.froms});
    e.tiles.forEach((tile, index) => {
      const from = e.froms[index];
      if (from === e.seat && e.seat === state.selfSeat) remove(tile);
      else if (from !== undefined && from !== e.seat) {
        const river = state.rivers[from];
        const discard = river?.at(-1);
        if (discard?.tile === tile) discard.called = true;
      }
    });
    if (e.seat === state.selfSeat) state.lastDraw = null;
  } else if (e.name === 'ActionAnGangAddGang') {
    state.noCallsYet = false;
    if (e.type === 2) {
      const meld = state.melds[e.seat].find(m => m.type === 1 && tileFamily(m.tiles[0]) === tileFamily(e.tile));
      if (meld) {meld.type = 2; meld.tiles.push(e.tile);}
      else invalidate('加杠缺少此前碰牌记录');
      if (e.seat === state.selfSeat) remove(e.tile);
    } else if (e.type === 3) {
      const family = tileFamily(e.tile), ownKnown = e.seat === state.selfSeat && state.handComplete;
      // Normal ranked play has one red five per suit; the action only names a family.
      const redAssumed = !ownKnown && /^5[mps]$/.test(family);
      const tiles = ownKnown ? state.hand.filter(tile => tileFamily(tile) === family) :
        redAssumed ? [`0${family[1]}`, family, family, family] : [family, family, family, family];
      state.melds[e.seat].push({type: 3, tiles, froms: [], redAssumed});
      if (e.seat === state.selfSeat) for (let i = 0; i < 4; i++) remove(e.tile, true);
    } else invalidate(`未知杠类型 ${e.type}`);
    if (e.seat === state.selfSeat) state.lastDraw = null;
  } else if (e.name === 'ActionBaBei') {
    state.noCallsYet = false;
    state.north[e.seat]++; state.playerCount = 3;
    if (e.seat === state.selfSeat) { remove('4z'); state.lastDraw = null; }
  } else if (['ActionHule', 'ActionNoTile', 'ActionLiuJu'].includes(e.name)) {
    state.phase = e.matchEnd ? 'ended' : 'between_rounds';
    state.riichiPending.forEach((pending, seat) => {if (pending && !state.riichi[seat]) state.riichiStep[seat] = null;});
    state.riichiPending.fill(false);
    state.doubleRiichiPending.fill(false);
  }
  setOperations(state, e);
  return true;
}

function applyRestore(state, result) {
  if (result.ended) {state.phase = 'ended'; setOperations(state, {}); return;}
  const start = result.actions.findLastIndex(e => e.name === 'ActionNewRound');
  if (start >= 0) {
    Object.assign(state, emptyState());
    for (const e of result.actions.slice(start)) apply(state, e);
    // The server's step convention needs a real restore capture before asserting completeness.
    state.baseline = 'restore_actions';
    state.warning = '已回放恢复动作；恢复响应边界待现场核对';
    state.historyComplete = false;
    setOperations(state, {});
  } else if (result.snapshot) {
    const s = result.snapshot;
    Object.assign(state, emptyState(), {phase: 'playing', selfSeat: s.selfSeat,
      hand: s.hand, handComplete: false, baseline: 'snapshot_unverified', left: s.left,
      doras: s.doras, scores: s.players.map(p => p.score), playerCount: s.players.length || 4,
      round: {chang: s.chang, ju: s.ju, ben: s.ben}, lastStep: result.step,
      warning: '已收到恢复快照；与补发动作的边界待核对，手牌仅作快照展示'});
    s.players.slice(0, 4).forEach((p, i) => {
      state.rivers[i] = p.discards.map(tile => ({tile, called: false, snapshot: true}));
      state.melds[i] = p.melds;
    });
  } else {
    state.phase = 'connected';
    state.handComplete = state.historyComplete = false;
    setOperations(state, {});
    state.warning = '恢复响应没有可独立使用的开局或快照';
  }
}

module.exports = {fields, envelope, action, restore, emptyState, apply, applyRestore};
