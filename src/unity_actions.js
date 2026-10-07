// Unity uses Liqi over its existing game-gateway, not the legacy Laya objects.
// Field numbers: official /1/v0.11.243.w/res/proto/liqi.json, checked 2026-10-06.
// Current Unity ron uses inputOperation (Naki 4e927649, LiqiRequestBuilder.swift).
(() => {
  'use strict';
  if (location.hostname !== 'game.maj-soul.com' || window.__mjUnityActions) return;
  const types = {discard:1, chi:2, pon:3, ankan:4, daiminkan:5, shouminkan:6,
    riichi:7, tsumo:8, ron:9, abort:10, kita:11};
  let pending = null, submitted = null, submittedStable = null;
  const now = () => performance.now();
  const check = (ok, message) => {if (!ok) throw new Error(message);};
  const reconnectError = message => Object.assign(new Error(message), {recoverable:true});
  const validTile = tile => typeof tile === 'string' && /^(?:[0-9][mps]|[1-7]z)$/.test(tile);
  const family = tile => tile.replace(/^0/, '5');
  // The dealer's 14th dealt tile is lastDraw for hand analysis, not a wire draw.
  const isDrawn = (state, tile) => state.lastAction?.name !== 'ActionNewRound' && tile === state.lastDraw;
  const sameTiles = (a, b) => Array.isArray(a) && Array.isArray(b) &&
    JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());
  const fingerprint = state => JSON.stringify(['phase','gameId','selfSeat','playerCount','round','match',
    'lastStep','lastAction','lastDraw','hand','handComplete','historyComplete','canAct','canDiscard',
    'operations','operationDetails','operationTiming','forbiddenDiscards','riichi','riichiPending',
    'melds','rivers','north'].map(key => state[key]));
  // Recovery replaces timers and the connection, but does not create a new turn.
  const validSubmission = key => Array.isArray(key) && key.length === 8 &&
    Number.isInteger(key[0]) && key[0] > 0 && key[0] <= 0xffffffff &&
    typeof key[1] === 'string' && key[1].length > 0 && key[1].length <= 256 &&
    [3,4].includes(key[3]) && key.slice(2).every(Number.isInteger) &&
    key[2] >= 0 && key[2] < key[3] && key[4] >= 0 && key[5] >= 0 && key[5] < key[3] && key[6] >= 0 && key[7] >= 0;
  function stableSubmission(state) {
    const live = window.__mjUnityTransport?.snapshot?.() || {};
    const key = [live.gameAccountId, live.gameIdentity, state?.selfSeat, state?.playerCount,
      state?.round?.chang, state?.round?.ju, state?.round?.ben, state?.lastStep];
    return validSubmission(key) ? key : null;
  }
  const localSubmission = state => [state.gameId ?? null, state.selfSeat, state.playerCount,
    state.round?.chang, state.round?.ju, state.round?.ben, state.lastStep];
  const submissionKey = state => JSON.stringify(stableSubmission(state) || localSubmission(state));
  const liveState = () => window.__mjMonitor?.getSnapshot()?.state;
  function offered(state) {
    const list = state.operationDetails;
    check(Array.isArray(list) && list.length > 0, '缺少服务端合法操作');
    const seen = new Set();
    for (const op of list) {
      check(Number.isInteger(op.type) && op.type >= 1 && op.type <= 11 && !seen.has(op.type), '服务端操作类型不受支持');
      check(Array.isArray(op.combination) && op.combination.every(c => typeof c === 'string'), '服务端操作组合不完整');
      seen.add(op.type);
    }
    check(sameTiles([...seen], state.operations), '合法操作列表不一致');
    check(state.canDiscard === seen.has(1), '弃牌许可与操作列表不一致');
    check(!seen.has(1) || ![2,3,5,9].some(type => seen.has(type)), '自己的操作与他家响应窗口冲突');
    return list;
  }
  function snapshot(expected) {
    const transport = window.__mjUnityTransport, state = liveState();
    const available = !!(transport && typeof transport.request === 'function' &&
      typeof window.__mjProtocol?.encode === 'function' && state);
    const inGame = state?.phase === 'playing';
    let remainingMs = null, reason = '', blocked = false, recoverable = false;
    try {
      check(available, 'Unity 操作接口尚未就绪');
      recoverable = true;
      check(transport.snapshot().gameConnected, '牌局连接尚未认证或已断开');
      check(state.recovery?.status !== 'waiting', '等待服务器恢复完整牌局状态');
      check(!pending, '等待上次操作的回应和权威动作');
      check(!submittedStable || stableSubmission(state), '等待恢复后的稳定牌局身份');
      check(submitted !== JSON.stringify(submittedStable ? stableSubmission(state) : localSubmission(state)),
        '本次操作已经提交，等待权威状态推进，不能重复发送');
      recoverable = false;
      check(inGame, '等待正在进行的对局');
      blocked = true;
      check(state.match?.category === 2 && state.match.playerCount === state.playerCount &&
        [3,4].includes(state.playerCount), '自动操作仅支持已确认的普通段位场');
      check(state.handComplete && state.historyComplete && state.canAct, '牌局基线或操作窗口已失效');
      check(Number.isInteger(state.selfSeat) && state.selfSeat >= 0 && state.selfSeat < state.playerCount &&
        Number.isInteger(state.lastStep) && state.round, '缺少本人座位或当前局信息');
      check(Array.isArray(state.hand) && state.hand.every(validTile), '当前手牌编码不完整');
      offered(state);
      const timing = state.operationTiming;
      check(timing && [timing.timeFixed,timing.timeAdd].every(t => Number.isInteger(t) && t >= 0 && t <= 0xffffffff) &&
        Number.isFinite(timing.receivedAt) && timing.receivedAt >= 0 && timing.receivedAt <= now(), '缺少服务端操作倒计时');
      // OptionalOperationList stores milliseconds; room-rule timer settings use seconds.
      remainingMs = Math.max(0, timing.timeFixed + timing.timeAdd - (now() - timing.receivedAt));
      check(remainingMs > 0, '本次操作已经超时');
      check(!expected || fingerprint(expected) === fingerprint(state), '建议所依据的牌局状态已过期');
      blocked = false;
    } catch (error) {reason = error.message;}
    return {available, inGame, canAct:!reason, blocked, recoverable, pending:!!pending,
      remainingMs, clientStep:state?.lastStep ?? null, reason};
  }
  function execute(advice, expected) {
    check(expected && typeof expected === 'object', '缺少建议所依据的牌局状态');
    const current = snapshot(expected);
    if (!current.canAct) throw Object.assign(new Error(current.reason), {recoverable:current.recoverable});
    const state = liveState(), list = offered(state);
    check(advice?.status === 'ready' || advice?.status === 'win', '当前建议不可执行');
    const choice = advice.status === 'win' ? {action:advice.action} : advice.best;
    check(choice && (Object.hasOwn(types, choice.action) || choice.action === 'pass'), '建议动作不受支持');
    check(advice.status !== 'win' || ['tsumo','ron'].includes(choice.action), '和牌建议格式无效');
    const action = choice.action, type = types[action], detail = list.find(op => op.type === type);
    check(action === 'pass' || detail, '服务端未许可建议动作');
    const reaction = list.some(op => [2,3,5,9].includes(op.type));
    const locked = state.riichi?.[state.selfSeat] || state.riichiPending?.[state.selfSeat];
    const entries = [], payload = {};
    const put = (name, field, value) => {payload[name] = value; if (value !== 0 && value !== false) entries.push([field, typeof value === 'boolean' ? Number(value) : value]);};
    const callChannel = ['chi','pon','daiminkan'].includes(action) || action === 'pass' && reaction;
    const method = `.lq.FastTest.${callChannel ? 'inputChiPengGang' : 'inputOperation'}`;
    function owns(tiles) {
      check(Array.isArray(tiles) && tiles.every(validTile), '建议消耗牌格式无效');
      const hand = [...state.hand];
      for (const tile of tiles) {
        const index = hand.indexOf(tile);
        check(index >= 0, '建议消耗了不存在的手牌'); hand.splice(index, 1);
      }
    }
    function combination(tiles) {
      const matches = detail.combination.map((c, index) => sameTiles(c.split('|'), tiles) ? index : -1).filter(i => i >= 0);
      check(matches.length === 1, '建议与服务端组合不能唯一匹配');
      put('index', 2, matches[0]);
    }
    if (action === 'pass') {
      check(!state.canDiscard, '不能用跳过代替弃牌');
      put('cancel_operation', callChannel ? 3 : 4, true);
    } else {
      put('type', 1, type);
      if (action === 'discard' || action === 'riichi') {
        check(!reaction && state.canDiscard, '当前不是可弃牌窗口');
        check(validTile(choice.tile) && state.hand.includes(choice.tile), '建议弃牌不在手中');
        check(!(state.forbiddenDiscards || []).some(tile => family(tile) === family(choice.tile)), '建议弃牌违反食替限制');
        check(!locked || choice.tile === state.lastDraw, '立直后只能摸切本次摸牌');
        if (action === 'riichi') {
          check(!locked && detail.combination.some(tile => validTile(tile) &&
            family(tile) === family(choice.tile)), '建议立直弃牌未经服务端许可');
        }
        put('tile', 3, choice.tile); put('moqie', 5, isDrawn(state, choice.tile));
      } else if (['chi','pon','daiminkan'].includes(action)) {
        const last = state.lastAction, river = state.rivers?.[choice.fromSeat]?.at(-1);
        check(!locked && reaction && last?.name === 'ActionDiscardTile' && last.step === state.lastStep &&
          last.seat === choice.fromSeat && last.tile === choice.calledTile && last.seat !== state.selfSeat &&
          river?.tile === last.tile && river.step === last.step && !river.called, '鸣牌目标已失效');
        owns(choice.consumed);
        check(choice.consumed.length === (action === 'daiminkan' ? 3 : 2), '鸣牌消耗张数不完整');
        const tiles = [...choice.consumed, choice.calledTile].map(family).sort();
        if (action === 'chi') {
          check(state.playerCount === 4 && choice.fromSeat === (state.selfSeat + 3) % 4 &&
            tiles.every(tile => /^[1-9][mps]$/.test(tile) && tile[1] === tiles[0][1]) &&
            Number(tiles[1][0]) === Number(tiles[0][0]) + 1 && Number(tiles[2][0]) === Number(tiles[0][0]) + 2, '吃牌来源或顺子不合法');
        } else check(new Set(tiles).size === 1, '碰杠牌种不一致');
        combination(choice.consumed);
      } else if (action === 'ankan' || action === 'shouminkan') {
        check(!reaction, '当前不是自己的杠牌窗口');
        owns(choice.consumed);
        let tiles = choice.consumed;
        if (action === 'shouminkan') {
          const meld = state.melds?.[state.selfSeat]?.[choice.meldIndex];
          check(!locked && tiles.length === 1 && meld?.type === 1 && meld.tiles?.length === 3, '加杠缺少对应碰牌');
          tiles = [...meld.tiles, ...tiles];
        }
        check(tiles.length === 4 && tiles.every(validTile) && new Set(tiles.map(family)).size === 1, '杠牌组合不完整');
        combination(tiles);
      } else if (action === 'kita') {
        check(!reaction && state.playerCount === 3 && state.hand.includes('4z'), '拔北需要三麻及手中北牌');
        check(!locked || state.lastDraw === '4z', '立直后只能拔本次摸到的北');
        put('moqie', 5, isDrawn(state, '4z'));
      } else if (action === 'abort') {
        const terminals = new Set(state.hand.map(family).filter(tile => /^[19][mps]$|^[1-7]z$/.test(tile)));
        check(!reaction && !locked && terminals.size >= 9, '九种九牌的手牌条件不成立');
      } else if (action === 'ron') {
        check(reaction && ['ActionDiscardTile','ActionAnGangAddGang','ActionBaBei'].includes(state.lastAction?.name) &&
          state.lastAction.seat !== state.selfSeat && state.lastAction.step === state.lastStep, '荣和目标已失效');
      } else check(!reaction, '当前不是自摸窗口');
    }
    put('timeuse', 6, Math.floor((now() - state.operationTiming.receivedAt) / 1000));
    const bytes = window.__mjProtocol.encode(entries), key = submissionKey(state);
    check(snapshot(expected).canAct, '提交前牌局状态发生变化');
    submitted = key; submittedStable = stableSubmission(state);
    return new Promise((resolve, reject) => {
      const request = pending = {state, choice:JSON.parse(JSON.stringify(choice)), action, method,
        moqie:payload.moqie, ack:false, echo:false, finish};
      const timer = setTimeout(() => finish(reconnectError('操作回应或权威动作确认超时；等待权威状态推进，暂不重复操作')),
        Math.min(60000, Math.max(10000, current.remainingMs + 5000)));
      function finish(error) {
        if (pending !== request) return;
        if (!error && (!request.ack || !request.echo)) return;
        pending = null; clearTimeout(timer);
        if (error) reject(error); else resolve({ok:true, action, method, ...payload});
      }
      try {
        window.__mjUnityTransport.request(method, bytes, {game:true}).then(response => {
          check(response?.payload instanceof Uint8Array, '操作响应格式无效');
          // Transport validates ResCommon.error and owns request IDs and response routing.
          request.ack = true; finish();
        }).catch(finish);
      } catch (error) {finish(error);}
    });
  }
  function onEvent(packet) {
    const ended = packet.phase === 'ended' || packet.state?.phase === 'ended';
    if (ended) submitted = submittedStable = null;
    const request = pending;
    if (!request) return;
    // A phase update can precede the final action; reset means no echo followed it.
    if (ended && packet.kind === 'status' && packet.reset && !request.echo) {
      request.finish(reconnectError('对局已结束，本次操作未获权威动作确认')); return;
    }
    if (packet.phase === 'disconnected' || packet.recovery?.status === 'waiting' ||
        packet.state?.recovery?.status === 'waiting') {
      request.finish(reconnectError('连接正在恢复，操作结果未确认，等待权威状态推进')); return;
    }
    if (packet.kind === 'error' || packet.phase === 'stopped') {
      request.finish(new Error('连接或牌局解析异常，操作结果未确认')); return;
    }
    if (packet.kind !== 'turn' || request.echo) return;
    const event = packet.action, state = request.state, choice = request.choice, action = request.action;
    if (event?.name === 'ActionNewRound' || packet.state &&
        (JSON.stringify(packet.state.round) !== JSON.stringify(state.round) || !packet.state.historyComplete)) {
      request.finish(new Error('牌局基线或局数已变化，操作结果未确认')); return;
    }
    if (!event || !Number.isInteger(event.step) || event.step <= state.lastStep) return;
    if (event.step !== state.lastStep + 1) {
      request.finish(new Error('权威动作不连续，操作结果未确认')); return;
    }
    const own = event.seat === state.selfSeat;
    let confirmed = false;
    if (action === 'pass') confirmed = !event.unsupported && ['ActionDealTile','ActionDiscardTile','ActionChiPengGang',
      'ActionAnGangAddGang','ActionBaBei','ActionHule','ActionNoTile','ActionLiuJu'].includes(event.name);
    else if (action === 'discard' || action === 'riichi') confirmed = own && event.name === 'ActionDiscardTile' &&
      event.tile === choice.tile && Boolean(event.riichi) === (action === 'riichi') && Boolean(event.moqie) === request.moqie;
    else if (['chi','pon','daiminkan'].includes(action)) confirmed = own && event.name === 'ActionChiPengGang' &&
      event.type === ({chi:0,pon:1,daiminkan:2}[action]) && sameTiles(event.tiles, [...choice.consumed,choice.calledTile]) &&
      Array.isArray(event.froms) && event.froms.length === event.tiles.length &&
      sameTiles(event.tiles.filter((tile, i) => event.froms[i] === state.selfSeat), choice.consumed) &&
      event.froms.filter(seat => seat === choice.fromSeat).length === 1;
    else if (action === 'ankan' || action === 'shouminkan') confirmed = own && event.name === 'ActionAnGangAddGang' &&
      event.type === (action === 'ankan' ? 3 : 2) && validTile(event.tile) &&
      (action === 'ankan' ? family(event.tile) === family(choice.consumed[0]) : event.tile === choice.consumed[0]);
    else if (action === 'kita') confirmed = own && event.name === 'ActionBaBei' && Boolean(event.moqie) === request.moqie;
    else if (action === 'abort') confirmed = own && event.name === 'ActionLiuJu' && event.type === 1;
    else confirmed = event.name === 'ActionHule' && event.hules?.some(h => h.seat === state.selfSeat && Boolean(h.zimo) === (action === 'tsumo'));
    if (!confirmed) request.finish(new Error('权威牌局动作已推进，但未确认本次建议操作；请核对牌局'));
    else {request.echo = true; request.finish();}
  }
  function checkpoint() {
    check(submitted === null || submittedStable, '旧操作缺少稳定牌局身份，无法安全自动恢复');
    return {submitted:submittedStable && [...submittedStable]};
  }
  function restoreCheckpoint(saved) {
    check(saved && (saved.submitted === null || validSubmission(saved.submitted)) && !pending && submitted === null,
      '自动恢复操作记录无效');
    submittedStable = saved.submitted && [...saved.submitted];
    submitted = submittedStable && JSON.stringify(submittedStable);
  }
  window.__mjUnityActions = {snapshot, execute, onEvent, checkpoint, restoreCheckpoint};
})();
