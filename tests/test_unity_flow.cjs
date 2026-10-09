// Whole injected stack, real wire encoding/decoding and synthetic server responses.
// No Laya globals, game account, or external connection is used.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const core = require('../src/core.cjs');
const read = name => fs.readFileSync(path.join(__dirname, '../src', name), 'utf8');
async function setup(players = 4, early = false, roundCount = 1, pristine = false) {
  let time = 0, timerId = 0;
  const timers = new Map(), intervals = new Map(), listeners = new Map(), packets = [], statuses = [];
  class Socket extends EventTarget {
    constructor(url) {super(); this.url = url; this.readyState = 1; this.sent = []; this.seen = [];
      // Assigned only after the transport and collector attach their own listeners.
    }
    send(data) {this.sent.push(new Uint8Array(data instanceof ArrayBuffer ? data : data.buffer, data.byteOffset || 0, data.byteLength).slice());}
  }
  const animationFrames = new Map();
  const window = {WebSocket:Socket, document:{hidden:false, getElementById:id => id === 'unity-canvas' ? {} : null},
    requestAnimationFrame:fn => {animationFrames.set(++timerId, fn); return timerId;},
    cancelAnimationFrame:id => animationFrames.delete(id),
    __mjStatsOverlay:{updateAutomation:value => statuses.push(value), invalidateAdvice() {}, expectAdvice() {}},
    webkit:{messageHandlers:{mjStatistics:{postMessage:raw => packets.push(JSON.parse(raw))}}}};
  const math = Object.create(Math); math.random = () => .5;
  const context = vm.createContext({window, core, location:{hostname:'game.maj-soul.com', href:'https://game.maj-soul.com/1/'},
    Uint8Array, ArrayBuffer, Blob, TextEncoder, TextDecoder, MessageEvent, URL, console, Math:math,
    performance:{now:() => time}, setTimeout:(fn, ms) => {timers.set(++timerId, {fn, at:time + ms}); return timerId;},
    clearTimeout:id => timers.delete(id), setInterval:fn => {intervals.set(++timerId, fn); return timerId;},
    clearInterval:id => intervals.delete(id), addEventListener:(type,fn)=>listeners.set(type,fn),
    removeEventListener:type=>listeners.delete(type)});
  vm.runInContext(read('background.js'), context);
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
  const api = window.__mjAutoplay;
  if (!pristine) {api.setPlayerCount(players); api.setRoundCount(roundCount);}
  return {window, api, lobby, packets, statuses, advance, feed, frame, reply, replyAccount, action, connect, encode, first, fields, str, account,
    async background(ms) {time += ms; window.__mjBackground.pulse(); await flush();},
    manual() {listeners.get('pointerdown')?.({isTrusted:true,composedPath:()=>[]});},
    last(socket) {return core.envelope(socket.sent.at(-1));},
    advice(best) {const packet = packets.findLast(p => p.kind === 'turn');
      api.onAdvice({adviceKey:`${packet.session}:${packet.serial}`, advice:{status:'ready',best}});}};
}

for (const background of [false, true]) for (const players of [4, 3]) for (const roundCount of [1, 2]) for (const switchQueued of [false, true])
  test(`Unity ${players}-player ${roundCount === 1 ? 'East' : 'South'} flow matches, discards, confirms a round and rematches ${switchQueued ? 'in the other wind after changing a submitted queue' : 'in the same wind'} ${background ? 'with only native background pulses' : 'without Laya globals'}`, async () => {
  const h = await setup(players, false, roundCount), {encode:e, first, fields, str} = h;
  if (background) {h.window.document.hidden = true; h.advance = h.background;}
  const mode = (players === 4 ? 7 : 20) + roundCount;
  const nextRoundCount = switchQueued ? 3 - roundCount : roundCount;
  const nextMode = (players === 4 ? 7 : 20) + nextRoundCount;
  assert.equal(h.window.GameMgr, undefined);
  assert.equal(h.api.getStatus().enabled, false);
  h.api.setEnabled(true); await h.advance(3000);
  assert.equal(h.last(h.lobby).name, '.lq.Lobby.fetchAccountInfo');
  assert.equal(h.last(h.lobby).data.length,0, 'the wire request must fetch private self-account data');
  await h.replyAccount();
  await h.advance(100); await h.advance(3000);
  const match = h.last(h.lobby);
  assert.equal(match.name, '.lq.Lobby.startUnifiedMatch');
  assert.equal(str(fields(match.data),1), `1:${mode}`);
  assert.equal(str(fields(match.data),2), 'current-native-client-version');
  if (switchQueued) {
    const submittedCount = h.lobby.sent.length;
    h.api.setRoundCount(nextRoundCount);
    await h.advance(3000);
    assert.equal(h.api.getStatus().enabled,true);
    assert.equal(h.api.getStatus().roundCount,nextRoundCount);
    assert.equal(h.lobby.sent.length,submittedCount, 'changing wind cannot cancel or add a queue before its ACK');
    const queued = h.window.__mjLobby.snapshot(players,nextRoundCount);
    assert.equal(queued.phase,'matching');
    assert.equal(queued.modeId,mode, 'the submitted queue retains its original mode');
  }
  await h.reply(h.lobby);
  await h.feed(h.lobby, h.frame(1,0,'.lq.NotifyMatchGameStart',e([[3,'public-test-match'],[4,mode]])));
  assert.equal(core.envelope(h.lobby.seen.at(-1)).name, '.lq.NotifyMatchGameStart');
  const game = h.connect(true), seats = [11,22,33,44].slice(0,players);
  game.send(h.frame(2,2,'.lq.FastTest.authGame',e([[1,11]])));
  const auth = e([...seats.map(id => [2,e([[1,id],[5,e([[1,10301]])],[7,e([[1,20301]])]])]),
    ...seats.map(id => [3,id]), [5,e([[1,2],[2,e([[1,(players === 4 ? 0 : 10) + roundCount]])],[3,e([[2,mode]])]])]]);
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
  assert.equal(state.match.roundCount,roundCount);
  assert.equal(state.canAct,true); assert.equal(state.operationTiming.timeFixed,5000);
  assert.equal(h.window.__mjUnityActions.snapshot(state).canAct,true);
  h.advice({action:'discard',tile:'1z'});
  await h.advance(h.api.getStatus().timing.targetMs - 1);
  assert.equal(game.sent.length,2);
  await h.advance(1);
  assert.equal(game.sent.length,3, 'the first advised action is sent exactly once after the valid deal');
  assert.equal(h.last(game).name,'.lq.FastTest.inputOperation', JSON.stringify(h.api.getStatus()));
  assert.equal(str(fields(h.last(game).data),3),'1z');
  assert.equal(first(fields(h.last(game).data),5),0,'the dealer opening tile is dealt, not a live draw');
  assert.equal(h.api.getStatus().enabled,true);
  // Acknowledgement is private to the adapter; Unity receives only the server's action.
  const seen = game.seen.length; await h.reply(game);
  assert.equal(game.seen.length,seen);
  assert.equal(h.window.__mjUnityActions.snapshot().pending,true);
  await h.action(game,'ActionDiscardTile',2,[[1,0],[2,'1z'],[5,0]]);
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
  assert.equal(str(fields(h.last(h.lobby).data),1),`1:${nextMode}`);
  await h.reply(h.lobby);
  h.api.setEnabled(false);
  assert.equal(h.last(h.lobby).name,'.lq.Lobby.cancelUnifiedMatch');
  assert.equal(str(fields(h.last(h.lobby).data),1),`1:${nextMode}`);
  await h.reply(h.lobby); await h.advance(100);
  assert.equal(h.api.getStatus().enabled,false);
  assert.ok(h.packets.every((packet, index) => !index || packet.serial > h.packets[index - 1].serial),
    'automation diagnostics must not reorder native log events');
});

for (const scenario of [
  {delay:31000}, {delay:38*60000}, {delay:38*60000,stop:'off'}, {delay:38*60000,stop:'manual'},
]) test(`Unity initial loading keeps user intent through ${scenario.delay}ms${scenario.stop?' then '+scenario.stop:''}`, async () => {
  const h=await setup(3,false,2),e=h.encode,game=h.connect(true),seats=[11,22,33];
  game.send(h.frame(2,2,'.lq.FastTest.authGame',e([[1,11],[3,'slow-initial-match']])));
  await h.reply(game,e([...seats.map(id=>[2,e([[1,id],[7,e([[1,20301]])]])]),
    ...seats.map(id=>[3,id]),[5,e([[1,2],[2,e([[1,12]])],[3,e([[2,22]])]])]]));
  game.send(h.frame(2,3,'.lq.FastTest.enterGame'));await h.reply(game);
  await h.action(game,'ActionMJStart',0,[]);
  h.api.setEnabled(true);await h.advance(scenario.delay);
  assert.equal(h.api.getStatus().enabled,true);
  assert.match(h.api.getStatus().message,/加载.*自动保持开启/);
  assert.equal(game.sent.length,2,'no input may be guessed while the complete first deal is missing');
  assert.equal(h.window.__mjMonitor.getSnapshot().state.canAct,false);
  if (scenario.stop==='off') h.api.setEnabled(false);
  if (scenario.stop==='manual') h.manual();
  const hand=['1p','2p','3p','4p','5p','6p','1s','2s','3s','4s','5s','6s','4z','1z'];
  await h.action(game,'ActionNewRound',1,[[1,0],[2,0],[3,0],...hand.map(tile=>[4,tile]),
    ...seats.map(()=>[6,35000]),[7,e([[1,0],[2,e([[1,1]])],[4,20000],[5,5000]])],[13,54],[14,'1p']]);
  assert.equal(h.window.__mjMonitor.getSnapshot().state.canAct,true);
  await h.advance(100);assert.equal(game.sent.length,2,'a complete deal still needs fresh advice');
  h.advice({action:'discard',tile:'1z'});await h.advance(5000);
  if (scenario.stop) {
    assert.equal(h.api.getStatus().enabled,false);assert.equal(game.sent.length,2);return;
  }
  assert.equal(h.api.getStatus().enabled,true);assert.equal(game.sent.length,3);
  assert.equal(h.last(game).name,'.lq.FastTest.inputOperation');
  assert.equal(h.str(h.fields(h.last(game).data),3),'1z');
  await h.reply(game);await h.action(game,'ActionDiscardTile',2,[[1,0],[2,'1z'],[5,0]]);
  await h.advance(1000);assert.equal(game.sent.length,3);
  assert.equal(h.window.__mjUnityActions.snapshot().pending,false);
  assert.equal(h.api.getStatus().enabled,true);
});

test('native background pulses progress hidden Unity entry and autoplay with JS timers and native frames suspended', async () => {
  const h=await setup(3),e=h.encode,game=h.connect(true),seats=[11,22,33];
  game.send(h.frame(2,2,'.lq.FastTest.authGame',e([[1,11],[3,'hidden-match']])));
  await h.reply(game,e([...seats.map(id=>[2,e([[1,id],[7,e([[1,20301]])]])]),
    ...seats.map(id=>[3,id]),[5,e([[1,2],[2,e([[1,11]])],[3,e([[2,21]])]])]]));
  h.api.setEnabled(true); h.window.document.hidden=true;
  h.window.requestAnimationFrame(() => game.send(h.frame(2,3,'.lq.FastTest.enterGame')));
  // No advance(): all JS intervals, timeouts and native rAF delivery stay stopped.
  await h.background(31000);
  assert.equal(h.last(game).name,'.lq.FastTest.enterGame');
  assert.equal(h.api.getStatus().enabled,true); await h.reply(game);
  const hand=['1p','2p','3p','4p','5p','6p','1s','2s','3s','4s','5s','6s','4z','1z'];
  await h.action(game,'ActionNewRound',1,[[1,0],[2,0],[3,0],...hand.map(tile=>[4,tile]),
    ...seats.map(()=>[6,35000]),[7,e([[1,0],[2,e([[1,1]])],[4,20000],[5,5000]])],[13,54],[14,'1p']]);
  await h.background(250); assert.equal(game.sent.length,2,'the background scheduler still requires advice');
  h.advice({action:'discard',tile:'1z'}); await h.background(3000);
  assert.equal(h.last(game).name,'.lq.FastTest.inputOperation');
  assert.equal(game.sent.length,3); assert.equal(h.api.getStatus().enabled,true);
  await h.reply(game); await h.action(game,'ActionDiscardTile',2,[[1,0],[2,'1z'],[5,0]]);
  await h.background(3000); assert.equal(game.sent.length,3,'background pulses do not duplicate confirmed input');
  assert.equal(h.window.__mjUnityActions.snapshot().pending,false);
  assert.equal(h.api.getStatus().enabled,true);
});

for (const fault of ['step gap','invalid first deal'])
  test(`Unity initial loading allowance does not accept ${fault}`, async () => {
    const h = await setup(4), e = h.encode, game = h.connect(true), seats = [11,22,33,44];
    game.send(h.frame(2,2,'.lq.FastTest.authGame',e([[1,11]])));
    await h.reply(game,e([...seats.map(id=>[2,e([[1,id],[5,e([[1,10301]])]])]),
      ...seats.map(id=>[3,id]), [5,e([[1,2],[2,e([[1,1]])],[3,e([[2,8]])]])]]));
    h.api.setEnabled(true);
    await h.advance(38*60000);
    assert.equal(h.api.getStatus().enabled,true,'long initial waiting cannot itself cancel automation');
    const hand = ['1p','2p','3p','4p','5p','6p','1s','2s','3s','4s','5s','6s','7z','1z'];
    const deal = cards => [[1,0],[2,0],[3,0],...cards.map(tile=>[4,tile]),
      ...seats.map(()=>[6,25000]),[7,e([[1,0],[2,e([[1,1]])],[4,20000],[5,5000]])],[13,69],[14,'1p']];
    await h.action(game,'ActionNewRound',1,deal(fault === 'invalid first deal' ? [] : hand));
    if (fault !== 'invalid first deal') {
      assert.equal(h.api.getStatus().enabled,true);
      const ready = h.window.__mjMonitor.getSnapshot().state;
      assert.equal(ready.handComplete,true); assert.equal(ready.historyComplete,true);
      await h.action(game,'ActionDiscardTile',3,[[1,1],[2,'7z']]);
    }
    assert.equal(h.api.getStatus().enabled,false);
    assert.match(h.api.getStatus().message,/基线/);
    const sent = game.sent.length;
    await h.advance(5000); assert.equal(game.sent.length,sent);
    await h.action(game,'ActionNewRound',4,deal(hand));
    assert.equal(h.api.getStatus().enabled,false, 'a later valid deal cannot override a safety pause');
  });

async function reconnectFixture(inFlight = false, timeAdd = 20000) {
  const h=await setup(),e=h.encode,seats=[11,22,33,44];
  const auth=e([...seats.map(id=>[2,e([[1,id],[5,e([[1,10301]])]])]),
    ...seats.map(id=>[3,id]),[5,e([[1,2],[2,e([[1,1]])],[3,e([[2,8]])]])]]);
  const hand=['1p','2p','3p','4p','5p','6p','1s','2s','3s','4s','5s','6s','7z','1z'];
  const operation=e([[1,0],[2,e([[1,1]])],[4,timeAdd],[5,5000]]);
  const opening=[[1,0],[2,0],[3,0],...hand.map(tile=>[4,tile]),
    ...seats.map(()=>[6,25000]),[7,operation],[13,69],[14,'1p']];
  const old=h.connect(true);old.send(h.frame(2,2,'.lq.FastTest.authGame',e([[1,11],[3,'reconnect-test-match']])));
  await h.reply(old,auth);await h.action(old,'ActionNewRound',0,opening);
  const previous=h.packets.findLast(p=>p.kind==='turn');
  const statusStart=h.statuses.length;
  h.api.setEnabled(true);h.advice({action:'discard',tile:'1z'});
  let oldInput;
  if (inFlight) {
    await h.advance(h.api.getStatus().timing.targetMs);
    oldInput=h.last(old);assert.equal(oldInput.name,'.lq.FastTest.inputOperation');
    assert.equal(h.window.__mjUnityActions.snapshot().pending,true);
  }
  return {h,e,seats,auth,hand,opening,operation,old,previous,oldInput,statusStart};
}

test('notification-only game end releases an acknowledged input before the settlement wait expires', async () => {
  const {h,old}=await reconnectFixture(true,90000);
  await h.reply(old);
  assert.equal(h.window.__mjUnityActions.snapshot().pending,true,'an ACK alone does not confirm the discard');
  await h.feed(old,h.frame(1,0,'.lq.NotifyGameEndResult'));
  assert.equal(h.window.__mjUnityActions.snapshot().pending,false);
  assert.equal(h.window.__mjUnityActions.checkpoint().submitted,null);
  assert.equal(h.api.getStatus().enabled,true);
  const before=h.lobby.sent.length;
  await h.advance(44999);assert.equal(h.lobby.sent.length,before);
  await h.advance(1);await h.advance(3000);
  assert.equal(h.last(h.lobby).name,'.lq.Lobby.fetchAccountInfo');
  assert.equal(h.api.getStatus().enabled,true);
});

test('disabled autoplay keeps cancelling an owned queue beyond transport timeouts without reopening its intent', async () => {
  const h=await setup();
  h.api.setEnabled(true);await h.advance(3000);await h.replyAccount();
  await h.advance(100);await h.advance(3000);await h.reply(h.lobby);
  h.api.setEnabled(false);
  const cancellations=()=>h.lobby.sent.map(bytes=>core.envelope(bytes)).filter(message=>message.name==='.lq.Lobby.cancelUnifiedMatch');
  assert.equal(cancellations().length,1);
  await h.advance(5100);h.api.setEnabled(true);
  assert.equal(h.api.getStatus().enabled,false,'unknown cancellation must block a fresh matching intent');
  await h.advance(5000);await h.advance(100);
  assert.equal(cancellations().length,2,'the same connection must retry after the first 10-second transport timeout');
  await h.advance(10000);await h.advance(100);
  assert.equal(cancellations().length,3);
  assert.ok(cancellations().every(message=>h.str(h.fields(message.data),1)==='1:8'));
  const statuses=h.statuses.length;
  await h.reply(h.lobby);await h.advance(100);await h.advance(30000);
  assert.equal(h.window.__mjUnityLobby.checkpoint().owned,null);
  assert.equal(h.api.getStatus().enabled,false);
  assert.match(h.api.getStatus().message,/已关闭.*手动/);
  assert.equal(h.window.__mjUnityTransport.snapshot().stalled,false,'the acknowledged cancellation settles this queue uncertainty');
  assert.ok(h.statuses.slice(statuses).every(status=>!status.enabled));
  assert.equal(cancellations().length,3);
  assert.equal(h.lobby.sent.filter(bytes=>core.envelope(bytes).name==='.lq.Lobby.startUnifiedMatch').length,1);
  h.api.setEnabled(true);
  assert.equal(h.api.getStatus().enabled,true);
  assert.equal(h.window.__mjRecovery.snapshot().stalled,false,'a new explicit intent must not reload for the cancelled queue');
  await h.advance(3000);
  assert.equal(h.last(h.lobby).name,'.lq.Lobby.fetchAccountInfo');
});

for (const method of ['.lq.NotifyMatchTimeout','.lq.NotifyMatchFailed'])
  test(`explicit re-enable recovers ${method} only after the owned queue is authoritatively cleared`, async () => {
    const h=await setup();
    h.api.setEnabled(true);await h.advance(3000);await h.replyAccount();
    await h.advance(100);await h.advance(3000);await h.reply(h.lobby);
    await h.feed(h.lobby,h.frame(1,0,method,h.encode([[1,'1:8']])));await h.advance(100);
    assert.equal(h.api.getStatus().enabled,false);
    assert.equal(h.window.__mjUnityLobby.checkpoint().owned,null);
    h.api.setEnabled(true);await h.advance(3000);
    assert.equal(h.api.getStatus().enabled,true);
    assert.equal(h.last(h.lobby).name,'.lq.Lobby.fetchAccountInfo');
    await h.replyAccount();await h.advance(100);await h.advance(3000);
    assert.equal(h.last(h.lobby).name,'.lq.Lobby.startUnifiedMatch');
  });

for (const scenario of [
  {name:'closed socket before input',close:true,authenticate:true},
  {name:'closed socket with unacknowledged input',close:true,authenticate:true,inFlight:true},
  {name:'same-socket authentication and sync',authenticate:true},
  {name:'same-socket sync without a close'},
  {name:'same-socket sync with unacknowledged input',inFlight:true},
  {name:'user turns off during recovery',close:true,authenticate:true,inFlight:true,cancel:'off'},
  {name:'manual takeover during recovery',close:true,authenticate:true,cancel:'manual'},
]) test(`Unity recovery preserves user intent: ${scenario.name}`, async () => {
  const {h,e,auth,opening,operation,old,previous,oldInput,statusStart}=await reconnectFixture(scenario.inFlight);
  if (scenario.close) {old.readyState=3;old.dispatchEvent(new Event('close'));await h.advance(0);}
  assert.equal(h.api.getStatus().enabled,true,'disconnect must preserve the enabled preference');
  const stopStatusStart=h.statuses.length;
  if (scenario.cancel === 'off') h.api.setEnabled(false);
  if (scenario.cancel === 'manual') h.manual();
  const enabled=!scenario.cancel;
  assert.equal(h.api.getStatus().enabled,enabled);
  const game=scenario.close?h.connect(true):old;
  if (scenario.authenticate) {
    game.send(h.frame(2,3,'.lq.FastTest.authGame',e([[1,11],[3,'reconnect-test-match']])));
    const sent=game.sent.length;await h.advance(3000);
    assert.equal(game.sent.length,sent,'authentication cannot send the previous decision');
    assert.equal(h.api.getStatus().enabled,enabled);
    await h.reply(game,auth);
  }
  game.send(h.frame(2,4,'.lq.FastTest.syncGame'));
  const beforeRestore=game.sent.length;
  await h.advance(3000);
  assert.equal(game.sent.length,beforeRestore,'sync must close the previous operation window immediately');
  assert.equal(h.api.getStatus().enabled,enabled);
  await h.reply(game,e([[3,1],[4,e([[2,e([[1,0],[2,'ActionNewRound'],[3,e(opening)]])]])]]));
  const restored=h.window.__mjMonitor.getSnapshot().state;
  assert.equal(restored.baseline,'restore_actions');assert.equal(restored.handComplete,true);
  assert.equal(restored.canAct,false,'a replay without an authoritative current timer cannot reopen old operations');
  assert.equal(h.api.getStatus().enabled,enabled);
  const staleAdvice={adviceKey:`${previous.session}:${previous.serial}`,
    advice:{status:'ready',best:{action:'discard',tile:'1z'}}};
  h.api.onAdvice(staleAdvice);
  await h.advance(5000);assert.equal(game.sent.length,beforeRestore);
  await h.action(game,'ActionDiscardTile',1,[[1,0],[2,'1z']]);
  await h.action(game,'ActionDealTile',2,[[1,0],[2,'2z'],[3,68],[4,operation]]);
  assert.equal(h.window.__mjMonitor.getSnapshot().state.canAct,true);
  assert.equal(h.api.getStatus().enabled,enabled);
  h.api.onAdvice(staleAdvice);
  await h.advance(100);assert.equal(game.sent.length,beforeRestore,'old advice is invalid even after live recovery');
  h.advice({action:'discard',tile:'2z'});
  await h.advance(5000);
  if (!enabled) {
    assert.equal(game.sent.length,beforeRestore,'off or manual takeover must survive all recovery packets and advice');
    assert.equal(h.api.getStatus().enabled,false);
    assert.ok(h.statuses.slice(stopStatusStart).every(status=>!status.enabled),'recovery must never flip a cancelled preference back on');
    return;
  }
  assert.equal(game.sent.length,beforeRestore+1,'fresh advice resumes automatically exactly once');
  const input=h.last(game);
  assert.equal(input.name,'.lq.FastTest.inputOperation');
  assert.equal(h.str(h.fields(input.data),3),'2z');
  await h.action(game,'ActionDiscardTile',3,[[1,0],[2,'2z'],[5,1]]);
  assert.equal(h.window.__mjUnityActions.snapshot().pending,true,'the action echo still needs its own ACK');
  if (oldInput) {
    await h.feed(old,h.frame(3,oldInput.id,''));
    assert.equal(h.window.__mjUnityActions.snapshot().pending,true,'an old RPC ACK cannot confirm the new input');
  }
  await h.reply(game);
  assert.equal(h.window.__mjUnityActions.snapshot().pending,false);
  h.api.onAdvice(staleAdvice);await h.feed(game,h.frame(3,input.id,''));await h.advance(5000);
  assert.equal(game.sent.length,beforeRestore+1,'late ACK or advice cannot repeat the confirmed action');
  assert.equal(h.api.getStatus().enabled,true);
  assert.ok(h.statuses.slice(statusStart).every(status=>status.enabled),'the toggle remains on throughout recovery');
});

test('Unity snapshot-only recovery waits with automation enabled until a trustworthy new round', async () => {
  const {h,e,seats,hand,opening,old:game}=await reconnectFixture();
  game.send(h.frame(2,4,'.lq.FastTest.syncGame'));
  const snapshot=e([[1,0],[2,0],[3,0],[4,0],[5,69],...hand.map(tile=>[6,tile]),[7,'1p'],
    ...seats.map(()=>[9,e([[1,25000]])])]);
  await h.reply(game,e([[3,2],[4,e([[1,snapshot]])]]));
  assert.equal(h.window.__mjMonitor.getSnapshot().state.baseline,'snapshot_unverified');
  assert.equal(h.api.getStatus().enabled,true);
  const sent=game.sent.length;
  h.advice({action:'discard',tile:'1z'});await h.advance(5000);
  assert.equal(game.sent.length,sent);
  await h.action(game,'ActionNewRound',3,opening);
  assert.equal(h.window.__mjMonitor.getSnapshot().state.canAct,true);
  h.advice({action:'discard',tile:'1z'});await h.advance(5000);
  assert.equal(game.sent.length,sent+1);
  assert.equal(h.last(game).name,'.lq.FastTest.inputOperation');
  assert.equal(h.api.getStatus().enabled,true);
});

for (const scenario of [
  {name:'unconfirmed same round',confirm:false,expected:1},
  {name:'same round with an unknown confirmation result',confirm:true,expected:0},
  {name:'same round already confirmed',confirm:true,ack:true,expected:0},
  {name:'a different round reusing the terminal step',confirm:true,ack:true,nextRound:true,expected:1},
]) test(`Unity terminal replay advances once: ${scenario.name}`, async () => {
  const {h,e,auth,opening,old}=await reconnectFixture();
  if (scenario.confirm) {
    await h.action(old,'ActionDiscardTile',1,[[1,0],[2,'1z']]);
    await h.action(old,'ActionNoTile',2,[]);
    await h.advance(100);await h.advance(3000);
    assert.equal(h.last(old).name,'.lq.FastTest.confirmNewRound');
    if (scenario.ack) await h.reply(old);
  }
  old.readyState=3;old.dispatchEvent(new Event('close'));await h.advance(0);
  assert.equal(h.api.getStatus().enabled,true);
  const game=h.connect(true);
  game.send(h.frame(2,3,'.lq.FastTest.authGame',e([[1,11],[3,'reconnect-test-match']])));
  await h.reply(game,auth);
  const restoredOpening=opening.map(([field,value])=>[field,field===3&&scenario.nextRound?1:value]);
  const replay=e([[3,3],[4,e([
    [2,e([[1,0],[2,'ActionNewRound'],[3,e(restoredOpening)]])],
    [2,e([[1,1],[2,'ActionDiscardTile'],[3,e([[1,0],[2,'1z']])]])],
    [2,e([[1,2],[2,'ActionNoTile'],[3,e([])]])],
  ])]]);
  game.send(h.frame(2,4,'.lq.FastTest.syncGame'));await h.reply(game,replay);
  const state=h.window.__mjMonitor.getSnapshot().state;
  assert.equal(state.phase,'between_rounds');assert.equal(state.recovery,null);
  assert.equal(state.canAct,false,'a terminal replay must not reopen its historical operations');
  const before=game.sent.length;
  await h.advance(100);await h.advance(3000);
  assert.equal(game.sent.length,before+scenario.expected);
  if (scenario.expected) {
    assert.equal(h.last(game).name,'.lq.FastTest.confirmNewRound');await h.reply(game);
  }
  game.send(h.frame(2,5,'.lq.FastTest.syncGame'));await h.reply(game,replay);
  const synced=game.sent.length;await h.advance(100);await h.advance(3000);
  assert.equal(game.sent.length,synced,'repeating a terminal replay cannot send another confirmation');
  assert.equal(h.api.getStatus().enabled,true);
});

test('a new game UUID can reuse a previously submitted step after reconnect', async () => {
  const {h,e,auth,opening,old,oldInput}=await reconnectFixture(true);
  const previousId=h.window.__mjMonitor.getSnapshot().state.gameId;
  old.readyState=3;old.dispatchEvent(new Event('close'));await h.advance(0);
  const game=h.connect(true);
  game.send(h.frame(2,3,'.lq.FastTest.authGame',e([[1,11],[3,'different-test-match']])));
  await h.reply(game,auth);await h.action(game,'ActionNewRound',0,opening);
  assert.notEqual(h.window.__mjMonitor.getSnapshot().state.gameId,previousId);
  assert.equal(h.window.__mjUnityActions.snapshot().canAct,true,'old-game deduplication cannot block a new match');
  h.advice({action:'discard',tile:'1z'});await h.advance(5000);
  assert.equal(game.sent.length,2);assert.equal(h.last(game).name,'.lq.FastTest.inputOperation');
  await h.feed(old,h.frame(3,oldInput.id,''));
  assert.equal(h.window.__mjUnityActions.snapshot().pending,true);
  await h.reply(game);await h.action(game,'ActionDiscardTile',1,[[1,0],[2,'1z'],[5,0]]);
  assert.equal(h.window.__mjUnityActions.snapshot().pending,false);
  assert.equal(h.api.getStatus().enabled,true);
});

for (const method of ['login','fastLogin'])
  test(`Unity ${method} without a running game clears stale recovery and matches again`, async () => {
    const {h,e,old,statusStart}=await reconnectFixture(method==='fastLogin');
    old.readyState=3;old.dispatchEvent(new Event('close'));
    h.lobby.readyState=3;h.lobby.dispatchEvent(new Event('close'));await h.advance(0);
    assert.equal(h.api.getStatus().enabled,true);
    const lobby=h.connect(),versionField=method==='fastLogin'?1:11;
    lobby.send(h.frame(2,7,`.lq.Lobby.${method}`,e([[versionField,'current-native-client-version']])));
    await h.advance(3000);
    assert.equal(lobby.sent.length,1,'an unauthenticated connection is not proof the old game ended');
    assert.ok(h.window.__mjMonitor.getSnapshot().state.hand.length>0);
    assert.equal(h.window.__mjMonitor.getSnapshot().state.recovery.status,'waiting');
    await h.reply(lobby,method==='fastLogin'?e([]):e([[2,11],[3,h.account()]]));
    const state=h.window.__mjMonitor.getSnapshot().state;
    assert.equal(state.phase,'waiting');assert.equal(state.recovery,null);
    assert.equal(state.baseline,null);assert.equal(state.hand.length,0);assert.equal(state.match,null);
    assert.equal(state.canAct,false);
    const reset=h.packets.findLast(packet=>packet.kind==='status'&&packet.reset);
    assert.equal(reset.phase,'waiting','returning to an empty lobby must not fabricate a new game-end notification');
    assert.equal(reset.recovery,null);
    await h.advance(100);await h.advance(3000);
    assert.equal(h.last(lobby).name,'.lq.Lobby.fetchAccountInfo');
    assert.equal(h.last(lobby).data.length,0);
    await h.reply(lobby,e([[2,h.account()]]));await h.advance(100);await h.advance(3000);
    assert.equal(h.last(lobby).name,'.lq.Lobby.startUnifiedMatch');
    assert.equal(h.str(h.fields(h.last(lobby).data),1),'1:8');
    assert.equal(h.api.getStatus().enabled,true);
    assert.ok(h.statuses.slice(statusStart).every(status=>status.enabled));
  });

test('Unity no-game relogin cancels an unknown old queue before refreshing and matching again', async () => {
  const h=await setup(),e=h.encode;
  h.api.setEnabled(true);await h.advance(3000);await h.replyAccount();
  await h.advance(100);await h.advance(3000);
  const oldMatch=h.last(h.lobby);
  assert.equal(oldMatch.name,'.lq.Lobby.startUnifiedMatch');
  h.lobby.readyState=3;h.lobby.dispatchEvent(new Event('close'));await h.advance(0);
  const lobby=h.connect();
  lobby.send(h.frame(2,7,'.lq.Lobby.fastLogin',e([[1,'current-native-client-version']])));
  await h.reply(lobby);
  assert.deepEqual(lobby.sent.map(bytes=>core.envelope(bytes).name),
    ['.lq.Lobby.fastLogin','.lq.Lobby.cancelUnifiedMatch']);
  assert.equal(h.str(h.fields(h.last(lobby).data),1),'1:8');
  const cancelling=lobby.sent.length;
  await h.feed(h.lobby,h.frame(3,oldMatch.id,''));await h.advance(5000);
  assert.equal(lobby.sent.length,cancelling,'the absent game_info does not prove an uncertain match queue was cancelled');
  assert.equal(h.api.getStatus().enabled,true);
  await h.reply(lobby);await h.advance(100);await h.advance(3000);
  assert.equal(h.last(lobby).name,'.lq.Lobby.fetchAccountInfo');
  await h.reply(lobby,e([[2,h.account()]]));await h.advance(100);await h.advance(3000);
  assert.equal(h.last(lobby).name,'.lq.Lobby.startUnifiedMatch');
  assert.equal(h.str(h.fields(h.last(lobby).data),1),'1:8');
  assert.equal(h.api.getStatus().enabled,true);
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

for (const [action, type, consumed] of [['chi',2,['2m','3m']], ['pon',3,['1m','1m']]])
  for (const scenario of ['matching', 'changed', 'before-ack'])
    test(`Unity ${action} follow-up ${scenario} requires confirmation and fresh advice`, async () => {
      const h = await setup(), {encode:e, first, fields, str} = h;
      const game = h.connect(true), seats = [11,22,33,44];
      game.send(h.frame(2,2,'.lq.FastTest.authGame',e([[1,11]])));
      await h.reply(game,e([...seats.map(id => [2,e([[1,id],[5,e([[1,10301]])]])]),
        ...seats.map(id => [3,id]), [5,e([[1,2],[2,e([[1,1]])],[3,e([[2,8]])]])]]));
      const hand = [...consumed,'1p','2p','3p','4p','5p','6p','1s','2s','3s','1z','7z'];
      const operation = (kind, combination = []) => e([[1,0],
        [2,e([[1,kind],...combination.map(value => [2,value])])],[4,20000],[5,5000]]);
      await h.action(game,'ActionNewRound',0,[[1,0],[2,3],[3,0],...hand.map(tile => [4,tile]),
        ...seats.map(() => [6,25000]),[13,69],[14,'1p']]);
      await h.action(game,'ActionDiscardTile',1,[[1,3],[2,'1m'],[4,operation(type,[consumed.join('|')])]]);
      h.api.setEnabled(true);
      h.advice({action,consumed,calledTile:'1m',fromSeat:3,followupDiscard:'1z'});
      const callDelay = h.api.getStatus().timing.targetMs;
      await h.advance(callDelay);
      assert.equal(h.last(game).name,'.lq.FastTest.inputChiPengGang');
      assert.equal(first(fields(h.last(game).data),1),type);
      const submitted = game.sent.length;
      const tiles = [...consumed,'1m'], froms = [0,0,3];
      await h.action(game,'ActionChiPengGang',2,[[1,0],[2,action === 'chi' ? 0 : 1],
        ...tiles.map(tile => [3,tile]),...froms.map(seat => [4,seat]),[6,operation(1)]]);
      const state = h.window.__mjMonitor.getSnapshot().state;
      assert.equal(state.handComplete,true);
      assert.equal(state.canDiscard,true);
      assert.equal(state.hand.length,11);
      assert.equal(h.window.__mjUnityActions.snapshot().pending,true);
      const tile = scenario === 'changed' ? '7z' : '1z';
      if (scenario === 'before-ack') {
        h.advice({action:'discard',tile});
        assert.equal(h.api.getStatus().timing.category,'followup');
        await h.advance(h.api.getStatus().timing.targetMs + 1);
      } else await h.advance(500);
      assert.equal(game.sent.length,submitted,'the authoritative call echo cannot replace its ACK');
      await h.reply(game);
      assert.equal(h.window.__mjUnityActions.snapshot().pending,false);
      if (scenario !== 'before-ack') {
        await h.advance(1000);
        assert.equal(game.sent.length,submitted,'a confirmed call cannot execute the old planned discard without fresh advice');
        assert.equal(h.api.getStatus().phase,'computing');
        h.advice({action:'discard',tile});
      }
      const timing = h.api.getStatus().timing;
      assert.equal(timing.category,scenario === 'changed' ? 'normal' : 'followup');
      if (scenario !== 'changed') assert.ok(timing.targetMs < callDelay);
      const remaining = timing.targetMs - timing.elapsedMs;
      if (remaining > 0) {
        await h.advance(remaining - 1);
        assert.equal(game.sent.length,submitted);
        await h.advance(1);
      } else await h.advance(0);
      assert.equal(game.sent.length,submitted + 1);
      assert.equal(h.last(game).name,'.lq.FastTest.inputOperation');
      assert.equal(str(fields(h.last(game).data),3),tile,'the submitted tile must come from the new recommendation');
      await h.reply(game);
      await h.action(game,'ActionDiscardTile',3,[[1,0],[2,tile]]);
      await h.advance(1000);
      assert.equal(game.sent.length,submitted + 1);
      assert.equal(h.window.__mjUnityActions.snapshot().pending,false);
      assert.equal(h.api.getStatus().enabled,true);
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

const budgetAdvice={status:'unavailable',reason:'search_budget_exceeded',recoverable:true,
  message:'前瞻计算超过时间预算，等待下一次局面',candidates:[],best:null};
async function budgetFixture() {
  const h=await setup(3,false,2),e=h.encode,seats=[11,22,33],game=h.connect(true);
  game.send(h.frame(2,2,'.lq.FastTest.authGame',e([[1,11],[3,'budget-test-match']])));
  await h.reply(game,e([...seats.map(id=>[2,e([[1,id],[7,e([[1,20301]])]])]),
    ...seats.map(id=>[3,id]),[5,e([[1,2],[2,e([[1,12]])],[3,e([[2,22]])]])]]));
  const hand=['1p','2p','3p','4p','5p','6p','1s','2s','3s','4s','5s','6s','4z','1z'];
  const operation=e([[1,0],[2,e([[1,1]])],[2,e([[1,11]])],[4,20000],[5,5000]]);
  await h.action(game,'ActionNewRound',0,[[1,1],[2,0],[3,0],...hand.map(tile=>[4,tile]),
    ...seats.map(()=>[6,35000]),[7,operation],[13,54],[14,'1p']]);
  const state=h.window.__mjMonitor.getSnapshot().state;
  assert.equal(state.playerCount,3);assert.equal(state.match.roundCount,2);
  assert.equal(state.canAct,true);assert.deepEqual([...state.operations],[1,11]);
  h.api.setEnabled(true);
  const packet=h.packets.findLast(p=>p.kind==='turn'),key=`${packet.session}:${packet.serial}`;
  const advice=(value,adviceKey=key)=>h.api.onAdvice({adviceKey,advice:value});
  return {h,e,game,key,advice,async nextWindow() {
    await h.action(game,'ActionDiscardTile',1,[[1,0],[2,'1z'],[5,0]]);
    await h.action(game,'ActionDealTile',2,[[1,0],[2,'2z'],[3,53],[4,operation]]);
    assert.equal(h.window.__mjMonitor.getSnapshot().state.canAct,true);
  }};
}

test('Unity sanma South budget exhaustion waits and accepts fresh advice within the same live window', async () => {
  const {h,game,advice}=await budgetFixture();
  await h.advance(2000);advice(budgetAdvice);
  assert.equal(h.api.getStatus().enabled,true);
  await h.advance(3000);assert.equal(game.sent.length,1,'an exhausted search cannot invent an action');
  advice({status:'ready',best:{action:'discard',tile:'1z'}});await h.advance(3000);
  assert.equal(game.sent.length,2);assert.equal(h.last(game).name,'.lq.FastTest.inputOperation');
  assert.equal(h.str(h.fields(h.last(game).data),3),'1z');
  await h.reply(game);await h.action(game,'ActionDiscardTile',1,[[1,0],[2,'1z'],[5,0]]);
  await h.advance(1000);assert.equal(game.sent.length,2);
  assert.equal(h.api.getStatus().enabled,true);
});

test('Unity budget exhaustion survives expiry, ignores late advice, and resumes from a fresh live window', async () => {
  const {h,game,advice,nextWindow}=await budgetFixture();
  advice(budgetAdvice);await h.advance(25001);
  assert.equal(h.api.getStatus().enabled,true);assert.equal(game.sent.length,1);
  advice({status:'ready',best:{action:'discard',tile:'1z'}});await h.advance(100);
  assert.equal(game.sent.length,1,'late advice must not execute an expired operation');
  await nextWindow();advice({status:'ready',best:{action:'discard',tile:'1z'}});
  await h.advance(100);assert.equal(game.sent.length,1,'the previous advice key cannot control a new window');
  h.advice({action:'discard',tile:'2z'});await h.advance(5000);
  assert.equal(game.sent.length,2);assert.equal(h.str(h.fields(h.last(game).data),3),'2z');
  assert.equal(h.api.getStatus().enabled,true);
});

for (const expired of [false,true])
  test(`Unity native fallback after a budget result preserves autoplay ${expired?'after expiry':'before expiry'}`, async () => {
    const {h,e,game,advice,nextWindow}=await budgetFixture();
    advice(budgetAdvice);await h.advance(expired?25001:2000);
    assert.equal(h.api.getStatus().enabled,true);
    game.send(h.frame(2,8,'.lq.FastTest.inputOperation',e([[1,1],[3,'1z'],[5,1]])));
    await h.reply(game);
    assert.equal(h.api.getStatus().enabled,true,'native fallback is not a trusted manual takeover');
    advice({status:'ready',best:{action:'discard',tile:'1z'}});await h.advance(1000);
    assert.equal(game.sent.length,2,'fresh advice cannot duplicate the native input');
    await nextWindow();h.advice({action:'discard',tile:'2z'});await h.advance(5000);
    assert.equal(game.sent.length,3);assert.equal(h.str(h.fields(h.last(game).data),3),'2z');
    assert.equal(h.api.getStatus().enabled,true);
  });

for (const cancel of ['off','manual'])
  test(`Unity budget wait cannot override ${cancel} user intent`, async () => {
    const {h,game,advice,nextWindow}=await budgetFixture();
    advice(budgetAdvice);assert.equal(h.api.getStatus().enabled,true);
    if (cancel==='off') h.api.setEnabled(false);else h.manual();
    advice({status:'ready',best:{action:'discard',tile:'1z'}});await h.advance(25001);
    await nextWindow();h.advice({action:'discard',tile:'2z'});await h.advance(5000);
    assert.equal(h.api.getStatus().enabled,false);assert.equal(game.sent.length,1);
  });

for (const invalid of [
  {status:'unavailable',reason:'invalid_state',recoverable:true,message:'牌局状态无法可靠计算',candidates:[],best:null},
  {status:'ready',best:{action:'discard',tile:'9m'}},
]) test(`Unity actual invalid advice still pauses: ${invalid.status}`, async () => {
  const {h,game,advice}=await budgetFixture();
  advice(invalid);await h.advance(5000);
  assert.equal(h.api.getStatus().enabled,false);assert.equal(game.sent.length,1);
});

test('whole injected stack carries one uncertain operation through controlled page recovery without resending', async()=>{
  const {h,e,auth,opening,operation,old,previous}=await reconnectFixture(true);
  h.api.setPlayerCount(3);h.api.setRoundCount(2);
  old.readyState=3;old.dispatchEvent(new Event('close'));await h.advance(0);
  const bridge=h.window.__mjRecovery, observed=bridge.snapshot();
  assert.equal(observed.stalled,true);
  for(let i=0;i<6;i++) await h.advance(10000);
  assert.equal(bridge.snapshot().progress,observed.progress,'page heartbeats cannot renew the recovery window');
  const prepared=bridge.prepare(observed.session,observed.revision,'controlled-navigation');
  assert.equal(prepared.prepared,true);
  assert.deepEqual(JSON.parse(JSON.stringify(prepared.checkpoint.actions.submitted)),
    [11,'reconnect-test-match',0,4,0,0,0,0]);
  assert.equal(Object.hasOwn(prepared.checkpoint,'hand'),false);
  const fresh=await setup(4,false,1,true), next=fresh.window.__mjRecovery;
  assert.equal(next.snapshot().revision,0);assert.equal(next.snapshot().enabled,false);
  const restored=next.restore(JSON.parse(JSON.stringify(prepared.checkpoint)),next.snapshot().session,0,'controlled-navigation');
  assert.equal(restored.restored,true);assert.equal(fresh.api.getStatus().playerCount,3);
  assert.equal(fresh.api.getStatus().roundCount,2);
  const game=fresh.connect(true);
  game.send(fresh.frame(2,2,'.lq.FastTest.authGame',e([[1,11],[3,'reconnect-test-match']])));
  await fresh.reply(game,auth);
  game.send(fresh.frame(2,3,'.lq.FastTest.syncGame'));
  await fresh.reply(game,e([[3,1],[4,e([[2,e([[1,0],[2,'ActionNewRound'],[3,e(opening)]])]])]]));
  assert.equal(fresh.window.__mjMonitor.getSnapshot().state.handComplete,true);
  assert.equal(fresh.window.__mjMonitor.getSnapshot().state.historyComplete,false,'replay still needs a contiguous live boundary');
  assert.equal(fresh.window.__mjMonitor.getSnapshot().state.canAct,false);
  fresh.api.onAdvice({adviceKey:`${previous.session}:${previous.serial}`,advice:{status:'ready',best:{action:'discard',tile:'1z'}}});
  await fresh.advance(3000);assert.equal(game.sent.length,2);
  assert.equal(fresh.api.getStatus().enabled,true);
  await fresh.action(game,'ActionDiscardTile',1,[[1,0],[2,'1z']]);
  await fresh.action(game,'ActionDealTile',2,[[1,0],[2,'2z'],[3,68],[4,operation]]);
  assert.equal(fresh.window.__mjMonitor.getSnapshot().state.historyComplete,true);
  await fresh.advance(1000);assert.equal(game.sent.length,2,'a current legal window still requires new advice');
  fresh.advice({action:'discard',tile:'2z'});await fresh.advance(5000);
  assert.equal(game.sent.length,3);assert.equal(fresh.last(game).name,'.lq.FastTest.inputOperation');
  assert.equal(fresh.str(fresh.fields(fresh.last(game).data),3),'2z');
  await fresh.reply(game);await fresh.action(game,'ActionDiscardTile',3,[[1,0],[2,'2z'],[5,1]]);
  await fresh.advance(1000);assert.equal(game.sent.length,3);assert.equal(next.snapshot().stalled,false);
  assert.ok(fresh.packets.some(packet=>packet.kind==='automation_intent'&&packet.source==='restore'));
  assert.ok(h.packets.some(packet=>packet.kind==='recovery_diagnostic'&&packet.phase==='socket-close'));
});

test('whole injected stack suppresses an old round confirmation even after same-round replay on a new page',async()=>{
  const {h,e,auth,opening,old}=await reconnectFixture();
  await h.action(old,'ActionDiscardTile',1,[[1,0],[2,'1z']]);
  await h.action(old,'ActionNoTile',2,[]);await h.advance(100);await h.advance(3000);
  assert.equal(h.last(old).name,'.lq.FastTest.confirmNewRound');
  old.readyState=3;old.dispatchEvent(new Event('close'));await h.advance(0);
  const state=h.window.__mjRecovery.snapshot();
  const prepared=h.window.__mjRecovery.prepare(state.session,state.revision,'round-navigation');
  assert.equal(prepared.prepared,true);
  const fresh=await setup(4,false,1,true), bridge=fresh.window.__mjRecovery;
  assert.equal(bridge.restore(JSON.parse(JSON.stringify(prepared.checkpoint)),bridge.snapshot().session,0,'round-navigation').restored,true);
  const game=fresh.connect(true);game.send(fresh.frame(2,2,'.lq.FastTest.authGame',e([[1,11],[3,'reconnect-test-match']])));
  await fresh.reply(game,auth);
  // A same-round ActionNewRound cannot erase the carried terminal identity.
  await fresh.action(game,'ActionNewRound',0,opening);
  await fresh.action(game,'ActionDiscardTile',1,[[1,0],[2,'1z']]);
  await fresh.action(game,'ActionNoTile',2,[]);
  await fresh.advance(100);await fresh.advance(3000);
  assert.equal(game.sent.length,1);assert.equal(bridge.snapshot().stalled,true);
  const following=opening.map(([field,value])=>[field,field===3?1:value]);
  await fresh.action(game,'ActionNewRound',0,following);
  await fresh.action(game,'ActionDiscardTile',1,[[1,0],[2,'1z']]);
  await fresh.action(game,'ActionNoTile',2,[]);await fresh.advance(100);await fresh.advance(3000);
  assert.equal(game.sent.length,2);assert.equal(fresh.last(game).name,'.lq.FastTest.confirmNewRound');
});

test('whole injected stack cancels an uncertain old queue after page recovery before creating a new queue',async()=>{
  const h=await setup(3,false,2), e=h.encode;
  h.api.setEnabled(true);await h.advance(3000);await h.replyAccount();
  await h.advance(100);await h.advance(3000);
  assert.equal(h.last(h.lobby).name,'.lq.Lobby.startUnifiedMatch');
  assert.equal(h.str(h.fields(h.last(h.lobby).data),1),'1:22');
  h.lobby.readyState=3;h.lobby.dispatchEvent(new Event('close'));await h.advance(0);
  const value=h.window.__mjRecovery.snapshot();
  const prepared=h.window.__mjRecovery.prepare(value.session,value.revision,'queue-navigation');
  assert.equal(prepared.prepared,true);assert.equal(prepared.checkpoint.lobby.owned.sid,'1:22');
  const fresh=await setup(4,false,1,true), bridge=fresh.window.__mjRecovery;
  assert.equal(bridge.restore(JSON.parse(JSON.stringify(prepared.checkpoint)),bridge.snapshot().session,0,'queue-navigation').restored,true);
  assert.equal(fresh.last(fresh.lobby).name,'.lq.Lobby.cancelUnifiedMatch');
  assert.equal(fresh.str(fresh.fields(fresh.last(fresh.lobby).data),1),'1:22');
  await fresh.advance(5000);assert.equal(fresh.lobby.sent.length,2,'no refresh or second start before cancellation ACK');
  await fresh.reply(fresh.lobby);await fresh.advance(100);await fresh.advance(3000);
  assert.equal(fresh.last(fresh.lobby).name,'.lq.Lobby.fetchAccountInfo');
  await fresh.replyAccount();await fresh.advance(100);await fresh.advance(3000);
  assert.equal(fresh.last(fresh.lobby).name,'.lq.Lobby.startUnifiedMatch');
  assert.equal(fresh.str(fresh.fields(fresh.last(fresh.lobby).data),1),'1:22');
  assert.equal(fresh.lobby.sent.filter(bytes=>core.envelope(bytes).name==='.lq.Lobby.startUnifiedMatch').length,1);
  await fresh.reply(fresh.lobby);
});
