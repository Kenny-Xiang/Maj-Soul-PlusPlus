// Installed before the collector and Unity; core is supplied by the native host.
(() => {
  if (window.__mjUnityTransport || location.hostname !== 'game.maj-soul.com') return;
  const NativeSocket = window.WebSocket, listeners = new Set(), sockets = new Set();
  const delivered = new WeakSet(), encoder = new TextEncoder(), decoder = new TextDecoder();
  const selected = new Map();
  let sequence = 0, nextId = 60000, sending = null, lastAccountId = null, stopped = false;
  const loginMethods = ['.lq.Lobby.login', '.lq.Lobby.emailLogin', '.lq.Lobby.oauth2Login', '.lq.Lobby.fastLogin'];
  const first = (map, field, fallback = 0) => map.get(field)?.[0] ?? fallback;
  const str = (map, field) => map.has(field) ? decoder.decode(first(map, field)) : null;
  function encode(entries) {
    const output = [];
    const uint = value => {
      if (!Number.isSafeInteger(value) || value < 0) throw new Error('无效的协议整数');
      do {const byte = value % 128; value = Math.floor(value / 128); output.push(byte | (value ? 128 : 0));} while (value);
    };
    for (const [field, value] of entries) {
      if (!Number.isInteger(field) || field < 1) throw new Error('无效的协议字段');
      if (typeof value === 'number' || typeof value === 'boolean') {uint(field * 8); uint(Number(value));}
      else {
        const bytes = typeof value === 'string' ? encoder.encode(value) : value;
        if (!(bytes instanceof Uint8Array)) throw new Error('无效的协议数据');
        uint(field * 8 + 2); uint(bytes.length);
        for (const byte of bytes) output.push(byte);
      }
    }
    return new Uint8Array(output);
  }
  const bytesOf = data => data instanceof ArrayBuffer ? new Uint8Array(data) :
    ArrayBuffer.isView(data) ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength) : null;
  const errorCode = payload => {const f = core.fields(payload); return f.has(1) ? first(core.fields(first(f, 1)), 1) : 0;};
  const latest = game => selected.get(game) || [...sockets].filter(meta => meta.game === game).at(-1);
  const ready = meta => !!(meta?.authenticated && meta.socket.readyState === 1);
  const connectionError = message => Object.assign(new Error(message), {recoverable:true});
  function interrupt(meta, message) {
    for (const [id, request] of meta.pending) if (request.injected) {
      meta.pending.delete(id); meta.retired.add(id); clearTimeout(request.timer);
      request.reject(connectionError(message));
    }
  }
  function snapshot() {
    const lobby = latest(false), game = latest(true);
    return {connected:ready(lobby), gameConnected:ready(game),
      lobbySessionId:lobby?.id ?? null, gameSessionId:game?.id ?? null,
      accountId:ready(lobby) ? lobby.accountId : null};
  }
  function emit(meta, packet) {
    for (const listener of listeners) {
      try {listener({game:meta.game, sessionId:meta.id, ...packet});}
      catch (error) {console.error('[自动打牌消息处理]', error.message);}
    }
  }
  function allocate(meta) {
    for (let i = 0; i < 65536; i++) {
      const id = nextId; nextId = (nextId + 1) & 65535;
      if (!meta.pending.has(id) && !meta.retired.has(id)) return id;
    }
    throw new Error('连接请求编号已耗尽，请重新连接');
  }
  function identify(meta, request, payload) {
    if (errorCode(payload)) return;
    if (selected.get(meta.game)?.id > meta.id) return;
    if (loginMethods.includes(request.method)) {
      meta.authenticated = true;
      if (request.method !== '.lq.Lobby.fastLogin') lastAccountId = first(core.fields(payload), 2, null);
      meta.accountId = lastAccountId;
    } else if (request.method === '.lq.FastTest.authGame') {
      meta.accountId = core.authAccount(request.payload); meta.authenticated = !!meta.accountId;
      const lobby = selected.get(false);
      if (ready(lobby) && lobby.accountId !== meta.accountId) meta.authenticated = false;
    }
    if (meta.authenticated && (loginMethods.includes(request.method) || request.method === '.lq.FastTest.authGame')) {
      for (const other of sockets) if (other !== meta && (other.game === meta.game ||
          !meta.game && meta.accountId && other.accountId !== meta.accountId)) {
        other.authenticated = false;
        interrupt(other, '连接已更新，等待恢复后的牌局状态');
      }
      selected.set(meta.game, meta);
    }
  }
  function deliver(meta, original, data = original.data) {
    const event = new MessageEvent('message', {data, origin:original.origin, lastEventId:original.lastEventId});
    delivered.add(event); meta.socket.dispatchEvent(event);
  }
  function receive(meta, event, bytes) {
    let env;
    try {env = core.envelope(bytes);} catch (_) {deliver(meta, event); return;}
    if (!env) {deliver(meta, event); return;}
    if (env.kind === 3) {
      const request = meta.pending.get(env.id);
      if (!request) {if (!meta.retired.has(env.id)) deliver(meta, event); return;}
      meta.pending.delete(env.id);
      if (request.injected) {meta.retired.add(env.id); clearTimeout(request.timer);}
      try {identify(meta, request, env.data);} catch (_) { /* An invalid response remains visible to its owner. */ }
      emit(meta, {direction:'in', kind:'response', method:request.method, payload:env.data,
        requestPayload:request.payload, injected:request.injected});
      if (request.injected) {
        try {
          const code = errorCode(env.data);
          if (code) {const error = new Error(`服务器拒绝操作（${code}）`); error.code = code; throw error;}
          request.resolve({payload:env.data});
        } catch (error) {request.reject(error);}
        return;
      }
      if (env.id !== request.clientId) {
        meta.retired.add(env.id);
        const data = bytes.slice(); data[1] = request.clientId & 255; data[2] = request.clientId >> 8;
        deliver(meta, event, data.buffer);
      } else deliver(meta, event);
    } else {
      if (env.kind === 1) emit(meta, {direction:'in', kind:'notify', method:env.name, payload:env.data, injected:false});
      deliver(meta, event);
    }
  }
  function attach(socket) {
    const pathname = new URL(socket.url, location.href).pathname;
    const game = /^\/game-gateway(?:[-/]|$)/.test(pathname);
    if (!game && !/^\/gateway(?:[-/]|$)/.test(pathname)) return;
    const meta = {socket, game, id:++sequence, authenticated:false, accountId:null,
      pending:new Map(), retired:new Set(), queue:Promise.resolve(), originalSend:socket.send,
      ownSendDescriptor:Object.getOwnPropertyDescriptor(socket, 'send')};
    sockets.add(meta);
    meta.message = event => {
      if (delivered.has(event)) return;
      const bytes = bytesOf(event.data), blob = event.data instanceof Blob;
      if (!bytes && !blob) return;
      // The first listener consumes our replies and restores remapped native IDs before Unity sees them.
      event.stopImmediatePropagation();
      meta.queue = meta.queue.then(async () => receive(meta, event,
        bytes || new Uint8Array(await event.data.arrayBuffer()))).catch(error => {
        for (const request of meta.pending.values()) if (request.injected) request.reject(error);
      });
    };
    meta.send = function(data) {
      const bytes = bytesOf(data);
      let env;
      try {env = bytes && core.envelope(bytes);} catch (_) { /* Native non-Liqi traffic is unchanged. */ }
      if (env?.kind !== 2) return Reflect.apply(meta.originalSend, this, arguments);
      const injected = sending?.meta === meta && sending.bytes === data;
      let id = env.id;
      if (!injected && (meta.pending.has(id) || meta.retired.has(id))) id = allocate(meta);
      const request = injected ? meta.pending.get(id) :
        {method:env.name, payload:env.data, clientId:env.id, injected:false};
      if (injected || id !== env.id) meta.modified = true;
      if (!injected) meta.pending.set(id, request);
      if (loginMethods.includes(env.name) || env.name === '.lq.FastTest.authGame')
        meta.authenticated = false;
      const wire = id === env.id ? data : bytes.slice();
      if (id !== env.id) {wire[1] = id & 255; wire[2] = id >> 8;}
      try {Reflect.apply(meta.originalSend, this, [wire]);}
      catch (error) {meta.pending.delete(id); throw error;}
      if (!injected && (loginMethods.includes(env.name) ||
          ['.lq.FastTest.authGame', '.lq.FastTest.syncGame', '.lq.FastTest.enterGame'].includes(env.name)))
        interrupt(meta, '客户端正在恢复连接，等待权威牌局状态');
      emit(meta, {direction:'out', kind:'request', method:env.name, payload:env.data, injected});
    };
    meta.close = () => {
      meta.authenticated = false;
      interrupt(meta, '连接已关闭，等待自动重新连接');
      meta.pending.clear();
      emit(meta, {direction:'in', kind:'close', method:'', payload:new Uint8Array(), injected:false});
      if (stopped) detach(meta);
    };
    socket.addEventListener('message', meta.message);
    socket.addEventListener('close', meta.close);
    socket.send = meta.send;
  }
  function request(method, payload, {game = method.startsWith('.lq.FastTest.')} = {}) {
    if (stopped) return Promise.reject(new Error('自动控制连接已停止'));
    const meta = latest(game);
    if (!ready(meta)) return Promise.reject(connectionError('尚未取得已登录的游戏连接，等待自动重新连接'));
    if (!(payload instanceof Uint8Array) || game !== method.startsWith('.lq.FastTest.') ||
        !['.lq.Lobby.fetchAccountInfo', '.lq.Lobby.startUnifiedMatch', '.lq.Lobby.cancelUnifiedMatch',
          '.lq.FastTest.inputOperation', '.lq.FastTest.inputChiPengGang', '.lq.FastTest.confirmNewRound'].includes(method))
      return Promise.reject(new Error('不支持的自动操作请求'));
    return new Promise((resolve, reject) => {
      const id = allocate(meta), body = encode([[1, method], [2, payload]]);
      const frame = new Uint8Array(3 + body.length); frame.set([2, id & 255, id >> 8]); frame.set(body, 3);
      const entry = {method, payload, injected:true, resolve, reject};
      meta.pending.set(id, entry);
      entry.timer = setTimeout(() => {
        if (meta.pending.get(id) !== entry) return;
        meta.pending.delete(id); meta.retired.add(id);
        reject(connectionError('等待服务器确认超时，等待权威状态恢复，暂不重复操作'));
      }, 10000);
      try {sending = {meta, bytes:frame}; meta.socket.send(frame);}
      catch (error) {clearTimeout(entry.timer); meta.pending.delete(id); meta.retired.add(id); reject(error);}
      finally {sending = null;}
    });
  }
  const wrapped = new Proxy(NativeSocket, {construct(target, args, newTarget) {
    const socket = Reflect.construct(target, args, newTarget); attach(socket); return socket;
  }});
  window.WebSocket = wrapped;
  function detach(meta) {
    meta.socket.removeEventListener('message', meta.message);
    meta.socket.removeEventListener('close', meta.close);
    if (meta.socket.send === meta.send) {
      if (meta.ownSendDescriptor) Object.defineProperty(meta.socket, 'send', meta.ownSendDescriptor);
      else delete meta.socket.send;
    }
  }
  window.__mjProtocol = {fields:core.fields, action:core.action, encode, first, str};
  window.__mjUnityTransport = {snapshot, request,
    isUnity:() => !!(window.unityInstance || typeof window.createUnityInstance === 'function' ||
      window.document?.getElementById('unity-canvas')),
    onMessage(listener) {listeners.add(listener); return () => listeners.delete(listener);},
    stop() {
      stopped = true;
      for (const meta of sockets) {
        for (const [id, entry] of meta.pending) if (entry.injected) {
          clearTimeout(entry.timer); meta.pending.delete(id); meta.retired.add(id);
          entry.reject(new Error('自动控制连接已停止'));
        }
        // Keep filtering until physical close: a late automation reply must never reach Unity,
        // and native requests already remapped still need their original IDs restored.
        if (!meta.modified || meta.socket.readyState > 1) detach(meta);
      }
      if (window.WebSocket === wrapped) window.WebSocket = NativeSocket;
      listeners.clear();
    }};
})();
