// Included by build.cjs with core and the Inspector's queryInstances helper.
if (window.__mjMonitor) return {installed:false, reason:'already running', status:window.__mjMonitor.getSnapshot()};
if (location.hostname !== 'game.maj-soul.com') return {installed:false, reason:'not game page'};
const nativeBridge = window.webkit?.messageHandlers?.mjStatistics;
const relayOrigin = 'http://127.0.0.1:17361';
const NativeSocket = window.WebSocket, sockets = new Map(), state = core.emptyState();
const session = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
const queue = [];
let running = true, sequence = 0, serial = 0, activeSocket = null;
let relayWindow = null, relayReady = false, inFlight = null;
let received = 0, errors = 0, turns = 0, connectedAt = 0;
let scanTimer, flushTimer, heartbeatTimer, wrappedConstructor;
const gamePath = url => /^\/game-gateway(?:[-/]|$)/.test(new URL(url).pathname);
function snapshot() {
  return JSON.parse(JSON.stringify({running, received, errors, turns, pending:queue.length,
    connectedAt, relayReady, relayOpen:Boolean(relayWindow && !relayWindow.closed),
    gameSockets:[...sockets.values()].filter(m => m.socket.readyState === 1).length, state}));
}
let connectButton = null;
if (!nativeBridge) {
  connectButton = document.createElement('button');
  connectButton.textContent = '连接终端统计';
  connectButton.style.cssText = 'position:fixed;top:12px;left:12px;z-index:2147483647;padding:10px 14px;font:14px system-ui;cursor:pointer';
  connectButton.onclick = openRelay;
  document.body.appendChild(connectButton);
}
function openRelay() {
  relayReady = false; inFlight = null;
  relayWindow = window.open(`${relayOrigin}/relay#${session}`, 'mj-local-relay');
  if (!relayWindow) console.warn('[雀魂监听] 请点击页面的连接按钮打开本地中转窗口');
}
function onRelayMessage(event) {
  if (event.origin !== relayOrigin || event.source !== relayWindow || event.data?.channel !== session) return;
  if (event.data.type === 'mj-relay-ready') {
    relayReady = true; connectButton.hidden = true; flush();
  } else if (event.data.type === 'mj-relay-ack' && inFlight?.batchId === event.data.batchId) {
    const lastSerial = inFlight.events.at(-1).serial;
    while (queue.length && queue[0].serial <= lastSerial) queue.shift();
    connectedAt = Date.now(); inFlight = null; flush();
  }
}
if (!nativeBridge) window.addEventListener('message', onRelayMessage);
function flush() {
  if (!running || !queue.length) return;
  if (!relayWindow || relayWindow.closed) {
    relayReady = false; connectButton.hidden = false; return;
  }
  if (!relayReady) return;
  if (inFlight && Date.now() - inFlight.sentAt < 2000) return;
  if (!inFlight) {
    const batch = queue.slice(0, 20);
    inFlight = {batchId:`${session}:${batch[0].serial}-${batch.at(-1).serial}`, events:batch};
  }
  inFlight.sentAt = Date.now();
  relayWindow.postMessage({type:'mj-relay-batch', channel:session,
    batchId:inFlight.batchId, events:inFlight.events}, relayOrigin);
}
function publish(event) {
  const packet = {session, serial:++serial, time:new Date().toISOString(), ...event};
  if (nativeBridge) {
    nativeBridge.postMessage(JSON.stringify(packet));
    connectedAt = Date.now();
    return;
  }
  queue.push(packet);
  if (queue.length > 200) {
    // Never silently pretend that an output lost while the terminal was offline was delivered.
    queue.shift(); errors++; state.warning = '终端离线队列已满，较早输出被丢弃';
  }
  void flush();
}
function status(message) {publish({kind:'status', message, phase:state.phase});}
function fail(error) {
  errors++; state.handComplete = state.historyComplete = false;
  state.warning = `解析失败：${error.message}，当前数据可能不完整`;
  publish({kind:'error', message:state.warning});
}
function updateStatistics(event) {
  turns++;
  publish({kind:'turn', trigger:event.name, actorSeat:event.seat, step:event.step, turnNumber:turns,
    statistics:{received, errors}, state:JSON.parse(JSON.stringify(state))});
}
function resetStatistics() {
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
function scan() {
  if (!running || !discover) return;
  try {for (const socket of discover(NativeSocket)) attach(socket);} catch (error) {fail(error);}
}
function stop() {
  running = false; clearInterval(scanTimer); clearInterval(flushTimer); clearInterval(heartbeatTimer);
  for (const meta of sockets.values()) detach(meta);
  if (window.WebSocket === wrappedConstructor) window.WebSocket = NativeSocket;
  if (!nativeBridge) window.removeEventListener('message', onRelayMessage);
  connectButton?.remove();
  state.phase = 'stopped'; console.log('[雀魂监听] 页面监听已停止');
}
wrappedConstructor = new Proxy(NativeSocket, {construct(target, args, newTarget) {
  const socket = Reflect.construct(target, args, newTarget);
  try {attach(socket);} catch (error) {fail(error);}
  return socket;
}});
window.WebSocket = wrappedConstructor;
window.__mjMonitor = {version:'3.0.0', getSnapshot:snapshot, stop, openRelay,
  uninstall:() => {stop(); delete window.__mjMonitor;}};
scan();
if (discover) scanTimer = setInterval(scan, 5000);
if (!nativeBridge) flushTimer = setInterval(flush, 2000);
heartbeatTimer = setInterval(() => {
  if (!queue.length) publish({kind:'heartbeat', phase:state.phase, received, turns});
}, 10000);
status('页面采集器已启动；发牌后及每个桌面动作后更新统计');
return {installed:true, foundGameSockets:sockets.size, canDiscoverExisting:Boolean(discover),
  transport:nativeBridge ? 'webkit-native-message' : 'window-message-relay'};
