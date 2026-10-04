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
  received = errors = turns = 0;
  if (!alreadyReset) publish({kind:'status', phase:'ended', reset:true,
    message:'对局已结束，统计已重置，等待下一场'});
}
function resetForConnection(meta) {
  if (activeSocket === meta.id) return;
  activeSocket = meta.id;
  Object.assign(state, core.emptyState(), {phase:'connected'});
}
function receivedFrame(meta, bytes) {
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
    const method = meta.pending.get(env.id); meta.pending.delete(env.id);
    resetForConnection(meta);
    const result = core.restore(env.data);
    if (result.ended) {resetStatistics(); return;}
    core.applyRestore(state, result);
    status(`已解析 ${method} 恢复响应；恢复边界仍需核对`);
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
      if (!running) return;
      const data = event.data;
      const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) :
        data instanceof Blob ? new Uint8Array(await data.arrayBuffer()) :
        ArrayBuffer.isView(data) ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength) : null;
      if (bytes) receivedFrame(meta, bytes);
    }).catch(fail);
  };
  meta.open = () => {
    if (['waiting','disconnected','ended'].includes(state.phase)) state.phase = 'connected';
    status('发现牌局连接，等待真实动作确认对局');
  };
  meta.close = () => {
    if ((activeSocket === meta.id || activeSocket === null) && state.phase !== 'ended') {
      closeDecisionWindow();
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
    try {
      const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) :
        ArrayBuffer.isView(data) ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength) : null;
      const env = bytes ? core.envelope(bytes) : null;
      if (env?.kind === 2 && ['.lq.FastTest.inputOperation','.lq.FastTest.inputChiPengGang'].includes(env.name)) {
        closeDecisionWindow();
      }
      if (env?.kind === 2 && ['.lq.FastTest.syncGame','.lq.FastTest.enterGame'].includes(env.name)) {
        meta.pending.set(env.id, env.name);
        if (meta.pending.size > 256) meta.pending.delete(meta.pending.keys().next().value);
      }
    } catch (error) {fail(error);}
    return Reflect.apply(meta.originalSend, this, arguments);
  };
  socket.send = meta.send;
  if (socket.readyState === 1) meta.open();
}
function detach(meta) {
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
