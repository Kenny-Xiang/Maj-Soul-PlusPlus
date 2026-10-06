const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/lobby.js'), 'utf8');

function harness() {
  const calls = [], entries = [
    {id:1, mode:0, room:1, is_open:1}, {id:4, mode:0, room:2, is_open:1},
    {id:7, mode:0, room:3, is_open:1}, {id:10, mode:0, room:4, is_open:1},
    {id:2, mode:1, room:1, level_limit:10101, level_limit_ceil:10203, glimit_floor:0, glimit_ceil:-1, is_open:1},
    {id:5, mode:1, room:2, level_limit:10201, level_limit_ceil:10303, glimit_floor:2000, glimit_ceil:-1, is_open:1},
    {id:8, mode:1, room:3, level_limit:10301, level_limit_ceil:10403, glimit_floor:10000, glimit_ceil:-1, is_open:1},
    {id:11, mode:1, room:4, level_limit:10401, level_limit_ceil:10503, glimit_floor:20000, glimit_ceil:-1, is_open:1},
    {id:17, mode:11, room:1, level_limit:20101, level_limit_ceil:20203, glimit_floor:0, glimit_ceil:-1, is_open:1},
    {id:19, mode:11, room:2, level_limit:20201, level_limit_ceil:20303, glimit_floor:2000, glimit_ceil:-1, is_open:1},
    {id:9, mode:2, room:3, level_limit:10301, level_limit_ceil:10403, glimit_floor:0, glimit_ceil:-1, is_open:1},
    {id:99, mode:1, room:200, level_limit:0, level_limit_ceil:0, glimit_floor:0, glimit_ceil:-1, is_open:1},
  ];
  const queued = new Set();
  const queue = {current_count:0, locked:false, addMatch(id) {calls.push(['match', id]); queued.add(id); this.current_count = queued.size; return true;},
    getMatchID(id) {return queued.has(id) ? 0 : -1;}, matchLocking() {return this.locked;},
    cancelPiPei(id) {calls.push(['cancel', id]); queued.delete(id); this.current_count = queued.size;}};
  const manager = {logined:true, ingame:false, account_id:11, account_refresh_time:1,
    account_data:{level:{id:10301}, level3:{id:20101}, gold:30000},
    updateAccountInfo(handler) {calls.push(['refresh']); this.account_refresh_time++; handler.run();}};
  const ui = {UI_Lobby:{Inst:{enable:true, locking:false}}, UI_PiPeiYuYue:{Inst:queue},
    UI_GameEnd:{Inst:{enable:false, locking:false, step:0, rewardIndex:0,
      btns:{visible:true}, btn_next:{visible:true, disabled:false}, onConfirm() {calls.push(['finish', this.step]); this.step++;}}}};
  const window = {GameMgr:{Inst:manager}, uiscript:ui, game:{LobbyNetMgr:{Inst:{isOK:true}}},
    view:{DesktopMgr:{Inst:{mode:1}}, EMJMode:{play:1}}, cfg:{desktop:{matchmode:{forEach:fn => entries.forEach(fn)}}},
    Laya:{Handler:{create:(caller, fn) => ({run:() => fn.call(caller)})}}};
  vm.runInNewContext(source, {window, location:{hostname:'game.maj-soul.com'}, setTimeout, clearTimeout, Map, Number, Promise});
  const app = window.__mjLobby;
  const refresh = async () => {const s = app.snapshot(); assert.equal(s.action, 'refresh'); assert.equal((await app.start(4, s.actionKey)).ok, true);};
  return {app, calls, window, manager, ui, queue, queued, entries, refresh};
}

test('chooses the highest eligible East room using separate sanma rank and current gold/open limits', async () => {
  const h = harness(); await h.refresh();
  assert.equal(h.app.snapshot().modeId, 8);
  assert.equal(h.app.snapshot(3).modeId, 17);
  h.manager.account_data.gold = 5000;
  assert.equal(h.app.snapshot().modeId, 5);
  h.entries.find(m => m.id === 4).is_open = 0;
  assert.equal(h.app.snapshot().phase, 'blocked');
  h.manager.account_data.level.id = 10203;
  assert.equal(h.app.snapshot().modeId, 2);
  h.entries.find(m => m.id === 2).glimit_ceil = 1000;
  assert.equal(h.app.snapshot().phase, 'blocked');
});

test('unknown account and config values cannot accidentally select a room', async () => {
  for (const change of [h => {h.manager.account_data.level.id = 20301;},
    h => {delete h.manager.account_data.gold;}, h => {h.window.cfg.desktop.matchmode = null;},
    h => {for (const m of h.entries) delete m.glimit_ceil;}]) {
    const h = harness(); await h.refresh(); change(h);
    assert.equal(h.app.snapshot().phase, 'blocked');
    assert.equal(h.calls.filter(c => c[0] === 'match').length, 0);
  }
});

test('delayed start rechecks rank, balance, openness and competing queues', async () => {
  const h = harness(); await h.refresh();
  const old = h.app.snapshot().actionKey;
  h.manager.account_data.gold = 5000;
  assert.equal(h.app.start(4, old).ok, false);
  const ready = h.app.snapshot();
  assert.equal(h.app.start(4, ready.actionKey).ok, true);
  assert.equal(h.app.start(4, ready.actionKey).ok, false);
  assert.equal(h.app.snapshot().phase, 'matching');
  assert.deepEqual(h.calls.filter(c => c[0] === 'match'), [['match', 5]]);
  h.queued.clear(); h.queue.current_count = 0;
  assert.equal(h.app.snapshot().phase, 'blocked');
});

test('cancel waits out the client lock and only cancels its own submitted queue', async () => {
  const h = harness(); await h.refresh();
  h.queued.add(17); h.queue.current_count = 1;
  assert.equal(h.app.cancel().ok, true);
  assert.equal(h.queued.has(17), true);
  h.queued.clear(); h.queue.current_count = 0;
  const s = h.app.snapshot(); h.app.start(4, s.actionKey);
  h.queued.add(17); h.queue.current_count = 2; h.queue.locked = true;
  assert.equal(h.app.cancel().pending, true);
  assert.equal(h.calls.some(c => c[0] === 'cancel'), false);
  h.queue.locked = false;
  assert.equal(h.app.cancel().pending, true);
  assert.equal(h.app.cancel().ok, true);
  assert.deepEqual([...h.queued], [17]);
  assert.deepEqual(h.calls.filter(c => c[0] === 'cancel'), [['cancel', 8]]);
});

test('login, reconnect, room membership and client prompts never start a new game', async () => {
  const h = harness(); await h.refresh();
  h.manager.logined = false; assert.equal(h.app.snapshot().phase, 'login');
  h.manager.logined = true; h.window.game.LobbyNetMgr.Inst.isOK = false;
  assert.equal(h.app.snapshot().phase, 'loading');
  h.window.game.LobbyNetMgr.Inst.isOK = true; h.manager.account_data.room_id = 123;
  assert.equal(h.app.snapshot().phase, 'blocked');
  delete h.manager.account_data.room_id; h.ui.UI_SecondConfirm = {Inst:{enable:true}};
  assert.equal(h.app.snapshot().phase, 'blocked');
  h.ui.UI_SecondConfirm.Inst.enable = false; h.manager.ingame = true;
  assert.equal(h.app.snapshot().phase, 'playing');
  assert.equal(h.calls.some(c => c[0] === 'match'), false);
});

test('settlement waits for each real button and refreshes rank before the next match', async () => {
  const h = harness(); await h.refresh();
  const end = h.ui.UI_GameEnd.Inst;
  h.manager.ingame = true; end.enable = true; end.locking = true;
  assert.equal(h.app.snapshot().actionKey, undefined);
  end.locking = false;
  const first = h.app.snapshot().actionKey;
  assert.equal(h.app.finish(first).ok, true);
  assert.equal(h.app.finish(first).ok, false);
  end.btn_next.visible = false;
  assert.equal(h.app.snapshot().actionKey, undefined);
  end.btn_next.visible = true; end.rewardIndex++;
  assert.equal(h.app.finish(h.app.snapshot().actionKey).ok, true);
  end.enable = false; h.manager.ingame = false;
  h.manager.account_data.level.id = 10401;
  assert.equal(h.app.snapshot().action, 'refresh');
  await h.refresh();
  assert.equal(h.app.snapshot().modeId, 11);
  assert.equal(h.calls.filter(c => c[0] === 'refresh').length, 2);
});

test('failed account refresh and replay settlement do not allow matching or confirmation', async () => {
  const h = harness();
  h.manager.updateAccountInfo = handler => handler.run();
  assert.equal((await h.app.start(4, h.app.snapshot().actionKey)).ok, false);
  assert.equal(h.app.snapshot().action, 'refresh');
  h.ui.UI_GameEnd.Inst.enable = true; h.window.view.DesktopMgr.Inst.mode = 2;
  assert.equal(h.app.snapshot().phase, 'blocked');
  assert.equal(h.app.finish('end:1:0:0').ok, false);
  assert.equal(h.calls.length, 0);
});

test('logout, reconnect and account replacement invalidate refreshed eligibility and queue ownership', async () => {
  const h = harness(); await h.refresh();
  h.window.game.LobbyNetMgr.Inst.isOK = false;
  assert.equal(h.app.snapshot().phase, 'loading');
  h.window.game.LobbyNetMgr.Inst.isOK = true;
  assert.equal(h.app.snapshot().action, 'refresh');
  await h.refresh();
  const ready = h.app.snapshot(); h.app.start(4, ready.actionKey);
  // The new account can have the same mode queued, but it is not our old request.
  h.manager.account_id = 22;
  assert.equal(h.app.cancel().ok, true);
  assert.equal(h.queued.has(8), true);
  assert.equal(h.calls.some(c => c[0] === 'cancel'), false);
  h.queued.clear(); h.queue.current_count = 0;
  await h.refresh();
  h.manager.logined = false; assert.equal(h.app.snapshot().phase, 'login');
  h.manager.logined = true; assert.equal(h.app.snapshot().action, 'refresh');
});
