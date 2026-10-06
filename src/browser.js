// Installed before page scripts by the native WKWebView host, with core in scope.
if (window.__mjMonitor) return {installed:false, reason:'already running', status:window.__mjMonitor.getSnapshot()};
if (location.hostname !== 'game.maj-soul.com') return {installed:false, reason:'not game page'};
const nativeBridge = window.webkit?.messageHandlers?.mjStatistics;
if (!nativeBridge) return {installed:false, reason:'native bridge unavailable'};
const NativeSocket = window.WebSocket, sockets = new Map(), state = core.emptyState();
const session = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
let running = true, sequence = 0, serial = 0, activeSocket = null;
let received = 0, errors = 0, turns = 0, connectedAt = 0;
let heartbeatTimer, wrappedConstructor;
const gamePath = url => /^\/game-gateway(?:[-/]|$)/.test(new URL(url).pathname);
function snapshot() {
  return JSON.parse(JSON.stringify({running, received, errors, turns, connectedAt,
    gameSockets:[...sockets.values()].filter(m => m.socket.readyState === 1).length, state}));
}
function publish(event) {
  const packet = {session, serial:++serial, time:new Date().toISOString(), ...event};
  if (packet.kind === 'turn') window.__mjStatsOverlay?.expectAdvice?.(`${session}:${packet.serial}`);
  nativeBridge.postMessage(JSON.stringify(packet));
  connectedAt = Date.now();
}
function status(message) {publish({kind:'status', message, phase:state.phase});}
function closeDecisionWindow() {
  window.__mjStatsOverlay?.invalidateAdvice();
  state.canAct = state.canDiscard = state.canDoubleRiichi = false; state.lastAction = null;
  state.operations = []; state.operationDetails = []; state.forbiddenDiscards = [];
}
function fail(error) {
  closeDecisionWindow();
  core.setMatch(state, null);
  for (const meta of sockets.values()) meta.pending.clear();
  errors++; state.handComplete = state.historyComplete = false;
  state.warning = `解析失败：${error.message}，当前数据可能不完整`;
  publish({kind:'error', message:state.warning});
}
function updateStatistics(event) {
  window.__mjStatsOverlay?.invalidateAdvice();
  turns++;
  publish({kind:'turn', trigger:event.name, actorSeat:event.seat, step:event.step, turnNumber:turns,
    statistics:{received, errors}, state:JSON.parse(JSON.stringify(state))});
}
function resetStatistics() {
  window.__mjStatsOverlay?.invalidateAdvice();
  const alreadyReset = state.phase === 'ended' && state.lastStep === null && turns === 0;
  Object.assign(state, core.emptyState(), {phase:'ended', warning:''});
  for (const meta of sockets.values()) meta.pending.clear();
  received = errors = turns = 0;
  if (!alreadyReset) publish({kind:'status', phase:'ended', reset:true,
    message:'对局已结束，统计已重置，等待下一场'});
}
function resetForConnection(meta) {
  if (activeSocket === meta.id) return;
  closeDecisionWindow();
  for (const previous of sockets.values()) if (previous !== meta) previous.pending.clear();
  activeSocket = meta.id;
  Object.assign(state, core.emptyState(), {phase:'connected'});
}
function receivedFrame(meta, bytes) {
  if (activeSocket !== null && meta.id < activeSocket) return;
  received++;
  const env = core.envelope(bytes);
  if (!env) return;
  if (env.kind === 1 && env.name === '.lq.ActionPrototype') {
    resetForConnection(meta);
    const event = core.action(env.data), previousPhase = state.phase;
    if (state.phase === 'ended' && state.lastStep === null &&
        ['ActionHule','ActionNoTile','ActionLiuJu'].includes(event.name)) {received = 0; return;}
    if (!core.apply(state, event)) return;
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
    meta.queue = meta.queue.then(async () => {
      if (!running || !sockets.has(socket)) return;
      const data = event.data;
      const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) :
        data instanceof Blob ? new Uint8Array(await data.arrayBuffer()) :
        ArrayBuffer.isView(data) ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength) : null;
      if (running && sockets.has(socket) && bytes) receivedFrame(meta, bytes);
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
        closeDecisionWindow();
      }
      if (env?.kind === 2 && (activeSocket === null || meta.id >= activeSocket) &&
          ['.lq.FastTest.authGame','.lq.FastTest.syncGame','.lq.FastTest.enterGame'].includes(env.name)) {
        if (env.name === '.lq.FastTest.authGame') {
          closeDecisionWindow();
          resetForConnection(meta);
          Object.assign(state, core.emptyState(), {phase:'connected'});
          meta.pending.clear();
        }
        meta.pending.set(env.id, {method:env.name,
          accountId:env.name === '.lq.FastTest.authGame' ? core.authAccount(env.data) : null});
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
  running = false; clearInterval(heartbeatTimer);
  closeDecisionWindow();
  core.setMatch(state, null);
  for (const meta of sockets.values()) detach(meta);
  if (window.WebSocket === wrappedConstructor) window.WebSocket = NativeSocket;
  state.phase = 'stopped'; console.log('[雀魂监听] 页面监听已停止');
}
wrappedConstructor = new Proxy(NativeSocket, {construct(target, args, newTarget) {
  const socket = Reflect.construct(target, args, newTarget);
  try {attach(socket);} catch (error) {fail(error);}
  return socket;
}});
window.WebSocket = wrappedConstructor;
window.__mjMonitor = {version:'3.0.0', getSnapshot:snapshot, stop,
  uninstall:() => {stop(); delete window.__mjMonitor;}};
heartbeatTimer = setInterval(() => {
  publish({kind:'heartbeat', phase:state.phase, received, turns});
}, 10000);
status('页面采集器已启动；发牌后及每个桌面动作后更新统计');
return {installed:true, foundGameSockets:sockets.size, transport:'webkit-native-message'};
