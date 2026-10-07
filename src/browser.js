// Installed before page scripts by the native WKWebView host, with core in scope.
if (window.__mjMonitor) return {installed:false, reason:'already running', status:window.__mjMonitor.getSnapshot()};
if (location.hostname !== 'game.maj-soul.com') return {installed:false, reason:'not game page'};
const nativeBridge = window.webkit?.messageHandlers?.mjStatistics;
if (!nativeBridge) return {installed:false, reason:'native bridge unavailable'};
const NativeSocket = window.WebSocket, sockets = new Map(), state = core.emptyState();
const session = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
// Keep reconnect identity stable without publishing the private game UUID.
const gameIds = new Map();
let running = true, sequence = 0, serial = 0, activeSocket = null;
let received = 0, errors = 0, turns = 0, connectedAt = 0;
let heartbeatTimer, wrappedConstructor;
let adviceRequest = null;
const gamePath = url => /^\/game-gateway(?:[-/]|$)/.test(new URL(url).pathname);
function snapshot() {
  return JSON.parse(JSON.stringify({running, received, errors, turns, connectedAt,
    gameSockets:[...sockets.values()].filter(m => m.socket.readyState === 1).length, state}));
}
function publish(event) {
  const packet = {session, serial:++serial, time:new Date().toISOString(), ...event};
  if (packet.kind === 'turn') {
    adviceRequest = {key:`${session}:${packet.serial}`, publishedAt:performance.now(),
      receivedAt:packet.state.operationTiming?.receivedAt};
    window.__mjStatsOverlay?.expectAdvice?.(adviceRequest.key);
  } else if (packet.kind === 'status' || packet.kind === 'error') adviceRequest = null;
  window.__mjUnityActions?.onEvent(packet);
  window.__mjUnityLobby?.onEvent?.(packet);
  window.__mjAutoplay?.onEvent(packet);
  nativeBridge.postMessage(JSON.stringify(packet));
  connectedAt = Date.now();
}
function status(message) {publish({kind:'status', message, phase:state.phase, recovery:state.recovery});}
function closeDecisionWindow() {
  window.__mjStatsOverlay?.invalidateAdvice();
  if (adviceRequest) {
    const key = adviceRequest.key;
    adviceRequest = null;
    publish({kind:'advice_invalidated', adviceKey:key});
  }
  state.canAct = state.canDiscard = state.canDoubleRiichi = false; state.lastAction = null;
  state.operations = []; state.operationDetails = []; state.forbiddenDiscards = [];
  state.operationTiming = null;
}
function fail(error) {
  closeDecisionWindow();
  core.setMatch(state, null);
  for (const meta of sockets.values()) meta.pending.clear();
  errors++; state.handComplete = state.historyComplete = false;
  state.warning = `解析失败：${error.message}，当前数据可能不完整`;
  state.recovery = {status:'failed', reason:state.warning};
  publish({kind:'error', message:state.warning, recovery:state.recovery});
}
function updateStatistics(event) {
  window.__mjStatsOverlay?.invalidateAdvice();
  turns++;
  publish({kind:'turn', trigger:event.name, actorSeat:event.seat, step:event.step, turnNumber:turns,
    action:event, statistics:{received, errors}, state:JSON.parse(JSON.stringify(state))});
}
function resetStatistics(phase = 'ended') {
  window.__mjStatsOverlay?.invalidateAdvice();
  const alreadyReset = state.phase === phase && state.lastStep === null && turns === 0;
  Object.assign(state, core.emptyState(), {phase, warning:''});
  for (const meta of sockets.values()) meta.pending.clear();
  received = errors = turns = 0;
  if (!alreadyReset) publish({kind:'status', phase, reset:true, recovery:null,
    message:phase === 'ended' ? '对局已结束，统计已重置，等待下一场' : '已确认没有进行中的对局，恢复状态已清除，等待大厅就绪'});
}
function resetForConnection(meta) {
  if (activeSocket === meta.id) return;
  const recovery = state.recovery || (state.baseline || state.phase === 'disconnected' ?
    {status:'waiting', reason:'authentication'} : null);
  closeDecisionWindow();
  for (const previous of sockets.values()) if (previous !== meta) previous.pending.clear();
  activeSocket = meta.id;
  Object.assign(state, core.emptyState(), {phase:'connected', recovery});
}
function receivedFrame(meta, bytes, receivedAt) {
  if (activeSocket !== null && meta.id < activeSocket) return;
  received++;
  const env = core.envelope(bytes);
  if (!env) return;
  if (env.kind === 1 && env.name === '.lq.ActionPrototype') {
    resetForConnection(meta);
    const event = core.action(env.data), previousPhase = state.phase;
    const recovery = state.recovery;
    if (event.operationTiming) event.operationTiming.receivedAt = receivedAt;
    if (state.phase === 'ended' && state.lastStep === null &&
        ['ActionHule','ActionNoTile','ActionLiuJu'].includes(event.name)) {received = 0; return;}
    if (!core.apply(state, event)) return;
    // A queued live packet must not bypass a restore/authentication still in flight.
    if (recovery?.status === 'waiting' && meta.pending.size &&
        state.recovery?.status !== 'failed' && state.phase !== 'ended') {
      state.recovery = recovery;
      closeDecisionWindow();
    }
    if (state.phase !== previousPhase) status('牌局状态更新');
    updateStatistics(event);
    if (state.phase === 'ended') resetStatistics();
  } else if (env.kind === 1 && env.name === '.lq.NotifyGameEndResult') {
    if (activeSocket === meta.id || activeSocket === null) resetStatistics();
  } else if (env.kind === 3 && meta.pending.has(env.id)) {
    const request = meta.pending.get(env.id); meta.pending.delete(env.id);
    resetForConnection(meta);
    if (request.method === '.lq.FastTest.authGame') {
      const result = core.authGame(env.data, request.accountId);
      core.setMatch(state, result.match);
      if (result.match) {
        state.selfSeat = result.selfSeat;
        state.playerCount = result.match.playerCount;
        state.gameId = request.gameId;
      }
      status(result.match ? '已从游戏认证信息读取段位与排位模式' : '排位信息未确认，使用通用策略');
      return;
    }
    const result = core.restore(env.data);
    if (result.ended) {resetStatistics(); return;}
    core.applyRestore(state, result);
    status(`已解析 ${request.method} 恢复响应；${state.warning || '牌局状态已更新'}`);
    // A recovery response is one current snapshot, not a series of live actions.
    const last = result.actions.at(-1);
    updateStatistics({name:last?.name || 'GameRestore', seat:last?.seat, step:state.lastStep ?? result.step});
    if (state.phase === 'ended') resetStatistics();
  }
}
function attach(socket) {
  if (!running || sockets.has(socket) || !gamePath(socket.url) || socket.readyState > 1) return;
  const meta = {socket, id:++sequence, pending:new Map(), queue:Promise.resolve()};
  sockets.set(socket, meta);
  meta.message = event => {
    const receivedAt = performance.now();
    meta.queue = meta.queue.then(async () => {
      if (!running || !sockets.has(socket)) return;
      const data = event.data;
      const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) :
        data instanceof Blob ? new Uint8Array(await data.arrayBuffer()) :
        ArrayBuffer.isView(data) ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength) : null;
      if (running && sockets.has(socket) && bytes) receivedFrame(meta, bytes, receivedAt);
    }).catch(error => {
      if (running && sockets.has(socket) && (activeSocket === null || meta.id >= activeSocket)) fail(error);
    });
  };
  meta.open = () => {
    if (activeSocket !== null && meta.id < activeSocket) return;
    resetForConnection(meta);
    if (['waiting','disconnected','ended'].includes(state.phase)) state.phase = 'connected';
    status('发现牌局连接，等待真实动作确认对局');
  };
  meta.close = () => {
    if ((activeSocket === meta.id || activeSocket === null) && state.phase !== 'ended') {
      closeDecisionWindow();
      core.setMatch(state, null);
      state.phase = 'disconnected';
      state.handComplete = state.historyComplete = false;
      state.warning = '牌局连接关闭，等待自动重新连接';
      if (state.recovery?.status !== 'failed') state.recovery = {status:'waiting', reason:'connection'};
      status(state.warning);
    }
    detach(meta); sockets.delete(socket);
  };
  socket.addEventListener('message', meta.message);
  socket.addEventListener('open', meta.open);
  socket.addEventListener('close', meta.close);
  meta.originalSend = socket.send;
  meta.ownSendDescriptor = Object.getOwnPropertyDescriptor(socket, 'send');
  meta.send = function(data) {
    if (activeSocket !== null && meta.id < activeSocket) return Reflect.apply(meta.originalSend, this, arguments);
    try {
      const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) :
        ArrayBuffer.isView(data) ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength) : null;
      const env = bytes ? core.envelope(bytes) : null;
      if (env?.kind === 2) meta.pending.delete(env.id);
      if (env?.kind === 2 && ['.lq.FastTest.inputOperation','.lq.FastTest.inputChiPengGang'].includes(env.name)) {
        window.__mjAutoplay?.onInput();
        closeDecisionWindow();
      }
      if (env?.kind === 2 && (activeSocket === null || meta.id >= activeSocket) &&
          ['.lq.FastTest.authGame','.lq.FastTest.syncGame','.lq.FastTest.enterGame'].includes(env.name)) {
        const recovering = Boolean(state.recovery || state.baseline || state.phase === 'disconnected' ||
          env.name === '.lq.FastTest.syncGame' && state.phase !== 'ended');
        closeDecisionWindow();
        if (env.name === '.lq.FastTest.authGame') {
          resetForConnection(meta);
          Object.assign(state, core.emptyState(), {phase:'connected'});
          meta.pending.clear();
        }
        if (recovering) {
          state.recovery = {status:'waiting', reason:env.name === '.lq.FastTest.authGame' ? 'authentication' : 'restore'};
          status('正在恢复牌局连接，等待可信实时操作');
        }
        let gameId = null;
        if (env.name === '.lq.FastTest.authGame') {
          const uuid = core.fields(env.data).get(3)?.[0];
          if (uuid instanceof Uint8Array && uuid.length) {
            const key = new TextDecoder().decode(uuid);
            if (!gameIds.has(key)) gameIds.set(key, `game-${gameIds.size + 1}`);
            gameId = gameIds.get(key);
          }
        }
        meta.pending.set(env.id, {method:env.name,
          accountId:env.name === '.lq.FastTest.authGame' ? core.authAccount(env.data) : null, gameId});
        if (meta.pending.size > 256) meta.pending.delete(meta.pending.keys().next().value);
      }
    } catch (error) {fail(error);}
    return Reflect.apply(meta.originalSend, this, arguments);
  };
  socket.send = meta.send;
  if (socket.readyState === 1) meta.open();
}
function detach(meta) {
  meta.pending.clear();
  meta.socket.removeEventListener('message', meta.message);
  meta.socket.removeEventListener('open', meta.open);
  meta.socket.removeEventListener('close', meta.close);
  if (meta.socket.send === meta.send) {
    if (meta.ownSendDescriptor) Object.defineProperty(meta.socket, 'send', meta.ownSendDescriptor);
    else delete meta.socket.send;
  }
}
function stop() {
  window.__mjAutoplay?.stop();
  running = false; clearInterval(heartbeatTimer);
  closeDecisionWindow();
  core.setMatch(state, null);
  for (const meta of sockets.values()) detach(meta);
  if (window.WebSocket === wrappedConstructor) window.WebSocket = NativeSocket;
  window.__mjUnityTransport?.stop();
  state.phase = 'stopped'; state.recovery = null; console.log('[雀魂监听] 页面监听已停止');
}
wrappedConstructor = new Proxy(NativeSocket, {construct(target, args, newTarget) {
  const socket = Reflect.construct(target, args, newTarget);
  try {attach(socket);} catch (error) {fail(error);}
  return socket;
}});
window.WebSocket = wrappedConstructor;
window.__mjMonitor = {version:'3.0.0', session, getSnapshot:snapshot, stop,
  onAdvice:packet => {
    if (!running) return;
    const now = performance.now();
    const current = packet.adviceKey === adviceRequest?.key;
    const elapsed = current ? now - adviceRequest.publishedAt : null;
    const receivedAt = current ? adviceRequest.receivedAt : null;
    // Both durations stay in the browser's clock domain; native queue/CPU
    // timings are separate records joined by the immutable advice key.
    publish({kind:'advisor_delivery', adviceKey:packet.adviceKey, current,
      ...(current ? {publishToAdviceMs:Math.max(0,elapsed)} : {}),
      ...(Number.isFinite(receivedAt) && receivedAt >= 0 && receivedAt <= now ?
        {operationToAdviceMs:now - receivedAt} : {})});
  },
  onLobbyRecovery:() => {if (running && state.recovery?.status === 'waiting') resetStatistics('waiting');},
  reportRecoveryDiagnostic:value => {if (running) publish({kind:'recovery_diagnostic', ...value});},
  reportAutomationIntent:value => {if (running) publish({kind:'automation_intent', ...value});},
  reportAutomation:value => Promise.resolve().then(() => {if (running) publish({kind:'automation', ...value});}),
  uninstall:() => {stop(); delete window.__mjMonitor;}};
heartbeatTimer = setInterval(() => {
  publish({kind:'heartbeat', phase:state.phase, received, turns});
}, 10000);
status('页面采集器已启动；发牌后及每个桌面动作后更新统计');
return {installed:true, foundGameSockets:sockets.size, transport:'webkit-native-message'};
