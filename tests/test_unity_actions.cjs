'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const core = require('../src/core.cjs');
const source = fs.readFileSync(path.join(__dirname, '../src/unity_actions.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
const hand = ['1m','2m','3m','4m','5m','6m','1p','2p','3p','4s','5s','7z','7z','1z'];
// Independent protocol boundary; assertions below decode using the real collector
// and fixed wire examples rather than relying on encoder/decoder round trips alone.
function encode(entries) {
  const bytes = [];
  function varint(value) {
    do {const low = value % 128; value = Math.floor(value / 128); bytes.push(low | (value ? 128 : 0));} while (value);
  }
  for (const [field, value] of entries) {
    if (typeof value === 'number') {varint(field * 8); varint(value);}
    else {const data = typeof value === 'string' ? Buffer.from(value) : value;
      varint(field * 8 + 2); varint(data.length); bytes.push(...data);}
  }
  return new Uint8Array(bytes);
}
function setup(options = {}) {
  const ops = options.ops || [{type:1,combination:[]}];
  const cards = options.hand || hand, players = options.players || 4;
  const state = Object.assign(core.emptyState(), {phase:'playing', gameId:'game-fixture', selfSeat:0, playerCount:players,
    match:{source:'auth-game',category:2,modeId:players === 3 ? 17 : 2,playerCount:players},
    hand:[...cards], handComplete:true, historyComplete:true, lastStep:12,
    lastDraw:options.drawn === false ? null : cards.at(-1), round:{chang:0,ju:0,ben:0},
    riichi:[false,false,false,false], canAct:true, canDiscard:ops.some(op => op.type === 1),
    operations:ops.map(op => op.type), operationDetails:plain(ops),
    operationTiming:{timeFixed:5000,timeAdd:20000,receivedAt:0},
    lastAction:options.lastAction || {name:'ActionDealTile',seat:0,tile:cards.at(-1),step:12},
    melds:options.melds || [[],[],[],[]]});
  if (state.lastAction.name === 'ActionDiscardTile') {
    state.rivers[state.lastAction.seat].push({tile:state.lastAction.tile,step:12,called:false});
  }
  const sent = [], timers = new Map();
  let time = 2200, timerId = 0, connected = true;
  const window = {__mjMonitor:{getSnapshot:() => ({running:true,state:plain(state)})},
    __mjProtocol:{encode}, __mjUnityTransport:{snapshot:() => ({connected,gameConnected:connected}),
      request(method, bytes, options) {
        return new Promise((resolve,reject) => sent.push({method,bytes,options,resolve,reject}));
      }}};
  vm.runInNewContext(source, {window,location:{hostname:'game.maj-soul.com'},Uint8Array,
    performance:{now:() => time}, setTimeout:(fn,delay) => {timers.set(++timerId,{fn,at:time+delay});return timerId;},
    clearTimeout:id => timers.delete(id)});
  const api = window.__mjUnityActions;
  return {api,window,state,sent,timers,
    run(choice) {return api.execute({status:'ready',best:choice},plain(state));},
    ack(index = 0) {sent[index].resolve({payload:new Uint8Array()});},
    echo(event, extra = {}) {api.onEvent({kind:'turn',action:{step:13,...event},...extra});},
    advance(ms) {time += ms; for (const [id,timer] of [...timers]) if (timer.at <= time) {timers.delete(id);timer.fn();}},
    reconnect() {connected = true;},
    disconnect() {connected = false; api.onEvent({kind:'status',phase:'disconnected'});}};
}
const fields = h => core.fields(h.sent[0].bytes);
const first = (h, n) => fields(h).get(n)?.[0] ?? 0;
const decodeTile = h => new TextDecoder().decode(first(h,3));
async function confirm(h, promise, event) {h.ack(); h.echo(event); return await promise;}

test('server operation deadlines are milliseconds, expire, and are never recreated from a stale snapshot', () => {
  const h = setup();
  assert.equal(h.api.snapshot(h.state).remainingMs,22800);
  h.advance(22799); assert.equal(h.api.snapshot(h.state).remainingMs,1);
  h.advance(1); assert.equal(h.api.snapshot(h.state).canAct,false);
  assert.equal(h.api.snapshot(h.state).blocked,true);
  assert.throws(() => h.run({action:'discard',tile:'1m'}), /超时/);
  assert.equal(h.sent.length,0);
});

test('physical red fives remain distinct and discard waits for both accepted response and exact echo', async () => {
  const h = setup({hand:[...hand.slice(0,12),'0p','5p']});
  const promise = h.run({action:'discard',tile:'0p'});
  assert.equal(Buffer.from(h.sent[0].bytes).toString('hex'),'08011a0230703002');
  assert.equal(h.sent[0].method,'.lq.FastTest.inputOperation');
  assert.deepEqual(plain(h.sent[0].options),{game:true});
  let settled = false; promise.then(() => {settled = true;});
  h.ack(); await Promise.resolve(); await Promise.resolve(); assert.equal(settled,false);
  h.echo({name:'ActionDiscardTile',seat:0,tile:'0p',moqie:false,riichi:false});
  assert.equal((await promise).action,'discard'); assert.equal(h.timers.size,0);
  assert.throws(() => h.run({action:'discard',tile:'0p'}), /已经提交/);
});

test('drawn duplicates use moqie and locked riichi never discards a different physical tile', async () => {
  const h = setup({hand:[...hand.slice(0,12),'0p','5p']}); h.state.riichi[0] = true;
  assert.throws(() => h.run({action:'discard',tile:'0p'}), /只能摸切/);
  const p = h.run({action:'discard',tile:'5p'});
  assert.equal(first(h,5),1); assert.equal(decodeTile(h),'5p');
  // Echo may precede the asynchronous response.
  h.echo({name:'ActionDiscardTile',seat:0,tile:'5p',moqie:true});
  assert.equal(h.api.snapshot(h.state).canAct,false);
  h.ack(); await p;
});

test('riichi follows the offered physical/family declaration and requires a riichi discard echo', async () => {
  // Official MJPai.Distance ignores the red flag in both LiqiSelect and Action_LiQi.
  for (const offered of ['0p','5p']) for (const tile of ['0p','5p']) {
    const h = setup({hand:[...hand.slice(0,11),'4p','0p','5p'],
      ops:[{type:1,combination:[]},{type:7,combination:[offered]}]});
    for (const other of ['4p','5s']) assert.throws(() => h.run({action:'riichi',tile:other}), /未经服务端/);
    const p = h.run({action:'riichi',tile});
    assert.equal(first(h,1),7); assert.equal(first(h,5),Number(tile === '5p'));
    assert.equal(decodeTile(h),tile);
    await confirm(h,p,{name:'ActionDiscardTile',seat:0,tile,moqie:tile === '5p',riichi:true});
  }
  const onlyRed = setup({hand:[...hand.slice(0,12),'0p','1z'],
    ops:[{type:1,combination:[]},{type:7,combination:['5p']}]});
  const p = onlyRed.run({action:'riichi',tile:'0p'});
  assert.equal(decodeTile(onlyRed),'0p');
  await confirm(onlyRed,p,{name:'ActionDiscardTile',seat:0,tile:'0p',moqie:false,riichi:true});
});

test('chi and pon choose the exact red-five combination index and verify the called seat', async () => {
  for (const [action,type,called,consumed,combos] of [
    ['chi',2,'4p',['3p','0p'],['2p|3p','0p|3p']],
    ['pon',3,'5p',['5p','0p'],['5p|5p','0p|5p']],
  ]) {
    const h = setup({hand:['2p','3p','0p','5p','5p',...hand.slice(0,8)],drawn:false,
      ops:[{type,combination:combos}],lastAction:{name:'ActionDiscardTile',seat:3,tile:called,step:12}});
    const p = h.run({action,consumed,calledTile:called,fromSeat:3});
    assert.equal(first(h,1),type); assert.equal(first(h,2),1);
    assert.equal(h.sent[0].method,'.lq.FastTest.inputChiPengGang');
    await confirm(h,p,{name:'ActionChiPengGang',seat:0,type:action === 'chi' ? 0 : 1,
      tiles:[...consumed,called],froms:[0,0,3]});
  }
});

test('daiminkan sends only the call; its replacement draw needs a new decision', async () => {
  const consumed = ['5p','0p','5p'];
  const h = setup({hand:[...consumed,...hand.slice(0,10)],drawn:false,
    ops:[{type:5,combination:['0p|5p|5p']}],lastAction:{name:'ActionDiscardTile',seat:1,tile:'5p',step:12}});
  const p = h.run({action:'daiminkan',consumed,calledTile:'5p',fromSeat:1});
  assert.equal(first(h,1),5); assert.equal(first(h,2),0);
  await confirm(h,p,{name:'ActionChiPengGang',seat:0,type:2,tiles:[...consumed,'5p'],froms:[0,0,0,1]});
  assert.equal(h.sent.length,1);
});

test('ankan uses its server index, including a concealed quad containing a red five', async () => {
  const consumed = ['5p','5p','5p','0p'];
  const h = setup({hand:[...consumed,...hand.slice(0,10)],ops:[{type:1,combination:[]},
    {type:4,combination:['1m|1m|1m|1m','0p|5p|5p|5p']}]});
  const p = h.run({action:'ankan',consumed});
  assert.equal(first(h,1),4); assert.equal(first(h,2),1);
  assert.equal(h.sent[0].method,'.lq.FastTest.inputOperation');
  await confirm(h,p,{name:'ActionAnGangAddGang',seat:0,type:3,tile:'5p'});
});

test('shouminkan reconstructs the exact full server combination from the identified pon', async () => {
  const h = setup({hand:['0p',...hand.slice(0,10)],melds:[[{type:1,tiles:['5p','5p','5p']}],[],[],[]],
    ops:[{type:1,combination:[]},{type:6,combination:['5p|5p|5p|0p']}]});
  assert.throws(() => h.run({action:'shouminkan',consumed:['0p'],meldIndex:1}), /对应碰牌/);
  const p = h.run({action:'shouminkan',consumed:['0p'],meldIndex:0});
  assert.equal(first(h,1),6); assert.equal(first(h,2),0);
  await confirm(h,p,{name:'ActionAnGangAddGang',seat:0,type:2,tile:'0p'});
});

test('Unity tsumo and ron both use inputOperation and only an own winning result confirms them', async () => {
  for (const [action,type,last] of [['tsumo',8,{name:'ActionDealTile',seat:0,tile:'1z',step:12}],
    ['ron',9,{name:'ActionAnGangAddGang',seat:2,tile:'5p',type:2,step:12}]]) {
    const h = setup({ops:[{type,combination:[]}],lastAction:last});
    const p = h.api.execute({status:'win',action},plain(h.state));
    assert.equal(h.sent[0].method,'.lq.FastTest.inputOperation'); assert.equal(first(h,1),type);
    await confirm(h,p,{name:'ActionHule',hules:[{seat:0,zimo:action === 'tsumo'}]});
  }
});

test('sanma kita preserves moqie and locked riichi only permits the drawn north', async () => {
  for (const drawn of [false,true]) {
    const h = setup({players:3,hand:[...hand.slice(0,13),'4z'],drawn,
      ops:[{type:1,combination:[]},{type:11,combination:[]}]});
    const p = h.run({action:'kita',consumed:['4z']});
    assert.equal(first(h,1),11); assert.equal(first(h,5),Number(drawn));
    await confirm(h,p,{name:'ActionBaBei',seat:0,moqie:drawn});
  }
  const h = setup({players:3,hand:[...hand.slice(0,12),'4z','1z'],ops:[{type:11,combination:[]}]});
  h.state.riichi[0] = true;
  assert.throws(() => h.run({action:'kita'}), /只能拔/);
});

test('nine-terminals requires both the offered operation and nine distinct terminals/honors', async () => {
  const h = setup({hand:['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','7z','1m'],
    ops:[{type:1,combination:[]},{type:10,combination:[]}]});
  const p = h.run({action:'abort'}); assert.equal(first(h,1),10);
  await confirm(h,p,{name:'ActionLiuJu',type:1,seat:0});
  const invalid = setup({ops:[{type:1,combination:[]},{type:10,combination:[]}]});
  assert.throws(() => invalid.run({action:'abort'}), /九种九牌/);
});

test('pass uses the correct cancel field for each window and waits for authoritative progression', async () => {
  for (const [type,field,method] of [[3,3,'inputChiPengGang'],[9,3,'inputChiPengGang'],[4,4,'inputOperation'],[11,4,'inputOperation']]) {
    const h = setup({ops:[{type,combination:[]}]});
    const p = h.run({action:'pass'}); h.ack();
    assert.equal(first(h,field),1); assert.equal(h.sent[0].method,`.lq.FastTest.${method}`);
    h.advance(11000); assert.equal(h.timers.size,1, 'pass may wait for another player beyond ACK timeout');
    h.echo({name:'ActionDealTile',seat:1}); await p;
  }
  const h = setup(); assert.throws(() => h.run({action:'pass'}), /不能用跳过/);
});

test('stale or incomplete state, invalid deadlines and unsupported modes never send', () => {
  const changes = [h => {h.state.historyComplete = false;},h => {h.state.handComplete = false;},
    h => {h.state.canAct = false;},h => {h.state.operationDetails.push({type:99,combination:[]});},
    h => {h.state.operationDetails[0].combination = null;},h => {h.state.operations = [2];},
    h => {h.state.operationTiming = null;},h => {h.state.operationTiming.receivedAt = 99999;},
    h => {h.state.operationTiming.timeFixed = -1;},h => {h.state.match.category = 1;},
    h => {h.state.hand[0] = '0z';},h => {h.state.selfSeat = 4;}];
  for (const change of changes) {
    const h = setup(); change(h);
    assert.equal(h.api.snapshot(h.state).canAct,false);
    assert.throws(() => h.run({action:'discard',tile:'1z'})); assert.equal(h.sent.length,0);
  }
  for (const key of ['lastStep','lastDraw','hand','round','operationDetails','operationTiming']) {
    const h = setup(), old = plain(h.state); old[key] = null;
    assert.throws(() => h.api.execute({status:'ready',best:{action:'discard',tile:'1z'}},old), /过期/);
    assert.equal(h.sent.length,0);
  }
});

test('forbidden discard, missing consumed tiles and ambiguous server combinations fail closed', () => {
  const h = setup(); h.state.forbiddenDiscards = ['0m'];
  assert.throws(() => h.run({action:'discard',tile:'5m'}), /食替/);
  const call = setup({drawn:false,hand:['0p','5p',...hand.slice(0,11)],
    ops:[{type:3,combination:['0p|5p','5p|0p']}],lastAction:{name:'ActionDiscardTile',seat:1,tile:'5p',step:12}});
  assert.throws(() => call.run({action:'pon',consumed:['0p','5p'],calledTile:'5p',fromSeat:1}), /唯一匹配/);
  assert.throws(() => call.run({action:'pon',consumed:['5p','5p'],calledTile:'5p',fromSeat:1}), /不存在/);
  call.state.rivers[1][0].called = true;
  assert.throws(() => call.run({action:'pon',consumed:['0p','5p'],calledTile:'5p',fromSeat:1}), /目标已失效/);
});

test('rejects incorrect chi direction, sanma chi, mismatched call families and locked calls', () => {
  const options = {drawn:false,hand:['2p','3p',...hand.slice(0,11)],ops:[{type:2,combination:['2p|3p']}],
    lastAction:{name:'ActionDiscardTile',seat:1,tile:'4p',step:12}};
  const h = setup(options);
  assert.throws(() => h.run({action:'chi',consumed:['2p','3p'],calledTile:'4p',fromSeat:1}), /吃牌来源/);
  const sanma = setup({...options,players:3,lastAction:{...options.lastAction,seat:2}});
  assert.throws(() => sanma.run({action:'chi',consumed:['2p','3p'],calledTile:'4p',fromSeat:2}), /吃牌来源/);
  const pon = setup({...options,ops:[{type:3,combination:['2p|3p']}]});
  assert.throws(() => pon.run({action:'pon',consumed:['2p','3p'],calledTile:'4p',fromSeat:1}), /牌种不一致/);
  pon.state.riichi[0] = true;
  assert.throws(() => pon.run({action:'pon',consumed:['2p','3p'],calledTile:'4p',fromSeat:1}), /目标已失效/);
});

test('a pending request rejects concurrent execution and server/transport rejection is never retried', async () => {
  const h = setup(), p = h.run({action:'discard',tile:'1m'});
  assert.throws(() => h.run({action:'discard',tile:'2m'}), /等待上次/);
  h.sent[0].reject(new Error('游戏拒绝操作：1023'));
  await assert.rejects(p,/1023/);
  assert.throws(() => h.run({action:'discard',tile:'1m'}), /已经提交/);
  h.advance(90000); assert.equal(h.sent.length,1); assert.equal(h.timers.size,0);
});

test('echo without ACK and ACK without echo both time out; late messages cannot confirm a later request', async () => {
  for (const part of ['ack','echo']) {
    const h = setup(), p = h.run({action:'discard',tile:'1m'});
    if (part === 'ack') h.ack(); else h.echo({name:'ActionDiscardTile',seat:0,tile:'1m',moqie:false});
    const rejected = assert.rejects(p,/确认超时/);
    h.advance(30000); await rejected;
    h.ack(); h.echo({name:'ActionDiscardTile',seat:0,tile:'1m'});
    await Promise.resolve(); assert.equal(h.sent.length,1);
    assert.throws(() => h.run({action:'discard',tile:'1m'}), /超时|已经提交/);
  }
});

test('wrong authoritative action, wrong physical tile, missing steps and new rounds reject confirmation', async () => {
  for (const event of [{name:'ActionDiscardTile',seat:1,tile:'1m'},
    {name:'ActionDiscardTile',seat:0,tile:'2m'}, {name:'ActionDiscardTile',seat:0,tile:'1m',step:14},
    {name:'ActionNewRound',step:0}]) {
    const h = setup(), p = h.run({action:'discard',tile:'1m'});
    h.ack(); h.echo(event); await assert.rejects(p,/未确认|不连续/);
    assert.equal(h.sent.length,1);
  }
});

test('another player winning does not confirm our ron, and disconnect stops an unresolved operation', async () => {
  const h = setup({ops:[{type:9,combination:[]}],lastAction:{name:'ActionDiscardTile',seat:2,tile:'1m',step:12}});
  const p = h.api.execute({status:'win',action:'ron'},plain(h.state));
  h.ack(); h.echo({name:'ActionHule',hules:[{seat:1,zimo:false}]});
  await assert.rejects(p,/未确认/);
  const next = setup(), waiting = next.run({action:'discard',tile:'1m'});
  next.disconnect(); await assert.rejects(waiting,/连接/);
  assert.equal(next.api.snapshot(next.state).canAct,false);
});

test('authority updates from the actual core can open a new decision only after the previous one is confirmed', async () => {
  const h = setup({hand:['1m','1m',...hand.slice(0,11)],drawn:false,
    ops:[{type:3,combination:['1m|1m']}],lastAction:{name:'ActionDiscardTile',seat:1,tile:'1m',step:12}});
  const p = h.run({action:'pon',consumed:['1m','1m'],calledTile:'1m',fromSeat:1});
  const event = {name:'ActionChiPengGang',step:13,seat:0,type:1,tiles:['1m','1m','1m'],froms:[0,0,1],
    selfSeat:0,operations:[1],operationDetails:[{type:1,combination:['1m']}],
    operationTiming:{timeFixed:5000,timeAdd:20000,receivedAt:2200}};
  core.apply(h.state,event); h.state.operationTiming = event.operationTiming;
  h.echo(event,{state:plain(h.state)}); h.ack(); await p;
  assert.equal(h.api.snapshot(h.state).canAct,true);
  const next = h.run({action:'discard',tile:'2m'});
  assert.equal(h.sent.length,2); assert.equal(new TextDecoder().decode(core.fields(h.sent[1].bytes).get(3)[0]),'2m');
  h.ack(1); h.echo({name:'ActionDiscardTile',seat:0,tile:'2m',moqie:false,step:14}); await next;
});

test('state changed by an encoding boundary is rechecked before any request leaves', () => {
  const h = setup(); h.window.__mjProtocol.encode = entries => {h.state.lastStep++;return encode(entries);};
  assert.throws(() => h.run({action:'discard',tile:'1m'}), /提交前/); assert.equal(h.sent.length,0);
});

test('a different abort kind or different physical added-kan tile cannot acknowledge the requested action', async () => {
  const abort = setup({hand:['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','7z','1m'],
    ops:[{type:10,combination:[]}]});
  const first = abort.run({action:'abort'}); abort.ack();
  abort.echo({name:'ActionLiuJu',seat:0,type:2}); await assert.rejects(first,/未确认/);
  const added = setup({hand:['0p',...hand.slice(0,10)],melds:[[{type:1,tiles:['5p','5p','5p']}],[],[],[]],
    ops:[{type:6,combination:['5p|5p|5p|0p']}]});
  const second = added.run({action:'shouminkan',consumed:['0p'],meldIndex:0}); added.ack();
  added.echo({name:'ActionAnGangAddGang',seat:0,type:2,tile:'5p'}); await assert.rejects(second,/未确认/);
});

test('malformed transport responses reject even when a matching authoritative action was observed', async () => {
  const h = setup(), p = h.run({action:'discard',tile:'1m'});
  h.echo({name:'ActionDiscardTile',seat:0,tile:'1m',moqie:false});
  h.sent[0].resolve({payload:null}); await assert.rejects(p,/响应格式/);
  assert.equal(h.api.snapshot(h.state).pending,false);
});

test('a final-hand win retains its authoritative echo across collector reset until its own ACK arrives', async () => {
  const h = setup({ops:[{type:8,combination:[]}]});
  const p = h.api.execute({status:'win',action:'tsumo'},plain(h.state));
  const event = {name:'ActionHule',step:13,matchEnd:true,hules:[{seat:0,zimo:true}]};
  core.apply(h.state,event);
  assert.equal(h.state.phase,'ended'); assert.equal(h.state.match,null);
  h.echo(event,{state:plain(h.state)});
  Object.assign(h.state,core.emptyState(),{phase:'ended'});
  h.api.onEvent({kind:'status',phase:'ended',reset:true});
  assert.equal(h.api.snapshot().pending,true);
  h.ack(); assert.equal((await p).action,'tsumo');
  assert.equal(h.api.snapshot().pending,false);
});

test('recovery preserves an unknown submitted turn despite new timing, and only a new authoritative turn can act',async()=>{
  const h=setup(), old=h.run({action:'discard',tile:'1m'});
  const interrupted=assert.rejects(old,error=>error.recoverable===true);
  h.disconnect(); await interrupted; h.reconnect();
  h.state.operationTiming.receivedAt=2000;
  const restored=h.api.snapshot(h.state);
  assert.equal(restored.canAct,false); assert.equal(restored.blocked,false); assert.equal(restored.recoverable,true);
  assert.throws(()=>h.run({action:'discard',tile:'1m'}),/已经提交/);
  assert.equal(h.sent.length,1);
  h.state.lastStep=14; h.state.lastAction={name:'ActionDealTile',seat:0,tile:'1z',step:14};
  const next=h.run({action:'discard',tile:'2m'});
  h.sent[0].reject(new Error('old socket closed')); await Promise.resolve(); await Promise.resolve();
  assert.equal(h.api.snapshot().pending,true,'old transport rejection cannot clear the new request');
  h.ack(1); h.echo({name:'ActionDiscardTile',seat:0,tile:'2m',step:15,moqie:false});
  assert.equal((await next).ok,true); assert.equal(h.sent.length,2);
});

test('same-socket recovery interrupts pending work and new game identity does not inherit the old submitted turn',async()=>{
  const h=setup(), pending=h.run({action:'discard',tile:'1m'});
  const interrupted=assert.rejects(pending,error=>error.recoverable===true);
  h.state.recovery={status:'waiting',reason:'restore'};
  h.api.onEvent({kind:'status',phase:'connected',recovery:h.state.recovery});
  await interrupted; assert.equal(h.api.snapshot().recoverable,true);
  h.ack(); await Promise.resolve(); assert.equal(h.api.snapshot().pending,false);
  h.state.recovery=null; h.state.gameId='next-game';
  const next=h.run({action:'discard',tile:'1m'});
  h.ack(1); h.echo({name:'ActionDiscardTile',seat:0,tile:'1m',moqie:false});
  assert.equal((await next).ok,true); assert.equal(h.sent.length,2);
});

test('a controlled reload blocks the same UUID round and step even when page game IDs change',async()=>{
  const previous=setup();
  previous.window.__mjUnityTransport.snapshot=()=>({gameConnected:true,gameIdentity:'stable-fixture',gameAccountId:81});
  const pending=previous.run({action:'discard',tile:'1m'});
  const rejected=assert.rejects(pending,/连接/); previous.disconnect(); await rejected;
  const checkpoint=plain(previous.api.checkpoint());
  assert.deepEqual(checkpoint,{submitted:[81,'stable-fixture',0,4,0,0,0,12]});
  const restored=setup(); restored.state.gameId='game-1';
  restored.api.restoreCheckpoint(checkpoint);
  assert.equal(restored.api.snapshot().canAct,false,'unproven UUID cannot release a restored guard');
  restored.window.__mjUnityTransport.snapshot=()=>({gameConnected:true,gameIdentity:'stable-fixture',gameAccountId:81});
  assert.throws(()=>restored.run({action:'discard',tile:'1m'}),/已经提交/);
  assert.equal(restored.sent.length,0);
  restored.state.lastStep=14;
  const next=restored.run({action:'discard',tile:'2m'});
  restored.ack(); restored.echo({name:'ActionDiscardTile',seat:0,tile:'2m',moqie:false,step:15}); await next;
});

test('a stable checkpoint does not conflate another game or a later round with repeated steps',async()=>{
  for (const changed of ['game','round']) {
    const h=setup();
    h.api.restoreCheckpoint({submitted:[81,'old-fixture',0,4,0,0,0,12]});
    h.window.__mjUnityTransport.snapshot=()=>({gameConnected:true,gameIdentity:changed==='game'?'new-fixture':'old-fixture',gameAccountId:81});
    if(changed==='round') h.state.round.ben=1;
    const pending=h.run({action:'discard',tile:'1m'});
    h.ack(); h.echo({name:'ActionDiscardTile',seat:0,tile:'1m',moqie:false}); await pending;
  }
});

test('checkpoint preparation fails closed for a submitted turn without proven stable identity',async()=>{
  const h=setup(), pending=h.run({action:'discard',tile:'1m'});
  assert.throws(()=>h.api.checkpoint(),/身份/);
  const rejected=assert.rejects(pending,/连接/); h.disconnect(); await rejected;
  assert.throws(()=>h.api.checkpoint(),/身份/);
  assert.throws(()=>setup().api.restoreCheckpoint({submitted:[81,'fixture',0,4,0,0,0,-1]}),/恢复/);
});
