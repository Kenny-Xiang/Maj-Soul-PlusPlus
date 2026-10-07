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
  return encode([[1,id], [5,roomId], ...(gold === null ? [] : [[11,gold]]),
    ...(rank === null ? [] : [[21,encode([[1,rank]])]]),
    ...(rank3 === null ? [] : [[22,encode([[1,rank3]])]])]);
}
function accountResponse(request, privateAccount) {
  // The official client's own-account refresh sends {}. An explicit account_id
  // requests a public profile, which does not contain the private gold balance.
  const publicProfile = first(core.fields(request),1) !== 0;
  const fields = [...core.fields(privateAccount)].flatMap(([id, values]) =>
    publicProfile && id === 11 ? [] : values.map(value => [id,value]));
  return encode([[2,encode(fields)]]);
}
function harness({gameConnected = false, onLobbyRecovery = () => {}} = {}) {
  let now = 0, listener;
  const live = {connected:true, gameConnected, accountId:42, lobbySessionId:1, gameSessionId:2};
  const calls = [];
  const transport = {isUnity:()=>true, snapshot:() => ({...live}), onMessage:fn => {listener=fn;},
    request(method,payload,options) {
      let resolve, reject;
      const promise = new Promise((a,b) => {resolve=a; reject=b;});
      const call = {method,payload,options,resolve,reject}; calls.push(call);
      emit(method,payload,{direction:'out',kind:'request',game:options.game,injected:true});
      return promise;
    }};
  const window = {__mjProtocol:{fields:core.fields,first,str,encode,action:core.action},__mjUnityTransport:transport,
    __mjMonitor:{onLobbyRecovery}};
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
      const request=calls.at(-1);
      request.resolve({payload:accountResponse(request.payload,data)});
      assert.equal((await result).ok,true);
    }};
}
const flush = async () => {await Promise.resolve(); await Promise.resolve(); await Promise.resolve();};

test('fresh account refresh chooses highest permitted East room using separate sanma rank and gold',async()=>{
  const h=harness(); await h.refresh();
  assert.equal(h.calls[0].method,'.lq.Lobby.fetchAccountInfo');
  assert.equal(h.calls[0].payload.length,0, 'own private-account refresh must send an empty payload');
  assert.equal(h.api.snapshot().modeId,5); assert.equal(h.api.snapshot(3).modeId,19);
  const old=h.api.snapshot().actionKey;
  h.emit('.lq.Lobby.fetchAccountInfo',encode([[2,account(42,10201,1000,20201)]]),
    {kind:'response',requestPayload:encode([])});
  assert.equal(h.api.snapshot().modeId,2);
  assert.equal((await h.api.start(4,old)).ok,false); assert.equal(h.calls.length,1);
});

test('request-aware server returns private gold only for an empty self query, allowing both gold East rooms',async()=>{
  const full=account(42,10301,30000,20301), h=harness();
  const profile=accountResponse(encode([[1,42]]),full);
  assert.equal(core.fields(first(core.fields(profile),2)).has(11),false);
  assert.equal(first(core.fields(first(core.fields(accountResponse(encode([]),full)),2)),11),30000);
  await h.refresh(full);
  assert.equal(h.api.snapshot(4).modeId,8, 'four-player 雀杰 should reach 金之间 with the private gold balance');
  assert.equal(h.api.snapshot(3).modeId,21, 'three-player 雀杰 should use its separate rank and reach 金之间');
  assert.equal(h.calls[0].payload.length,0);
});

test('native public profiles, including our own ID, cannot overwrite private gold or invalidate a match key',async()=>{
  const h=harness(); await h.refresh(account(42,10301,30000,20301));
  const key=h.api.snapshot(4).actionKey;
  for (const id of [42,99]) {
    h.emit('.lq.Lobby.fetchAccountInfo',encode([[2,account(id,10301,null,20301)]]),
      {kind:'response',requestPayload:encode([[1,id]])});
    assert.equal(h.api.snapshot(4).modeId,8);
    assert.equal(h.api.snapshot(3).modeId,21);
    assert.equal(h.api.snapshot(4).actionKey,key);
  }
  // A response without its originating request is not proof of a self query.
  h.emit('.lq.Lobby.fetchAccountInfo',encode([[2,account(42,10301,null,20301)]]),{kind:'response'});
  assert.equal(h.api.snapshot(4).actionKey,key);
  const started=h.api.start(4,key);
  assert.equal(h.calls.at(-1).method,'.lq.Lobby.startUnifiedMatch');
  h.calls.at(-1).resolve({payload:encode([])}); assert.equal((await started).ok,true);
});

test('known native self responses honor proto3 omitted gold as zero and invalidate old eligibility',async()=>{
  for (const requestPayload of [encode([]),encode([[1,0]])]) {
    const h=harness(); await h.refresh(account(42,10201,3000,20201));
    const old=h.api.snapshot().actionKey;
    h.emit('.lq.Lobby.fetchAccountInfo',encode([[2,account(42,10201,null,20201)]]),
      {kind:'response',requestPayload});
    assert.equal(h.api.snapshot(4).modeId,2);
    assert.equal(h.api.snapshot(3).modeId,17);
    assert.notEqual(h.api.snapshot().actionKey,old);
    assert.equal((await h.api.start(4,old)).ok,false);
    assert.equal(h.calls.length,1);
  }
});

test('an own refresh with omitted gold is valid zero, while missing or invalid ranks report a different problem',async()=>{
  const zero=harness(); await zero.refresh(account(42,10301,null,20301));
  assert.equal(zero.api.snapshot().phase,'blocked');
  assert.match(zero.api.snapshot().message,/金币/);
  for (const rank of [null,20201]) {
    const invalid=harness(); await invalid.refresh(account(42,rank,30000,20301));
    assert.equal(invalid.api.snapshot().phase,'blocked');
    assert.match(invalid.api.snapshot().message,/段位/);
    assert.notEqual(invalid.api.snapshot().message,zero.api.snapshot().message);
    assert.equal(invalid.api.snapshot(3).modeId,21);
  }
});

test('disabling invalidates cached eligibility so reopening refreshes recovered gold before matching',async()=>{
  const h=harness(); await h.refresh(account(42,10301,null,20301));
  assert.equal(h.api.snapshot().phase,'blocked');
  assert.equal(h.api.cancel().ok,true);
  assert.equal(h.api.snapshot().action,'refresh');
  await h.refresh(account(42,10301,6000,20301));
  assert.equal(h.calls.length,2);
  assert.ok(h.calls.every(call=>call.method==='.lq.Lobby.fetchAccountInfo' && call.payload.length===0));
  assert.equal(h.api.snapshot(4).modeId,8); assert.equal(h.api.snapshot(3).modeId,21);
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
    const h=harness({gameConnected:true}), state=core.emptyState(); state.phase='playing';
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
  const h=harness({gameConnected:true}), plain=encode([[5,25000]]), keys=[132,94,78,66,57,162,31,96,28];
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
  const h=harness({gameConnected:true});
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
  const h=harness({gameConnected:true});
  h.api.onEvent({kind:'turn',state:{phase:'between_rounds'},action:{name:'ActionNoTile',step:99,matchEnd:false}});
  const result=h.api.finish(h.api.snapshot().actionKey);
  h.calls.at(-1).resolve({payload:encode([])}); await result;
  h.advance(30001); assert.equal(h.api.snapshot().phase,'reconnecting');
  assert.equal(h.api.snapshot().recoveryStalled,true);
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

test('whole-game settlement exposes a countdown and offers the next match refresh at 45 seconds',async()=>{
  const h=harness(); await h.refresh();
  h.emit('.lq.NotifyGameEndResult');
  const initial=h.api.snapshot(3);
  assert.equal(initial.phase,'settlement');
  assert.equal(initial.remainingMs,45000);
  assert.equal(initial.message,'结算等待 · 45 秒后准备下一场');
  assert.equal(initial.actionKey,undefined);
  h.advance(26000);
  const later=h.api.snapshot(3);
  assert.equal(later.remainingMs,19000);
  assert.equal(later.message,'结算等待 · 19 秒后准备下一场');
  h.advance(14000);
  const nearEnd=h.api.snapshot(3);
  assert.equal(nearEnd.remainingMs,5000);
  assert.equal(nearEnd.message,'结算等待 · 5 秒后准备下一场');
  assert.equal(h.calls.length,1,'countdown polling must not send a refresh or match request');
  h.advance(4999);
  assert.equal(h.api.snapshot(3).phase,'settlement');
  assert.equal(h.api.snapshot(3).actionKey,undefined);
  h.advance(1);
  const ready=h.api.snapshot(3);
  assert.equal(ready.phase,'lobby');
  assert.equal(ready.action,'refresh');
  assert.ok(ready.actionKey,'the controller can now schedule a fresh eligibility check');
});

test('disabling and rechecking automation or duplicate end notifications do not restart settlement waiting',async()=>{
  const h=harness(); await h.refresh();
  h.api.onEvent({kind:'status',phase:'ended'});
  h.advance(26000);
  // The controller calls cancel when disabled and snapshot again when enabled.
  assert.equal(h.api.cancel().ok,true);
  assert.equal(h.api.snapshot().remainingMs,19000);
  h.api.onEvent({kind:'status',phase:'ended'});
  h.emit('.lq.NotifyGameEndResult');
  assert.equal(h.api.snapshot().remainingMs,19000);
  h.advance(14000);
  assert.equal(h.api.cancel().ok,true);
  h.api.onEvent({kind:'status',phase:'ended'});
  assert.equal(h.api.snapshot().remainingMs,5000);
  h.advance(5000);
  const next=h.api.snapshot();
  assert.equal(next.phase,'lobby');
  assert.equal(next.action,'refresh');
  assert.equal(h.calls.length,1,'cancel/re-enable must neither match early nor restart the wait');
});

for (const [players, rounds, modeId, label] of [
  [4,1,8,'四麻东风'], [4,2,9,'四麻南风'], [3,1,21,'三麻东风'], [3,2,22,'三麻南风'],
]) test(`ranked ${label} uses its official match mode in the request`,async()=>{
  const h=harness(); await h.refresh(account(42,10301,7000,20301));
  const s=h.api.snapshot(players,rounds);
  assert.equal(s.modeId,modeId); assert.equal(s.roomName,'金之间');
  assert.equal(s.message,`准备匹配金之间 · ${label}`);
  const started=h.api.start(players,s.actionKey,rounds);
  assert.equal(h.calls.at(-1).method,'.lq.Lobby.startUnifiedMatch');
  assert.equal(str(core.fields(h.calls.at(-1).payload),1),`1:${modeId}`);
  h.calls.at(-1).resolve({payload:encode([])}); assert.equal((await started).ok,true);
});

test('omitting round count retains East defaults for both player counts',async()=>{
  const h=harness(); await h.refresh(account(42,10301,7000,20301));
  for (const players of [3,4]) {
    assert.equal(h.api.snapshot(players).actionKey,h.api.snapshot(players,1).actionKey);
    assert.match(h.api.snapshot(players).message,/东风$/);
  }
});

test('South gold thresholds select the highest affordable eligible room, independently of East',async()=>{
  // Thresholds are the official desktop.matchmode values, not East-mode limits.
  for (const [rank, gold, east4, south4, east3, south3] of [
    [10101,0,2,3,17,18],
    [10201,3499,5,3,19,18], [10201,3500,5,6,19,20],
    [10301,6999,8,6,21,20], [10301,7000,8,9,21,22],
    [10401,13999,11,9,23,22], [10401,14000,11,12,23,24],
    [10501,14000,15,16,25,26],
  ]) {
    const h=harness(); await h.refresh(account(42,rank,gold,rank+10000));
    assert.equal(h.api.snapshot(4,1).modeId,east4,`four East rank=${rank} gold=${gold}`);
    assert.equal(h.api.snapshot(4,2).modeId,south4,`four South rank=${rank} gold=${gold}`);
    assert.equal(h.api.snapshot(3,1).modeId,east3,`three East rank=${rank} gold=${gold}`);
    assert.equal(h.api.snapshot(3,2).modeId,south3,`three South rank=${rank} gold=${gold}`);
  }
});

test('South reports its own minimum when no lower room is eligible; ordinary rooms have no gold ceiling',async()=>{
  const h=harness(); await h.refresh(account(42,10501,13999,20501));
  for (const players of [3,4]) {
    const s=h.api.snapshot(players,2);
    assert.equal(s.phase,'blocked'); assert.equal(s.actionKey,undefined);
    assert.match(s.message,/南风场最低需要 14000/);
    assert.equal(h.api.snapshot(players,1).phase,'lobby');
  }
  const g=harness(); await g.refresh(account(42,10101,0xffffffff,20101));
  assert.equal(g.api.snapshot(4,2).modeId,3);
  assert.equal(g.api.snapshot(3,2).modeId,18);
});

test('changing East/South invalidates a pending match or refresh key before any request is sent',async()=>{
  const h=harness(), refreshKey=h.api.snapshot(4,1).actionKey;
  assert.equal((await h.api.start(4,refreshKey,2)).ok,false);
  assert.equal(h.calls.length,0);
  await h.refresh(account(42,10301,7000,20301));
  for (const players of [3,4]) {
    const east=h.api.snapshot(players,1),south=h.api.snapshot(players,2);
    assert.notEqual(east.actionKey,south.actionKey);
    assert.equal((await h.api.start(players,east.actionKey,2)).ok,false);
    assert.equal((await h.api.start(players,south.actionKey,1)).ok,false);
  }
  assert.equal(h.calls.length,1,'only the completed account refresh should have been sent');
});

test('a selection change cannot add a second queue and cancellation still targets the original wind',async()=>{
  const h=harness(); await h.refresh(account(42,10301,7000,20301));
  const east=h.api.snapshot(3,1),south=h.api.snapshot(3,2);
  const started=h.api.start(3,east.actionKey,1);
  assert.equal(h.api.snapshot(3,2).phase,'matching');
  assert.equal((await h.api.start(3,south.actionKey,2)).ok,false);
  h.calls.at(-1).resolve({payload:encode([])}); await started;
  assert.equal(h.api.snapshot(3,2).phase,'matching');
  assert.equal((await h.api.start(3,south.actionKey,2)).ok,false);
  assert.equal(h.calls.length,2);
  h.api.cancel();
  assert.equal(h.calls.at(-1).method,'.lq.Lobby.cancelUnifiedMatch');
  assert.equal(str(core.fields(h.calls.at(-1).payload),1),'1:21');
  h.calls.at(-1).resolve({payload:encode([])}); await flush();
  assert.equal(h.api.snapshot(3,2).modeId,22);
});

test('a late refresh failure from an old connection is recoverable and cannot poison a newer account refresh',async()=>{
  const h=harness(), old=h.api.start(4,h.api.snapshot().actionKey), oldRequest=h.calls[0];
  h.live.connected=false; h.live.accountId=null; h.api.snapshot();
  h.live.connected=true; h.live.accountId=42; h.live.lobbySessionId=3;
  h.emit('.lq.Lobby.fastLogin',encode([[1,'WebGL_test']]),{direction:'out',kind:'request'});
  await h.refresh(account(42,10301,8000,20301));
  oldRequest.reject(new Error('late connection close'));
  assert.equal((await old).recoverable,true);
  assert.equal(h.api.snapshot().modeId,8);
  assert.equal(h.calls.length,2);
});

test('an uncertain old match is cancelled after reconnect before any new match can be submitted',async()=>{
  const h=harness(); await h.refresh();
  const started=h.api.start(4,h.api.snapshot().actionKey), original=h.calls.at(-1);
  h.live.connected=false; h.live.accountId=null; h.api.snapshot();
  original.reject(Object.assign(new Error('connection closed'),{recoverable:true}));
  assert.equal((await started).recoverable,true);
  h.live.connected=true; h.live.accountId=42; h.live.lobbySessionId=3;
  h.emit('.lq.Lobby.fastLogin',encode([[1,'WebGL_test']]),{direction:'out',kind:'request'});
  h.emit('.lq.Lobby.fastLogin',encode([]),{kind:'response'});
  assert.equal(h.api.snapshot().phase,'matching');
  assert.equal(h.calls.at(-1).method,'.lq.Lobby.cancelUnifiedMatch');
  assert.equal(str(core.fields(h.calls.at(-1).payload),1),'1:5');
  assert.equal(h.calls.filter(call=>call.method.endsWith('startUnifiedMatch')).length,1);
  h.calls.at(-1).resolve({payload:encode([])}); await flush();
  assert.equal(h.api.snapshot().action,'refresh');
  await h.refresh();
  assert.equal(h.api.snapshot().action,'match');
});

test('late cancellation failure does not block cancelling the same owned queue on the new connection',async()=>{
  const h=harness(); await h.refresh();
  const started=h.api.start(4,h.api.snapshot().actionKey);
  h.calls.at(-1).resolve({payload:encode([])}); await started;
  h.api.cancel(); const oldCancel=h.calls.at(-1);
  h.live.connected=false; h.live.accountId=null; h.api.snapshot();
  h.live.connected=true; h.live.accountId=42; h.live.lobbySessionId=3;
  h.emit('.lq.Lobby.fastLogin',encode([]),{kind:'response'});
  oldCancel.reject(new Error('late connection close')); await flush();
  assert.notEqual(h.calls.at(-1),oldCancel);
  assert.equal(h.calls.at(-1).method,'.lq.Lobby.cancelUnifiedMatch');
  h.calls.at(-1).resolve({payload:encode([])}); await flush();
  assert.equal(h.api.cancel().ok,true);
  assert.equal(h.api.snapshot().action,'refresh');
});

test('reauthenticated active game does not become a new entry wait when the lobby reconnects later',async()=>{
  const h=harness({gameConnected:true});
  h.emit('.lq.FastTest.authGame',encode([]),{kind:'response',game:true});
  h.live.connected=false; h.live.accountId=null; h.api.snapshot();
  h.live.connected=true; h.live.accountId=42; h.live.lobbySessionId=3;
  h.emit('.lq.Lobby.fastLogin',encode([[2,encode([[3,'existing-game']])]]),{kind:'response'});
  h.advance(60000);
  assert.equal(h.api.snapshot().phase,'playing');
  assert.equal(h.calls.length,0);
});

test('game recovery suppresses obsolete watchdogs, clears an old game error, and ignores its late RPC failure',async()=>{
  const h=harness({gameConnected:true});
  h.api.onEvent({kind:'turn',state:{phase:'between_rounds'},action:{name:'ActionNoTile',step:99}});
  const finished=h.api.finish(h.api.snapshot().actionKey), old=h.calls.at(-1);
  h.emit('.lq.FastTest.confirmNewRound',encode([[1,encode([[1,1004]])]]),{kind:'response',game:true});
  assert.equal(h.api.snapshot().phase,'blocked');
  h.live.gameConnected=false; h.api.snapshot();
  h.api.onEvent({kind:'status',phase:'disconnected',recovery:{status:'waiting',reason:'connection'}});
  h.advance(60000); assert.equal(h.api.snapshot().phase,'reconnecting');
  h.live.gameConnected=true; h.live.gameSessionId=4;
  h.emit('.lq.FastTest.authGame',encode([]),{kind:'response',game:true});
  old.reject(new Error('late old game failure'));
  assert.equal((await finished).recoverable,true);
  h.api.onEvent({kind:'turn',state:{phase:'playing',recovery:null},action:{name:'ActionNewRound',chang:0,ju:1,ben:0,step:0}});
  assert.equal(h.api.snapshot().phase,'playing');
  assert.equal(h.calls.length,1);
});

test('same-round terminal recovery does not repeat a confirmation sent on the old socket',async()=>{
  const h=harness({gameConnected:true}), auth=encode([[1,42],[3,'same-game']]);
  h.emit('.lq.FastTest.authGame',auth,{direction:'out',kind:'request',game:true});
  h.api.onEvent({kind:'turn',state:{phase:'playing'},action:{name:'ActionNewRound',chang:0,ju:0,ben:0,step:0}});
  const terminal={name:'ActionNoTile',step:99,matchEnd:false};
  h.api.onEvent({kind:'turn',state:{phase:'between_rounds'},action:terminal});
  const finished=h.api.finish(h.api.snapshot().actionKey);
  h.calls.at(-1).resolve({payload:encode([])}); await finished;
  h.live.gameConnected=false; h.api.snapshot();
  h.live.gameSessionId=4;
  h.emit('.lq.FastTest.authGame',auth,{direction:'out',kind:'request',game:true});
  h.live.gameConnected=true; h.emit('.lq.FastTest.authGame',encode([]),{kind:'response',game:true});
  h.api.onEvent({kind:'turn',state:{phase:'between_rounds',recovery:null},action:terminal});
  assert.equal(h.api.snapshot().actionKey,undefined);
  assert.equal(h.calls.length,1);
});

test('a restored later round can confirm even when its terminal action and step equal the previous round',async()=>{
  const h=harness({gameConnected:true}), terminal={name:'ActionNoTile',step:99,matchEnd:false};
  for (const ju of [0,1]) {
    h.api.onEvent({kind:'turn',state:{phase:'between_rounds',recovery:null,round:{chang:0,ju,ben:0}},action:terminal});
    const s=h.api.snapshot(); assert.equal(s.action,'confirm');
    const confirmed=h.api.finish(s.actionKey);
    h.calls.at(-1).resolve({payload:encode([])}); await confirmed;
    h.api.onEvent({kind:'turn',state:{phase:'between_rounds',round:{chang:0,ju,ben:0}},action:terminal});
    assert.equal(h.api.snapshot().actionKey,undefined);
  }
  assert.equal(h.calls.length,2);
});

test('successful login without an active game clears recovery through the collector and resumes lobby refresh',async()=>{
  for (const method of ['.lq.Lobby.login','.lq.Lobby.fastLogin']) {
    let resets=0;
    const h=harness({gameConnected:true,onLobbyRecovery:()=>{resets++;}});
    h.api.onEvent({kind:'turn',state:{phase:'between_rounds'},action:{name:'ActionNoTile',step:99}});
    h.live.gameConnected=false;
    h.api.onEvent({kind:'status',phase:'disconnected',recovery:{status:'waiting',reason:'connection'}});
    assert.equal(h.api.snapshot().phase,'reconnecting');
    h.emit(method,encode([]),{kind:'response'});
    assert.equal(resets,1);
    assert.equal(h.api.snapshot().action,'refresh');
    assert.equal(h.calls.length,0,'clearing old game state must not itself send a game operation');
  }
});

test('a failed login, existing game info, or still authenticated game cannot clear recovery',()=>{
  for (const [payload,connected] of [
    [encode([[1,encode([[1,1004]])]]),false],
    [encode([[2,encode([[3,'active-game']])]]),false],
    [encode([[2,encode([])]]),false],
    [encode([]),true],
  ]) {
    let resets=0;
    const h=harness({gameConnected:connected,onLobbyRecovery:()=>{resets++;}});
    h.api.onEvent({kind:'status',phase:'disconnected',recovery:{status:'waiting',reason:'connection'}});
    h.emit('.lq.Lobby.fastLogin',payload,{kind:'response'});
    assert.equal(resets,0);
    assert.notEqual(h.api.snapshot().action,'refresh');
  }
});

test('no-game login recovery retains an uncertain owned match until its cancellation is confirmed',async()=>{
  let resets=0;
  const h=harness({onLobbyRecovery:()=>{resets++;}}); await h.refresh();
  const started=h.api.start(4,h.api.snapshot().actionKey);
  h.live.connected=false; h.live.accountId=null;
  h.api.onEvent({kind:'status',phase:'disconnected',recovery:{status:'waiting',reason:'connection'}});
  h.calls.at(-1).reject(Object.assign(new Error('closed'),{recoverable:true})); await started;
  h.live.connected=true; h.live.accountId=42; h.live.lobbySessionId=3;
  h.emit('.lq.Lobby.fastLogin',encode([]),{kind:'response'});
  assert.equal(resets,1);
  assert.equal(h.api.snapshot().phase,'matching');
  assert.equal(h.calls.at(-1).method,'.lq.Lobby.cancelUnifiedMatch');
  assert.equal(str(core.fields(h.calls.at(-1).payload),1),'1:5');
  h.calls.at(-1).resolve({payload:encode([])}); await flush();
  assert.equal(h.api.snapshot().action,'refresh');
});

test('a confirmed game end clears round deduplication even when later game authentication omits its UUID',async()=>{
  const h=harness({gameConnected:true}), round={chang:0,ju:0,ben:0};
  const action={name:'ActionNoTile',step:99,matchEnd:false}, keys=[];
  for (let game=0;game<2;game++) {
    h.api.onEvent({kind:'turn',state:{phase:'between_rounds',round},action});
    const s=h.api.snapshot(); assert.equal(s.action,'confirm'); keys.push(s.actionKey);
    const finished=h.api.finish(s.actionKey);
    h.calls.at(-1).resolve({payload:encode([])}); await finished;
    h.emit('.lq.NotifyGameEndResult');
  }
  assert.notEqual(keys[0],keys[1]);
  assert.equal(h.calls.length,2);
});

test('reloaded queue waits for same-account login and cancellation acknowledgement before rematching',async()=>{
  const h=harness();
  assert.equal(typeof h.api.restoreCheckpoint,'function');
  h.api.restoreCheckpoint({owned:{accountId:42,sid:'1:5',modeId:5},confirmation:null},42);
  assert.equal(h.api.snapshot().phase,'reconnecting');assert.equal(h.calls.length,0);
  h.emit('.lq.Lobby.oauth2Login',encode([[2,42],[3,account()]]),{kind:'response'});
  assert.equal(h.api.snapshot().phase,'matching');assert.equal(h.calls.length,1);
  assert.equal(h.calls[0].method,'.lq.Lobby.cancelUnifiedMatch');
  h.advance(50000);assert.notEqual(h.api.snapshot().phase,'lobby');assert.equal(h.calls.length,1);
  h.calls[0].resolve({payload:encode([])});await flush();
  assert.equal(h.api.snapshot().phase,'lobby');assert.equal(h.api.snapshot().action,'refresh');
});

for (const name of ['ActionHule','ActionNoTile','ActionLiuJu']) test(`cross-page ${name} confirmation is deduplicated by account UUID round and terminal step`,async()=>{
  const h=harness({gameConnected:true});h.live.gameIdentity='stable-game';
  const terminal={name,step:99,matchEnd:false}, round={chang:0,ju:0,ben:0};
  h.api.onEvent({kind:'turn',state:{phase:'between_rounds',round},action:terminal});
  const first=h.api.finish(h.api.snapshot().actionKey);
  h.calls.at(-1).resolve({payload:encode([])});await first;
  const checkpoint=JSON.parse(JSON.stringify(h.api.checkpoint()));
  assert.ok(checkpoint.confirmation.includes('stable-game'));
  const next=harness({gameConnected:true});next.live.gameIdentity='stable-game';
  next.api.restoreCheckpoint(checkpoint,42);
  next.emit('.lq.Lobby.oauth2Login',encode([[2,42],[3,account()],[4,encode([[3,'stable-game']])]]),{kind:'response'});
  next.emit('.lq.FastTest.authGame',encode([]),{kind:'response',game:true});
  next.api.onEvent({kind:'turn',state:{phase:'between_rounds',round},action:terminal});
  assert.equal(next.api.snapshot().actionKey,undefined);assert.equal(next.calls.length,0);
  assert.equal(next.api.snapshot().recoveryStalled,true);
  next.api.onEvent({kind:'turn',state:{phase:'between_rounds',round:{...round,ju:1}},action:terminal});
  assert.equal(next.api.snapshot().action,'confirm');
  const second=next.api.finish(next.api.snapshot().actionKey);next.calls[0].resolve({payload:encode([])});await second;
  assert.equal(next.calls.length,1);
});

test('restored ownership cannot cancel or match under another account or uncertain game information',()=>{
  const checkpoint={owned:{accountId:42,sid:'1:5',modeId:5},confirmation:null};
  const h=harness();h.api.restoreCheckpoint(checkpoint,42);
  h.live.accountId=99;h.live.lobbySessionId=3;
  h.emit('.lq.Lobby.oauth2Login',encode([[2,99],[3,account(99)]]),{kind:'response'});
  assert.equal(h.api.snapshot().phase,'blocked');assert.match(h.api.snapshot().message,/账号已变化/);
  assert.equal(h.calls.length,0);
  for(const game of [encode([]),encode([[3,'existing-game']])]) {
    const g=harness();g.api.restoreCheckpoint(checkpoint,42);
    g.emit('.lq.Lobby.oauth2Login',encode([[2,42],[4,game]]),{kind:'response'});
    assert.notEqual(g.api.snapshot().phase,'lobby');assert.equal(g.calls.length,0);
  }
});

test('manual queues and a confirmation without stable game identity cannot be exported for replay',async()=>{
  const h=harness();h.emit('.lq.Lobby.startUnifiedMatch',encode([[1,'1:5']]),{direction:'out',kind:'request'});
  assert.throws(()=>h.api.checkpoint(),/手动匹配/);
  const g=harness({gameConnected:true});
  g.api.onEvent({kind:'turn',state:{phase:'between_rounds'},action:{name:'ActionHule',step:9}});
  const action=g.api.finish(g.api.snapshot().actionKey);g.calls[0].resolve({payload:encode([])});await action;
  assert.throws(()=>g.api.checkpoint(),/稳定牌局标识/);
});

test('early native confirmation binds to the later collected terminal and a real new round releases it',()=>{
  const h=harness({gameConnected:true});h.live.gameIdentity='stable-game';
  h.emit('.lq.FastTest.confirmNewRound',encode([]),{direction:'out',kind:'request',game:true});
  assert.throws(()=>h.api.checkpoint(),/稳定牌局标识/);
  h.api.onEvent({kind:'turn',state:{phase:'between_rounds',round:{chang:0,ju:0,ben:0}},
    action:{name:'ActionNoTile',step:99}});
  assert.equal(h.api.snapshot().actionKey,undefined);assert.equal(h.calls.length,0);
  assert.ok(h.api.checkpoint().confirmation.includes('stable-game'));
  h.api.onEvent({kind:'turn',state:{phase:'playing',round:{chang:0,ju:1,ben:0}},
    action:{name:'ActionNewRound',chang:0,ju:1,ben:0,step:0}});
  assert.equal(h.api.checkpoint().confirmation,null);
});

test('restored between-round snapshot keeps unknown confirmation waiting without repeating it',()=>{
  const h=harness({gameConnected:true});h.live.gameIdentity='stable-game';
  h.api.restoreCheckpoint({owned:null,confirmation:JSON.stringify([42,'stable-game',0,0,0,'ActionNoTile',99])},42);
  h.emit('.lq.Lobby.oauth2Login',encode([[2,42],[4,encode([[3,'stable-game']])]]),{kind:'response'});
  h.emit('.lq.FastTest.authGame',encode([]),{kind:'response',game:true});
  h.api.onEvent({kind:'turn',state:{phase:'between_rounds',round:{chang:0,ju:0,ben:0}},action:{name:'GameRestore',step:99}});
  assert.equal(h.api.snapshot().recoveryStalled,true);assert.equal(h.api.snapshot().actionKey,undefined);
  assert.equal(h.calls.length,0);
});
