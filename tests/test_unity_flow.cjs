// Whole injected stack, real wire encoding/decoding and synthetic server responses.
// No Laya globals, game account, or external connection is used.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const core = require('../src/core.cjs');
const read = name => fs.readFileSync(path.join(__dirname, '../src', name), 'utf8');
async function setup(players = 4, early = false) {
  let time = 0, timerId = 0;
  const timers = new Map(), intervals = new Map(), packets = [], statuses = [];
  class Socket extends EventTarget {
    constructor(url) {super(); this.url = url; this.readyState = 1; this.sent = []; this.seen = [];
      // Assigned only after the transport and collector attach their own listeners.
    }
    send(data) {this.sent.push(new Uint8Array(data instanceof ArrayBuffer ? data : data.buffer, data.byteOffset || 0, data.byteLength).slice());}
  }
  const window = {WebSocket:Socket, document:{getElementById:id => id === 'unity-canvas' ? {} : null},
    __mjStatsOverlay:{updateAutomation:value => statuses.push(value), invalidateAdvice() {}, expectAdvice() {}},
    webkit:{messageHandlers:{mjStatistics:{postMessage:raw => packets.push(JSON.parse(raw))}}}};
  const math = Object.create(Math); math.random = () => .5;
  const context = vm.createContext({window, core, location:{hostname:'game.maj-soul.com', href:'https://game.maj-soul.com/1/'},
    Uint8Array, ArrayBuffer, Blob, TextEncoder, TextDecoder, MessageEvent, URL, console, Math:math,
    performance:{now:() => time}, setTimeout:(fn, ms) => {timers.set(++timerId, {fn, at:time + ms}); return timerId;},
    clearTimeout:id => timers.delete(id), setInterval:fn => {intervals.set(++timerId, fn); return timerId;},
    clearInterval:id => intervals.delete(id), addEventListener() {}, removeEventListener() {}});
  vm.runInContext(read('unity_transport.js'), context);
  vm.runInContext(`(() => {${read('browser.js')}\n})()`, context);
  for (const file of ['unity_actions.js','unity_lobby.js','autoplay.js'])
    vm.runInContext(read(file), context);
  if (early) window.__mjAutoplay.setEnabled(true);
  const {encode, first, fields, str} = window.__mjProtocol;
  const flush = () => new Promise(setImmediate);
  async function advance(ms) {
    time += ms;
    for (const [id, timer] of [...timers]) if (timer.at <= time) {timers.delete(id); timer.fn();}
    for (const fn of intervals.values()) fn();
    await flush();
  }
  const frame = (kind, id, method, payload = new Uint8Array()) => new Uint8Array([
    ...(kind === 1 ? [1] : [kind, id & 255, id >> 8]), ...encode([[1, method], [2, payload]])]);
  function connect(game = false) {
    const socket = new window.WebSocket(`wss://example.test/${game ? 'game-gateway' : 'gateway'}`);
    socket.addEventListener('message', event => socket.seen.push(new Uint8Array(event.data).slice()));
    return socket;
  }
  async function feed(socket, bytes) {socket.dispatchEvent(new MessageEvent('message', {data:bytes.buffer})); await flush();}
  async function reply(socket, payload = new Uint8Array()) {
    const request = core.envelope(socket.sent.at(-1));
    await feed(socket, frame(3, request.id, '', payload)); return request;
  }
  async function action(socket, name, step, entries) {
    const payload = encode(entries), keys = [132,94,78,66,57,162,31,96,28];
    const masked = payload.map((byte, i) => byte ^ (((23 ^ payload.length) + 5 * i + keys[i % 9]) & 255));
    await feed(socket, frame(1, 0, '.lq.ActionPrototype', encode([[1, step], [2, name], [3, masked]])));
  }
  const account = (gold = 30000) => encode([[1, 11], ...(gold === null ? [] : [[11,gold]]),
    [21, encode([[1,10301]])], [22,encode([[1,20301]])]]);
  async function replyAccount(gold = 30000) {
    const request = core.envelope(lobby.sent.at(-1));
    assert.equal(request.name,'.lq.Lobby.fetchAccountInfo');
    // Explicit account_id is the profile endpoint and omits private gold, even
    // when the requested ID happens to be the currently logged-in account.
    const privateGold = first(fields(request.data),1) === 0 ? gold : null;
    return reply(lobby,encode([[2,account(privateGold)]]));
  }
  const lobby = connect();
  lobby.send(frame(2, 1, '.lq.Lobby.login', encode([[11, 'current-native-client-version']])));
  await reply(lobby, encode([[2,11], [3,account()]]));
  const api = window.__mjAutoplay; api.setPlayerCount(players);
  return {window, api, lobby, packets, statuses, advance, feed, frame, reply, replyAccount, action, connect, encode, first, fields, str, account,
    last(socket) {return core.envelope(socket.sent.at(-1));},
    advice(best) {const packet = packets.findLast(p => p.kind === 'turn');
      api.onAdvice({adviceKey:`${packet.session}:${packet.serial}`, advice:{status:'ready',best}});}};
}

for (const players of [4, 3]) test(`Unity ${players}-player flow matches, discards, confirms a round and rematches without Laya globals`, async () => {
  const h = await setup(players), {encode:e, first, fields, str} = h;
  assert.equal(h.window.GameMgr, undefined);
  assert.equal(h.api.getStatus().enabled, false);
  h.api.setEnabled(true); await h.advance(3000);
  assert.equal(h.last(h.lobby).name, '.lq.Lobby.fetchAccountInfo');
  assert.equal(h.last(h.lobby).data.length,0, 'the wire request must fetch private self-account data');
  await h.replyAccount();
  await h.advance(100); await h.advance(3000);
  const match = h.last(h.lobby);
  assert.equal(match.name, '.lq.Lobby.startUnifiedMatch');
  assert.equal(str(fields(match.data),1), players === 4 ? '1:8' : '1:21');
  assert.equal(str(fields(match.data),2), 'current-native-client-version');
  await h.reply(h.lobby);
  await h.feed(h.lobby, h.frame(1,0,'.lq.NotifyMatchGameStart',e([[3,'public-test-match'],[4,players === 4 ? 8 : 21]])));
  assert.equal(core.envelope(h.lobby.seen.at(-1)).name, '.lq.NotifyMatchGameStart');
  const game = h.connect(true), seats = [11,22,33,44].slice(0,players);
  game.send(h.frame(2,2,'.lq.FastTest.authGame',e([[1,11]])));
  const auth = e([...seats.map(id => [2,e([[1,id],[5,e([[1,10301]])],[7,e([[1,20301]])]])]),
    ...seats.map(id => [3,id]), [5,e([[1,2],[2,e([[1,players === 4 ? 1 : 11]])],[3,e([[2,players === 4 ? 8 : 21]])]])]]);
  await h.reply(game,auth);
  game.send(h.frame(2,3,'.lq.FastTest.enterGame'));
  await h.reply(game);
  assert.equal(h.api.getStatus().enabled,true, 'an empty initial enterGame response is not a damaged round');
  await h.action(game,'ActionMJStart',0,[]);
  assert.equal(h.api.getStatus().enabled,true, 'the pre-deal start signal must preserve automation intent');
  assert.equal(h.window.__mjMonitor.getSnapshot().state.canAct,false);
  await h.advance(5000);
  assert.equal(h.api.getStatus().enabled,true, 'normal initial loading must wait for the real deal');
  assert.deepEqual(game.sent.map(bytes=>core.envelope(bytes).name),
    ['.lq.FastTest.authGame','.lq.FastTest.enterGame'], 'no automatic input is allowed before the deal');
  const hand = ['1p','2p','3p','4p','5p','6p','1s','2s','3s','4s','5s','6s','7z','1z'];
  await h.action(game,'ActionNewRound',1,[[1,0],[2,0],[3,0],...hand.map(tile => [4,tile]),
    ...seats.map(() => [6,players === 4 ? 25000 : 35000]), [7,e([[1,0],[2,e([[1,1]])],[4,20000],[5,5000]])],
    [13,players === 4 ? 69 : 54],[14,'1p']]);
  const state = h.window.__mjMonitor.getSnapshot().state;
  assert.equal(state.canAct,true); assert.equal(state.operationTiming.timeFixed,5000);
  assert.equal(h.window.__mjUnityActions.snapshot(state).canAct,true);
  h.advice({action:'discard',tile:'1z'}); await h.advance(2999);
  assert.equal(game.sent.length,2);
  await h.advance(1);
  assert.equal(game.sent.length,3, 'the first advised action is sent exactly once after the valid deal');
  assert.equal(h.last(game).name,'.lq.FastTest.inputOperation', JSON.stringify(h.api.getStatus()));
  assert.equal(str(fields(h.last(game).data),3),'1z');
  assert.equal(h.api.getStatus().enabled,true);
  // Acknowledgement is private to the adapter; Unity receives only the server's action.
  const seen = game.seen.length; await h.reply(game);
  assert.equal(game.seen.length,seen);
  assert.equal(h.window.__mjUnityActions.snapshot().pending,true);
  await h.action(game,'ActionDiscardTile',2,[[1,0],[2,'1z'],[5,1]]);
  assert.equal(h.window.__mjUnityActions.snapshot().pending,false);
  assert.equal(h.api.getStatus().enabled,true);
  await h.action(game,'ActionNoTile',3,[]);
  assert.equal(h.window.__mjMonitor.getSnapshot().state.phase,'between_rounds');
  await h.advance(100); await h.advance(3000);
  assert.equal(h.last(game).name,'.lq.FastTest.confirmNewRound');
  await h.reply(game);
  await h.feed(game,h.frame(1,0,'.lq.NotifyGameEndResult'));
  const before = h.lobby.sent.length; await h.advance(44000);
  assert.equal(h.lobby.sent.length,before);
  await h.advance(1000); await h.advance(3000);
  assert.equal(h.last(h.lobby).name,'.lq.Lobby.fetchAccountInfo');
  assert.equal(h.last(h.lobby).data.length,0);
  await h.replyAccount();
  await h.advance(100); await h.advance(3000);
  assert.equal(h.last(h.lobby).name,'.lq.Lobby.startUnifiedMatch');
  await h.reply(h.lobby);
  h.api.setEnabled(false);
  assert.equal(h.last(h.lobby).name,'.lq.Lobby.cancelUnifiedMatch');
  await h.reply(h.lobby); await h.advance(100);
  assert.equal(h.api.getStatus().enabled,false);
  assert.ok(h.packets.every((packet, index) => !index || packet.serial > h.packets[index - 1].serial),
    'automation diagnostics must not reorder native log events');
});

for (const fault of ['step gap','unverified snapshot','invalid first deal'])
  test(`Unity initial loading allowance does not accept ${fault}`, async () => {
    const h = await setup(4), e = h.encode, game = h.connect(true), seats = [11,22,33,44];
    game.send(h.frame(2,2,'.lq.FastTest.authGame',e([[1,11]])));
    await h.reply(game,e([...seats.map(id=>[2,e([[1,id],[5,e([[1,10301]])]])]),
      ...seats.map(id=>[3,id]), [5,e([[1,2],[2,e([[1,1]])],[3,e([[2,8]])]])]]));
    h.api.setEnabled(true);
    const hand = ['1p','2p','3p','4p','5p','6p','1s','2s','3s','4s','5s','6s','7z','1z'];
    const deal = cards => [[1,0],[2,0],[3,0],...cards.map(tile=>[4,tile]),
      ...seats.map(()=>[6,25000]),[7,e([[1,0],[2,e([[1,1]])],[4,20000],[5,5000]])],[13,69],[14,'1p']];
    await h.action(game,'ActionNewRound',1,deal(fault === 'invalid first deal' ? [] : hand));
    if (fault !== 'invalid first deal') {
      assert.equal(h.api.getStatus().enabled,true);
      const ready = h.window.__mjMonitor.getSnapshot().state;
      assert.equal(ready.handComplete,true); assert.equal(ready.historyComplete,true);
      if (fault === 'step gap') {
        await h.action(game,'ActionDiscardTile',3,[[1,1],[2,'7z']]);
      } else {
        game.send(h.frame(2,3,'.lq.FastTest.syncGame'));
        const snapshot = e([[1,0],[2,0],[3,0],[4,0],[5,69],...hand.map(tile=>[6,tile]),[7,'1p'],
          ...seats.map(()=>[9,e([[1,25000]])])]);
        await h.reply(game,e([[3,2],[4,e([[1,snapshot]])]]));
        assert.equal(h.window.__mjMonitor.getSnapshot().state.baseline,'snapshot_unverified');
      }
    }
    assert.equal(h.api.getStatus().enabled,false);
    assert.match(h.api.getStatus().message,/基线/);
    const sent = game.sent.length;
    await h.advance(5000); assert.equal(game.sent.length,sent);
    await h.action(game,'ActionNewRound',4,deal(hand));
    assert.equal(h.api.getStatus().enabled,false, 'a later valid deal cannot override a safety pause');
  });

test('reopening during settlement preserves the countdown and automatically queues the next match after it expires', async () => {
  const h=await setup(3), game=h.connect(true);
  game.send(h.frame(2,2,'.lq.FastTest.authGame',h.encode([[1,11]])));
  await h.reply(game);
  await h.feed(game,h.frame(1,0,'.lq.NotifyGameEndResult'));
  await h.advance(26000); h.api.setEnabled(true);
  assert.equal(h.api.getStatus().phase,'settlement');
  assert.match(h.api.getStatus().message,/19 秒/);
  const sent=h.lobby.sent.length;
  await h.advance(13000); h.api.setEnabled(false);
  await h.feed(game,h.frame(1,0,'.lq.NotifyGameEndResult'));
  await h.advance(1000); h.api.setEnabled(true);
  assert.match(h.api.getStatus().message,/5 秒/);
  await h.advance(4999);
  assert.equal(h.lobby.sent.length,sent);
  assert.equal(h.api.getStatus().enabled,true);
  await h.advance(1); await h.advance(3000);
  assert.equal(h.last(h.lobby).name,'.lq.Lobby.fetchAccountInfo');
  await h.replyAccount(); await h.advance(100); await h.advance(3000);
  assert.equal(h.last(h.lobby).name,'.lq.Lobby.startUnifiedMatch');
  assert.equal(h.str(h.fields(h.last(h.lobby).data),1),'1:21');
  await h.reply(h.lobby); h.api.setEnabled(false); await h.reply(h.lobby);
});

test('enabling while Unity has no authenticated connection proceeds when native login finishes', async () => {
  const h = await setup(4, true);
  assert.equal(h.api.getStatus().enabled,true);
  await h.advance(100); await h.advance(3000);
  assert.equal(h.last(h.lobby).name,'.lq.Lobby.fetchAccountInfo');
  assert.equal(h.last(h.lobby).data.length,0);
  assert.equal(h.api.getStatus().enabled,true);
  assert.ok(h.statuses.some(s => /登录/.test(s.message)));
});

test('re-enabling after insufficient private gold refreshes the balance and then enters the eligible queue', async () => {
  const h = await setup(4);
  h.api.setEnabled(true); await h.advance(3000);
  await h.replyAccount(null); await h.advance(100);
  assert.equal(h.api.getStatus().enabled,false);
  assert.match(h.api.getStatus().message,/金币/);
  const previous = h.lobby.sent.length;
  h.api.setEnabled(true); await h.advance(3000);
  assert.equal(h.lobby.sent.length,previous+1, 'reopening must query fresh private data rather than reusing cached zero');
  assert.equal(h.last(h.lobby).name,'.lq.Lobby.fetchAccountInfo');
  assert.equal(h.last(h.lobby).data.length,0);
  await h.replyAccount(6000); await h.advance(100); await h.advance(3000);
  assert.equal(h.last(h.lobby).name,'.lq.Lobby.startUnifiedMatch');
  assert.equal(h.str(h.fields(h.last(h.lobby).data),1),'1:8');
  assert.equal(h.api.getStatus().enabled,true);
  await h.reply(h.lobby); h.api.setEnabled(false);
  await h.reply(h.lobby); await h.advance(100);
});
