// Decoded official records -> the same seat-visible state used by the live client.
// Raw userInputs belong after this record and before the next record result.
const core = require('./core.cjs');

const STATE_FIELDS = ['phase', 'selfSeat', 'hand', 'handComplete', 'historyComplete',
  'baseline', 'lastStep', 'lastDraw', 'lastAction', 'left', 'doras', 'scores', 'rivers',
  'melds', 'north', 'riichi', 'riichiPending', 'doubleRiichi', 'doubleRiichiPending',
  'riichiStep', 'riichiSticks', 'furiten', 'canAct', 'canDiscard', 'noCallsYet',
  'canDoubleRiichi', 'operations', 'operationDetails', 'forbiddenDiscards',
  'playerCount', 'round', 'match', 'recovery'];
const clone = value => JSON.parse(JSON.stringify(value));
const family = tile => tile?.replace(/^0/, '5');
const recordName = record => record.name.replace(/^\.lq\./, '');
const responseNames = new Set(['ActionDiscardTile', 'ActionAnGangAddGang', 'ActionBaBei']);
const operationTypes = {discard:1, chi:2, pon:3, ankan:4, daiminkan:5,
  shouminkan:6, riichi:7, tsumo:8, ron:9, abort:10, kita:11};
const canPass = state => !state.canDiscard && state.operations.length > 0;

function visibleState(state) {
  const result = Object.fromEntries(STATE_FIELDS.map(key => [key, state[key]]));
  result.match = state.match ? {playerCount:state.match.playerCount, roundCount:state.match.roundCount} : null;
  return clone(result);
}

function projectRecord(record, seat, step) {
  const d = {seat:0, chang:0, ju:0, ben:0, liqibang:0, left_tile_count:0, type:0, ...record.data};
  const name = recordName(record).replace(/^Record/, 'Action');
  const e = {name, step};
  const choices = [...(Array.isArray(d.operations) ? d.operations : []),
    ...(d.operation ? [d.operation] : [])].filter(op => (op.seat ?? 0) === seat);
  if (choices.length > 1) throw new Error('Duplicate operation list for one seat');
  if (choices.length) {
    const op = choices[0];
    if (op.operation_list !== undefined && !Array.isArray(op.operation_list)) throw new Error('Malformed operation_list');
    e.selfSeat = seat;
    e.operationDetails = (op.operation_list || []).map(value => ({type:value.type,
      combination:[...(value.combination || [])]}));
    e.operations = e.operationDetails.map(value => value.type);
  }
  if (Array.isArray(d.zhenting) && typeof d.zhenting[seat] === 'boolean') e.furiten = d.zhenting[seat];
  if (Array.isArray(d.doras)) e.doras = [...d.doras];
  if (['ActionDealTile', 'ActionChiPengGang', 'ActionLiuJu'].includes(name) && d.liqi) {
    e.liqiSuccess = {seat:d.liqi.seat ?? 0, score:d.liqi.score ?? 0, failed:Boolean(d.liqi.failed)};
    if (d.liqi.liqibang !== undefined) e.liqiSuccess.riichiSticks = d.liqi.liqibang;
  }
  if (name === 'ActionNewRound') {
    Object.assign(e, {selfSeat:seat, hand:[...(d[`tiles${seat}`] || [])], scores:[...d.scores],
      chang:d.chang, ju:d.ju, ben:d.ben, left:d.left_tile_count, riichiSticks:d.liqibang,
      doras:d.doras?.length ? [...d.doras] : d.dora ? [d.dora] : []});
  } else if (name === 'ActionDealTile') {
    Object.assign(e, {seat:d.seat, tile:d.seat === seat ? d.tile : null, left:d.left_tile_count});
  } else if (name === 'ActionDiscardTile') {
    Object.assign(e, {seat:d.seat, tile:d.tile, moqie:Boolean(d.moqie),
      riichi:Boolean(d.is_liqi || d.is_wliqi), doubleRiichi:Boolean(d.is_wliqi)});
  } else if (name === 'ActionChiPengGang') {
    Object.assign(e, {seat:d.seat, type:d.type, tiles:[...d.tiles], froms:[...d.froms]});
  } else if (name === 'ActionAnGangAddGang') {
    Object.assign(e, {seat:d.seat, type:d.type, tile:d.tiles});
  } else if (name === 'ActionBaBei') {
    Object.assign(e, {seat:d.seat, moqie:Boolean(d.moqie)});
  } else if (name === 'ActionHule') {
    Object.assign(e, {matchEnd:Boolean(d.gameend), scores:[...(d.scores || [])],
      hules:(d.hules || []).map(h => ({seat:h.seat ?? 0, zimo:Boolean(h.zimo)}))});
  } else if (name === 'ActionNoTile') e.matchEnd = Boolean(d.gameend);
  else if (name === 'ActionLiuJu') Object.assign(e, {matchEnd:Boolean(d.gameend), seat:d.seat, type:d.type});
  else e.unsupported = true;
  return e;
}

function callAction(state, action, consumed) {
  const last = state.lastAction;
  return {action, tile:last.tile, calledTile:last.tile, fromSeat:last.seat, consumed};
}

function kanAction(state, type, tile) {
  if (type === 3) return {action:'ankan', tile:family(tile),
    consumed:state.hand.filter(value => family(value) === family(tile))};
  if (type === 2) return {action:'shouminkan', tile, consumed:[tile],
    meldIndex:state.melds[state.selfSeat].findIndex(m => m.type === 1 && family(m.tiles[0]) === family(tile))};
  return null;
}

function acceptedAction(window, record) {
  const d = {seat:0, type:0, ...record.data}, state = window.state, seat = state.selfSeat;
  switch (recordName(record)) {
  case 'RecordDiscardTile':
    if (d.seat === seat && canPass(state) && state.lastAction.name === 'ActionDealTile' &&
        d.moqie && d.tile === state.lastDraw) return {action:'pass', consumed:[]};
    return d.seat === seat ? {action:d.is_liqi || d.is_wliqi ? 'riichi' : 'discard',
      tile:d.tile, moqie:Boolean(d.moqie), consumed:[]} : null;
  case 'RecordChiPengGang': {
    if (d.seat !== seat || ![0, 1, 2].includes(d.type)) return null;
    const consumed = d.tiles.filter((_, index) => d.froms[index] === seat);
    return callAction(state, ['chi', 'pon', 'daiminkan'][d.type], consumed);
  }
  case 'RecordAnGangAddGang': return d.seat === seat ? kanAction(state, d.type, d.tiles) : null;
  case 'RecordBaBei': return d.seat === seat ? {action:'kita', tile:'4z', consumed:['4z'], moqie:Boolean(d.moqie)} : null;
  case 'RecordHule': {
    const hule = d.hules?.find(h => (h.seat ?? 0) === seat);
    return !hule ? null : hule.zimo ? {action:'tsumo', consumed:[]} : callAction(state, 'ron', []);
  }
  case 'RecordLiuJu': return d.type === 1 && d.seat === seat ? {action:'abort', consumed:[]} : null;
  default: return null;
  }
}

function explicitAction(state, input) {
  const request = input.operation || input.cpg;
  if (!request) return null;
  if (request.cancel_operation) return canPass(state) ? {action:'pass', consumed:[]} : null;
  const action = Object.keys(operationTypes).find(key => operationTypes[key] === request.type);
  if (!action) return null;
  if (['discard', 'riichi'].includes(action)) return {action, tile:request.tile,
    moqie:state.lastAction.name !== 'ActionNewRound' && Boolean(request.moqie), consumed:[]};
  if (action === 'kita') return {action, tile:'4z', consumed:['4z'], moqie:Boolean(request.moqie)};
  if (['tsumo', 'abort'].includes(action)) return {action, consumed:[]};
  if (action === 'ron') return callAction(state, action, []);
  const detail = state.operationDetails.find(op => op.type === request.type);
  const combination = detail?.combination[request.index ?? 0];
  if (typeof combination !== 'string') return null;
  const tiles = combination.split('|');
  if (['chi', 'pon', 'daiminkan'].includes(action)) return callAction(state, action, tiles);
  if (action === 'ankan') return kanAction(state, 3, tiles[0]);
  if (action === 'shouminkan') {
    const matches = state.melds[state.selfSeat].flatMap((meld, meldIndex) => {
      if (meld.type !== 1) return [];
      const remaining = [...tiles];
      for (const tile of meld.tiles) {
        const index = remaining.indexOf(tile);
        if (index < 0) return [];
        remaining.splice(index, 1);
      }
      return remaining.length === 1 ? [{action, tile:remaining[0], consumed:remaining, meldIndex}] : [];
    });
    return matches.length === 1 ? matches[0] : null;
  }
  return null;
}

function actionKey(action) {
  return JSON.stringify([action.action, action.tile ?? null, action.moqie ?? null,
    action.fromSeat ?? null, [...(action.consumed || [])].sort(), action.meldIndex ?? null]);
}

function validateAction(state, action) {
  if (action.action === 'pass') return canPass(state);
  if (!state.operations.includes(operationTypes[action.action])) return false;
  if (['discard', 'riichi'].includes(action.action)) {
    if (!state.hand.includes(action.tile)) return false;
    if (action.moqie && (state.lastAction.name === 'ActionNewRound' || state.lastDraw !== action.tile)) return false;
    if (!action.moqie && state.lastAction.name !== 'ActionNewRound' && state.lastDraw === action.tile &&
        state.hand.filter(t => t === action.tile).length < 2) return false;
    if (state.forbiddenDiscards.some(t => family(t) === family(action.tile))) return false;
  }
  const hand = [...state.hand];
  for (const tile of action.consumed || []) {
    const index = hand.indexOf(tile);
    if (index < 0) return false;
    hand.splice(index, 1);
  }
  if (action.action === 'ankan' && action.consumed.length !== 4) return false;
  if (action.action === 'shouminkan' && action.meldIndex < 0) return false;
  if (['chi', 'pon', 'daiminkan'].includes(action.action)) {
    const combination = [...action.consumed].sort().join('|');
    if (!state.operationDetails.find(op => op.type === operationTypes[action.action])?.combination
      .some(value => value.split('|').sort().join('|') === combination)) return false;
  }
  return true;
}

function extractGame(game) {
  if (!game || typeof game.gameId !== 'string' || !Array.isArray(game.records)) throw new Error('Expected gameId and decoded records');
  const mode = game.head?.config?.mode?.mode;
  const modeId = game.head?.config?.meta?.mode_id;
  const ranked = game.head?.config?.category === 2 && core.rankedModes[modeId]?.[0] === mode;
  const synthetic = !game.head && game.ruleset === 'majsoul-standard-v1' && game.source?.kind === 'hand-authored';
  if (!ranked && !synthetic) throw new Error('Unverified ruleset: require a standard ranked record head');
  const samples = [], audit = {gameId:game.gameId, records:game.records.length, rounds:0,
    windows:0, emitted:0, labels:{accepted:0, explicit:0, inferred_pass:0}, excluded:{}};
  const exclude = reason => {audit.excluded[reason] = (audit.excluded[reason] || 0) + 1;};
  let states = [], discardFuriten = [], pending = new Map(), roundId = null, step = 0;
  function emit(window, action, labelSource) {
    if (!validateAction(window.state, action)) {exclude('invalid_label'); return;}
    samples.push({schemaVersion:1, ruleset:'majsoul-standard-v1', gameId:game.gameId,
      roundId:window.roundId, decisionId:window.id,
      seat:window.state.selfSeat, state:window.state, action, labelSource});
    audit.labels[labelSource]++; audit.emitted++;
  }
  function resolve(record) {
    for (const window of pending.values()) {
      const accepted = acceptedAction(window, record), explicit = window.explicit;
      const last = window.state.lastAction;
      const expectedDraw = last.name === 'ActionDiscardTile' ? (last.seat + 1) % window.state.playerCount : last.seat;
      if (window.conflict || accepted && explicit && actionKey(accepted) !== actionKey(explicit) ||
          recordName(record) === 'RecordDealTile' && explicit && explicit.action !== 'pass') exclude('conflicting_input');
      else if (accepted) emit(window, accepted, explicit ? 'explicit' : accepted.action === 'pass' ? 'inferred_pass' : 'accepted');
      else if (explicit) emit(window, explicit, 'explicit');
      else if (recordName(record) === 'RecordDealTile' && (record.data.seat ?? 0) === expectedDraw && responseNames.has(last.name)) {
        emit(window, {action:'pass', consumed:[]}, 'inferred_pass');
      } else exclude(responseNames.has(window.state.lastAction.name) ? 'censored_response' : 'unresolved_self_action');
    }
    pending.clear();
  }
  for (const record of game.records) {
    if (!record?.data || typeof record.name !== 'string') throw new Error('Malformed decoded record');
    const name = recordName(record), d = {seat:0, ju:0, chang:0, ben:0, type:0, ...record.data};
    if (name === 'RecordNewRound') {
      for (const window of pending.values()) exclude('unfinished_window');
      pending.clear();
      const count = d.scores?.length;
      if (![3, 4].includes(count) || !Number.isInteger(d.ju) || d.ju < 0 || d.ju >= count ||
          (mode !== undefined && (mode > 10 ? 3 : 4) !== count)) throw new Error('Inconsistent active player count');
      for (let seat = 0; seat < count; seat++) {
        if (d[`tiles${seat}`]?.length !== (seat === d.ju ? 14 : 13)) throw new Error('Incomplete starting hands');
      }
      if (count === 3 && d.tiles3?.length) throw new Error('Nonempty absent seat in sanma');
      states = Array.from({length:count}, () => core.emptyState());
      discardFuriten = Array(count).fill(false);
      if (ranked) for (const state of states) core.setMatch(state, {playerCount:count, roundCount:mode % 10});
      roundId = `${audit.rounds}:${d.chang}:${d.ju}:${d.ben}`;
      audit.rounds++; step = 0;
    } else {
      if (!states.length) throw new Error('Record before initial round');
      resolve(record);
    }
    for (let seat = 0; seat < states.length; seat++) {
      const state = states[seat], event = projectRecord(record, seat, step);
      const furitenBefore = state.furiten;
      core.apply(state, event);
      if (name === 'RecordDiscardTile' && d.seat === seat) {
        // These waits are also in the live actor's ActionDiscardTile, not an
        // opponent hand or a future result. An omitted repeated field is empty.
        const ownRiver = new Set(state.rivers[seat].map(discard => family(discard.tile)));
        discardFuriten[seat] = (d.tingpais || []).some(wait => ownRiver.has(family(wait.tile)));
      } else if (d.seat === seat && (['RecordAnGangAddGang', 'RecordBaBei'].includes(name) ||
          name === 'RecordChiPengGang' && d.type === 2)) {
        // These hand-changing actions carry no own tingpais. A replacement
        // draw cannot distinguish an old temporary flag from changed waits.
        discardFuriten[seat] = null;
      }
      if (state.canAct) {
        const snapshot = visibleState(state);
        // RecordDiscardTile eagerly sets missed-win zhenting while still
        // offering ron (even a no-yaku shape wait can set it). The response
        // decision uses the previous flag; the stored flag applies afterwards.
        if (responseNames.has(event.name) && event.seat !== seat) snapshot.furiten = furitenBefore;
        // RecordDealTile can retain temporary zhenting until the next discard.
        // The draw clears that component, not discard or permanent riichi
        // furiten. Keep the prior discard's waits until a new discard changes it.
        else if (event.name === 'ActionDealTile' && event.seat === seat) {
          snapshot.furiten = state.riichi[seat] || state.riichiPending[seat] ? state.furiten :
            state.furiten === false ? false : discardFuriten[seat];
        }
        const window = {state:snapshot, roundId, id:`${game.gameId}:${roundId}:${step}:${seat}`};
        pending.set(seat, window); audit.windows++;
      } else if (event.operations?.length) exclude('incomplete_state');
    }
    // Count missing actor operation windows separately from ordinary non-decisions.
    if (['RecordNewRound', 'RecordDealTile', 'RecordChiPengGang'].includes(name)) {
      const actor = name === 'RecordNewRound' ? d.ju : d.seat;
      if (!pending.has(actor) && !(name === 'RecordChiPengGang' && d.type === 2)) exclude('missing_actor_operations');
    }
    for (const input of record.userInputs || []) {
      if (!input.operation && !input.cpg) continue;
      const window = pending.get(input.seat ?? 0);
      if (!window) {exclude('input_without_window'); continue;}
      const action = explicitAction(window.state, input);
      if (!action || !validateAction(window.state, action)) {exclude('unusable_input'); continue;}
      if (window.explicit && actionKey(window.explicit) !== actionKey(action)) window.conflict = true;
      else window.explicit = action;
    }
    step++;
  }
  // A truncated suffix is not evidence that the last offered decisions were made.
  for (const window of pending.values()) exclude('unfinished_window');
  return {samples, audit};
}

module.exports = {extractGame, projectRecord, visibleState};
