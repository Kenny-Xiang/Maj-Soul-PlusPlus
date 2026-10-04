const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const core = require('../src/core.cjs');
const collectorCode = `(function(){'use strict';const core=(()=>{const module={exports:{}};
${fs.readFileSync(path.join(__dirname, '../src/core.cjs'), 'utf8')}
return module.exports;})();
${fs.readFileSync(path.join(__dirname, '../src/browser.js'), 'utf8')}
})();`;
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

test('normal and double riichi are confirmed per player and reset on the next round', () => {
  for (const flag of [3, 9]) {
    const s = core.emptyState();
    assert.deepEqual(s.riichi, [null,null,null,null]);
    const deal = {name:'ActionNewRound', step:0, selfSeat:0, hand:['1p'],
      scores:[25000,25000,25000,25000], doras:['7p'], left:60, chang:0, ju:0, ben:0};
    core.apply(s, deal);
    const discard = core.action(core.envelope(actionFrame('ActionDiscardTile',1,
      [...num(1,1), ...str(2,'3p'), ...num(flag,1)])).data);
    assert.equal(discard.riichi, true);
    core.apply(s, discard);
    assert.equal(s.rivers[1][0].riichi, true);
    assert.deepEqual(s.riichi, [false,false,false,false]);
    const draw = core.action(core.envelope(actionFrame('ActionDealTile',2,
      [...num(1,2), ...num(3,59), ...bytes(5,[...num(1,1), ...num(2,24000)])])).data);
    core.apply(s, draw);
    assert.deepEqual(s.riichi, [false,true,false,false]);
    assert.equal(s.scores[1],24000);
    assert.equal(core.apply(s, draw),false);
    assert.equal(core.apply(s, deal),false);
    assert.equal(s.riichi[1],true);
    core.apply(s, {name:'ActionDiscardTile',step:3,seat:2,tile:'5p'});
    core.apply(s, {name:'ActionHule',step:4,matchEnd:false});
    assert.equal(s.riichi[1],true);
    core.apply(s, {...deal,ju:1});
    assert.deepEqual(s.riichi, [false,false,false,false]);
  }
});

test('failed or interrupted declarations do not become confirmed riichi', () => {
  for (const outcome of ['failed','ron']) {
    const s = core.emptyState();
    core.apply(s, {name:'ActionNewRound',step:0,hand:['1p'],scores:[35000,35000,35000],doras:[],left:50});
    core.apply(s, {name:'ActionDiscardTile',step:1,seat:1,tile:'3p',riichi:true});
    const frame = outcome === 'failed' ? actionFrame('ActionDealTile',2,
      [...num(1,2), ...num(3,49), ...bytes(5,[...num(1,1), ...num(2,35000), ...num(4,1)])]) :
      actionFrame('ActionHule',2);
    core.apply(s, core.action(core.envelope(frame).data));
    assert.deepEqual(s.riichi, [false,false,false,false]);
    assert.equal(s.scores[1],35000);
  }
});

test('riichi confirmations on calls and abortive draws are recorded without a declaration baseline', () => {
  const confirmation = bytes(5,[...num(1,1), ...num(2,24000)]);
  for (const frame of [
    actionFrame('ActionChiPengGang',42,[...num(1,2), ...num(2,1),
      ...str(3,'3p'), ...str(3,'3p'), ...str(3,'3p'), ...num(4,2), ...num(4,2), ...num(4,1), ...confirmation]),
    actionFrame('ActionLiuJu',42,[...num(1,4), ...confirmation])
  ]) {
    const s = core.emptyState();
    core.apply(s, core.action(core.envelope(frame).data));
    assert.deepEqual(s.riichi, [null,true,null,null]);
  }
});

test('restored actions recover confirmed riichi while an unverified snapshot leaves it unknown', () => {
  const raw = (name, step, data) => bytes(2,[...num(1,step), ...str(2,name), ...bytes(3,data)]);
  const response = new Uint8Array([...num(3,2), ...bytes(4,[
    ...raw('ActionNewRound',0,[...str(4,'1p'), ...num(6,35000), ...num(6,35000), ...num(6,35000)]),
    ...raw('ActionDiscardTile',1,[...num(1,1), ...str(2,'3p'), ...num(3,1)]),
    ...raw('ActionDealTile',2,[...num(1,2), ...num(3,49), ...bytes(5,[...num(1,1), ...num(2,34000)])])
  ])]);
  const s = core.emptyState();
  core.applyRestore(s, core.restore(response));
  assert.deepEqual(s.riichi, [false,true,false,false]);
  assert.equal(s.historyComplete,false);
  core.applyRestore(s, {actions:[],step:2,snapshot:{selfSeat:0,hand:['1p'],doras:[],left:49,
    chang:0,ju:0,ben:0,players:[{score:35000,discards:[],melds:[]}]}});
  assert.deepEqual(s.riichi, [null,null,null,null]);
});

test('collector requires the native bridge and leaves unsupported pages untouched', () => {
  class Socket {}
  const window = {WebSocket:Socket};
  const missing = vm.runInNewContext(collectorCode, {window, location:{hostname:'game.maj-soul.com'}, TextDecoder});
  assert.equal(missing.installed, false);
  assert.equal(missing.reason, 'native bridge unavailable');
  assert.equal(window.WebSocket, Socket);
  assert.equal(window.__mjMonitor, undefined);
  const unrelated = vm.runInNewContext(collectorCode, {window, location:{hostname:'other.example'}, TextDecoder});
  assert.equal(unrelated.installed, false);
  assert.equal(unrelated.reason, 'not game page');
});

test('native listener preserves socket sends and fully detaches on uninstall', async () => {
  const posts = [], sent = [], timers = new Set();
  class Socket extends EventTarget {
    constructor(url) {super(); this.url = url; this.readyState = 1;}
    send(...args) {sent.push({socket:this,args}); return 'original-result';}
  }
  const window = {WebSocket:Socket, webkit:{messageHandlers:{mjStatistics:{postMessage:raw=>posts.push(JSON.parse(raw))}}}};
  const sandbox = {window, location:{hostname:'game.maj-soul.com'}, TextDecoder, Uint8Array, ArrayBuffer, Blob, URL,
    setInterval:fn=>{timers.add(fn);return fn;}, clearInterval:fn=>timers.delete(fn), console:{log(){}}};
  vm.runInNewContext(collectorCode, sandbox);
  const game = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-zone');
  const lobby = new window.WebSocket('wss://sample.maj-soul.com/gateway');
  const data = new Uint8Array([2,9,0,...str(1,'.lq.FastTest.heartbeat'),...bytes(2,[])]);
  assert.equal(game.send(data, 'extra'), 'original-result');
  assert.equal(sent[0].socket, game);
  assert.equal(sent[0].args[0], data);
  assert.equal(sent[0].args[1], 'extra');
  assert.equal(lobby.send, Socket.prototype.send);
  assert.equal(window.__mjMonitor.getSnapshot().gameSockets, 1);
  const later = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-next');
  assert.equal(window.__mjMonitor.getSnapshot().gameSockets, 2);
  window.__mjMonitor.uninstall();
  assert.equal(window.WebSocket, Socket);
  assert.equal(game.send, Socket.prototype.send);
  assert.equal(later.send, Socket.prototype.send);
  assert.equal(timers.size, 0);
  const before = posts.length;
  game.dispatchEvent(new MessageEvent('message', {data:Uint8Array.from(Buffer.from(frames[0].hex,'hex')).buffer}));
  await new Promise(setImmediate);
  assert.equal(posts.length, before);
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
  const code = collectorCode;
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
      vm.runInNewContext(collectorCode,sandbox);
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
      await feed(actionFrame('ActionDealTile',1,[...num(1,2), ...num(3,49),
        ...bytes(5,[...num(1,0), ...num(2,34000)])]));
      assert.equal(window.__mjMonitor.getSnapshot().state.riichi[0],true);
      const updatesBeforeEnd = posts.filter(p=>p.kind==='turn').length;
      const end = async () => {
        if (ending === 'notification') {
          await feed(new Uint8Array([1,...str(1,'.lq.NotifyGameEndResult'),...bytes(2,[])]));
        } else if (ending === 'restore') {
          game.send(new Uint8Array([2,42,0,...str(1,'.lq.FastTest.syncGame'),...bytes(2,[])]));
          await feed(new Uint8Array([3,42,0,...bytes(2,num(2,1))]));
        } else {
          const payload = ending === 'ActionHule' ? bytes(6,[]) : ending === 'ActionNoTile' ? num(4,1) : bytes(2,[]);
          await feed(actionFrame(ending,2,payload));
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
