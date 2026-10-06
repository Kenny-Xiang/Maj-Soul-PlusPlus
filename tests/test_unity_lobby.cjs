const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const core = require('../src/core.cjs');
const source = fs.readFileSync(require.resolve('../src/unity_lobby.js'), 'utf8');
const encoder = new TextEncoder(), decoder = new TextDecoder();
function encode(entries) {
  const b = [], uint = n => {do {const x = n % 128; n = Math.floor(n / 128); b.push(x | (n ? 128 : 0));} while(n);};
  for (const [field, value] of entries) {
    if (typeof value === 'number') {uint(field * 8); uint(value);}
    else {const v = typeof value === 'string' ? encoder.encode(value) : value; uint(field * 8 + 2); uint(v.length); b.push(...v);}
  }
  return new Uint8Array(b);
}
const first = (f, n, fallback = 0) => f.get(n)?.[0] ?? fallback;
const str = (f, n) => f.has(n) ? decoder.decode(first(f, n)) : null;
function account(id = 42, rank = 10201, gold = 3000, rank3 = 20201, roomId = 0) {
  return encode([[1,id], [5,roomId], [11,gold], [21,encode([[1,rank]])], [22,encode([[1,rank3]])]]);
}
function harness() {
  let now = 0, listener;
  const live = {connected:true, gameConnected:false, accountId:42, lobbySessionId:1, gameSessionId:2};
  const calls = [];
  const transport = {isUnity:()=>true, snapshot:() => ({...live}), onMessage:fn => {listener=fn;},
    request(method,payload,options) {
      let resolve, reject;
      const promise = new Promise((a,b) => {resolve=a; reject=b;});
      const call = {method,payload,options,resolve,reject}; calls.push(call);
      emit(method,payload,{direction:'out',kind:'request',game:options.game,injected:true});
      return promise;
    }};
  const window = {__mjProtocol:{fields:core.fields,first,str,encode,action:core.action},__mjUnityTransport:transport};
  vm.runInNewContext(source,{window,location:{hostname:'game.maj-soul.com'},performance:{now:()=>now},Uint8Array,console});
  function emit(method,payload=encode([]),extra={}) {
    const game = extra.game || method.startsWith('.lq.FastTest.') || method === '.lq.NotifyGameEndResult';
    listener({method,payload,direction:'in',kind:'notify',game,sessionId:game?live.gameSessionId:live.lobbySessionId,injected:false,...extra});
  }
  emit('.lq.Lobby.oauth2Login',encode([[10,'WebGL_2022-0.16.257']]),{direction:'out',kind:'request'});
  return {api:window.__mjUnityLobby,calls,live,emit,advance:ms=>{now+=ms;},
    async refresh(data=account()) {
      const s=this.api.snapshot(); assert.equal(s.action,'refresh');
      const result=this.api.start(4,s.actionKey);
      calls.at(-1).resolve({payload:encode([[2,data]])});
      assert.equal((await result).ok,true);
    }};
}
const flush = async () => {await Promise.resolve(); await Promise.resolve(); await Promise.resolve();};

test('fresh account refresh chooses highest permitted East room using separate sanma rank and gold',async()=>{
  const h=harness(); await h.refresh();
  assert.equal(h.calls[0].method,'.lq.Lobby.fetchAccountInfo');
  assert.equal(first(core.fields(h.calls[0].payload),1),42);
  assert.equal(h.api.snapshot().modeId,5); assert.equal(h.api.snapshot(3).modeId,19);
  const old=h.api.snapshot().actionKey;
  h.emit('.lq.Lobby.fetchAccountInfo',encode([[2,account(42,10201,1000,20201)]]),{kind:'response'});
  assert.equal(h.api.snapshot().modeId,2);
  assert.equal((await h.api.start(4,old)).ok,false); assert.equal(h.calls.length,1);
});

test('match start serializes official sid/version, native notification and auth confirm entry',async()=>{
  const h=harness(); await h.refresh(); const s=h.api.snapshot();
  const started=h.api.start(4,s.actionKey); const c=h.calls.at(-1);
  assert.equal(c.method,'.lq.Lobby.startUnifiedMatch');
  assert.equal(str(core.fields(c.payload),1),'1:5');
  assert.equal(str(core.fields(c.payload),2),'WebGL_2022-0.16.257');
  assert.equal(h.api.snapshot().phase,'matching');
  c.resolve({payload:encode([])}); assert.equal((await started).ok,true);
  assert.equal(h.api.snapshot().phase,'matching');
  h.emit('.lq.NotifyMatchGameStart',encode([[4,5]]));
  assert.equal(h.api.snapshot().phase,'matching');
  h.live.gameConnected=true; h.emit('.lq.FastTest.authGame',encode([]),{kind:'response',game:true});
  assert.equal(h.api.snapshot().phase,'playing');
  assert.equal(h.api.cancel().ok,true);
});

test('round completion confirms once, original client confirmation cancels delayed duplicate',async()=>{
  const h=harness(); await h.refresh(); h.live.gameConnected=true;
  h.api.onEvent({kind:'turn',state:{phase:'between_rounds'},action:{name:'ActionHule',step:9,matchEnd:false}});
  const s=h.api.snapshot(); assert.equal(s.action,'confirm');
  h.emit('.lq.FastTest.confirmNewRound',encode([]),{game:true,direction:'out',kind:'request'});
  assert.equal((await h.api.finish(s.actionKey)).ok,false); assert.equal(h.calls.length,1);
  h.api.onEvent({kind:'turn',state:{phase:'between_rounds'},action:{name:'ActionNoTile',step:20,matchEnd:false}});
  const finish=h.api.finish(h.api.snapshot().actionKey);
  assert.equal(h.calls.at(-1).method,'.lq.FastTest.confirmNewRound');
  h.calls.at(-1).resolve({payload:encode([])}); assert.equal((await finish).ok,true);
  assert.equal((await h.api.finish(s.actionKey)).ok,false);
});

test('whole-game end waits 45 seconds, refreshes rank before picking the next room',async()=>{
  const h=harness(); await h.refresh();
  h.api.onEvent({kind:'turn',state:{phase:'ended'},action:{name:'ActionHule',matchEnd:true}});
  assert.equal(h.api.snapshot().phase,'settlement'); assert.equal(h.api.snapshot().actionKey,undefined);
  h.advance(44000); h.emit('.lq.NotifyGameEndResult'); h.advance(1000);
  await h.refresh(account(42,10301,6000,20301));
  assert.equal(h.api.snapshot().modeId,8); assert.equal(h.api.snapshot(3).modeId,21);
});

test('manual queue is observed but never cancelled by automation',async()=>{
  const h=harness(); await h.refresh();
  h.emit('.lq.Lobby.startUnifiedMatch',encode([[1,'1:2'],[2,'WebGL_current']]),{direction:'out',kind:'request'});
  assert.equal(h.api.snapshot().phase,'matching'); assert.equal(h.api.cancel().ok,true);
  assert.equal(h.calls.length,1);
  h.emit('.lq.Lobby.cancelUnifiedMatch',encode([]),{kind:'response',requestPayload:encode([[1,'1:2']])});
  assert.equal(h.api.snapshot().phase,'lobby');
});

test('turning off during match submission cancels own queue after response and permits reopening',async()=>{
  const h=harness(); await h.refresh(); const started=h.api.start(4,h.api.snapshot().actionKey);
  assert.equal(h.api.cancel().pending,true); assert.equal(h.calls.length,2);
  h.calls.at(-1).resolve({payload:encode([])}); await started;
  assert.equal(h.api.cancel().pending,true); assert.equal(h.calls.at(-1).method,'.lq.Lobby.cancelUnifiedMatch');
  h.calls.at(-1).resolve({payload:encode([])}); await flush();
  assert.equal(h.api.cancel().ok,true); assert.equal(h.api.snapshot().phase,'lobby');
});

test('old account refresh and queue cannot be used on a newly logged-in account',async()=>{
  const h=harness(), s=h.api.snapshot(); const refresh=h.api.start(4,s.actionKey);
  h.live.accountId=99; h.api.snapshot();
  h.calls[0].resolve({payload:encode([[2,account()]])});
  assert.equal((await refresh).ok,false);
  await h.refresh(account(99));
  const start=h.api.start(4,h.api.snapshot().actionKey);
  h.live.accountId=100; h.api.snapshot(); h.calls.at(-1).resolve({payload:encode([])});
  assert.equal((await start).ok,false); assert.equal(h.api.cancel().ok,true);
  assert.equal(h.calls.filter(c=>c.method.includes('cancel')).length,0);
});

test('disconnected ownership survives only for the same account and cancels on new lobby session',async()=>{
  const h=harness(); await h.refresh(); const start=h.api.start(4,h.api.snapshot().actionKey);
  h.calls.at(-1).resolve({payload:encode([])}); await start;
  h.live.connected=false; h.live.accountId=null;
  assert.equal(h.api.snapshot().phase,'login'); assert.equal(h.api.cancel().pending,true);
  h.live.connected=true; h.live.accountId=42; h.live.lobbySessionId=3;
  assert.equal(h.api.cancel().pending,true); assert.equal(h.calls.at(-1).method,'.lq.Lobby.cancelUnifiedMatch');
  h.calls.at(-1).resolve({payload:encode([])}); await flush(); assert.equal(h.api.cancel().ok,true);
});

test('refresh failure and missing/mismatching account do not create a queue',async()=>{
  for (const response of [null,encode([]),encode([[2,account(99)]])]) {
    const h=harness(); const action=h.api.start(4,h.api.snapshot().actionKey);
    if(response) h.calls[0].resolve({payload:response}); else h.calls[0].reject(new Error('timeout'));
    assert.equal((await action).ok,false); assert.equal(h.calls.length,1);
  }
});

test('native rank notification invalidates pending action and forces fresh eligibility',async()=>{
  const h=harness(); await h.refresh(); const key=h.api.snapshot().actionKey;
  h.emit('.lq.NotifyAccountLevelChange');
  assert.equal(h.api.snapshot().action,'refresh'); assert.equal((await h.api.start(4,key)).ok,false);
  h.emit('.lq.Lobby.fetchAccountInfo',encode([[2,account(123,10720,999999)]]),{kind:'response'});
  await h.refresh(account(42,10201,0)); assert.equal(h.api.snapshot().modeId,2);
});

test('notifications from stale sockets cannot enter games and both entry and queue waits are bounded',async()=>{
  const h=harness(); await h.refresh();
  h.emit('.lq.NotifyMatchGameStart',encode([]),{sessionId:999}); assert.equal(h.api.snapshot().phase,'lobby');
  h.emit('.lq.NotifyMatchGameStart'); h.advance(30001); assert.equal(h.api.snapshot().phase,'blocked');
  const g=harness(); await g.refresh(); const action=g.api.start(4,g.api.snapshot().actionKey);
  g.calls.at(-1).resolve({payload:encode([])}); await action;
  g.advance(180001); assert.equal(g.api.snapshot().phase,'blocked'); assert.equal(g.api.cancel().pending,true);
});

test('room membership and invalid ranks reject matching; login with existing game waits for client recovery',async()=>{
  const h=harness(); await h.refresh(account(42,10201,3000,20201,123)); assert.equal(h.api.snapshot().phase,'blocked');
  const g=harness(); await g.refresh(account(42,20201)); assert.equal(g.api.snapshot().phase,'blocked');
  const j=harness(); j.emit('.lq.Lobby.oauth2Login',encode([[2,42],[3,account()],[4,encode([[3,'existing-game']])]]),{kind:'response'});
  assert.equal(j.api.snapshot().phase,'matching'); assert.equal(j.calls.length,0);
});

test('actual core round-end state triggers confirmation once for win, exhaustive and abortive draws',async()=>{
  for (const name of ['ActionHule','ActionNoTile','ActionLiuJu']) {
    const h=harness(), state=core.emptyState(); state.phase='playing';
    const action={name,step:30,matchEnd:false};
    core.apply(state,action); assert.equal(state.phase,'between_rounds');
    h.api.onEvent({kind:'turn',state,action});
    const key=h.api.snapshot().actionKey; assert.ok(key?.startsWith('round:'));
    const result=h.api.finish(key);
    assert.equal(h.calls.at(-1).method,'.lq.FastTest.confirmNewRound');
    h.calls.at(-1).resolve({payload:encode([])}); await result;
    h.api.onEvent({kind:'turn',state,action});
    assert.equal(h.api.snapshot().actionKey,undefined); assert.equal(h.calls.length,1);
  }
});

test('late start response cancels without further engine polling',async()=>{
  const h=harness(); await h.refresh(); const start=h.api.start(4,h.api.snapshot().actionKey);
  h.api.cancel(); h.advance(6000);
  h.calls.at(-1).resolve({payload:encode([])}); await start;
  assert.equal(h.calls.at(-1).method,'.lq.Lobby.cancelUnifiedMatch');
  assert.equal(h.calls.length,3);
});

test('closing during account refresh discards the response without starting a queue',async()=>{
  const h=harness(); const refresh=h.api.start(4,h.api.snapshot().actionKey);
  h.api.cancel(); h.calls[0].resolve({payload:encode([[2,account()]])});
  assert.equal((await refresh).ok,false); assert.equal(h.api.snapshot().action,'refresh');
  assert.equal(h.calls.length,1);
});

test('termination and a mismatching matched mode stop automatic operation',async()=>{
  const h=harness(); h.emit('.lq.NotifyGameTerminate',encode([]),{game:true});
  assert.equal(h.api.snapshot().phase,'blocked');
  const g=harness(); await g.refresh(); const start=g.api.start(4,g.api.snapshot().actionKey);
  g.calls.at(-1).resolve({payload:encode([])}); await start;
  g.emit('.lq.NotifyMatchGameStart',encode([[4,19]]));
  assert.equal(g.api.snapshot().phase,'blocked');
});

test('unrelated manual cancel and timeout do not clear an existing queue',async()=>{
  const h=harness(); await h.refresh();
  h.emit('.lq.Lobby.startUnifiedMatch',encode([[1,'1:2'],[2,'WebGL_current']]),{direction:'out',kind:'request'});
  h.emit('.lq.Lobby.cancelUnifiedMatch',encode([]),{kind:'response',requestPayload:encode([[1,'1:19']])});
  h.emit('.lq.NotifyMatchTimeout',encode([[1,'1:19']]));
  assert.equal(h.api.snapshot().phase,'matching');
});

test('native confirm before collector delivery cannot re-arm the same round',async()=>{
  const h=harness(), plain=encode([[5,25000]]), keys=[132,94,78,66,57,162,31,96,28];
  const scrambled=plain.map((b,i)=>b^(((23^plain.length)+5*i+keys[i%9])&255));
  const payload=encode([[1,99],[2,'ActionHule'],[3,scrambled]]);
  h.emit('.lq.ActionPrototype',payload,{game:true});
  assert.equal(h.api.snapshot().action,'confirm');
  h.emit('.lq.FastTest.confirmNewRound',encode([]),{game:true,direction:'out',kind:'request'});
  const action=core.action(payload),state=core.emptyState(); state.phase='playing'; core.apply(state,action);
  h.api.onEvent({kind:'turn',state,action});
  assert.equal(h.api.snapshot().actionKey,undefined); assert.equal(h.calls.length,0);
});

test('explicit match rejection clears ownership while transport uncertainty retains cancellation',async()=>{
  const h=harness(); await h.refresh(); const start=h.api.start(4,h.api.snapshot().actionKey);
  const error=new Error('rejected');error.code=1303;
  h.calls.at(-1).reject(error); assert.equal((await start).ok,false);
  assert.equal(h.api.cancel().pending,undefined); assert.equal(h.calls.length,2);
  const g=harness(); await g.refresh(); const pending=g.api.start(4,g.api.snapshot().actionKey);
  g.calls.at(-1).reject(new Error('timeout')); assert.equal((await pending).ok,false);
  assert.equal(g.api.cancel().pending,true); assert.equal(g.calls.at(-1).method,'.lq.Lobby.cancelUnifiedMatch');
});

test('a new round resets confirmation deduplication when terminal action names and steps repeat',async()=>{
  const h=harness();
  const action={name:'ActionNoTile',step:99,matchEnd:false};
  const actionKeys=[];
  for (let i=0;i<2;i++) {
    h.api.onEvent({kind:'turn',state:{phase:'playing'},action:{name:'ActionNewRound',step:0}});
    h.api.onEvent({kind:'turn',state:{phase:'between_rounds'},action});
    assert.equal(h.api.snapshot().action,'confirm');
    actionKeys.push(h.api.snapshot().actionKey);
    const result=h.api.finish(h.api.snapshot().actionKey);
    h.calls.at(-1).resolve({payload:encode([])}); await result;
  }
  assert.equal(h.calls.length,2); assert.notEqual(actionKeys[0],actionKeys[1]);
});

test('confirmation ACK waits for a real new round with a bounded timeout, and native rejection stops',async()=>{
  const h=harness();
  h.api.onEvent({kind:'turn',state:{phase:'between_rounds'},action:{name:'ActionNoTile',step:99,matchEnd:false}});
  const result=h.api.finish(h.api.snapshot().actionKey);
  h.calls.at(-1).resolve({payload:encode([])}); await result;
  h.advance(30001); assert.equal(h.api.snapshot().phase,'blocked');
  const g=harness();
  g.emit('.lq.FastTest.confirmNewRound',encode([]),{direction:'out',kind:'request',game:true});
  g.emit('.lq.FastTest.confirmNewRound',encode([[1,encode([[1,1004]])]]),{kind:'response',game:true});
  assert.equal(g.api.snapshot().phase,'blocked');
});

test('a requested cancellation resumes after same-account reconnect without engine polling',async()=>{
  const h=harness(); await h.refresh(); const started=h.api.start(4,h.api.snapshot().actionKey);
  h.calls.at(-1).resolve({payload:encode([])}); await started;
  h.live.connected=false; h.live.accountId=null; h.api.cancel();
  h.live.connected=true; h.live.accountId=42; h.live.lobbySessionId=3;
  h.emit('.lq.Lobby.oauth2Login',encode([[2,42],[3,account()]]),{kind:'response'});
  assert.equal(h.calls.at(-1).method,'.lq.Lobby.cancelUnifiedMatch');
  assert.equal(h.calls.length,3);
});
