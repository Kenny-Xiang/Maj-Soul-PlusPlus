// Whole injected stack, real wire encoding/decoding and synthetic server responses.
// No Laya globals, game account, or external connection is used.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const core = require('../src/core.cjs');
const read = name => fs.readFileSync(path.join(__dirname, '../src', name), 'utf8');
async function setup(players = 4, early = false, roundCount = 1) {
  let time = 0, timerId = 0;
  const timers = new Map(), intervals = new Map(), listeners = new Map(), packets = [], statuses = [];
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
    clearInterval:id => intervals.delete(id), addEventListener:(type,fn)=>listeners.set(type,fn),
    removeEventListener:type=>listeners.delete(type)});
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
  const api = window.__mjAutoplay; api.setPlayerCount(players); api.setRoundCount(roundCount);
  return {window, api, lobby, packets, statuses, advance, feed, frame, reply, replyAccount, action, connect, encode, first, fields, str, account,
    manual() {listeners.get('pointerdown')?.({isTrusted:true,composedPath:()=>[]});},
    last(socket) {return core.envelope(socket.sent.at(-1));},
    advice(best) {const packet = packets.findLast(p => p.kind === 'turn');
      api.onAdvice({adviceKey:`${packet.session}:${packet.serial}`, advice:{status:'ready',best}});}};
}

for (const players of [4, 3]) for (const roundCount of [1, 2]) for (const switchQueued of [false, true])
  test(`Unity ${players}-player ${roundCount === 1 ? 'East' : 'South'} flow matches, discards, confirms a round and rematches ${switchQueued ? 'in the other wind after changing a submitted queue' : 'in the same wind'} without Laya globals`, async () => {
  const h = await setup(players, false, roundCount), {encode:e, first, fields, str} = h;
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

for (const fault of ['step gap','invalid first deal'])
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
      await h.action(game,'ActionDiscardTile',3,[[1,1],[2,'7z']]);
    }
    assert.equal(h.api.getStatus().enabled,false);
    assert.match(h.api.getStatus().message,/基线/);
    const sent = game.sent.length;
    await h.advance(5000); assert.equal(game.sent.length,sent);
    await h.action(game,'ActionNewRound',4,deal(hand));
    assert.equal(h.api.getStatus().enabled,false, 'a later valid deal cannot override a safety pause');
  });

async function reconnectFixture(inFlight = false) {
  const h=await setup(),e=h.encode,seats=[11,22,33,44];
  const auth=e([...seats.map(id=>[2,e([[1,id],[5,e([[1,10301]])]])]),
    ...seats.map(id=>[3,id]),[5,e([[1,2],[2,e([[1,1]])],[3,e([[2,8]])]])]]);
  const hand=['1p','2p','3p','4p','5p','6p','1s','2s','3s','4s','5s','6s','7z','1z'];
  const operation=e([[1,0],[2,e([[1,1]])],[4,20000],[5,5000]]);
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
  await h.reply(game);await h.action(game,'ActionDiscardTile',1,[[1,0],[2,'1z'],[5,1]]);
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
