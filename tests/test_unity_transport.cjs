const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const core = require('../src/core.cjs');
const source = fs.readFileSync(path.join(__dirname, '../src/unity_transport.js'), 'utf8');
const collector = fs.readFileSync(path.join(__dirname, '../src/browser.js'), 'utf8');

function setup({collect = false} = {}) {
  let clock = 0, nextTimer = 0, inputs = 0;
  const timers = new Map(), packets = [], events = [], sockets = [];
  const bytes = value => value instanceof ArrayBuffer ? new Uint8Array(value) :
    new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  class Socket extends EventTarget {
    constructor(url) {
      super(); this.url = url; this.readyState = 0; this.sent = []; sockets.push(this);
    }
    send(data) {
      if (this.readyState !== 1) throw new Error('socket not open');
      if (this.sendError) throw this.sendError;
      this.sent.push(typeof data === 'string' ? data : bytes(data).slice());
    }
    open() {this.readyState = 1; this.dispatchEvent(new Event('open'));}
    close() {this.readyState = 3; this.dispatchEvent(new Event('close'));}
    receive(data) {
      this.dispatchEvent(new MessageEvent('message', {data, origin:'https://game.maj-soul.com'}));
    }
    set onmessage(callback) {
      if (this._onmessage) this.removeEventListener('message', this._onmessage);
      this._onmessage = callback;
      if (callback) this.addEventListener('message', callback);
    }
    get onmessage() {return this._onmessage;}
  }
  Object.assign(Socket, {CONNECTING:0, OPEN:1, CLOSING:2, CLOSED:3});
  const location = {hostname:'game.maj-soul.com', href:'https://game.maj-soul.com/1/'};
  const window = {WebSocket:Socket, document:{getElementById:() => ({})},
    webkit:{messageHandlers:{mjStatistics:{postMessage:value => packets.push(JSON.parse(value))}}},
    __mjStatsOverlay:{invalidateAdvice() {}, expectAdvice() {}},
    __mjAutoplay:{onInput() {inputs++;}, onEvent() {}, stop() {}}};
  const context = vm.createContext({window, location, core, Event, EventTarget, MessageEvent,
    ArrayBuffer, Uint8Array, Blob, TextEncoder, TextDecoder, URL, console,
    performance:{now:() => clock},
    setTimeout:(fn, delay) => {const id = ++nextTimer; timers.set(id, {fn, due:clock + delay}); return id;},
    clearTimeout:id => timers.delete(id), setInterval:() => ++nextTimer, clearInterval() {}});
  vm.runInContext(source, context);
  if (collect) vm.runInContext(`(() => {${collector}\n})()`, context);
  const api = window.__mjUnityTransport, protocol = window.__mjProtocol;
  api.onMessage(event => events.push(event));
  function frame(kind, id, method = '', payload = new Uint8Array()) {
    const body = protocol.encode([[1, method], [2, payload]]), prefix = kind === 1 ? [1] : [kind, id & 255, id >> 8];
    return new Uint8Array([...prefix, ...body]);
  }
  const flush = async () => {for (let i = 0; i < 20; i++) await Promise.resolve();};
  async function advance(ms) {
    clock += ms;
    for (const [id, timer] of timers) if (timer.due <= clock) {timers.delete(id); timer.fn();}
    await flush();
  }
  function connect(game = false) {
    const socket = new window.WebSocket(`wss://example.test/${game ? 'game-gateway' : 'gateway'}`);
    const unity = [];
    // Unity 4.0.47 _WS_Create only examines e.data: binary bytes are copied to
    // HEAPU8 and passed to the WASM callback. It does not inspect isTrusted.
    // Source: game.maj-soul.com/1/Build/chs_t-WebGL-release-4.0.47(47).framework.js.gz
    socket.binaryType = 'arraybuffer';
    socket.onmessage = event => {
      if (event.data instanceof ArrayBuffer) {
        const heap = new Uint8Array(event.data.byteLength);
        heap.set(new Uint8Array(event.data));
        unity.push({bytes:heap, target:event.target, origin:event.origin});
      } else unity.push({text:event.data});
    };
    socket.open(); return {socket, unity};
  }
  async function login(connection, accountId = 23, game = false) {
    const method = game ? '.lq.FastTest.authGame' : '.lq.Lobby.login';
    connection.socket.send(frame(2, 7, method, protocol.encode([[1, accountId]])));
    connection.socket.receive(frame(3, 7, '', game ? new Uint8Array() : protocol.encode([[2, accountId]])).buffer);
    await flush(); assert.equal(core.envelope(connection.unity.at(-1).bytes).id, 7);
    connection.unity.length = 0; connection.socket.sent.length = 0; events.length = 0;
  }
  const acknowledge = (connection, index = 0, payload = new Uint8Array()) => {
    connection.socket.receive(frame(3, core.envelope(connection.socket.sent[index]).id, '', payload).buffer);
  };
  return {api, protocol, window, Socket, sockets, events, packets, frame, connect, login,
    acknowledge, flush, advance, get inputs() {return inputs;}, get timerCount() {return timers.size;}};
}

test('native login proves the connection and passes the original response to the Unity binary callback', async () => {
  const h = setup(), c = h.connect();
  assert.equal(h.api.snapshot().connected, false);
  await h.login(c, 81);
  assert.equal(h.api.snapshot().accountId, 81);
  assert.equal(h.api.snapshot().connected, true);
  assert.equal(h.api.isUnity(), true);
  delete h.window.document; assert.equal(h.api.isUnity(), false);
});

test('requests require authentication and reject methods or gateway overrides outside the narrow API', async () => {
  const h = setup(), c = h.connect();
  await assert.rejects(h.api.request('.lq.Lobby.startUnifiedMatch', new Uint8Array()), /登录/);
  await h.login(c);
  await assert.rejects(h.api.request('.lq.Lobby.createRoom', new Uint8Array()), /不支持/);
  await assert.rejects(h.api.request('.lq.Lobby.startUnifiedMatch', [], {}), /不支持/);
  await assert.rejects(h.api.request('.lq.FastTest.inputOperation', new Uint8Array(), {game:false}), /不支持/);
  assert.equal(c.socket.sent.length, 0);
});

test('injected ACK resolves its owner, exposes request context and never reaches Unity', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  const payload = h.protocol.encode([[1, '1:2'], [2, 'WebGL_test']]);
  const pending = h.api.request('.lq.Lobby.startUnifiedMatch', payload);
  assert.equal(core.envelope(c.socket.sent[0]).name, '.lq.Lobby.startUnifiedMatch');
  h.acknowledge(c); await pending; await h.flush();
  assert.equal(c.unity.length, 0);
  assert.equal(h.events.length, 2);
  assert.equal(h.events[0].injected, true);
  assert.equal(h.events[1].kind, 'response');
  assert.deepEqual(h.events[1].requestPayload, payload);
  assert.equal(h.timerCount, 0);
});

test('server rejection is not counted as a successful injected operation', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  const pending = h.api.request('.lq.Lobby.startUnifiedMatch', new Uint8Array());
  h.acknowledge(c, 0, h.protocol.encode([[1, h.protocol.encode([[1, 1306]])]]));
  await assert.rejects(pending, /1306/);
  assert.equal(c.unity.length, 0);
});

test('a native ID colliding with an in-flight injection is remapped only on the wire and restored for Unity', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  const pending = h.api.request('.lq.Lobby.startUnifiedMatch', new Uint8Array());
  const injectedId = core.envelope(c.socket.sent[0]).id;
  c.socket.send(h.frame(2, injectedId, '.lq.Lobby.fetchServerTime'));
  const nativeId = core.envelope(c.socket.sent[1]).id;
  assert.notEqual(nativeId, injectedId);
  h.acknowledge(c, 1, h.protocol.encode([[2, 1234]]));
  h.acknowledge(c, 0); await pending; await h.flush();
  assert.equal(c.unity.length, 1);
  assert.equal(core.envelope(c.unity[0].bytes).id, injectedId);
  assert.equal(c.unity[0].target, c.socket);
  assert.equal(c.unity[0].origin, 'https://game.maj-soul.com');
});

test('the allocator respects native requests already using the initial injected ID', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  c.socket.send(h.frame(2, 60000, '.lq.Lobby.fetchServerTime'));
  const pending = h.api.request('.lq.Lobby.startUnifiedMatch', new Uint8Array());
  assert.notEqual(core.envelope(c.socket.sent[1]).id, 60000);
  h.acknowledge(c, 0); h.acknowledge(c, 1); await pending; await h.flush();
  assert.equal(c.unity.length, 1); assert.equal(core.envelope(c.unity[0].bytes).id, 60000);
});

test('uncontended native IDs and payload bytes pass through without rewriting', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  const request = h.frame(2, 22, '.lq.Lobby.fetchServerTime', h.protocol.encode([[4, 'opaque']]));
  c.socket.send(request);
  assert.deepEqual(c.socket.sent[0], request);
  const response = h.frame(3, 22, '', h.protocol.encode([[2, 987]]));
  c.socket.receive(response.buffer); await h.flush();
  assert.deepEqual(c.unity[0].bytes, response);
});

test('timeout retires the injected ID: late ACK is swallowed and a later native collision is restored', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  const pending = h.api.request('.lq.Lobby.startUnifiedMatch', new Uint8Array());
  const rejected = assert.rejects(pending, /超时/), injectedId = core.envelope(c.socket.sent[0]).id;
  await h.advance(10000); await rejected;
  h.acknowledge(c, 0); await h.flush(); assert.equal(c.unity.length, 0);
  c.socket.send(h.frame(2, injectedId, '.lq.Lobby.fetchServerTime'));
  assert.notEqual(core.envelope(c.socket.sent[1]).id, injectedId);
  h.acknowledge(c, 1); await h.flush();
  assert.equal(core.envelope(c.unity[0].bytes).id, injectedId);
});

test('notifications preserve order and bytes while injected responses are removed between them', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  const pending = h.api.request('.lq.Lobby.startUnifiedMatch', new Uint8Array());
  const start = h.frame(1, null, '.lq.NotifyMatchGameStart', h.protocol.encode([[3, 'uuid'], [5, 'region']]));
  const end = h.frame(1, null, '.lq.NotifyGameEndResult');
  c.socket.receive(start.buffer); h.acknowledge(c); c.socket.receive(end.buffer);
  await pending; await h.flush();
  assert.deepEqual(c.unity.map(item => item.bytes), [start, end]);
  assert.deepEqual(h.events.filter(event => event.kind === 'notify').map(event => event.method),
    ['.lq.NotifyMatchGameStart', '.lq.NotifyGameEndResult']);
});

test('slow Blob decoding cannot let a subsequent binary notification overtake it', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  const first = h.frame(1, null, '.lq.NotifyMatchGameStart'), second = h.frame(1, null, '.lq.NotifyGameEndResult');
  let release;
  class SlowBlob extends Blob {arrayBuffer() {return new Promise(resolve => {release = resolve;});}}
  c.socket.receive(new SlowBlob([first])); c.socket.receive(second.buffer);
  await h.flush(); assert.equal(c.unity.length, 0);
  release(first.buffer); await h.flush();
  assert.equal(c.unity.length, 2);
  assert.deepEqual(c.unity[1].bytes, second);
});

test('opaque non-Liqi frames stay visible to Unity and do not emit protocol events', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  const data = new Uint8Array([255, 0, 7]);
  c.socket.receive(data.buffer); await h.flush();
  assert.deepEqual(c.unity[0].bytes, data); assert.equal(h.events.length, 0);
});

test('game operations use the authenticated game connection rather than the lobby', async () => {
  const h = setup(), lobby = h.connect(), game = h.connect(true);
  await h.login(lobby, 23); await h.login(game, 23, true);
  const pending = h.api.request('.lq.FastTest.confirmNewRound', new Uint8Array());
  assert.equal(lobby.socket.sent.length, 0); assert.equal(game.socket.sent.length, 1);
  h.acknowledge(game); await pending;
  assert.equal(h.events.at(-1).game, true);
});

test('closing a socket rejects its pending operation and invalidates authentication', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  const pending = h.api.request('.lq.Lobby.startUnifiedMatch', new Uint8Array());
  c.socket.close(); await assert.rejects(pending, /连接已关闭/);
  assert.equal(h.api.snapshot().connected, false); assert.equal(h.timerCount, 0);
  await assert.rejects(h.api.request('.lq.Lobby.startUnifiedMatch', new Uint8Array()), /登录/);
});

test('stop rejects injected work but keeps late ACK filtering and native collision restoration until close', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  const pending = h.api.request('.lq.Lobby.startUnifiedMatch', new Uint8Array());
  const injectedId = core.envelope(c.socket.sent[0]).id;
  c.socket.send(h.frame(2, injectedId, '.lq.Lobby.fetchServerTime'));
  h.api.stop(); await assert.rejects(pending, /已停止/);
  assert.equal(h.window.WebSocket, h.Socket); assert.equal(h.timerCount, 0);
  h.acknowledge(c, 0); h.acknowledge(c, 1); await h.flush();
  assert.equal(c.unity.length, 1); assert.equal(core.envelope(c.unity[0].bytes).id, injectedId);
  await assert.rejects(h.api.request('.lq.Lobby.startUnifiedMatch', new Uint8Array()), /已停止/);
  c.socket.close();
  assert.equal(c.socket.send, h.Socket.prototype.send);
});

test('stop detaches a socket that never needed injected traffic or native remapping', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  h.api.stop(); assert.equal(c.socket.send, h.Socket.prototype.send);
});

test('synchronous send failures reject the operation and clean its timeout', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  c.socket.sendError = new Error('test send failed');
  await assert.rejects(h.api.request('.lq.Lobby.startUnifiedMatch', new Uint8Array()), /test send failed/);
  assert.equal(h.timerCount, 0);
});

test('a failed native re-login invalidates the previous authenticated account', async () => {
  const h = setup(), c = h.connect(); await h.login(c);
  c.socket.send(h.frame(2, 9, '.lq.Lobby.oauth2Login'));
  assert.equal(h.api.snapshot().connected, false);
  c.socket.receive(h.frame(3, 9, '', h.protocol.encode([[1, h.protocol.encode([[1, 1004]])]])).buffer);
  await h.flush(); assert.equal(h.api.snapshot().connected, false);
  assert.equal(c.unity.length, 1);
});

test('fetching another player account never changes the authenticated identity', async () => {
  const h = setup(), c = h.connect(); await h.login(c, 81);
  c.socket.send(h.frame(2, 9, '.lq.Lobby.fetchAccountInfo', h.protocol.encode([[1, 99]])));
  c.socket.receive(h.frame(3, 9, '', h.protocol.encode([[2, h.protocol.encode([[1, 99]])]])).buffer);
  await h.flush(); assert.equal(h.api.snapshot().accountId, 81);
});

test('a successful login after reconnect establishes the new session and account', async () => {
  const h = setup(), old = h.connect(); await h.login(old, 81);
  const previous = h.api.snapshot().lobbySessionId;
  old.socket.close(); const current = h.connect(); await h.login(current, 99);
  assert.equal(h.api.snapshot().accountId, 99);
  assert.notEqual(h.api.snapshot().lobbySessionId, previous);
});

test('an unlogged or failed auxiliary lobby socket does not replace the proven authenticated connection', async () => {
  const h = setup(), active = h.connect(); await h.login(active, 81);
  const session = h.api.snapshot().lobbySessionId, auxiliary = h.connect();
  assert.equal(h.api.snapshot().connected, true);
  assert.equal(h.api.snapshot().lobbySessionId, session);
  auxiliary.socket.send(h.frame(2, 17, '.lq.Lobby.oauth2Login'));
  auxiliary.socket.receive(h.frame(3, 17, '', h.protocol.encode([[1, h.protocol.encode([[1, 1004]])]])).buffer);
  await h.flush(); assert.equal(h.api.snapshot().accountId, 81);
  auxiliary.socket.close(); assert.equal(h.api.snapshot().connected, true);
  const pending = h.api.request('.lq.Lobby.fetchAccountInfo', h.protocol.encode([[1, 81]]));
  assert.equal(active.socket.sent.length, 1); assert.equal(auxiliary.socket.sent.length, 1);
  h.acknowledge(active); await pending;
});

test('a new authenticated lobby replaces the old session and closing it never revives the old account', async () => {
  const h = setup(), previous = h.connect(); await h.login(previous, 81);
  const oldSession = h.api.snapshot().lobbySessionId, current = h.connect(); await h.login(current, 99);
  assert.equal(h.api.snapshot().accountId, 99);
  assert.notEqual(h.api.snapshot().lobbySessionId, oldSession);
  const pending = h.api.request('.lq.Lobby.fetchAccountInfo', h.protocol.encode([[1, 99]]));
  assert.equal(previous.socket.sent.length, 0); assert.equal(current.socket.sent.length, 1);
  h.acknowledge(current); await pending;
  current.socket.close(); assert.equal(h.api.snapshot().connected, false);
  await assert.rejects(h.api.request('.lq.Lobby.fetchAccountInfo', new Uint8Array()), /登录/);
});

test('the game role also retains its proven socket until a replacement successfully authenticates', async () => {
  const h = setup(), lobby = h.connect(), previous = h.connect(true);
  await h.login(lobby, 81); await h.login(previous, 81, true);
  const oldSession = h.api.snapshot().gameSessionId, current = h.connect(true);
  assert.equal(h.api.snapshot().gameConnected, true);
  assert.equal(h.api.snapshot().gameSessionId, oldSession);
  await h.login(current, 81, true);
  assert.notEqual(h.api.snapshot().gameSessionId, oldSession);
  const pending = h.api.request('.lq.FastTest.confirmNewRound', new Uint8Array());
  assert.equal(previous.socket.sent.length, 0); assert.equal(current.socket.sent.length, 1);
  h.acknowledge(current); await pending;
  current.socket.close(); assert.equal(h.api.snapshot().gameConnected, false);
});

test('logging in as another account invalidates the previous account game connection', async () => {
  const h = setup(), lobby = h.connect(), game = h.connect(true);
  await h.login(lobby, 81); await h.login(game, 81, true);
  assert.equal(h.api.snapshot().gameConnected, true);
  const other = h.connect(); await h.login(other, 99);
  assert.equal(h.api.snapshot().accountId, 99); assert.equal(h.api.snapshot().gameConnected, false);
  await assert.rejects(h.api.request('.lq.FastTest.confirmNewRound', new Uint8Array()), /登录/);
});

test('real collector observes outgoing actions once while injected ACK never enters Unity', async () => {
  const h = setup({collect:true}), c = h.connect(true); await h.login(c, 23, true);
  const pending = h.api.request('.lq.FastTest.inputOperation', h.protocol.encode([[1, 1], [2, '1m']]));
  assert.equal(h.inputs, 1);
  h.acknowledge(c); await pending; await h.flush();
  assert.equal(c.unity.length, 0);
  c.socket.send(h.frame(2, 31, '.lq.FastTest.inputOperation', h.protocol.encode([[1, 1], [2, '2m']])));
  assert.equal(h.inputs, 2);
  h.acknowledge(c, 1); await h.flush();
  assert.equal(c.unity.length, 1); assert.equal(core.envelope(c.unity[0].bytes).id, 31);
});
