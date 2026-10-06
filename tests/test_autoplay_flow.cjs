const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sources = ['lobby.js', 'autoplay.js'].map(name =>
  fs.readFileSync(path.join(__dirname, '../src', name), 'utf8'));

function setup(random = .5) {
  let time = 0, nextTimer = 0, finishPage = 0;
  const timers = new Map(), calls = [], refreshes = [], queued = new Set(), statuses = [];
  const addTimer = (fn, ms, interval = 0) => {
    const id = ++nextTimer; timers.set(id, {fn, due:time + ms, interval}); return id;
  };
  const manager = {logined:true, ingame:false, account_id:11, account_refresh_time:1,
    account_data:{level:{id:10301}, level3:{id:20101}, gold:30000},
    updateAccountInfo(handler) {calls.push({type:'refresh', at:time}); refreshes.push(handler);}};
  const queue = {current_count:0, locked:false,
    addMatch(modeId) {calls.push({type:'match', modeId, at:time}); queued.add(modeId); this.current_count = queued.size; return true;},
    getMatchID(modeId) {return queued.has(modeId) ? 0 : -1;},
    matchLocking() {return this.locked;},
    cancelPiPei(modeId) {calls.push({type:'cancel', modeId, at:time}); queued.delete(modeId); this.current_count = queued.size;}};
  const end = {enable:false, locking:true, step:0, rewardIndex:0,
    btns:{visible:false}, btn_next:{visible:false, disabled:false},
    onConfirm() {
      calls.push({type:'finish', step:this.step, at:time});
      if (++finishPage === 1) {this.step = 31; this.locking = true; this.btn_next.visible = false;}
      else {this.enable = false; manager.ingame = false; ui.UI_Lobby.Inst.enable = true;}
    }};
  const ui = {UI_GameEnd:{Inst:end}, UI_Lobby:{Inst:{enable:true, locking:false}}, UI_PiPeiYuYue:{Inst:queue}};
  const modes = [
    {id:1, mode:0, room:1, is_open:1}, {id:4, mode:0, room:2, is_open:1},
    {id:7, mode:0, room:3, is_open:1}, {id:10, mode:0, room:4, is_open:1},
    {id:2, mode:1, room:1, level_limit:10101, level_limit_ceil:10203, glimit_floor:0, glimit_ceil:-1},
    {id:5, mode:1, room:2, level_limit:10201, level_limit_ceil:10303, glimit_floor:2000, glimit_ceil:-1},
    {id:8, mode:1, room:3, level_limit:10301, level_limit_ceil:10403, glimit_floor:10000, glimit_ceil:-1},
    {id:11, mode:1, room:4, level_limit:10401, level_limit_ceil:10503, glimit_floor:20000, glimit_ceil:-1},
    {id:17, mode:11, room:1, level_limit:20101, level_limit_ceil:20203, glimit_floor:0, glimit_ceil:-1},
  ];
  const window = {GameMgr:{Inst:manager}, uiscript:ui, game:{LobbyNetMgr:{Inst:{isOK:true}}},
    view:{DesktopMgr:{Inst:{mode:1}}, EMJMode:{play:1}}, cfg:{desktop:{matchmode:{forEach:fn => modes.forEach(fn)}}},
    Laya:{Handler:{create:(caller, fn) => ({run:() => fn.call(caller)})}},
    __mjStatsOverlay:{updateAutomation:value => statuses.push(value)},
    __mjGameActions:{snapshot:() => ({available:true, canAct:true, remainingMs:15000}),
      execute(advice, state) {calls.push({type:'play', advice, state, at:time}); window.__mjAutoplay.onInput(); return {ok:true};}}};
  const math = Object.create(Math); math.random = () => random;
  const context = vm.createContext({window, location:{hostname:'game.maj-soul.com'}, performance:{now:() => time}, Math:math,
    setTimeout:(fn, ms) => addTimer(fn, ms), clearTimeout:id => timers.delete(id),
    setInterval:(fn, ms) => addTimer(fn, ms, ms), clearInterval:id => timers.delete(id),
    addEventListener() {}, removeEventListener() {}});
  for (const source of sources) vm.runInContext(source, context);
  const api = window.__mjAutoplay;
  const flush = async () => {await Promise.resolve(); await Promise.resolve(); await Promise.resolve();};
  async function advance(ms) {
    const target = time + ms;
    for (;;) {
      const next = [...timers.entries()].filter(([, timer]) => timer.due <= target)
        .sort((a, b) => a[1].due - b[1].due || a[0] - b[0])[0];
      if (!next) break;
      const [id, timer] = next; time = timer.due;
      if (timer.interval) timer.due += timer.interval; else timers.delete(id);
      timer.fn(); await flush();
    }
    time = target; await flush();
  }
  async function completeRefresh(changes = {}, success = true) {
    const handler = refreshes.shift(); assert.ok(handler, 'client must have requested account refresh');
    if (success) {Object.assign(manager.account_data, changes); manager.account_refresh_time++;}
    handler.run(); await flush();
  }
  function enterGame() {
    queued.clear(); queue.current_count = 0; manager.ingame = true; ui.UI_Lobby.Inst.enable = false;
    api.onEvent({kind:'turn', session:'game-1', serial:1,
      state:{phase:'playing', canAct:true, handComplete:true, historyComplete:true, lastStep:7}});
    api.onAdvice({adviceKey:'game-1:1', advice:{status:'ready', best:{action:'discard', tile:'7z'}}});
  }
  function readySettlement() {end.locking = false; end.btns.visible = end.btn_next.visible = true;}
  const ofType = type => calls.filter(call => call.type === type);
  return {window, api, manager, queue, queued, ui, end, calls, statuses, modes, refreshes,
    advance, completeRefresh, enterGame, readySettlement, ofType, get time() {return time;}};
}

test('actual autoplay and lobby complete two queues, one advised action and every settlement page', async () => {
  const h = setup();
  await h.advance(5000); assert.equal(h.calls.length, 0);
  assert.equal(h.api.getStatus().enabled, false); assert.equal(h.api.getStatus().playerCount, 4);
  h.api.setEnabled(true);
  await h.advance(2999); assert.equal(h.calls.length, 0);
  await h.advance(1); assert.equal(h.ofType('refresh').length, 1);
  await h.completeRefresh(); await h.advance(100);
  await h.advance(2999); assert.equal(h.ofType('match').length, 0);
  await h.advance(1); assert.deepEqual(h.ofType('match').map(call => call.modeId), [8]);
  h.enterGame(); await h.advance(2999); assert.equal(h.ofType('play').length, 0);
  await h.advance(1); assert.equal(h.ofType('play').length, 1);
  assert.equal(h.ofType('play')[0].advice.best.tile, '7z');
  await h.advance(5000); assert.equal(h.ofType('play').length, 1); assert.equal(h.api.getStatus().enabled, true);

  h.end.enable = true;
  h.api.onEvent({kind:'status', phase:'ended'});
  await h.advance(5000); assert.equal(h.ofType('finish').length, 0); assert.equal(h.api.getStatus().enabled, true);
  h.readySettlement(); await h.advance(100);
  await h.advance(2999); assert.equal(h.ofType('finish').length, 0);
  await h.advance(1); assert.deepEqual(h.ofType('finish').map(call => call.step), [0]);
  await h.advance(4000); assert.equal(h.ofType('finish').length, 1);
  h.readySettlement(); await h.advance(100); await h.advance(3000);
  assert.deepEqual(h.ofType('finish').map(call => call.step), [0, 31]);
  await h.advance(100); await h.advance(3000);
  assert.equal(h.ofType('refresh').length, 2); assert.equal(h.ofType('match').length, 1);
  await h.completeRefresh({level:{id:10401}, gold:30000});
  await h.advance(100); await h.advance(3000);
  assert.deepEqual(h.ofType('match').map(call => call.modeId), [8, 11]);
  h.api.setEnabled(false); await h.advance(100);
  assert.deepEqual(h.ofType('cancel').map(call => call.modeId), [11]); assert.equal(h.queued.size, 0);
  await h.advance(10000); assert.equal(h.ofType('match').length, 2);
});

test('real lobby account refresh failure and timeout resolve to a stopped automation', async () => {
  for (const failure of ['response', 'timeout']) {
    const h = setup(); h.api.setEnabled(true); await h.advance(3000);
    if (failure === 'response') await h.completeRefresh({}, false); else await h.advance(10000);
    assert.equal(h.api.getStatus().enabled, false);
    assert.match(h.api.getStatus().message, /未能刷新|超时/);
    await h.advance(20000); assert.equal(h.ofType('match').length, 0);
    // A late success after the timeout cannot mark the next attempt refreshed.
    if (failure === 'timeout') await h.completeRefresh();
    h.api.setEnabled(true); await h.advance(3000);
    assert.equal(h.ofType('refresh').length, 2);
    await h.completeRefresh(); await h.advance(100); await h.advance(3000);
    assert.equal(h.ofType('match').length, 1);
  }
});

test('closing a real queued match respects the client lock then permits the same mode again', async () => {
  const h = setup(); h.api.setEnabled(true); await h.advance(3000); await h.completeRefresh();
  await h.advance(100); await h.advance(3000); assert.equal(h.ofType('match').length, 1);
  h.queue.locked = true; h.api.setEnabled(false); h.api.setEnabled(true);
  assert.equal(h.api.getStatus().enabled, false);
  await h.advance(300); assert.equal(h.ofType('cancel').length, 0);
  h.queue.locked = false; await h.advance(200);
  assert.equal(h.ofType('cancel').length, 1); assert.equal(h.queued.size, 0);
  h.api.setEnabled(true); await h.advance(2999); assert.equal(h.ofType('match').length, 1);
  await h.advance(1); assert.deepEqual(h.ofType('match').map(call => call.modeId), [8, 8]);
});

test('live gold and rank changes during delay replace the scheduled mode without sending the old one', async () => {
  const h = setup(); h.api.setEnabled(true); await h.advance(3000); await h.completeRefresh();
  await h.advance(100); await h.advance(2000);
  h.manager.account_data.gold = 5000;
  await h.advance(100); await h.advance(2900);
  assert.equal(h.ofType('match').length, 0);
  h.manager.account_data.level.id = 10203;
  h.manager.account_data.gold = 1000;
  await h.advance(100); await h.advance(2999);
  assert.equal(h.ofType('match').length, 0);
  await h.advance(1); assert.deepEqual(h.ofType('match').map(call => call.modeId), [2]);
});

test('switching accounts with identical rank and gold invalidates the old match delay', async () => {
  const h = setup(); h.api.setEnabled(true); await h.advance(3000); await h.completeRefresh();
  await h.advance(100); await h.advance(2000);
  h.manager.account_id = 22;
  await h.advance(1000);
  assert.equal(h.ofType('match').length, 0, 'the previous account must not authorize a new-account queue');
});

test('an old account refresh callback cannot release matching after an account switch', async () => {
  const h = setup(); h.api.setEnabled(true); await h.advance(3000);
  h.manager.account_id = 22;
  await h.advance(100); await h.completeRefresh();
  await h.advance(6000);
  assert.equal(h.ofType('match').length, 0);
});

test('actual refresh submission is bounded by the selected random delay at both endpoints', async () => {
  for (const [random, milliseconds] of [[0, 1000], [1, 5000]]) {
    const h = setup(random); h.api.setEnabled(true);
    await h.advance(milliseconds - 1); assert.equal(h.ofType('refresh').length, 0);
    await h.advance(1); assert.equal(h.ofType('refresh')[0].at, milliseconds);
    h.api.setEnabled(false); await h.completeRefresh(); await h.advance(10000);
    assert.equal(h.ofType('match').length, 0);
  }
});
