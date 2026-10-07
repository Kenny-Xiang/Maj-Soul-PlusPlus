const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/autoplay.js'), 'utf8');

function setup(random = () => .5) {
  let time = 0, tick;
  const actions = [], starts = [], finishes = [], statuses = [], intents = [], listeners = new Map();
  let cancels = 0, randomCalls = 0;
  const lobby = {phase:'playing', message:'playing'};
  const client = {available:true, canAct:true, remainingMs:10000};
  const window = {
    __mjMonitor:{session:'session',reportAutomationIntent:value=>intents.push(value)},
    __mjStatsOverlay:{updateAutomation:s=>statuses.push(s)},
    __mjLobby:{snapshot:()=>lobby,
      start:(count,key,roundCount)=>{starts.push({count,key,roundCount}); return {ok:true};},
      cancel:()=>{cancels++;return {ok:true};}, finish:key=>{finishes.push(key);return {ok:true};}},
    __mjUnityActions:{snapshot:()=>client, execute:(advice,state)=>{
      actions.push({advice,state,at:time}); window.__mjAutoplay.onInput(); return Promise.resolve({});
    }},
  };
  vm.runInNewContext(source, {window,location:{hostname:'game.maj-soul.com'},
    performance:{now:()=>time},Math:Object.assign(Object.create(Math), {random:()=>{randomCalls++;return random();}}),
    setInterval:fn=>{tick=fn;return 1;},clearInterval:()=>{tick=null;},
    addEventListener:(type,fn)=>listeners.set(type,fn),removeEventListener:type=>listeners.delete(type)});
  const api = window.__mjAutoplay;
  const state = {phase:'playing',canAct:true,canDiscard:true,handComplete:true,historyComplete:true,recovery:null,
    selfSeat:0,playerCount:4,round:{chang:0,ju:0,ben:0},lastStep:3,lastDraw:'7z',
    hand:['1m','2m','3m','4m','5m','6m','1p','2p','3p','1s','2s','3s','7z','7z'],
    operations:[1],operationDetails:[{type:1,combination:[]}],
    operationTiming:{receivedAt:0,timeFixed:10000,timeAdd:10000},
    lastAction:{name:'ActionDealTile',seat:0,step:3,tile:'7z'},
    riichi:[false,false,false,false],riichiPending:[false,false,false,false],
    melds:[[],[],[],[]],doras:['3p']};
  function turn(serial=1, changes={}, action) {
    const next = {...state,...changes};
    api.onEvent({kind:'turn',session:'session',serial,state:next,action:action || next.lastAction});
  }
  function advice(serial=1, value={status:'ready',best:{action:'discard',tile:'7z'}}) {
    api.onAdvice({kind:'advice',adviceKey:`session:${serial}`,advice:value});
  }
  return {window,api,lobby,client,actions,starts,finishes,statuses,intents,listeners,turn,advice,
    advance(ms){time+=ms;tick?.();},tick(){tick?.();},get cancels(){return cancels;},
    get now(){return time;},get randomCalls(){return randomCalls;},
    finishAction(count=1){for (let i=0;i<200 && actions.length<count;i++) {time+=100;tick?.();}assert.equal(actions.length,count);}};
}

function comparedAdvice(gap = 1000, bestChanges = {}, otherChanges = {}) {
  const best = {action:'discard',tile:'7z',currentStrategy:'push',metricContext:'discard',
    score:2000,decisionBasis:{scoreGap:gap,componentAdvantages:{efficiency:gap,defense:0,draw:0,actionCost:0}},
    ...bestChanges};
  const other = {action:'discard',tile:'1m',currentStrategy:'push',metricContext:'discard',score:2000-gap,...otherChanges};
  return {status:'ready',best,candidates:[best,other],rankedCandidateCount:2,warnings:[]};
}

function responseTime(advice, changes = {}, random) {
  const s=setup(random);s.turn(1,changes);s.advice(1,advice);s.api.setEnabled(true);s.finishAction();
  return {ms:s.actions[0].at,s};
}

const budgetExceeded = {status:'unavailable',reason:'search_budget_exceeded',recoverable:true,
  message:'前瞻计算超过时间预算，等待下一次局面',best:null,candidates:[]};

for (const arrivalMs of [500,2000,8000,29000,31000,38*60000]) test(`initial round arriving after ${arrivalMs}ms resumes from its event, not a fixed five-second delay`, () => {
  const s=setup(); s.api.setEnabled(true);
  assert.match(s.api.getStatus().message,/等待开局牌局信息/);
  s.turn(1,{phase:'connected',baseline:null,handComplete:false,historyComplete:false,canAct:false});
  s.advice(1,{status:'unavailable',message:'尚未取得基线'}); s.advance(arrivalMs);
  assert.equal(s.api.getStatus().enabled,true); assert.equal(s.actions.length,0);
  s.turn(2,{operationTiming:{receivedAt:s.now,timeFixed:10000,timeAdd:10000}});
  s.advice(2); s.advance(s.api.getStatus().timing.targetMs - 1); assert.equal(s.actions.length,0);
  s.advance(1); assert.equal(s.actions.length,1); assert.equal(s.api.getStatus().enabled,true);
});

test('confirmed game loading stays enabled after 30 seconds and repeated connected statuses', () => {
  const s=setup(); s.api.setEnabled(true); s.advance(15000);
  s.turn(1,{phase:'connected',baseline:null,handComplete:false,historyComplete:false,canAct:false});
  s.api.onEvent({kind:'status',phase:'connected'}); s.advance(14999);
  assert.equal(s.api.getStatus().enabled,true); s.advance(1);
  assert.equal(s.api.getStatus().enabled,true); assert.match(s.api.getStatus().message,/加载.*自动保持开启/);
  s.advance(38*60000);assert.equal(s.actions.length,0);assert.equal(s.cancels,0);
  s.turn(2,{operationTiming:{receivedAt:s.now,timeFixed:10000,timeAdd:10000}});
  s.advice(2);s.finishAction();assert.equal(s.api.getStatus().enabled,true);
});

test('initial waiting never suppresses an incomplete playing state or manual takeover', () => {
  for (const stop of [s=>s.turn(2,{handComplete:false,historyComplete:false,baseline:'new_round'}),
    s=>s.turn(2,{handComplete:false,historyComplete:false,baseline:'snapshot_unverified'}),
    s=>s.api.onEvent({kind:'error',message:'invalid frame'}),
    s=>s.api.setEnabled(false),
    s=>s.listeners.get('pointerdown')({isTrusted:true,composedPath:()=>[]})]) {
    const s=setup(); s.api.setEnabled(true); s.advance(38*60000);
    assert.equal(s.api.getStatus().enabled,true);stop(s);
    assert.equal(s.api.getStatus().enabled,false);
    s.turn(3); s.advice(3); s.advance(5000);
    assert.equal(s.api.getStatus().enabled,false); assert.equal(s.actions.length,0);
  }
});

test('enabling after an incomplete reconnect pauses until a fresh complete state arrives', () => {
  for (const incomplete of [{baseline:'restore_actions',handComplete:true,historyComplete:false},
    {baseline:'snapshot_unverified',handComplete:false,historyComplete:false}]) {
    const s=setup();s.turn(1,{...incomplete,canAct:false,canDiscard:false,operationTiming:null});
    s.advice(1,{status:'unavailable',message:'正在恢复牌局'});
    s.api.setEnabled(true);
    assert.equal(s.api.getStatus().enabled,false);
    assert.match(s.api.getStatus().message,/基线不完整/);
    s.advance(5000);assert.equal(s.actions.length,0);
    s.turn(2,{operationTiming:{receivedAt:s.now,timeFixed:10000,timeAdd:10000}});s.advice(2);
    s.advance(5000);assert.equal(s.actions.length,0);
    s.api.setEnabled(true);s.finishAction();
    assert.equal(s.api.getStatus().enabled,true);
  }
});

test('default off, four players and East; enabling observes a window then submits exactly once', () => {
  const s=setup(); s.turn();s.advice();s.advance(10000);
  assert.equal(s.actions.length,0);assert.equal(s.api.getStatus().playerCount,4);
  assert.equal(s.api.getStatus().roundCount,1);
  s.api.setEnabled(true);assert.equal(s.actions.length,0);
  s.finishAction();assert.equal(s.api.getStatus().enabled,true);
  s.advice();s.advance(50000);assert.equal(s.actions.length,1);
});

test('delay and calculation overlap instead of adding another full random wait', () => {
  const baseline=responseTime({status:'ready',best:{action:'discard',tile:'7z'}}).ms;
  const s=setup();s.turn();s.api.setEnabled(true);s.advance(baseline-100);s.advice();
  s.advance(100);assert.equal(s.actions.length,1);
});

test('short decision deadline overrides target delay; no available decision skips only that window', () => {
  const s=setup();s.turn();s.advice();s.client.remainingMs=300;s.api.setEnabled(true);
  assert.equal(s.actions.length,1);
  const unavailable=setup();unavailable.turn();unavailable.client.remainingMs=300;unavailable.api.setEnabled(true);
  assert.equal(unavailable.actions.length,0);assert.equal(unavailable.api.getStatus().enabled,true);
  unavailable.advice();unavailable.advance(100);
  assert.equal(unavailable.actions.length,0,'advice arriving after the submission cutoff cannot revive this window');
});

test('missing countdown and unknown client adapter fail closed', () => {
  for (const remainingMs of [null,NaN]) {
    const s=setup();s.turn();s.advice();s.client.remainingMs=remainingMs;s.api.setEnabled(true);
    assert.equal(s.actions.length,0);assert.equal(s.api.getStatus().enabled,false);
  }
  const s=setup();s.turn();s.advice();s.client.available=false;s.api.setEnabled(true);
  assert.equal(s.api.getStatus().enabled,false);
});

test('expired countdown skips stale advice without disabling the next window', () => {
  const s=setup();s.turn();s.advice();s.client.remainingMs=0;s.client.blocked=true;s.client.canAct=false;
  s.api.setEnabled(true);s.advance(5000);
  assert.equal(s.api.getStatus().enabled,true);assert.equal(s.actions.length,0);
  Object.assign(s.client,{remainingMs:10000,canAct:true,blocked:false});
  s.advice();s.advance(100);assert.equal(s.actions.length,0);
  s.turn(2,{lastStep:4,operationTiming:{receivedAt:s.now,timeFixed:10000,timeAdd:10000}});
  s.advice(2);s.finishAction();assert.equal(s.api.getStatus().enabled,true);
});

test('budget exhaustion preserves intent until fresh advice or a new legal window', () => {
  for (const expires of [false,true]) {
    const s=setup();s.turn();s.api.setEnabled(true);s.advice(1,budgetExceeded);s.advance(3000);
    assert.equal(s.api.getStatus().enabled,true);assert.equal(s.actions.length,0);
    if (expires) {
      Object.assign(s.client,{remainingMs:0,blocked:true,canAct:false});s.advance(25000);
      assert.equal(s.api.getStatus().enabled,true);
      s.advice();s.tick();assert.equal(s.actions.length,0);
      s.api.onInput();assert.equal(s.api.getStatus().enabled,true,'native timeout handling is not manual takeover');
      Object.assign(s.client,{remainingMs:10000,blocked:false,canAct:true});
      s.turn(2,{lastStep:5,operationTiming:{receivedAt:s.now,timeFixed:10000,timeAdd:10000}});s.advice(1);
      s.advance(500);assert.equal(s.actions.length,0);s.advice(2);
    } else s.advice();
    s.finishAction();assert.equal(s.api.getStatus().enabled,true);
  }
});

test('only a structured budget timeout is recoverable, and manual/off remain authoritative', () => {
  for (const advice of [{...budgetExceeded,recoverable:false}, {...budgetExceeded,reason:'invalid_state'},
    {status:'unavailable',message:budgetExceeded.message}]) {
    const s=setup();s.turn();s.api.setEnabled(true);s.advice(1,advice);
    assert.equal(s.api.getStatus().enabled,false);assert.equal(s.actions.length,0);
  }
  for (const off of [s=>s.api.setEnabled(false),
    s=>s.listeners.get('pointerdown')({isTrusted:true,composedPath:()=>[]})]) {
    const s=setup();s.turn();s.api.setEnabled(true);s.advice(1,budgetExceeded);off(s);
    s.turn(2);s.advice(2);s.advance(5000);
    assert.equal(s.api.getStatus().enabled,false);assert.equal(s.actions.length,0);
  }
});

test('native input after a known deadline keeps intent even before the next scheduler tick', () => {
  const s=setup();s.turn();s.api.setEnabled(true);s.client.remainingMs=0;
  s.api.onInput();assert.equal(s.api.getStatus().enabled,true);
  const invalid=setup();invalid.turn();invalid.api.setEnabled(true);invalid.client.remainingMs=null;
  invalid.api.onInput();assert.equal(invalid.api.getStatus().enabled,false);
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
  const s=setup();s.turn();s.api.setEnabled(true);s.advance(2000);s.turn(2,{lastStep:4});
  s.advice(1);s.advance(5000);assert.equal(s.actions.length,0);
  s.advice(2);s.tick();assert.equal(s.actions.length,1);
  assert.equal(s.actions[0].state.lastStep,4);
});

test('win uses its top-level action while analysis, waiting and unavailable never execute', () => {
  const s=setup();s.turn();s.advice(1,{status:'win',action:'ron',best:null});
  s.api.setEnabled(true);s.advance(3000);assert.equal(s.actions[0].advice.action,'ron');
  for (const status of ['analysis','waiting','unavailable']) {
    const x=setup();x.turn();x.api.setEnabled(true);x.advice(1,{status,best:{action:'discard',tile:'1m'}});
    x.advance(3000);assert.equal(x.actions.length,0);
  }
});

test('close, manual input, incomplete baseline, error and stop cancel pending operations', () => {
  for (const cancel of [s=>s.api.setEnabled(false),s=>s.api.onInput(),
    s=>s.turn(2,{historyComplete:false}),s=>s.api.onEvent({kind:'error'}),
    s=>s.api.onEvent({kind:'status',phase:'stopped'})]) {
    const s=setup();s.turn();s.advice();s.api.setEnabled(true);s.advance(10);cancel(s);s.advance(5000);
    assert.equal(s.actions.length,0);assert.equal(s.api.getStatus().enabled,false);
  }
});

test('disconnect and verified recovery preserve intent and resume only with fresh advice', () => {
  const s=setup();s.turn();s.advice();s.api.setEnabled(true);s.advance(100);
  s.api.onEvent({kind:'status',phase:'disconnected',recovery:{status:'waiting',reason:'connection'}});
  Object.assign(s.lobby,{phase:'lobby',actionKey:'must-not-match-during-recovery'});
  s.advance(120000);
  assert.equal(s.api.getStatus().enabled,true);assert.equal(s.api.getStatus().phase,'reconnecting');
  assert.equal(s.actions.length,0);assert.equal(s.starts.length,0);assert.equal(s.cancels,0);
  s.api.onEvent({kind:'status',phase:'connected',recovery:{status:'waiting',reason:'authentication'}});
  s.turn(2,{baseline:'restore_actions',handComplete:true,historyComplete:false,canAct:false,
    operationTiming:null,recovery:{status:'waiting',reason:'live'}});
  s.advice(2,{status:'unavailable',message:'等待恢复边界'});s.advance(30000);
  assert.equal(s.api.getStatus().enabled,true);assert.equal(s.actions.length,0);
  s.api.onInput();assert.equal(s.api.getStatus().enabled,true,'native recovery input must not turn off intent');
  s.lobby.phase='playing';s.turn(3,{operationTiming:{receivedAt:s.now,timeFixed:10000,timeAdd:10000}});
  s.advice(1);s.advice(2);s.advance(500);assert.equal(s.actions.length,0);
  s.advice(3);s.finishAction();assert.equal(s.api.getStatus().enabled,true);
  assert.equal(s.cancels,0);
});

test('manual takeover or switching off during recovery prevents automatic resumption', () => {
  for (const stop of [s=>s.api.setEnabled(false),
    s=>s.listeners.get('pointerdown')({isTrusted:true,composedPath:()=>[]}),s=>s.api.stop()]) {
    const s=setup();s.turn();s.advice();s.api.setEnabled(true);
    s.api.onEvent({kind:'status',phase:'disconnected',recovery:{status:'waiting',reason:'connection'}});
    stop(s);s.turn(2);s.advice(2);s.advance(5000);
    assert.equal(s.api.getStatus().enabled,false);assert.equal(s.actions.length,0);
  }
});

test('enabling during recovery waits, while malformed replay still pauses', () => {
  const s=setup();s.turn(1,{baseline:'restore_actions',historyComplete:false,canAct:false,
    operationTiming:null,recovery:{status:'waiting',reason:'live'}});
  s.api.setEnabled(true);s.advance(60000);
  assert.equal(s.api.getStatus().enabled,true);assert.equal(s.api.getStatus().phase,'reconnecting');
  s.turn(2,{baseline:'restore_actions',historyComplete:false,canAct:false,
    recovery:{status:'failed',reason:'恢复动作顺序不连续'}});
  assert.equal(s.api.getStatus().enabled,false);assert.equal(s.actions.length,0);
});

test('recoverable client gates retain intent without reusing the previous operation', () => {
  const s=setup();s.turn();s.advice();
  Object.assign(s.client,{canAct:false,recoverable:true,remainingMs:0,reason:'等待恢复后的权威动作'});
  s.api.setEnabled(true);s.advance(60000);
  assert.equal(s.api.getStatus().enabled,true);assert.equal(s.actions.length,0);
  Object.assign(s.client,{canAct:true,recoverable:false,remainingMs:10000});
  s.turn(2,{operationTiming:{receivedAt:s.now,timeFixed:10000,timeAdd:10000}});s.advice(2);
  s.finishAction();assert.equal(s.api.getStatus().enabled,true);
});

test('recoverable request failures keep the switch on and a late old failure cannot stop a recovered turn', async () => {
  for (const fail of [()=>Promise.resolve({ok:false,recoverable:true,reason:'连接替换'}),
    ()=>Promise.reject(Object.assign(new Error('连接断开'),{recoverable:true}))]) {
    const s=setup();s.window.__mjLobby.start=fail;
    Object.assign(s.lobby,{phase:'lobby',actionKey:'old-lobby'});
    s.api.setEnabled(true);s.advance(3000);await new Promise(setImmediate);
    assert.equal(s.api.getStatus().enabled,true);assert.equal(s.cancels,0);
    s.lobby.phase='login';s.advance(60000);
    assert.equal(s.api.getStatus().enabled,true);
  }
  const s=setup();let rejectOld;
  s.window.__mjUnityActions.execute=()=>new Promise((resolve,reject)=>{rejectOld=reject;});
  s.turn();s.advice();s.api.setEnabled(true);s.advance(3000);
  s.api.onEvent({kind:'status',phase:'disconnected',recovery:{status:'waiting',reason:'connection'}});
  s.turn(2,{operationTiming:{receivedAt:s.now,timeFixed:10000,timeAdd:10000}});s.advice(2);
  rejectOld(new Error('迟到的旧操作错误'));await new Promise(setImmediate);
  assert.equal(s.api.getStatus().enabled,true);
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

test('South selection preserves the current decision and is passed to the next queue', () => {
  const s=setup();s.turn();s.advice();s.api.setEnabled(true);
  const target=s.api.getStatus().timing.targetMs;
  s.advance(100);s.api.setRoundCount(2);
  for (const invalid of [0,3,'1',null]) s.api.setRoundCount(invalid);
  assert.equal(s.api.getStatus().roundCount,2);
  assert.equal(s.api.getStatus().timing.targetMs,target);
  s.advance(target-101);assert.equal(s.actions.length,0);
  s.advance(1);assert.equal(s.actions.length,1);
  let preference;
  s.window.__mjLobby.snapshot=(players,roundCount)=>{
    preference={players,roundCount};return {phase:'lobby',actionKey:`next:${players}:${roundCount}`};
  };
  s.tick();s.advance(3000);
  assert.deepEqual(preference,{players:4,roundCount:2});
  assert.deepEqual(s.starts,[{count:4,key:'next:4:2',roundCount:2}]);
});

test('changing match length invalidates the queued start and records the new preference', () => {
  const s=setup(),logs=[];
  s.window.__mjMonitor={reportAutomation:value=>logs.push(value)};
  s.window.__mjLobby.snapshot=(players,roundCount)=>({phase:'lobby',actionKey:`next:${players}:${roundCount}`});
  s.api.setEnabled(true);s.advance(1000);s.api.setRoundCount(2);
  s.advance(200);assert.equal(s.starts.length,0);
  s.advance(1199);assert.equal(s.starts.length,0);
  s.advance(1);assert.deepEqual(s.starts,[{count:4,key:'next:4:2',roundCount:2}]);
  assert.ok(logs.some(value=>value.roundCount===2));
  s.api.setEnabled(false);s.api.setRoundCount(1);
  assert.equal(s.api.getStatus().roundCount,1);
  s.advance(5000);assert.equal(s.starts.length,1);
});

test('client rejection and asynchronous request failures pause without retry', async () => {
  const s=setup();s.window.__mjUnityActions.execute=()=>Promise.reject(new Error('server rejected'));
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

test('native heartbeat ticks cannot act after automation is off or stopped', () => {
  for (const stop of [s=>s.api.setEnabled(false),s=>s.api.stop()]) {
    const s=setup();s.turn();s.advice();s.api.setEnabled(true);stop(s);
    Object.assign(s.lobby,{phase:'lobby',actionKey:'heartbeat-queue'});
    s.advance(5000);s.api.tick();s.advance(5000);s.api.tick();
    assert.equal(s.api.getStatus().enabled,false);
    assert.equal(s.actions.length,0);assert.equal(s.starts.length,0);
  }
});

test('unidentified startup waits are bounded without timing out login or matching', () => {
  const s = setup(); Object.assign(s.lobby, {phase:'loading', clientLoading:true});
  s.api.setEnabled(true); s.advance(60000); s.api.setPlayerCount(3); s.advance(29999);
  assert.equal(s.api.getStatus().enabled,true); s.advance(1);
  assert.equal(s.api.getStatus().enabled,false); assert.match(s.api.getStatus().message,/90 秒/);
  s.api.setEnabled(true); s.advance(89999); assert.equal(s.api.getStatus().enabled,true);
  Object.assign(s.lobby, {phase:'login', clientLoading:false}); s.advance(180000);
  assert.equal(s.api.getStatus().enabled,true);
  s.lobby.phase = 'matching'; s.advance(180000); assert.equal(s.api.getStatus().enabled,true);
  assert.equal(s.starts.length,0);
});

test('Unity result confirmation gates settlement and prevents re-enabling an unresolved action', () => {
  const s = setup(); s.window.__mjUnityTransport = {isUnity:() => true};
  Object.assign(s.lobby, {phase:'settlement', actionKey:'round:1'});
  s.api.setEnabled(true); s.client.pending = true; s.advance(5000);
  assert.equal(s.finishes.length,0);
  s.api.setEnabled(false); s.api.setEnabled(true); assert.equal(s.api.getStatus().enabled,false);
  s.client.pending = false; s.api.setEnabled(true); s.advance(3000);
  assert.deepEqual(s.finishes,['round:1']);
});

test('wins and forced riichi discards respond faster without changing the advised move', () => {
  const ordinary=responseTime({status:'ready',best:{action:'discard',tile:'7z'}});
  const win=responseTime({status:'win',action:'ron',best:null});
  const forced=responseTime({status:'ready',best:{action:'discard',tile:'7z'}}, {riichi:[true,false,false,false]});
  assert.ok(win.ms<ordinary.ms);assert.ok(forced.ms<ordinary.ms);
  assert.equal(win.s.actions[0].advice.action,'ron');
  assert.equal(forced.s.actions[0].advice.best.tile,'7z');
});

test('optional actions and warnings prevent the forced-discard shortcut', () => {
  const advice={status:'ready',best:{action:'discard',tile:'7z'}};
  const locked={riichi:[true,false,false,false]};
  const forced=responseTime(advice,locked).ms;
  for (const optional of [4,11]) {
    const measured=responseTime(advice,{...locked,operations:[1,optional],
      operationDetails:[{type:1,combination:[]},{type:optional,combination:[]}]}).ms;
    assert.ok(measured>forced,`operation ${optional} still requires a decision`);
  }
  assert.ok(responseTime({...advice,warnings:['an optional action could not be evaluated']},locked).ms>forced);
});

test('a clear comparable choice is quicker than close scores or conflicting routes', () => {
  const clear=responseTime(comparedAdvice()).ms;
  const close=responseTime(comparedAdvice(25)).ms;assert.ok(close>clear);
  for (const advice of [comparedAdvice(25,{}, {action:'riichi'}),
    comparedAdvice(25,{}, {currentStrategy:'fold'}),
    comparedAdvice(25,{}, {metricContext:'replacement'}),
    comparedAdvice(25,{decisionBasis:{scoreGap:25,componentAdvantages:{efficiency:1000,defense:-975}}})]) {
    assert.ok(responseTime(advice).ms>close);
  }
  assert.ok(responseTime({...comparedAdvice(),warnings:['one legal route was not evaluated']}).ms>clear);
});

test('unranked alternatives cannot supply evidence for the clear-choice shortcut', () => {
  const clear=responseTime(comparedAdvice()).ms;
  const incomplete={...comparedAdvice(),rankedCandidateCount:1};
  assert.ok(responseTime(incomplete).ms>clear);
});

test('same-window advice refresh preserves its start and sample but rejects the old key', () => {
  const s=setup();s.turn();s.advice(1,comparedAdvice());s.api.setEnabled(true);
  const planned=s.api.getStatus().timing;
  assert.ok(Number.isFinite(planned?.targetMs));
  s.advance(100);const calls=s.randomCalls;s.turn(2);s.advice(1,comparedAdvice());
  s.advance(planned.targetMs);assert.equal(s.actions.length,0);
  assert.equal(s.randomCalls,calls);
  s.advice(2,comparedAdvice());s.tick();assert.equal(s.actions.length,1);
  assert.ok(s.api.getStatus().timing.elapsedMs>=planned.targetMs);
});

test('a genuinely new operation window starts a new reaction budget', () => {
  const s=setup();s.turn();s.advice(1,comparedAdvice());s.api.setEnabled(true);s.advance(100);
  const calls=s.randomCalls;
  s.turn(2,{lastStep:4,operationTiming:{receivedAt:100,timeFixed:10000,timeAdd:10000},
    lastAction:{name:'ActionDealTile',seat:0,step:4,tile:'7z'}});
  s.advice(2,comparedAdvice());s.tick();
  assert.ok(s.randomCalls>calls);assert.equal(s.actions.length,0);
  assert.equal(s.api.getStatus().timing.elapsedMs,0);
  s.finishAction();assert.ok(s.actions[0].at>100);
});

test('harmless status refresh pauses execution without resampling the same operation window', () => {
  const s=setup();s.turn();s.advice(1,comparedAdvice());s.api.setEnabled(true);
  const planned=s.api.getStatus().timing.targetMs;s.advance(100);const calls=s.randomCalls;
  s.api.onEvent({kind:'status',phase:'playing'});s.advance(planned);
  assert.equal(s.actions.length,0);
  s.turn(2);s.advice(2,comparedAdvice());s.tick();
  assert.equal(s.randomCalls,calls);assert.equal(s.actions.length,1);
});

test('an enabled action budget starts at packet receipt before parsing or advice completes', () => {
  const s=setup();s.api.setEnabled(true);s.advance(750);s.turn();s.advice(1,comparedAdvice());s.tick();
  assert.equal(s.api.getStatus().timing.elapsedMs,750);
  const target=s.api.getStatus().timing.targetMs;s.finishAction();
  assert.ok(s.actions[0].at>=target && s.actions[0].at<target+100);
});

test('the session pace remains stable across successive windows', () => {
  let samples=0;
  const s=setup(()=>++samples===1?.1:.5);s.api.setEnabled(true);s.turn();s.advice(1,comparedAdvice());s.tick();
  const first=s.api.getStatus().timing.targetMs;s.finishAction();
  s.turn(2,{lastStep:4,operationTiming:{receivedAt:s.now,timeFixed:10000,timeAdd:10000}});
  s.advice(2,comparedAdvice());s.tick();assert.equal(s.api.getStatus().timing.targetMs,first);
});

test('late advice consumes the original budget and a short deadline remains authoritative', () => {
  const s=setup();s.turn();s.api.setEnabled(true);s.advance(6000);s.advice(1,comparedAdvice(25));s.tick();
  assert.equal(s.actions.length,1);
  const short=setup();short.turn();short.advice(1,comparedAdvice(25));short.client.remainingMs=300;
  short.api.setEnabled(true);assert.equal(short.actions.length,1);
  assert.equal(short.api.getStatus().timing.deadlineLimited,true);
});

test('bounded jitter favors shorter waits and does not depend on advice compute time', () => {
  function measured(sample) {
    let calls=0;
    return responseTime(comparedAdvice(25),{},()=>++calls===1?.5:sample).ms;
  }
  const low=measured(0),middle=measured(.5),high=measured(1);
  assert.ok(low<middle && middle<high);
  assert.ok(middle-low<(high-low)/2);
  assert.ok(high<6000);
});

function callThenDiscard({tile='1m',threat=false,pending=false,reset=false,newRound=false} = {}) {
  const s=setup();s.window.__mjUnityTransport={isUnity:()=>true};
  const call={action:'pon',consumed:['7z','7z'],calledTile:'7z',fromSeat:1,followupDiscard:'1m',
    currentStrategy:'push',metricContext:'followup'};
  s.turn(1,{canDiscard:false,operations:[3],operationDetails:[{type:3,combination:['7z|7z']}],
    lastAction:{name:'ActionDiscardTile',seat:1,step:3,tile:'7z'}});
  s.advice(1,{status:'ready',best:call});s.api.setEnabled(true);s.finishAction();
  if (reset) {
    if (reset==='disconnect') s.api.onEvent({kind:'status',phase:'disconnected'});
    else s.api.setEnabled(false);
    s.api.setEnabled(true);
  }
  const receivedAt=s.now;
  const action={name:'ActionChiPengGang',seat:0,step:4,type:1,tiles:['7z','7z','7z'],froms:[0,0,1]};
  s.client.pending=pending;
  s.turn(2,{lastStep:4,lastDraw:null,hand:['1m','2m','3m','4m','5m','6m','1p','2p','3p','1s','2s'],
    round:{chang:0,ju:newRound?1:0,ben:0},
    operationTiming:{receivedAt,timeFixed:10000,timeAdd:10000},lastAction:action,
    melds:[[{type:1,tiles:action.tiles,froms:action.froms}],[],[],[]],
    riichi:[false,threat,false,false]},action);
  s.advice(2,{status:'ready',best:{action:'discard',tile}});s.tick();
  return {s,receivedAt};
}

test('a confirmed call continues the planned discard faster, only while the plan remains valid', () => {
  const continued=callThenDiscard();continued.s.finishAction(2);
  const quick=continued.s.actions[1].at-continued.receivedAt;
  for (const changes of [{tile:'2m'},{threat:true},{reset:true},{reset:'disconnect'},{newRound:true}]) {
    const fresh=callThenDiscard(changes);fresh.s.finishAction(2);
    assert.ok(fresh.s.actions[1].at-fresh.receivedAt>quick);
  }
});

test('a follow-up plan never bypasses pending server confirmation', () => {
  const {s}=callThenDiscard({pending:true});s.advance(5000);assert.equal(s.actions.length,1);
  s.client.pending=false;s.tick();assert.equal(s.actions.length,2);
});

test('new opponent threats survive passive events and are consumed by one decision window', () => {
  for (const change of [{riichi:[false,true,false,false]},
    {melds:[[],[{type:1,tiles:['5m','5m','5m']}],[],[]]}, {doras:['3p','4p']}]) {
    const s=setup();s.turn(1,{canAct:false,canDiscard:false,operations:[],operationDetails:[]});s.api.setEnabled(true);
    s.turn(2,{...change,canAct:false,canDiscard:false,operations:[],operationDetails:[],lastStep:4});
    s.advance(100);
    s.turn(3,{...change,lastStep:5,operationTiming:{receivedAt:s.now,timeFixed:10000,timeAdd:10000}});
    s.advice(3,comparedAdvice());s.tick();
    const first=s.api.getStatus().timing?.targetMs;assert.ok(Number.isFinite(first));
    s.finishAction();
    s.turn(4,{...change,lastStep:6,operationTiming:{receivedAt:s.now,timeFixed:10000,timeAdd:10000}});
    s.advice(4,comparedAdvice());s.tick();
    assert.ok(first>s.api.getStatus().timing.targetMs);
  }
});

test('a game reset clears unconsumed threats even when the next game reuses its round identity', () => {
  const s=setup();s.turn(1,{canAct:false,canDiscard:false,operations:[],operationDetails:[]});s.api.setEnabled(true);
  s.turn(2,{riichi:[false,true,false,false],canAct:false,canDiscard:false,operations:[],operationDetails:[],lastStep:4});
  s.api.onEvent({kind:'status',phase:'ended',reset:true});
  s.advance(100);
  const action={name:'ActionNewRound',seat:0,step:0};
  s.turn(3,{lastStep:0,lastAction:action,operationTiming:{receivedAt:s.now,timeFixed:10000,timeAdd:10000}},action);
  s.advice(3,comparedAdvice());s.tick();
  assert.equal(s.api.getStatus().timing.category,'clear');
});

// A live heartbeat is deliberately not recovery progress. The native supervisor
// can now distinguish this incident from normal waiting for an opponent.
test('recovery snapshot remains stalled despite continuing heartbeat and repeated status callbacks', () => {
  const s=setup();s.turn();s.advice();s.api.setEnabled(true);
  s.api.onEvent({kind:'status',phase:'disconnected',recovery:{status:'waiting',reason:'connection'}});
  assert.ok(s.window.__mjRecovery, 'native recovery bridge must exist');
  const before=s.window.__mjRecovery.snapshot();
  for(let i=0;i<60;i++) {
    s.api.onEvent({kind:'heartbeat',phase:'disconnected'});
    s.api.onEvent({kind:'status',phase:'disconnected',recovery:{status:'waiting',reason:'connection'}});
    s.advance(10000);
  }
  const after=s.window.__mjRecovery.snapshot();
  assert.equal(after.enabled,true);assert.equal(after.stalled,true);
  assert.equal(after.progress,before.progress);assert.equal(s.actions.length,0);
  s.turn(2,{lastStep:4,operationTiming:{receivedAt:s.now,timeFixed:10000,timeAdd:10000}});
  assert.equal(s.window.__mjRecovery.snapshot().stalled,false);
  assert.ok(s.window.__mjRecovery.snapshot().progress>after.progress);
  s.advance(1000);assert.equal(s.actions.length,0);s.advice(2);s.finishAction();
});

function recoverySetup() {
  const s=setup(), checkpoints=[];
  const transport={connected:true,gameConnected:true,accountId:42,lastAccountId:42,progress:1,stalled:false};
  s.window.__mjUnityTransport={snapshot:()=>transport,isUnity:()=>true};
  s.window.__mjUnityActions.checkpoint=()=>({submitted:null});
  s.window.__mjUnityActions.restoreCheckpoint=value=>checkpoints.push(['actions',value]);
  s.window.__mjUnityLobby={checkpoint:()=>({owned:null,confirmation:null}),
    restoreCheckpoint:(value,account)=>checkpoints.push(['lobby',value,account])};
  return {...s,transport,checkpoints,bridge:s.window.__mjRecovery};
}
function prepareRecovery(s) {
  s.api.setPlayerCount(3);s.api.setRoundCount(2);s.api.setEnabled(true);
  s.api.onEvent({kind:'status',phase:'disconnected',recovery:{status:'waiting',reason:'connection'}});
  const value=s.bridge.snapshot();
  const prepared=s.bridge.prepare(value.session,value.revision,'one-shot');
  assert.equal(prepared.prepared,true);return prepared;
}

test('prepare freezes actions and validates each explicit user intent including repeated off',()=>{
  const s=recoverySetup();s.turn();s.advice();const prepared=prepareRecovery(s);
  assert.deepEqual(JSON.parse(JSON.stringify(prepared.checkpoint)),{enabled:true,playerCount:3,roundCount:2,
    accountId:42,actions:{submitted:null},lobby:{owned:null,confirmation:null}});
  s.turn(2,{lastStep:4});s.advice(2);s.advance(3000);assert.equal(s.actions.length,0);
  s.bridge.cancel('wrong');s.tick();assert.equal(s.actions.length,0);
  s.bridge.cancel('one-shot');s.tick();assert.equal(s.actions.length,1);
  s.api.setEnabled(false);const revision=s.bridge.snapshot().revision;s.api.setEnabled(false);
  assert.equal(s.bridge.snapshot().revision,revision+1);
  assert.equal(s.intents.at(-1).enabled,false);assert.equal(s.intents.at(-1).source,'user');
  assert.equal(s.bridge.prepare('session',prepared.revision,'old').prepared,false);
});

test('only an untouched new document restores selected modes and waits for login complete state and fresh advice',()=>{
  const previous=recoverySetup(), prepared=prepareRecovery(previous), fresh=recoverySetup();
  assert.equal(fresh.bridge.snapshot().enabled,false);assert.equal(fresh.intents[0].source,'init');
  fresh.transport.connected=false;fresh.transport.accountId=null;
  assert.equal(fresh.bridge.restore(prepared.checkpoint,'session',0,'one-shot').restored,true);
  assert.equal(fresh.checkpoints.length,2);assert.equal(fresh.api.getStatus().playerCount,3);
  assert.equal(fresh.api.getStatus().roundCount,2);assert.equal(fresh.intents.at(-1).source,'restore');
  fresh.turn();fresh.advice();fresh.advance(3000);assert.equal(fresh.actions.length,0);
  fresh.transport.connected=true;fresh.transport.accountId=42;
  fresh.turn(2,{lastStep:4,operationTiming:{receivedAt:fresh.now,timeFixed:10000,timeAdd:10000}});
  fresh.api.onAdvice({adviceKey:'session:1',advice:{status:'ready',best:{action:'discard',tile:'7z'}}});
  fresh.advance(3000);assert.equal(fresh.actions.length,0);fresh.advice(2);fresh.tick();
  assert.equal(fresh.actions.length,1);assert.equal(fresh.bridge.restore(prepared.checkpoint,'session',0,'one-shot').restored,false);
  const ordinary=setup();ordinary.advance(60000);assert.equal(ordinary.api.getStatus().enabled,false);
});

test('off manual touch mode edits and fatal errors all reject a late document restore',()=>{
  const checkpoint=prepareRecovery(recoverySetup()).checkpoint;
  for(const touch of [s=>s.api.setEnabled(false),s=>s.api.setPlayerCount(4),s=>s.api.setRoundCount(1),
    s=>s.listeners.get('pointerdown')({isTrusted:true,composedPath:()=>[]}),
    s=>s.api.onEvent({kind:'error',message:'bad frame'})]) {
    const s=recoverySetup();touch(s);
    assert.equal(s.bridge.restore(checkpoint,'session',0,'one-shot').restored,false);
    assert.equal(s.checkpoints.length,0);assert.equal(s.api.getStatus().enabled,false);
  }
  const s=recoverySetup();assert.equal(s.bridge.restore(checkpoint,'wrong-page',0,'one-shot').restored,false);
});

test('late native failure cannot overwrite a user stop or fatal error, and client sends revoke prepared credentials',()=>{
  for(const action of [s=>s.api.onInput(),s=>s.bridge.onClientAction()]) {
    const s=recoverySetup(), prepared=prepareRecovery(s);action(s);
    assert.equal(s.api.getStatus().enabled,false);assert.ok(s.bridge.snapshot().revision>prepared.revision);
    assert.equal(s.intents.at(-1).source,'pause');
  }
  const s=recoverySetup(), prepared=prepareRecovery(s);s.api.setEnabled(false);
  s.bridge.fail('session',prepared.revision,'old timeout');assert.match(s.api.getStatus().message,/已关闭/);
  const e=recoverySetup();prepareRecovery(e);e.api.onEvent({kind:'error',message:'invalid'});
  const before=e.api.getStatus().message;e.bridge.fail('session',e.bridge.snapshot().revision,'max retries');
  assert.equal(e.api.getStatus().message,before);
  const t=recoverySetup(), p=prepareRecovery(t);t.bridge.fail('session',p.revision,'恢复已达次数上限');
  assert.equal(t.api.getStatus().enabled,false);assert.match(t.api.getStatus().message,/次数上限/);
});

test('missing stable replay guard or changed account fails closed without carrying hand or advice',()=>{
  const s=recoverySetup();s.window.__mjUnityActions.checkpoint=()=>{throw new Error('missing UUID');};
  s.api.setEnabled(true);s.api.onEvent({kind:'status',phase:'disconnected'});
  const value=s.bridge.snapshot(), result=s.bridge.prepare(value.session,value.revision,'one-shot');
  assert.equal(result.prepared,false);assert.match(result.reason,/UUID/);
  const checkpoint=prepareRecovery(recoverySetup()).checkpoint, fresh=recoverySetup();
  fresh.bridge.restore(checkpoint,'session',0,'one-shot');fresh.transport.accountId=99;fresh.tick();
  assert.equal(fresh.api.getStatus().enabled,false);assert.match(fresh.api.getStatus().message,/账号已变化/);
  assert.equal(fresh.actions.length,0);
});

test('a controlled new page with no authentication remains stalled while ordinary startup does not',()=>{
  const checkpoint=prepareRecovery(recoverySetup()).checkpoint, s=recoverySetup();
  s.transport.connected=false;s.transport.gameConnected=false;s.transport.accountId=null;s.transport.lastAccountId=null;
  s.lobby.phase='login';
  assert.equal(s.bridge.snapshot().stalled,false);
  s.bridge.restore(checkpoint,'session',0,'one-shot');
  const first=s.bridge.snapshot();assert.equal(first.stalled,true);
  s.advance(60000);assert.equal(s.bridge.snapshot().stalled,true);
  assert.equal(s.bridge.snapshot().progress,first.progress);assert.equal(s.api.getStatus().enabled,true);
  const retry=s.bridge.prepare(first.session,first.revision,'second-reload');
  assert.equal(retry.prepared,true);assert.equal(retry.checkpoint.accountId,42);s.bridge.cancel('second-reload');
  s.transport.connected=true;s.transport.accountId=42;s.transport.progress++;
  s.lobby.phase='lobby';s.lobby.recoveryReady=true;s.tick();
  assert.equal(s.bridge.snapshot().stalled,false);assert.ok(s.bridge.snapshot().progress>first.progress);
});

test('explicit enable after a restored account mismatch creates fresh user intent',()=>{
  const checkpoint=prepareRecovery(recoverySetup()).checkpoint,s=recoverySetup();let begins=0;
  s.window.__mjUnityLobby.beginIntent=()=>begins++;
  s.bridge.restore(checkpoint,'session',0,'one-shot');s.transport.accountId=99;s.tick();
  assert.equal(s.api.getStatus().enabled,false);s.api.setEnabled(true);
  assert.equal(begins,1);assert.equal(s.api.getStatus().enabled,true);
});
