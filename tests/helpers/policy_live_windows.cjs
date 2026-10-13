// Real ActionPrototype frames through the injected collector, without a server.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const core = require('../../src/core.cjs');

async function collect(item) {
  const packets = [], expected = [];
  class Socket extends EventTarget {
    constructor(url) {super(); this.url = url; this.readyState = 1; this.sent = [];}
    send(bytes) {this.sent.push(bytes);}
  }
  const window = {WebSocket:Socket,
    __mjStatsOverlay:{invalidateAdvice() {}, expectAdvice:key => expected.push(key)},
    webkit:{messageHandlers:{mjStatistics:{postMessage:raw => packets.push(JSON.parse(raw))}}}};
  const context = vm.createContext({window, core, location:{hostname:'game.maj-soul.com'},
    Uint8Array, ArrayBuffer, Blob, TextEncoder, TextDecoder, MessageEvent, URL, console,
    performance:{now:() => 1000}, setTimeout, clearTimeout, setInterval:() => 1, clearInterval() {}});
  for (const file of ['unity_transport.js', 'browser.js']) {
    const source = fs.readFileSync(path.join(__dirname, '../../src', file), 'utf8');
    vm.runInContext(file === 'browser.js' ? `(() => {${source}\n})()` : source, context);
  }
  const encode = entries => window.__mjProtocol.encode(entries.map(([field, value]) =>
    [field, Array.isArray(value) ? encode(value) : value]));
  const socket = new window.WebSocket('wss://example.test/game-gateway');
  const keys = [132,94,78,66,57,162,31,96,28];
  for (const [step, action] of item.actions.entries()) {
    const payload = encode(action.fields);
    const masked = payload.map((byte, i) => byte ^ (((23 ^ payload.length) + 5 * i + keys[i % 9]) & 255));
    const actionBytes = window.__mjProtocol.encode([[1, step], [2, action.name], [3, masked]]);
    const bytes = new Uint8Array([1, ...window.__mjProtocol.encode([[1, '.lq.ActionPrototype'], [2, actionBytes]])]);
    socket.dispatchEvent(new MessageEvent('message', {data:bytes.buffer}));
    await new Promise(setImmediate);
  }
  if (packets.some(packet => packet.kind === 'error')) throw new Error(JSON.stringify(packets));
  const turns = packets.filter(packet => packet.kind === 'turn');
  if (turns.length !== item.actions.length || expected.length !== turns.length || socket.sent.length)
    throw new Error('Collector must publish each action once without sending game input');
  if (!turns.every((packet, index) => expected[index] === `${packet.session}:${packet.serial}`))
    throw new Error('Every snapshot must carry its own advice key');
  return {name:item.name, turns};
}

(async () => {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const results = [];
  for (const item of JSON.parse(input)) results.push(await collect(item));
  process.stdout.write(JSON.stringify(results));
})().catch(error => {console.error(error); process.exitCode = 1;});
