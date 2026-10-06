// Exercise the real lobby/controller pair before the game has created its globals.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sources = ['lobby.js', 'autoplay.js'].map(name =>
  fs.readFileSync(path.join(__dirname, '../src', name), 'utf8'));

function setup(unity = null) {
  let time = 0, tick, hasUnityCanvas = unity === 'canvas';
  const calls = [], statuses = [];
  const canvas = {id:'unity-canvas', tagName:'CANVAS'};
  const document = {
    getElementById:id => id === 'unity-canvas' && hasUnityCanvas ? canvas : null,
    querySelector:selector => selector === '#unity-canvas' && hasUnityCanvas ? canvas : null,
  };
  const window = {document, __mjStatsOverlay:{updateAutomation:status => statuses.push(status)}};
  if (unity === 'ready') window.unityInstance = {SendMessage() {calls.push('unity-message');}};
  if (unity === 'loader') window.createUnityInstance = () => {calls.push('unity-load');};
  const math = Object.create(Math); math.random = () => .5;
  vm.runInNewContext(sources.join('\n'), {window, document, location:{hostname:'game.maj-soul.com'},
    performance:{now:() => time}, Math:math,
    setInterval:fn => {tick = fn; return 1;}, clearInterval:() => {tick = null;},
    setTimeout:() => 1, clearTimeout() {}, addEventListener() {}, removeEventListener() {}});
  function installLegacy(logined = true) {
    const manager = {logined, ingame:false, account_id:11, account_refresh_time:1,
      account_data:{level:{id:10101}, level3:{id:20101}, gold:1000},
      updateAccountInfo(handler) {calls.push('refresh'); this.account_refresh_time++; handler.run();}};
    const queue = {current_count:0,
      addMatch() {calls.push('match'); this.current_count++; return true;},
      cancelPiPei() {calls.push('cancel'); this.current_count = 0;},
      getMatchID() {return this.current_count ? 0 : -1;}, matchLocking:() => false};
    const modes = [{id:1, room:1, mode:0, is_open:1},
      {id:2, room:1, mode:1, level_limit:10101, level_limit_ceil:10203, glimit_floor:0, glimit_ceil:-1}];
    Object.assign(window, {GameMgr:{Inst:manager},
      uiscript:{UI_Lobby:{Inst:{enable:true, locking:false}}, UI_PiPeiYuYue:{Inst:queue}},
      game:{LobbyNetMgr:{Inst:{isOK:true}}},
      cfg:{desktop:{matchmode:{forEach:fn => modes.forEach(fn)}}},
      Laya:{Handler:{create:(caller, fn) => ({run:() => fn.call(caller)})}}});
    return {manager, queue};
  }
  return {window, calls, statuses, installLegacy, api:window.__mjAutoplay,
    advance(ms) {time += ms; tick?.();},
    removeUnity() {hasUnityCanvas = false; delete window.unityInstance; delete window.createUnityInstance;}};
}

for (const marker of ['ready', 'canvas', 'loader']) {
  test(`Unity ${marker} marker stops unsupported automation without waiting for readiness`, () => {
    const h = setup(marker);
    assert.equal(h.api.getStatus().enabled, false);
    h.api.setEnabled(true);
    const status = h.api.getStatus();
    assert.equal(status.enabled, false);
    assert.equal(status.phase, 'paused');
    assert.match(status.message, /Unity/i);
    assert.match(status.message, /未适配|不支持/);
    h.advance(180000);
    assert.deepEqual(h.calls, [], 'engine detection must not initialize or message Unity');
  });
}

test('unknown engine waits at startup but stops at 90 seconds from enabling', () => {
  const h = setup();
  h.api.setEnabled(true);
  assert.equal(h.api.getStatus().phase, 'loading');
  assert.equal(h.api.getStatus().enabled, true);
  h.advance(60000);
  h.api.setPlayerCount(3);
  h.window.GameMgr = {Inst:{logined:false}};
  h.advance(29999);
  assert.equal(h.api.getStatus().enabled, true, 'partial globals and mode changes do not restart the deadline');
  h.advance(1);
  assert.equal(h.api.getStatus().enabled, false);
  assert.equal(h.api.getStatus().phase, 'paused');
  assert.doesNotMatch(h.api.getStatus().message, /^等待游戏客户端加载$/);
  assert.deepEqual(h.calls, []);
});

test('a recognized legacy client that appears during startup proceeds to one queue', async () => {
  const h = setup();
  h.api.setEnabled(true); h.advance(30000);
  h.installLegacy(); h.advance(0);
  assert.equal(h.api.getStatus().enabled, true);
  h.advance(2999); assert.deepEqual(h.calls, []);
  h.advance(1); await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(h.calls, ['refresh']);
  h.advance(100); h.advance(3000);
  assert.deepEqual(h.calls, ['refresh', 'match']);
  h.advance(180000);
  assert.equal(h.api.getStatus().enabled, true, 'normal queue duration is not a client-startup timeout');
  assert.equal(h.api.getStatus().phase, 'matching');
  assert.deepEqual(h.calls, ['refresh', 'match']);
});

test('Unity discovered after enabling interrupts the initial unknown-client wait', () => {
  const h = setup(); h.api.setEnabled(true); h.advance(1000);
  assert.equal(h.api.getStatus().enabled, true);
  h.window.createUnityInstance = () => {h.calls.push('unity-load');};
  h.advance(100);
  assert.equal(h.api.getStatus().enabled, false);
  assert.equal(h.api.getStatus().phase, 'paused');
  assert.match(h.api.getStatus().message, /Unity/i);
  assert.deepEqual(h.calls, []);
});

test('recognized login waiting is separate from an unidentified engine timeout', () => {
  const h = setup();
  h.installLegacy(false); h.api.setEnabled(true); h.advance(180000);
  assert.equal(h.api.getStatus().enabled, true);
  assert.equal(h.api.getStatus().phase, 'login');
  assert.deepEqual(h.calls, []);
});

test('a paused startup does not resume when a client later appears', () => {
  for (const marker of [null, 'canvas']) {
    const h = setup(marker); h.api.setEnabled(true); h.advance(90000);
    assert.equal(h.api.getStatus().enabled, false);
    h.removeUnity(); h.installLegacy(); h.advance(10000);
    assert.equal(h.api.getStatus().enabled, false);
    assert.deepEqual(h.calls, []);
    h.api.setEnabled(true); h.advance(3000);
    assert.deepEqual(h.calls, ['refresh']);
  }
});

test('an explicit off/on retry receives a fresh startup deadline', () => {
  const h = setup(); h.api.setEnabled(true); h.advance(60000);
  h.api.setEnabled(false); h.advance(60000); h.api.setEnabled(true);
  h.advance(89999); assert.equal(h.api.getStatus().enabled, true);
  h.advance(1); assert.equal(h.api.getStatus().enabled, false);
  assert.deepEqual(h.calls, []);
});
