const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const core = require('../src/core.cjs');
const {formatTurn} = require('../legacy/terminal.cjs');
const sampleFolder = path.join(__dirname, 'fixtures/recording');
const frames = JSON.parse(fs.readFileSync(path.join(sampleFolder, 'capture.json')));
const expected = JSON.parse(fs.readFileSync(path.join(sampleFolder, 'decoded-events.json')));
const decoded = frames.map(f => core.envelope(new Uint8Array(Buffer.from(f.hex, 'hex'))))
  .filter(e => e.kind === 1 && e.name === '.lq.ActionPrototype').map(e => core.action(e.data));
const vi = n => {const a = []; n = BigInt(n); do {const b = Number(n & 127n); n >>= 7n; a.push(b | (n ? 128 : 0));} while(n); return a;};
const num = (id, n) => [...vi(id * 8), ...vi(n)];
const bytes = (id, a) => [...vi(id * 8 + 2), ...vi(a.length), ...a];
const str = (id, s) => bytes(id, Buffer.from(s));
const actionFrame = (name, step, data = []) => {
  const keys = [132, 94, 78, 66, 57, 162, 31, 96, 28];
  const encrypted = data.map((b, i) => b ^ (((23 ^ data.length) + 5 * i + keys[i % 9]) & 255));
  return new Uint8Array([1, ...str(1, '.lq.ActionPrototype'),
    ...bytes(2, [...num(1, step), ...str(2, name), ...bytes(3, encrypted)])]);
};

test('48 live actions match independently verified tile, seat, steps and visibility', () => {
  assert.equal(decoded.length, 48);
  decoded.forEach((e, i) => {
    assert.equal(e.name, expected[i].action); assert.equal(e.step, expected[i].step);
    assert.equal(e.seat, expected[i].seat);
    if ('tile' in expected[i]) assert.equal(e.tile, expected[i].tile);
    if (e.tiles) {assert.deepEqual(e.tiles, expected[i].tiles); assert.deepEqual(e.froms, expected[i].froms);}
  });
  assert.deepEqual(decoded.filter(e => e.canDiscard).map(e => e.step), [66,72,78,84,90,98,104]);
  assert.equal(decoded.filter(e => e.name === 'ActionDealTile' && !e.tile).length, 16);
});

test('mid-round sample never invents a complete hand, and called tile is counted once', () => {
  const s = core.emptyState(); decoded.forEach(e => core.apply(s, e));
  assert.equal(s.selfSeat, 1); assert.equal(s.handComplete, false); assert.equal(s.historyComplete, false);
  assert.equal(s.rivers.flat().length, 23); assert.equal(s.north[0], 1);
  assert.deepEqual(s.melds[1][0].tiles, ['6p','6p','6p']);
  assert.equal(s.rivers[0].find(x => x.tile === '6p').called, true);
  assert.equal(s.rivers[0].at(-1).called, true);
});

test('new-round baseline tracks own tiles, ignores duplicate, invalidates on gap', () => {
  const s = core.emptyState();
  core.apply(s, {name:'ActionNewRound', step:0, selfSeat:1, hand:['1p','2p','6p','6p'], scores:[35000,35000,35000], doras:['7p'], left:50});
  core.apply(s, {name:'ActionDealTile', step:1, seat:1, tile:'3p', left:49});
  core.apply(s, {name:'ActionDiscardTile', step:2, seat:1, tile:'1p'});
  assert.deepEqual(s.hand, ['2p','6p','6p','3p']);
  assert.equal(core.apply(s, {name:'ActionDiscardTile', step:2, seat:1, tile:'1p'}), false);
  core.apply(s, {name:'ActionDiscardTile', step:3, seat:0, tile:'6p'});
  core.apply(s, {name:'ActionChiPengGang', step:4, seat:1, type:1, tiles:['6p','6p','6p'], froms:[1,1,0]});
  assert.deepEqual(s.hand, ['2p','3p']); assert.equal(s.handComplete, true);
  core.apply(s, {name:'ActionDealTile', step:6, seat:2, tile:null, left:48});
  assert.equal(s.handComplete, false); assert.match(s.warning, /缺口/);
});

test('duplicate deal cannot rewind an active round, while a completed or different round can start', () => {
  const s = core.emptyState();
  const deal = {name:'ActionNewRound', step:0, selfSeat:1, hand:['1p','2p'],
    scores:[35000,35000,35000], doras:['7p'], left:50, chang:0, ju:1, ben:0};
  assert.equal(core.apply(s, deal), true);
  assert.equal(core.apply(s, deal), false);
  core.apply(s, {name:'ActionDiscardTile', step:1, seat:1, tile:'1p'});
  assert.equal(core.apply(s, deal), false);
  assert.deepEqual(s.hand, ['2p']);
  assert.equal(s.rivers[1].length, 1);
  assert.equal(core.apply(s, {...deal, ben:1}), true);
  core.apply(s, {name:'ActionHule', step:1, matchEnd:false});
  assert.equal(core.apply(s, {...deal, ben:1}), true);
  assert.equal(core.apply(core.emptyState(), deal), true);
});

test('restore action uses plain Protobuf, not live XOR', () => {
  const rawAction = [...num(1, 4), ...str(2, 'ActionDealTile'), ...bytes(3, [...num(1, 1), ...str(2, '7s'), ...num(3, 20)])];
  const response = new Uint8Array([...num(3,4), ...bytes(4, bytes(2, rawAction))]);
  const r = core.restore(response);
  assert.equal(r.actions[0].tile, '7s'); assert.equal(r.actions[0].seat, 1);
});

test('round end is not confused with end of whole match', () => {
  const s = core.emptyState();
  core.apply(s, {name:'ActionHule', step:10, matchEnd:false}); assert.equal(s.phase, 'between_rounds');
  core.apply(s, {name:'ActionHule', step:11, matchEnd:true}); assert.equal(s.phase, 'ended');
});

test('terminal shows missing baseline clearly', () => {
  const s = core.emptyState(); decoded.slice(0,4).forEach(e => core.apply(s,e));
  const out = formatTurn({time:'2026-10-04T02:29:24Z', step:66, turnNumber:1, trigger:'ActionDealTile', state:s, statistics:{received:4, errors:0}});
  assert.match(out, /本人完整手牌：尚未取得/); assert.match(out, /南/); assert.match(out, /历史不完整/);
});

test('browser attachment forwards game sends unchanged, publishes all 48 actions, stops cleanly', async () => {
  const sent = [], posts = [], intervals = [];
  class Socket extends EventTarget {
    constructor(url) {super(); this.url = url; this.readyState = 1;}
    send(data) {sent.push(data); return 'original-result';}
  }
  const game = new Socket('wss://route-2.maj-soul.com/game-gateway-zone');
  const lobby = new Socket('wss://route-2.maj-soul.com/gateway');
  const window = new EventTarget();
  const button = {style:{}, remove(){this.removed = true;}};
  let channel;
  const dispatch = data => {
    const event = new Event('message');
    Object.assign(event, {origin:'http://127.0.0.1:17361', source:relay, data:{channel, ...data}});
    window.dispatchEvent(event);
  };
  const relay = {closed:false, postMessage(packet, origin) {
    assert.equal(origin, 'http://127.0.0.1:17361');
    posts.push(...packet.events);
    queueMicrotask(() => dispatch({type:'mj-relay-ack', batchId:packet.batchId}));
  }};
  window.WebSocket = Socket;
  window.open = url => {
    channel = new URL(url).hash.slice(1);
    queueMicrotask(() => dispatch({type:'mj-relay-ready'}));
    return relay;
  };
  const sandbox = {window, location:{hostname:'game.maj-soul.com'}, TextDecoder, Uint8Array, ArrayBuffer, Blob,
    document:{createElement:()=>button, body:{appendChild(){}}},
    URL, AbortSignal, setInterval:fn => {intervals.push(fn); return fn;}, clearInterval:fn => intervals.splice(intervals.indexOf(fn),1),
    console:{warn(){}, log(){}}, queryInstances:() => [game,lobby]};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../legacy/安装终端监听.js'),'utf8'), sandbox);
  window.__mjMonitor.openRelay();
  assert.equal(window.__mjMonitor.getSnapshot().gameSockets, 1);
  const untouched = new Uint8Array([1,2,3]);
  assert.equal(lobby.send(untouched), 'original-result'); assert.equal(sent[0], untouched);
  const request = new Uint8Array([2,250,255,...str(1,'.lq.FastTest.syncGame'),...bytes(2,[])]);
  assert.equal(game.send(request), 'original-result'); assert.equal(sent[1], request);
  for (const frame of frames) {
    const event = new Event('message'); event.data = Uint8Array.from(Buffer.from(frame.hex,'hex')).buffer; game.dispatchEvent(event);
  }
  await new Promise(setImmediate);
  for (const fn of [...intervals]) fn();
  await new Promise(setImmediate);
  assert.equal(window.__mjMonitor.getSnapshot().turns,48);
  assert.deepEqual(posts.filter(e => e.kind==='turn').map(e => e.step), decoded.map(e => e.step));
  assert.equal(window.__mjMonitor.getSnapshot().errors,0);
  // New game sockets created after installation are caught immediately.
  const later = new window.WebSocket('wss://route-4.maj-soul.com/game-gateway-zone');
  assert.equal(window.__mjMonitor.getSnapshot().gameSockets,2);
  window.__mjMonitor.uninstall();
  assert.equal(window.WebSocket,Socket); assert.equal(game.send,Socket.prototype.send);
  assert.equal(later.send,Socket.prototype.send); assert.equal(intervals.length,0);
  assert.equal(button.removed, true);
});

test('relay validates sender, retries failed delivery, acknowledges duplicate without reposting', async () => {
  let listener, attempts = 0;
  const messages = [], status = {}, opener = {postMessage:message => messages.push(message)};
  const sandbox = {window:{opener, addEventListener:(name, fn)=>{listener=fn;}},
    location:{hash:'#test-channel'}, document:{getElementById:()=>status}, setInterval(){}, AbortSignal,
    fetch:async () => {attempts++; return {ok:attempts > 1, status:503};}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../legacy/relay.js'),'utf8'), sandbox);
  const event = {origin:'https://game.maj-soul.com', source:opener,
    data:{type:'mj-relay-batch',channel:'test-channel',batchId:'one',events:[{kind:'turn'}]}};
  await listener({...event, origin:'https://other.example'});
  await listener({...event, source:{}});
  await listener({...event, data:{...event.data, channel:'wrong'}});
  assert.equal(attempts, 0);
  await listener(event);
  assert.equal(messages.filter(m=>m.type==='mj-relay-ack').length, 0);
  await listener(event);
  await listener(event);
  assert.equal(attempts, 2);
  assert.equal(messages.filter(m=>m.type==='mj-relay-ack').length, 2);
  assert.match(status.textContent, /1 次/);
});

test('native bridge publishes every action and one initial deal without requiring own discard operation', async () => {
  const posts = [], timers = new Set(), sent = [];
  class Socket extends EventTarget {
    constructor(url) {super(); this.url = url; this.readyState = 1;}
    send(data) {sent.push(data); return 'ok';}
  }
  const window = {WebSocket:Socket, webkit:{messageHandlers:{mjStatistics:{postMessage:raw=>posts.push(JSON.parse(raw))}}}};
  const sandbox = {window, location:{hostname:'game.maj-soul.com'}, TextDecoder, Uint8Array, ArrayBuffer, Blob, URL,
    setInterval:fn=>{timers.add(fn);return fn;}, clearInterval:fn=>timers.delete(fn), console:{log(){}}};
  const code = fs.readFileSync(path.join(__dirname,'../legacy/安装终端监听.js'),'utf8');
  const installed = vm.runInNewContext(code, sandbox);
  assert.equal(installed.transport, 'webkit-native-message');
  assert.equal(vm.runInNewContext(code, sandbox).installed, false);
  const game = new window.WebSocket('wss://route-2.maj-soul.com/game-gateway-zone');
  const untouched = new Uint8Array([2,1,0,...str(1,'.lq.FastTest.heartbeat'),...bytes(2,[])]);
  assert.equal(game.send(untouched),'ok'); assert.equal(sent[0],untouched);
  for (const frame of frames) {
    const event = new Event('message'); event.data = Uint8Array.from(Buffer.from(frame.hex,'hex')).buffer; game.dispatchEvent(event);
  }
  await new Promise(setImmediate);
  assert.deepEqual(posts.filter(e=>e.kind==='turn').map(e=>e.step), decoded.map(e=>e.step));
  assert.deepEqual(posts.filter(e=>e.kind==='turn').map(e=>e.actorSeat), decoded.map(e=>e.seat));
  const ownDiscard = bytes(6, [...num(1,1), ...bytes(2,num(1,1))]);
  const fixtures = [
    actionFrame('ActionNewRound', 0, [...num(2,1), ...str(4,'1p'), ...str(4,'2p'), ...str(4,'6p'), ...str(4,'6p'),
      ...num(6,35000), ...num(6,35000), ...num(6,35000), ...num(13,50), ...str(14,'7p')]),
    actionFrame('ActionDealTile', 1, [...num(1,0), ...num(3,49)]),
    actionFrame('ActionDiscardTile', 2, [...num(1,0), ...str(2,'6p')]),
    actionFrame('ActionChiPengGang', 3, [...num(1,1), ...num(2,1), ...str(3,'6p'), ...str(3,'6p'), ...str(3,'6p'),
      ...num(4,1), ...num(4,1), ...num(4,0), ...ownDiscard]),
    actionFrame('ActionDiscardTile', 4, [...num(1,1), ...str(2,'1p')]),
    actionFrame('ActionAnGangAddGang', 5, [...num(1,2), ...num(2,3), ...str(3,'9s')]),
    actionFrame('ActionBaBei', 6, [...num(1,0)]),
    actionFrame('ActionHule', 7)
  ];
  for (const frame of fixtures) {
    // Duplicate delivery must not publish a second snapshot or apply the action twice.
    for (let repeat=0; repeat<2; repeat++) {
      const event = new Event('message'); event.data = frame.buffer; game.dispatchEvent(event);
    }
  }
  await new Promise(setImmediate);
  const updates = posts.filter(e=>e.kind==='turn').slice(decoded.length);
  assert.deepEqual(updates.map(e=>e.step), [0,1,2,3,4,5,6,7]);
  assert.equal(updates[0].trigger,'ActionNewRound');
  assert.equal(updates[0].actorSeat,undefined);
  assert.equal(updates[3].actorSeat,1);
  assert.deepEqual(updates[0].state.hand,['1p','2p','6p','6p']);
  assert.deepEqual(updates[3].state.melds[1][0].tiles,['6p','6p','6p']);
  assert.equal(updates[5].state.melds[2][0].type,3);
  assert.equal(updates[6].state.north[0],1);
  assert.equal(updates[7].state.phase,'between_rounds');
  assert.equal(window.__mjMonitor.getSnapshot().errors,0);
  assert.equal(window.__mjMonitor.getSnapshot().pending,0);
  game.dispatchEvent(new Event('close'));
  assert.equal(window.__mjMonitor.getSnapshot().state.phase,'disconnected');
  window.__mjMonitor.uninstall();
  assert.equal(window.WebSocket, Socket); assert.equal(game.send,Socket.prototype.send); assert.equal(timers.size,0);
});

test('whole-match end resets all live statistics once and next match starts at update one', async t => {
  for (const ending of ['ActionHule','ActionNoTile','ActionLiuJu','notification','restore']) {
    await t.test(ending, async () => {
      const posts = [], timers = new Set(), sent = [];
      class Socket extends EventTarget {
        constructor(url) {super(); this.url=url; this.readyState=1;}
        send(data) {sent.push(data);}
      }
      const window = {WebSocket:Socket, webkit:{messageHandlers:{mjStatistics:{postMessage:raw=>posts.push(JSON.parse(raw))}}}};
      const sandbox = {window, location:{hostname:'game.maj-soul.com'}, TextDecoder, Uint8Array, ArrayBuffer, Blob, URL,
        setInterval:fn=>{timers.add(fn);return fn;}, clearInterval:fn=>timers.delete(fn), console:{log(){}}};
      vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../legacy/安装终端监听.js'),'utf8'),sandbox);
      const game = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-zone');
      const feed = async frame => {
        const event = new Event('message'); event.data=frame.buffer; game.dispatchEvent(event);
        await new Promise(setImmediate);
      };
      const deal = ju => actionFrame('ActionNewRound',0,[...num(2,ju), ...str(4,'1p'), ...str(4,'2p'), ...str(4,'4z'),
        ...num(6,35000), ...num(6,35000), ...num(6,35000), ...bytes(7,num(1,1)), ...num(13,50)]);
      await feed(deal(0));
      await feed(actionFrame('ActionDiscardTile',1,[...num(1,1),...str(2,'1p')]));
      await feed(actionFrame('ActionBaBei',2,num(1,1)));
      await feed(new Uint8Array([1,0]));
      assert.equal(window.__mjMonitor.getSnapshot().errors,1);
      await feed(actionFrame('ActionHule',3));
      const between = window.__mjMonitor.getSnapshot();
      assert.equal(between.state.phase,'between_rounds');
      assert.equal(between.state.rivers[1].length,1);
      assert.equal(between.state.north[1],1);
      assert.equal(posts.filter(p=>p.reset).length,0);
      await feed(deal(1));
      const updatesBeforeEnd = posts.filter(p=>p.kind==='turn').length;
      const end = async () => {
        if (ending === 'notification') {
          await feed(new Uint8Array([1,...str(1,'.lq.NotifyGameEndResult'),...bytes(2,[])]));
        } else if (ending === 'restore') {
          game.send(new Uint8Array([2,42,0,...str(1,'.lq.FastTest.syncGame'),...bytes(2,[])]));
          await feed(new Uint8Array([3,42,0,...bytes(2,num(2,1))]));
        } else {
          const payload = ending === 'ActionHule' ? bytes(6,[]) : ending === 'ActionNoTile' ? num(4,1) : bytes(2,[]);
          await feed(actionFrame(ending,1,payload));
        }
      };
      await end();
      const cleared = window.__mjMonitor.getSnapshot();
      assert.deepEqual(JSON.parse(JSON.stringify(cleared.state)),{...core.emptyState(),phase:'ended',warning:''});
      assert.equal(cleared.turns,0); assert.equal(cleared.received,0); assert.equal(cleared.errors,0);
      assert.equal(cleared.gameSockets,1);
      assert.equal(posts.at(-1).reset,true);
      assert.equal(posts.at(-1).message,'对局已结束，统计已重置，等待下一场');
      assert.equal(posts.filter(p=>p.kind==='turn').length, updatesBeforeEnd + (ending.startsWith('Action') ? 1 : 0));
      const countAfterEnd = posts.length;
      await end();
      assert.equal(posts.length,countAfterEnd);
      assert.equal(posts.filter(p=>p.reset).length,1);
      await feed(deal(0));
      assert.equal(posts.at(-1).kind,'turn');
      assert.equal(posts.at(-1).trigger,'ActionNewRound');
      assert.equal(posts.at(-1).turnNumber,1);
      assert.equal(posts.at(-1).statistics.errors,0);
      assert.equal(window.__mjMonitor.getSnapshot().state.phase,'playing');
      window.__mjMonitor.uninstall();
      assert.equal(timers.size,0);
      assert.equal(sent.length,ending === 'restore' ? 2 : 0);
    });
  }
});
