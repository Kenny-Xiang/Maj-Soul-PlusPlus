const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/autoplay.js'), 'utf8');

function setup() {
  let time = 0, tick;
  const actions = [], starts = [], finishes = [], statuses = [], listeners = new Map();
  let cancels = 0;
  const lobby = {phase:'playing', message:'playing'};
  const client = {available:true, canAct:true, remainingMs:10000};
  const window = {
    __mjStatsOverlay:{updateAutomation:s=>statuses.push(s)},
    __mjLobby:{snapshot:()=>lobby,
      start:(count,key)=>{starts.push({count,key}); return {ok:true};},
      cancel:()=>{cancels++;return {ok:true};}, finish:key=>{finishes.push(key);return {ok:true};}},
    __mjGameActions:{snapshot:()=>client, execute:(advice,state)=>{
      actions.push({advice,state}); window.__mjAutoplay.onInput(); return Promise.resolve({});
    }},
  };
  vm.runInNewContext(source, {window,location:{hostname:'game.maj-soul.com'},
    performance:{now:()=>time},Math:{random:()=>.5,min:Math.min,max:Math.max},
    setInterval:fn=>{tick=fn;return 1;},clearInterval:()=>{tick=null;},
    addEventListener:(type,fn)=>listeners.set(type,fn),removeEventListener:type=>listeners.delete(type)});
  const api = window.__mjAutoplay;
  const state = {phase:'playing',canAct:true,handComplete:true,historyComplete:true,lastStep:3};
  function turn(serial=1, changes={}) {
    api.onEvent({kind:'turn',session:'session',serial,state:{...state,...changes}});
  }
  function advice(serial=1, value={status:'ready',best:{action:'discard',tile:'7z'}}) {
    api.onAdvice({kind:'advice',adviceKey:`session:${serial}`,advice:value});
  }
  return {window,api,lobby,client,actions,starts,finishes,statuses,listeners,turn,advice,
    advance(ms){time+=ms;tick?.();},tick(){tick?.();},get cancels(){return cancels;}};
}

test('default off and four players; enabling observes a window then submits exactly once', () => {
  const s=setup(); s.turn();s.advice();s.advance(10000);
  assert.equal(s.actions.length,0);assert.equal(s.api.getStatus().playerCount,4);
  s.api.setEnabled(true);s.advance(2999);assert.equal(s.actions.length,0);
  s.advance(1);assert.equal(s.actions.length,1);assert.equal(s.api.getStatus().enabled,true);
  s.advice();s.advance(50000);assert.equal(s.actions.length,1);
});

test('delay and calculation overlap instead of adding another full random wait', () => {
  const s=setup();s.turn();s.api.setEnabled(true);s.advance(2000);s.advice();
  s.advance(999);assert.equal(s.actions.length,0);s.advance(1);assert.equal(s.actions.length,1);
});

test('short decision deadline overrides target delay; no available decision pauses', () => {
  const s=setup();s.turn();s.advice();s.client.remainingMs=300;s.api.setEnabled(true);
  assert.equal(s.actions.length,1);
  const unavailable=setup();unavailable.turn();unavailable.client.remainingMs=300;unavailable.api.setEnabled(true);
  assert.equal(unavailable.actions.length,0);assert.equal(unavailable.api.getStatus().enabled,false);
});

test('missing or expired countdown and unknown client adapter fail closed', () => {
  for (const remainingMs of [null,NaN,0,-1]) {
    const s=setup();s.turn();s.advice();s.client.remainingMs=remainingMs;s.api.setEnabled(true);
    assert.equal(s.actions.length,0);assert.equal(s.api.getStatus().enabled,false);
  }
  const s=setup();s.turn();s.advice();s.client.available=false;s.api.setEnabled(true);
  assert.equal(s.api.getStatus().enabled,false);
});

test('waiting for client animation does not execute until a valid action surface appears', () => {
  const s=setup();s.client.canAct=false;s.turn();s.advice();s.api.setEnabled(true);s.advance(4000);
  assert.equal(s.actions.length,0);s.client.canAct=true;s.tick();assert.equal(s.actions.length,1);
});

test('unsupported client state pauses immediately and stalled animations have a bounded wait', () => {
  const s=setup();s.turn();s.advice();Object.assign(s.client,{canAct:false,blocked:true,reason:'内置自动摸切已开启'});
  s.api.setEnabled(true);assert.equal(s.api.getStatus().enabled,false);
  assert.match(s.api.getStatus().message,/内置自动摸切/);
  const x=setup();x.turn();x.client.canAct=false;x.client.remainingMs=null;
  x.api.setEnabled(true);x.advance(14000);assert.equal(x.api.getStatus().enabled,false);
});

test('stale advice is rejected and a new action receives its own delay', () => {
  const s=setup();s.turn();s.api.setEnabled(true);s.advance(2000);s.turn(2);
  s.advice(1);s.advance(5000);assert.equal(s.actions.length,0);
  s.advice(2);s.tick();assert.equal(s.actions.length,1);
  assert.equal(s.actions[0].state.lastStep,3);
});

test('win uses its top-level action while analysis, waiting and unavailable never execute', () => {
  const s=setup();s.turn();s.advice(1,{status:'win',action:'ron',best:null});
  s.api.setEnabled(true);s.advance(3000);assert.equal(s.actions[0].advice.action,'ron');
  for (const status of ['analysis','waiting','unavailable']) {
    const x=setup();x.turn();x.api.setEnabled(true);x.advice(1,{status,best:{action:'discard',tile:'1m'}});
    x.advance(3000);assert.equal(x.actions.length,0);
  }
});

test('close, manual input, incomplete baseline, error and disconnect cancel pending operations', () => {
  for (const cancel of [s=>s.api.setEnabled(false),s=>s.api.onInput(),
    s=>s.turn(2,{historyComplete:false}),s=>s.api.onEvent({kind:'error'}),
    s=>s.api.onEvent({kind:'status',phase:'disconnected'})]) {
    const s=setup();s.turn();s.advice();s.api.setEnabled(true);s.advance(2000);cancel(s);s.advance(5000);
    assert.equal(s.actions.length,0);assert.equal(s.api.getStatus().enabled,false);
  }
});

test('trusted manual input yields control, overlay controls and synthetic events do not', () => {
  const s=setup();s.turn();s.advice();s.api.setEnabled(true);
  const pointer=s.listeners.get('pointerdown');
  pointer({isTrusted:true,composedPath:()=>[{id:'mj-statistics-overlay'}]});
  assert.equal(s.api.getStatus().enabled,true);
  pointer({isTrusted:false,composedPath:()=>[]});assert.equal(s.api.getStatus().enabled,true);
  pointer({isTrusted:true,composedPath:()=>[]});s.advance(5000);
  assert.equal(s.api.getStatus().enabled,false);assert.equal(s.actions.length,0);
});

test('matching and settlement are delayed, keyed and never repeated while awaiting confirmation', () => {
  const s=setup();Object.assign(s.lobby,{phase:'lobby',actionKey:'lobby:4:rank:gold'});
  s.api.setEnabled(true);s.advance(3000);assert.equal(s.starts.length,1);assert.equal(s.starts[0].count,4);
  s.advance(3000);assert.equal(s.starts.length,1);
  Object.assign(s.lobby,{phase:'settlement',actionKey:'game:1:reward:1'});s.tick();s.advance(3000);
  assert.deepEqual(s.finishes,['game:1:reward:1']);s.advance(3000);assert.equal(s.finishes.length,1);
  s.lobby.actionKey='game:1:reward:2';s.tick();s.advance(3000);assert.equal(s.finishes.length,2);
});

test('mode change affects next queue and does not interrupt the current game', () => {
  const s=setup();s.turn();s.advice();s.api.setEnabled(true);s.api.setPlayerCount(3);s.advance(3000);
  assert.equal(s.actions.length,1);assert.equal(s.api.getStatus().playerCount,3);
  Object.assign(s.lobby,{phase:'lobby',actionKey:'next:3'});s.tick();s.advance(3000);
  assert.equal(s.starts[0].count,3);s.api.setPlayerCount(7);assert.equal(s.api.getStatus().playerCount,3);
});

test('client rejection and asynchronous request failures pause without retry', async () => {
  const s=setup();s.window.__mjGameActions.execute=()=>Promise.reject(new Error('server rejected'));
  s.turn();s.advice();s.api.setEnabled(true);s.advance(3000);await new Promise(setImmediate);
  assert.equal(s.api.getStatus().enabled,false);assert.match(s.api.getStatus().message,/server rejected/);
  const x=setup();Object.assign(x.lobby,{phase:'lobby',actionKey:'queue'});
  x.window.__mjLobby.start=()=>({ok:false,reason:'rank changed'});x.api.setEnabled(true);x.advance(3000);
  assert.equal(x.api.getStatus().enabled,false);assert.match(x.api.getStatus().message,/rank changed/);
});

test('settlement animations without an action key wait without disabling automation', () => {
  const s=setup();Object.assign(s.lobby,{phase:'settlement',message:'等待结算动画'});
  s.api.setEnabled(true);s.advance(5000);assert.equal(s.api.getStatus().enabled,true);
  assert.equal(s.finishes.length,0);s.lobby.actionKey='end:ready';s.tick();s.advance(3000);
  assert.deepEqual(s.finishes,['end:ready']);
});

test('resolved async failures pause but obsolete requests cannot disable a new intent', async () => {
  const s=setup();Object.assign(s.lobby,{phase:'lobby',actionKey:'refresh'});
  s.window.__mjLobby.start=()=>Promise.resolve({ok:false,reason:'refresh failed'});
  s.api.setEnabled(true);s.advance(3000);await new Promise(setImmediate);
  assert.equal(s.api.getStatus().enabled,false);assert.match(s.api.getStatus().message,/refresh failed/);
  const x=setup();Object.assign(x.lobby,{phase:'lobby',actionKey:'refresh'});let reject;
  x.window.__mjLobby.start=()=>new Promise((resolve,fail)=>{reject=fail;});
  x.api.setEnabled(true);x.advance(3000);x.api.setEnabled(false);x.api.setEnabled(true);
  reject(new Error('old request'));await new Promise(setImmediate);assert.equal(x.api.getStatus().enabled,true);
});

test('a cancelled matching intent can be re-enabled with the same account and mode', () => {
  const s=setup();Object.assign(s.lobby,{phase:'lobby',actionKey:'same-mode'});
  s.api.setEnabled(true);s.advance(3000);s.api.setEnabled(false);
  s.api.setEnabled(true);s.advance(3000);assert.equal(s.starts.length,2);
});

test('missing confirmation pauses and a pending cancellation is retried even while disabled', () => {
  const s=setup();Object.assign(s.lobby,{phase:'lobby',actionKey:'queue'});
  s.api.setEnabled(true);s.advance(3000);s.advance(15001);assert.equal(s.api.getStatus().enabled,false);
  const x=setup();let calls=0;x.window.__mjLobby.cancel=()=>({ok:true,pending:++calls<3});
  x.api.setEnabled(true);x.api.setEnabled(false);x.api.setEnabled(true);
  assert.equal(x.api.getStatus().enabled,false);x.advance(100);x.advance(100);assert.equal(calls,3);
  x.api.setEnabled(true);assert.equal(x.api.getStatus().enabled,true);
});

test('stop detaches timers and input handlers and cannot be re-enabled', () => {
  const s=setup();s.turn();s.advice();s.api.setEnabled(true);s.api.stop();s.advance(10000);
  assert.equal(s.actions.length,0);assert.equal(s.listeners.size,0);s.api.setEnabled(true);
  assert.equal(s.api.getStatus().enabled,false);
});
