// Offline boundary runner: real Unity transport/action code, in-memory socket.
// JSON cases come from the Python model's actual serialized advice.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const core = require('../../src/core.cjs');
const plain = value => JSON.parse(JSON.stringify(value));
const flush = async () => {for (let i = 0; i < 20; i++) await Promise.resolve();};

async function check(item) {
  const state = plain(item.state), timers = new Map();
  let nextTimer = 0;
  class Socket extends EventTarget {
    constructor(url) {super(); this.url = url; this.readyState = 1; this.sent = [];}
    send(value) {this.sent.push(new Uint8Array(value).slice());}
    receive(value) {this.dispatchEvent(new MessageEvent('message', {data:value.buffer}));}
  }
  Object.assign(Socket, {CONNECTING:0, OPEN:1, CLOSING:2, CLOSED:3});
  const window = {WebSocket:Socket, __mjMonitor:{getSnapshot:() => ({state:plain(state)})}};
  const context = vm.createContext({window, core, location:{hostname:'game.maj-soul.com'},
    Event, EventTarget, MessageEvent, ArrayBuffer, Uint8Array, Blob, TextEncoder, TextDecoder, URL, console,
    performance:{now:() => 2200},
    setTimeout:(fn, delay) => {timers.set(++nextTimer, {fn, delay}); return nextTimer;},
    clearTimeout:id => timers.delete(id)});
  for (const filename of ['unity_transport.js', 'unity_actions.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../src', filename), 'utf8'), context);
  }
  const protocol = window.__mjProtocol, api = window.__mjUnityActions;
  const frame = (id, method, payload, response = false) => new Uint8Array([
    response ? 3 : 2, id & 255, id >> 8, ...protocol.encode([[1, method], [2, payload]])]);
  const socket = new window.WebSocket('wss://example.test/game-gateway');
  socket.send(frame(7, '.lq.FastTest.authGame', protocol.encode([[1, 23], [3, 'contract-game']])));
  socket.receive(frame(7, '', new Uint8Array(), true));
  await flush();
  assert.equal(window.__mjUnityTransport.snapshot().gameConnected, true);
  socket.sent.length = 0;
  if (item.stale) state.lastStep++;
  if (item.reject) {
    assert.throws(() => api.execute(item.advice, item.state), new RegExp(item.reject));
    assert.equal(socket.sent.length, 0);
    assert.equal(timers.size, 0);
    return {name:item.name, rejected:true};
  }
  let settled = false;
  const pending = api.execute(item.advice, item.state);
  pending.then(() => {settled = true;}, () => {settled = true;});
  assert.equal(socket.sent.length, 1);
  const sent = core.envelope(socket.sent[0]), fields = core.fields(sent.data);
  assert.equal(sent.name, item.method);
  const actual = Object.fromEntries([...fields].map(([field, values]) => [field,
    values[0] instanceof Uint8Array ? new TextDecoder().decode(values[0]) : values[0]]));
  assert.deepEqual(actual, item.fields);
  const echo = () => api.onEvent({kind:'turn', action:{step:state.lastStep + 1, ...item.echo}});
  const ack = () => socket.receive(frame(sent.id, '', new Uint8Array(), true));
  (item.echoFirst ? echo : ack)();
  await flush();
  assert.equal(settled, false, 'one confirmation is not sufficient');
  (item.echoFirst ? ack : echo)();
  assert.equal((await pending).ok, true);
  assert.equal(timers.size, 0);
  assert.throws(() => api.execute(item.advice, item.state), /已经提交/);
  assert.equal(socket.sent.length, 1, 'same decision cannot be sent twice');
  return {name:item.name, action:item.advice.best.action, method:sent.name, bytes:socket.sent[0].length};
}

(async () => {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const results = [];
  for (const item of JSON.parse(input)) {
    try {results.push(await check(item));}
    catch (error) {throw new Error(`${item.name}: ${error.stack}`);}
  }
  process.stdout.write(JSON.stringify(results));
})().catch(error => {console.error(error); process.exitCode = 1;});
