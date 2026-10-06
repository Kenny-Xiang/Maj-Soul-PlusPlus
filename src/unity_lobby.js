// Unity uses Liqi on the client's authenticated sockets, not Laya UI globals.
// Schema: /1/v0.11.243.w/res/proto/liqi.json. Candidate ranked East rooms below
// were decoded from /1/v0.11.252.w/res/config/lqc.lqbin on 2026-10-06,
// SHA256 a5959513fa31d3b5297d2dda400c86c0eacbdb4adad461b583439d7f673c9086.
// The server remains authoritative for availability. Unity rematch/automatic
// settlement evidence: Sunalamye/Naki @ 4e927649, AUDIT.md:180 and AutoRematchEngine.
(() => {
  if (location.hostname !== 'game.maj-soul.com' || window.__mjUnityLobby) return;
  const rooms = [
    [1, '铜之间', 2, 17, 10101, 10203, 0],
    [2, '银之间', 5, 19, 10201, 10303, 2500],
    [3, '金之间', 8, 21, 10301, 10403, 5000],
    [4, '玉之间', 11, 23, 10401, 10503, 10000],
    [6, '王座间', 15, 25, 10501, 10720, 10000],
  ];
  const versions = new Map();
  let transport, identity = '', lastAccountId = null, generation = 0, account = null, refreshNeeded = true;
  let busy = null, owned = null, externalQueue = null, playing = false, enteringAt = null;
  let endedAt = null, roundKey = null, lastRound = null, roundEpoch = 0, roundLocation = null;
  let confirmingAt = null, problem = '', cancelError = '';
  const clock = () => performance.now();
  const result = (phase, message, extra = {}) => ({phase, message, ...extra});
  const protocol = () => window.__mjProtocol;
  const validId = id => Number.isInteger(id) && id > 0 && id <= 0xffffffff;

  function sync() {
    if (transport !== window.__mjUnityTransport) {
      transport = window.__mjUnityTransport;
      transport?.onMessage?.(onMessage);
    }
    const live = transport?.snapshot?.() || {};
    const next = `${live.accountId || 0}:${live.lobbySessionId || 0}:${!!live.connected}`;
    if (next !== identity) {
      const changedAccount = validId(live.accountId) && lastAccountId !== null && lastAccountId !== live.accountId;
      if (validId(live.accountId)) lastAccountId = live.accountId;
      identity = next; generation++; account = null; refreshNeeded = true; busy = null;
      // Keep cancellation ownership through a reconnect of the same account.
      if (changedAccount) {
        owned = externalQueue = null; playing = false;
        enteringAt = endedAt = roundKey = confirmingAt = lastRound = roundLocation = null;
      }
      problem = ''; cancelError = '';
    }
    return live;
  }

  function readAccount(bytes) {
    const {fields, first} = protocol(), f = fields(bytes);
    return {id:first(f, 1), roomId:first(f, 5), gold:first(f, 11), frozen:first(f, 29),
      level:f.has(21) ? first(fields(first(f, 21)), 1) : null,
      level3:f.has(22) ? first(fields(first(f, 22)), 1) : null};
  }
  function responseFields(payload) {
    const {fields, first} = protocol(), f = fields(payload);
    const error = f.has(1) ? first(fields(first(f, 1)), 1) : 0;
    if (error) throw new Error(`服务器拒绝操作（${error}）`);
    return f;
  }
  function newRound(event) {
    const location = [transport?.snapshot().gameSessionId, event.chang, event.ju, event.ben].join(':');
    if (![event.chang, event.ju, event.ben].every(Number.isInteger) || location !== roundLocation) {
      roundLocation = location; roundEpoch++; lastRound = null;
    }
    roundKey = null; confirmingAt = null;
  }
  function endGame() {
    if (endedAt === null) endedAt = clock();
    playing = false; enteringAt = null; roundKey = null; confirmingAt = null;
    owned = externalQueue = null; refreshNeeded = true; generation++;
  }
  function onEvent(packet) {
    const event = packet.action;
    if (packet.kind === 'turn') {
      if (packet.state?.phase === 'ended' || event?.matchEnd) {endGame(); return;}
      if (['playing', 'between_rounds'].includes(packet.state?.phase)) {
        playing = true; enteringAt = endedAt = null; owned = externalQueue = null;
        if (['ActionHule', 'ActionNoTile', 'ActionLiuJu'].includes(event?.name)) {
          const key = `round:${identity}:${transport?.snapshot().gameSessionId}:${roundEpoch}:${event.name}:${event.step}`;
          if (lastRound !== key) {lastRound = key; roundKey = key;}
        } else {
          roundKey = null;
          if (event?.name === 'ActionNewRound') newRound(event);
        }
      }
    } else if (packet.kind === 'status' && packet.phase === 'ended') endGame();
  }

  function onMessage(message) {
    try {
      const live = sync(), {fields, first, str} = protocol();
      const {method, payload, direction, kind, game, sessionId, injected} = message;
      if (direction === 'out' && kind === 'request' && !game) {
        const field = {'.lq.Lobby.login':11, '.lq.Lobby.oauth2Login':10,
          '.lq.Lobby.emailLogin':6, '.lq.Lobby.fastLogin':1, '.lq.Lobby.startUnifiedMatch':2}[method];
        if (field) {
          const version = str(fields(payload), field);
          if (version) versions.set(sessionId, version);
        }
      }
      if (game) {
        if (sessionId !== live.gameSessionId) return;
        if (direction === 'in' && method === '.lq.ActionPrototype') {
          // Establish the round key before Unity consumes the notification. Its own
          // immediate confirm may precede the collector's asynchronous onEvent.
          const name = str(fields(payload), 2);
          if (['ActionHule', 'ActionNoTile', 'ActionLiuJu'].includes(name)) {
            const action = protocol().action(payload);
            onEvent({kind:'turn', action, state:{phase:action.matchEnd ? 'ended' : 'between_rounds'}});
          } else if (name === 'ActionNewRound') newRound(protocol().action(payload));
        }
        if (direction === 'out' && method === '.lq.FastTest.confirmNewRound') {
          roundKey = null; confirmingAt ??= clock();
        }
        if (direction === 'in' && kind === 'response' && method === '.lq.FastTest.confirmNewRound')
          responseFields(payload);
        if (direction === 'in' && kind === 'response' && method === '.lq.FastTest.authGame') {
          responseFields(payload); playing = true; enteringAt = endedAt = roundKey = confirmingAt = null;
          owned = externalQueue = null; refreshNeeded = true;
        }
        if (direction === 'in' && method === '.lq.NotifyGameEndResult') endGame();
        if (direction === 'in' && method === '.lq.NotifyGameTerminate') problem = '对局被终止，请检查游戏提示';
        return;
      }
      if (sessionId !== live.lobbySessionId) return;
      if (direction === 'out' && !injected && method === '.lq.Lobby.startUnifiedMatch') {
        externalQueue = str(fields(payload), 1) || 'unknown';
      }
      if (direction !== 'in') return;
      if (kind === 'response' && ['.lq.Lobby.login', '.lq.Lobby.oauth2Login', '.lq.Lobby.emailLogin', '.lq.Lobby.fastLogin'].includes(method)) {
        const f = responseFields(payload), fast = method === '.lq.Lobby.fastLogin';
        const gameInfo = fast ? 2 : 4;
        if (f.has(gameInfo) && str(fields(first(f, gameInfo)), 3)) enteringAt = clock();
        if (!fast && f.has(3)) account = readAccount(first(f, 3));
        if (fast && f.has(3)) problem = '请先退出当前房间并返回大厅';
      } else if (kind === 'response' && method === '.lq.Lobby.fetchAccountInfo' && !injected) {
        // Explicit account_id requests are profile lookups, not a full wallet
        // refresh. Even our own public profile must not overwrite private gold.
        if (!message.requestPayload || first(fields(message.requestPayload), 1) !== 0) return;
        const f = responseFields(payload);
        if (f.has(2)) {
          const next = readAccount(first(f, 2));
          if (next.id === live.accountId) {account = next; generation++;}
        }
      } else if (method === '.lq.NotifyMatchGameStart' || method === '.lq.NotifyRoomGameStart') {
        const modeId = first(fields(payload), 4);
        if (method === '.lq.NotifyMatchGameStart' && owned && modeId !== owned.modeId)
          problem = '实际匹配模式与预期不符，已停止自动操作';
        enteringAt = clock(); owned = externalQueue = null; refreshNeeded = true; generation++;
      } else if (method === '.lq.NotifyAccountUpdate' || method === '.lq.NotifyAccountLevelChange') {
        refreshNeeded = true; generation++;
      } else if (['.lq.NotifyMatchTimeout', '.lq.NotifyMatchFailed'].includes(method)) {
        const sid = str(fields(payload), 1);
        if (owned?.sid !== sid && externalQueue !== sid) return;
        if (owned?.sid === sid) owned = null;
        if (externalQueue === sid) externalQueue = null;
        problem = '匹配失败或超时，请重新开启自动打牌';
      } else if (['.lq.NotifyAccountLogout', '.lq.NotifyAnotherLogin'].includes(method)) {
        generation++; account = null; owned = externalQueue = null; busy = null;
        problem = '账号已退出或在其他设备登录';
      } else if (kind === 'response' && !injected && method === '.lq.Lobby.cancelUnifiedMatch') {
        responseFields(payload);
        const sid = message.requestPayload && str(fields(message.requestPayload), 1);
        if (externalQueue === sid) externalQueue = null;
        if (owned?.sid === sid) {owned = null; generation++;}
      } else if (kind === 'response' && !injected && method === '.lq.Lobby.startUnifiedMatch') {
        try {responseFields(payload);} catch (error) {externalQueue = null; problem = error.message;}
      }
      if (owned?.cancelRequested && live.connected && !owned.submitting && !owned.cancelling) cancel();
    } catch (error) {problem = `大厅协议解析失败：${error.message}`;}
  }

  function snapshot(playerCount = 4) {
    const live = sync();
    if (!transport?.isUnity?.() || !protocol()) return result('loading', '等待 Unity 游戏客户端加载', {clientLoading:true});
    if (!live.connected) return result('login', '等待大厅连接，请先在游戏窗口登录');
    if (!validId(live.accountId)) return result('login', '请先在游戏窗口登录');
    if (problem) return result('blocked', problem);
    if (enteringAt !== null) {
      if (clock() - enteringAt > 30000) return result('blocked', '匹配已成功，但客户端未能进入对局，请检查游戏界面');
      return result('matching', '匹配成功，等待客户端进入对局');
    }
    if (confirmingAt !== null && clock() - confirmingAt > 30000)
      return result('blocked', '已确认下一小局，但未收到开局通知，请检查游戏界面');
    if (roundKey) return result('settlement', '准备进入下一小局', {actionKey:roundKey, action:'confirm'});
    if (playing) return result('playing', '对局进行中');
    if (owned || externalQueue) {
      if (owned && clock() - owned.at > 180000) return result('blocked', '匹配等待超过 3 分钟，正在取消本次队列');
      return result('matching', owned?.submitting ? '正在提交匹配' : '正在匹配', {modeId:owned?.modeId});
    }
    if (endedAt !== null && clock() - endedAt < 45000)
      return result('settlement', '等待结算动画完成并返回大厅');
    if (busy) return result('loading', '正在刷新段位与金币');
    if (refreshNeeded || !account)
      return result('lobby', '准备刷新段位与金币', {action:'refresh', actionKey:`refresh:${identity}:${generation}`});
    if (account.roomId) return result('blocked', '请先退出当前房间并返回大厅');
    if (account.frozen) return result('blocked', '账号当前无法匹配，请检查游戏提示');
    const rank = playerCount === 3 ? account.level3 : account.level;
    const offset = playerCount === 3 ? 10000 : 0;
    const mode = playerCount === 3 ? '三麻' : '四麻';
    if (!Number.isInteger(rank) || rank === 0)
      return result('blocked', `未取得${mode}段位，请重新登录后开启`);
    const rankedRooms = [3, 4].includes(playerCount) ?
      rooms.filter(row => rank >= row[4] + offset && rank <= row[5] + offset) : [];
    if (!rankedRooms.length)
      return result('blocked', `无法识别${mode}段位（${rank}），请重新登录后开启`);
    if (!Number.isInteger(account.gold)) return result('blocked', '未取得金币信息，请重新登录后开启');
    const room = rankedRooms.filter(row => account.gold >= row[6]).at(-1);
    if (!room) return result('blocked', `金币不足：当前 ${account.gold}，${mode}当前段位的东风场最低需要 ${rankedRooms[0][6]}`);
    const version = versions.get(live.lobbySessionId);
    if (!version) return result('blocked', '尚未取得当前客户端版本，请重新登录后开启');
    const modeId = room[playerCount === 3 ? 3 : 2];
    return result('lobby', `准备匹配${room[1]} · ${playerCount === 3 ? '三麻' : '四麻'}东风`, {
      action:'match', actionKey:`match:${identity}:${generation}:${playerCount}:${modeId}:${rank}:${account.gold}`,
      modeId, sid:`1:${modeId}`, version, roomName:room[1],
    });
  }

  async function start(playerCount, actionKey) {
    const state = snapshot(playerCount), binding = identity, version = generation;
    if (state.phase !== 'lobby' || !actionKey || state.actionKey !== actionKey)
      return {ok:false, reason:'大厅状态已经变化，取消本次操作'};
    const {encode, first} = protocol();
    if (state.action === 'refresh') {
      const request = busy = {}, accountId = transport.snapshot().accountId;
      try {
        // The official client's own-account refresh sends an empty request;
        // account_id selects a public profile that can omit the private wallet.
        const {payload} = await transport.request('.lq.Lobby.fetchAccountInfo', encode([]), {game:false});
        sync();
        if (binding !== identity || generation !== version || busy !== request)
          return {ok:false, reason:'账号或连接已变化，取消旧账号刷新'};
        const f = responseFields(payload);
        if (!f.has(2)) throw new Error('服务器没有返回账号信息');
        const next = readAccount(first(f, 2));
        if (next.id !== accountId) throw new Error('服务器返回了不同账号');
        if (f.has(3)) next.roomId ||= 1;
        account = next; refreshNeeded = false; generation++; endedAt = null;
        return {ok:true};
      } catch (error) {return {ok:false, reason:`账号刷新失败：${error.message}`};}
      finally {if (busy === request) busy = null;}
    }
    const queue = owned = {sid:state.sid, modeId:state.modeId, accountId:transport.snapshot().accountId,
      at:clock(), submitting:true, cancelling:false};
    try {
      const {payload} = await transport.request('.lq.Lobby.startUnifiedMatch',
        encode([[1, state.sid], [2, state.version]]), {game:false});
      responseFields(payload);
      sync();
      if (binding !== identity) return {ok:false, reason:'账号或连接已变化，请检查匹配状态'};
      return {ok:true, modeId:state.modeId};
    } catch (error) {
      // A server rejection is definite; timeout/disconnect still needs cancellation.
      if (Number.isInteger(error.code) && owned === queue) {owned = null; generation++;}
      return {ok:false, reason:`开始匹配失败：${error.message}`};
    } finally {
      queue.submitting = false;
      if (owned === queue && queue.cancelRequested) cancel();
    }
  }

  async function finish(actionKey) {
    const state = snapshot();
    if (state.phase !== 'settlement' || !actionKey || state.actionKey !== actionKey || state.action !== 'confirm')
      return {ok:false, reason:'结算状态已经变化，取消本次操作'};
    roundKey = null;
    try {
      const {payload} = await transport.request('.lq.FastTest.confirmNewRound', new Uint8Array(), {game:true});
      responseFields(payload); return {ok:true};
    } catch (error) {return {ok:false, reason:`进入下一小局失败：${error.message}`};}
  }

  function cancel() {
    const live = sync();
    if (busy) {busy = null; generation++;}
    if (cancelError) {const reason = cancelError; cancelError = ''; return {ok:false, reason};}
    if (!owned) {refreshNeeded = true; generation++; return {ok:true};}
    owned.cancelRequested = true;
    if (validId(live.accountId) && owned.accountId !== live.accountId) {owned = null; return {ok:true};}
    if (!live.connected || owned.submitting || owned.cancelling) return {ok:true, pending:true};
    const queue = owned; queue.cancelling = true;
    transport.request('.lq.Lobby.cancelUnifiedMatch', protocol().encode([[1, queue.sid]]), {game:false})
      .then(({payload}) => {responseFields(payload); sync(); if (owned === queue) {owned = null; generation++;}})
      .catch(error => {if (owned === queue) cancelError = error.message;})
      .finally(() => {queue.cancelling = false;});
    return {ok:true, pending:true};
  }

  window.__mjLobby = window.__mjUnityLobby = {snapshot, start, finish, cancel, onEvent};
  sync();
})();
