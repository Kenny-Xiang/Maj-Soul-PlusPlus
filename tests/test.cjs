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
const authResponse = ({category=2, modeId=12, mode=2, seats=[11,22,4000000007,44],
  players=seats.map((id, i) => ({id, level:10401 + i % 3, level3:20401 + i % 3})), packed=false} = {}) => new Uint8Array([
  ...players.flatMap(p => bytes(2, [...num(1,p.id), ...str(4,'private-nickname'),
    ...(p.level ? bytes(5,num(1,p.level)) : []), ...(p.level3 ? bytes(7,num(1,p.level3)) : [])])),
  ...(packed ? bytes(3,seats.flatMap(vi)) : seats.flatMap(id => num(3,id))),
  ...bytes(5,[...num(1,category), ...bytes(2,num(1,mode)), ...bytes(3,num(2,modeId))]),
]);
const rpcFrame = (kind, id, name, data) => new Uint8Array([kind,id & 255,id >> 8,
  ...str(1,name), ...bytes(2,data)]);

test('the initial match-start notification waits for the first round without creating an incomplete playing state', () => {
  const state = core.emptyState(); state.phase = 'connected'; state.selfSeat = 0;
  core.applyRestore(state, core.restore(new Uint8Array()));
  const start = core.action(core.envelope(actionFrame('ActionMJStart',0)).data);
  assert.equal(core.apply(state,start),true);
  assert.equal(state.phase,'connected'); assert.equal(state.lastStep,0);
  assert.equal(state.baseline,null); assert.equal(state.canAct,false);
  assert.equal(state.handComplete,false); assert.equal(state.historyComplete,false);
  assert.equal(state.recovery,null, 'initial loading is not reconnect recovery');
  assert.equal(core.apply(state,start),false, 'a duplicate start must not restart initialization');
  core.apply(state,{name:'ActionNewRound',step:1,selfSeat:0,
    hand:['1p','2p','3p','4p','5p','6p','1s','2s','3s','4s','5s','6s','7z','1z'],
    scores:[25000,25000,25000,25000],chang:0,ju:0,ben:0,doras:['1p'],
    operations:[1],operationDetails:[{type:1,combination:[]}]});
  assert.equal(state.phase,'playing'); assert.equal(state.canAct,true);
  assert.equal(state.baseline,'new_round'); assert.equal(state.historyComplete,true);
});

test('match-start cannot conceal an existing invalid baseline or missing prior actions', () => {
  for (const changes of [{baseline:'snapshot_unverified'}, {lastStep:3}]) {
    const state = Object.assign(core.emptyState(),changes);
    core.apply(state,{name:'ActionMJStart',step:4});
    assert.equal(state.phase,'playing'); assert.equal(state.handComplete,false);
    assert.equal(state.historyComplete,false); assert.equal(state.canAct,false);
  }
});

test('recorded operation timers keep their wire millisecond units and replay does not create a deadline', () => {
  const event = decoded.find(e => e.name === 'ActionDealTile' && e.step === 66);
  assert.deepEqual(event.operationTiming,{timeFixed:5000,timeAdd:20000});
  const state = core.emptyState();
  core.apply(state,{name:'ActionNewRound',step:0,selfSeat:0,hand:['1p'],scores:[25000,25000,25000,25000],
    chang:0,ju:0,ben:0,operationDetails:[{type:1,combination:[]}],operations:[1],
    operationTiming:event.operationTiming});
  assert.equal(state.operationTiming,null);
  core.apply(state,{...event,step:1,operationTiming:{...event.operationTiming,receivedAt:123}});
  assert.equal(state.operationTiming.receivedAt,123);
});

test('winning and abortive-draw echoes preserve the exact seat and result type', () => {
  const decode = frame => core.action(core.envelope(frame).data);
  const win = decode(actionFrame('ActionHule',8,bytes(1,[...num(4,2),...num(5,1)])));
  assert.deepEqual(win.hules,[{seat:2,zimo:true}]);
  const draw = decode(actionFrame('ActionLiuJu',9,[...num(1,1),...num(3,2)]));
  assert.equal(draw.type,1); assert.equal(draw.seat,2);
});

test('authGame resolves own seat by account id, reads the correct rank and omits private fields', () => {
  const account = 4000000007;
  assert.equal(core.authAccount(new Uint8Array([...num(1,account), ...str(2,'private-token'),
    ...str(3,'private-game-uuid')])),account);
  assert.equal(core.authAccount(new Uint8Array()),null);
  const seats = [11,22,account,44];
  const players = [{id:44,level:10501}, {id:account,level:10402}, {id:11,level:10401}, {id:22,level:10403}];
  for (const packed of [false,true]) {
    assert.deepEqual(core.authGame(authResponse({seats,players,packed}),account),{selfSeat:2,match:{
      source:'auth-game',category:2,modeId:12,room:4,levelId:10402,
      levelIds:[10401,10403,10402,10501],playerCount:4,roundCount:2,
    }});
  }
  const three = core.authGame(authResponse({modeId:23,mode:11,seats:seats.slice(0,3),
    players:[{id:account,level:10503,level3:20401},{id:11,level:10401,level3:20502},{id:22,level3:20403}]}),account);
  assert.deepEqual(three,{selfSeat:2,match:{source:'auth-game',category:2,modeId:23,room:4,
    levelId:20401,levelIds:[20502,20403,20401],playerCount:3,roundCount:1}});
  assert.doesNotMatch(JSON.stringify(three),/4000000007|nickname|token|uuid|account/);
});

test('authGame fails closed on custom modes, missing own rank, identity ambiguity and mode mismatches', () => {
  const unknown = {selfSeat:null,match:null};
  const cases = [
    new Uint8Array(), new Uint8Array(bytes(1,num(1,1001))),
    authResponse({category:1}), authResponse({category:4}), authResponse({modeId:13,mode:1}),
    authResponse({modeId:999}), authResponse({mode:1}), authResponse({seats:[11,22,44]}),
    authResponse({seats:[11,22,4000000007,4000000007]}), authResponse({seats:[0,22,4000000007,44]}),
    authResponse({players:[{id:11,level:10401}]}),
    authResponse({players:[{id:4000000007,level:10401},{id:4000000007,level:10402}]}),
    authResponse({players:[{id:4000000007,level3:20401}]}),
    authResponse({players:[{id:4000000007,level:20401}]}),
  ];
  for (const response of cases) assert.deepEqual(core.authGame(response,4000000007),unknown);
  assert.deepEqual(core.authGame(authResponse(),null),unknown);
  assert.deepEqual(core.authGame(authResponse(),99),unknown);
  assert.deepEqual(core.authGame(authResponse({modeId:24,mode:12,seats:[11,22,4000000007],
    players:[{id:4000000007,level:10401}]}),4000000007),unknown);
});

test('known match format identifies scheduled all-last and extension without guessing South four', () => {
  for (const [modeId, mode, count, winds] of [[11,1,4,1],[12,2,4,2],[23,11,3,1],[24,12,3,2]]) {
    const state = core.emptyState(), seats = [11,22,4000000007,44].slice(0,count);
    const auth = core.authGame(authResponse({modeId,mode,seats}),4000000007);
    Object.assign(state,{selfSeat:auth.selfSeat}); core.setMatch(state,auth.match);
    const opening = {name:'ActionNewRound',step:0,selfSeat:2,hand:['1p'],scores:Array(count).fill(35000),
      doras:[],left:50,chang:winds-1,ju:count-2,ben:0};
    core.apply(state,opening);
    assert.equal(state.round.isFinal,false);
    core.apply(state,{...opening,ju:count-1});
    assert.equal(state.round.isFinal,true); assert.equal(state.round.isExtension,false);
    core.apply(state,{...opening,chang:winds,ju:0});
    assert.equal(state.round.isFinal,true); assert.equal(state.round.isExtension,true);
    assert.deepEqual(state.match,auth.match);
    core.applyRestore(state,{ended:false,actions:[{...opening,ju:count-1}],snapshot:null});
    assert.deepEqual(state.match,auth.match); assert.equal(state.selfSeat,2);
    assert.equal(state.round.isFinal,true);
    core.applyRestore(state,{ended:false,actions:[],step:7,snapshot:{selfSeat:2,hand:['2p'],doras:[],
      chang:winds,ju:0,ben:1,left:20,players:seats.map(()=>({score:35000,discards:[],melds:[]}))}});
    assert.deepEqual(state.match,auth.match); assert.equal(state.round.isExtension,true);
    core.applyRestore(state,{ended:true,actions:[]});
    assert.equal(state.match,null); assert.equal(state.round.isFinal,undefined);
  }
  const state = core.emptyState();
  core.apply(state,{name:'ActionNewRound',step:0,selfSeat:0,hand:['1p'],scores:[25000,25000,25000,25000],
    doras:[],left:50,chang:1,ju:3,ben:0});
  assert.equal(state.match,null); assert.equal(state.round.isFinal,undefined);
});

test('rank metadata is cleared when action evidence contradicts the authenticated player count or seat', () => {
  for (const overrides of [{selfSeat:1},{scores:[35000,35000,35000]}]) {
    const state = core.emptyState(), auth = core.authGame(authResponse(),4000000007);
    Object.assign(state,{match:auth.match,selfSeat:auth.selfSeat});
    core.apply(state,{name:'ActionNewRound',step:0,selfSeat:2,hand:['1p'],scores:Array(4).fill(25000),
      doras:[],left:50,chang:1,ju:3,ben:0,...overrides});
    assert.equal(state.match,null); assert.equal(state.round.isFinal,undefined);
  }
});

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

test('advisor operations decode forbidden discards, riichi choices and authoritative wins', () => {
  const operation = (type, choices = []) => bytes(2,[...num(1,type), ...choices.flatMap(tile => str(2,tile))]);
  const e = core.action(core.envelope(actionFrame('ActionDealTile',4,[
    ...num(1,0), ...str(2,'0p'), ...num(3,30), ...num(7,1),
    ...bytes(4,[...num(1,0), ...operation(1,['5p','8p']), ...operation(7,['0p']), ...operation(8)])
  ])).data);
  assert.deepEqual(e.operations,[1,7,8]);
  assert.deepEqual(e.operationDetails,[{type:1,combination:['5p','8p']},
    {type:7,combination:['0p']},{type:8,combination:[]}]);
  assert.equal(e.canDiscard,true);
  assert.equal(e.furiten,true);
  const ron = core.action(core.envelope(actionFrame('ActionDiscardTile',5,[
    ...num(1,1), ...str(2,'3p'), ...bytes(4,[...num(1,0), ...operation(9)])
  ])).data);
  assert.deepEqual(ron.operations,[9]);
  assert.equal(ron.canDiscard,false);
  assert.equal(ron.furiten,false);
});

test('operation combinations retain exact consumed tiles and red kan candidates', () => {
  // Shapes checked against majsoulrpa operation/_decode.py and _materialize.py
  // at 13698e226eace210ff8772fcabacfd2916299c4e. An added kan describes all four
  // tiles, including the three already in the pon; it does not consume four.
  const details = [
    {type:2,combination:['3p|4p','4p|6p']}, {type:3,combination:['0p|5p']},
    {type:4,combination:['0p|5p|5p|5p']}, {type:5,combination:['0p|5p|5p']},
    {type:6,combination:['0p|5p|5p|5p']}, {type:7,combination:['0p','9s']},
    {type:10,combination:[]}, {type:11,combination:[]},
  ];
  const operations = details.flatMap(op => bytes(2,[...num(1,op.type),
    ...op.combination.flatMap(combination => str(2,combination))]));
  const event = core.action(core.envelope(actionFrame('ActionDealTile',4,[
    ...num(1,0), ...str(2,'5p'), ...num(3,30), ...bytes(4,[...num(1,0), ...operations]),
  ])).data);
  assert.deepEqual(event.operationDetails,details);
  assert.deepEqual(event.operations,details.map(op => op.type));
});

test('call decision context tracks the current red discard and closes on the next action', () => {
  const s = core.emptyState();
  core.apply(s,{name:'ActionNewRound',step:0,selfSeat:0,hand:['5p','5p','1s'],
    scores:[25000,25000,25000,25000],doras:[],left:60,chang:0,ju:1,ben:0});
  const offered = {name:'ActionDiscardTile',step:1,seat:3,tile:'0p',selfSeat:0,
    operations:[3],operationDetails:[{type:3,combination:['5p|5p']}]};
  core.apply(s,offered);
  assert.equal(s.canAct,true);
  assert.equal(s.canDiscard,false);
  assert.deepEqual(s.lastAction,{name:'ActionDiscardTile',seat:3,tile:'0p',type:null,step:1});
  assert.equal(core.apply(s,offered),false);
  assert.equal(s.canAct,true);
  core.apply(s,{name:'ActionDealTile',step:2,seat:1,tile:null,left:59});
  assert.equal(s.canAct,false);
  assert.deepEqual(s.operations,[]);
  assert.deepEqual(s.lastAction,{name:'ActionDealTile',seat:1,tile:null,type:null,step:2});
  core.apply(s,{name:'ActionBaBei',step:3,seat:1,selfSeat:0,operations:[9]});
  assert.equal(s.canAct,true);
  assert.equal(s.lastAction.tile,'4z');
  core.apply(s,{name:'ActionHule',step:4,matchEnd:false});
  assert.equal(s.canAct,false);
  assert.equal(s.lastAction,null);
});

test('non-discard decisions require intact history and matching local operation seat', () => {
  const opening = {name:'ActionNewRound',step:0,selfSeat:0,hand:['5p','5p','1s'],
    scores:[25000,25000,25000,25000],doras:[],left:60,chang:0,ju:1,ben:0};
  const offered = {name:'ActionDiscardTile',step:1,seat:3,tile:'0p',selfSeat:0,
    operations:[3],operationDetails:[{type:3,combination:['5p|5p']}]};
  const s = core.emptyState();
  core.apply(s,offered);
  assert.equal(s.canAct,false);
  for (const invalid of [{...offered,step:2},{...offered,selfSeat:2},
    {...offered,selfSeat:undefined},{...offered,operations:[99]}]) {
    const state = core.emptyState();
    core.apply(state,opening);
    core.apply(state,invalid);
    assert.equal(state.canAct,false);
    assert.equal(state.canDoubleRiichi,false);
  }
  core.apply(s,opening);
  core.apply(s,offered);
  core.apply(s,{name:'ActionUnsupported',step:2,unsupported:true,selfSeat:0,operations:[3]});
  assert.equal(s.canAct,false);
  assert.equal(s.lastAction,null);
  assert.deepEqual(s.operations,[]);
  for (const restored of [
    {ended:true,actions:[]}, {ended:false,actions:[opening,offered]},
    {ended:false,actions:[],snapshot:null},
  ]) {
    const state = core.emptyState();
    core.apply(state,opening);
    core.apply(state,offered);
    core.applyRestore(state,restored);
    assert.equal(state.canAct,false);
    assert.equal(state.canDoubleRiichi,false);
    assert.equal(state.lastAction,null);
    assert.deepEqual(state.operations,[]);
  }
});

test('first-turn riichi eligibility ends on any call, kan, kita or own discard', () => {
  const opening = {name:'ActionNewRound',step:0,selfSeat:0,hand:['1p','4z'],
    scores:[35000,35000,35000],doras:[],left:50,chang:0,ju:1,ben:0};
  const decision = {selfSeat:0,operations:[1,7],operationDetails:[{type:1,combination:[]},
    {type:7,combination:['4z']}]};
  const interruptions = [
    {name:'ActionChiPengGang',seat:1,type:1,tiles:['2p','2p','2p'],froms:[1,1,2]},
    {name:'ActionAnGangAddGang',seat:1,type:3,tile:'2p'},
    {name:'ActionBaBei',seat:1}, {name:'ActionDiscardTile',seat:0,tile:'1p'},
  ];
  for (const interruption of interruptions) {
    const s = core.emptyState();
    core.apply(s,opening);
    core.apply(s,{name:'ActionDealTile',step:1,seat:0,tile:'9s',left:49,...decision});
    assert.equal(s.canDoubleRiichi,true);
    core.apply(s,{...interruption,step:2});
    core.apply(s,{name:'ActionDealTile',step:3,seat:0,tile:'8s',left:48,...decision});
    assert.equal(s.canDoubleRiichi,false);
  }
  const s = core.emptyState();
  core.apply(s,{...opening,ju:0,...decision});
  assert.equal(s.canDoubleRiichi,true);
  core.apply(s,{name:'ActionDiscardTile',step:1,seat:1,tile:'9p'});
  core.apply(s,{name:'ActionDealTile',step:2,seat:0,tile:'9s',left:49,...decision});
  assert.equal(s.canDoubleRiichi,true);
});

test('advisor discard window follows actual server operations and closes on every next action', () => {
  const hand = ['1p','2p','3p','4p','5p','6p','6p','7p','8p','1s','2s','3s','4s','9s'];
  const permission = {selfSeat:0,operations:[1],operationDetails:[{type:1,combination:[]}]};
  const s = core.emptyState();
  const deal = {name:'ActionNewRound',step:0,hand,scores:[35000,35000,35000],
    doras:['1z'],left:54,chang:0,ju:0,ben:0,...permission};
  core.apply(s,deal);
  assert.equal(s.lastDraw,'9s');
  assert.equal(s.canDiscard,true);
  core.apply(s,deal);
  assert.equal(s.canDiscard,true);
  core.apply(s,{name:'ActionDiscardTile',step:1,seat:0,tile:'9s'});
  assert.equal(s.canDiscard,false);
  assert.deepEqual(s.operations,[]);
  core.apply(s,{name:'ActionDiscardTile',step:2,seat:1,tile:'6p',selfSeat:0,operations:[3]});
  assert.equal(s.canDiscard,false);
  core.apply(s,{name:'ActionChiPengGang',step:3,seat:0,type:1,tiles:['6p','6p','6p'],froms:[0,0,1],
    ...permission,operationDetails:[{type:1,combination:['6p']}]});
  assert.equal(s.canDiscard,true);
  assert.deepEqual(s.forbiddenDiscards,['6p']);
  assert.equal(s.lastDraw,null);
  core.apply(s,{name:'ActionDiscardTile',step:4,seat:0,tile:'1p'});
  core.apply(s,{name:'ActionDealTile',step:5,seat:0,tile:'5s',left:53,...permission});
  assert.equal(s.canDiscard,true);
  assert.equal(s.lastDraw,'5s');
  assert.deepEqual(s.forbiddenDiscards,[]);
  core.apply(s,{name:'ActionHule',step:6,matchEnd:false});
  assert.equal(s.canDiscard,false);
  assert.deepEqual(s.operations,[]);
});

test('advisor never opens a discard window with missing baseline, action gaps or conflicting seat', () => {
  const permission = {selfSeat:0,operations:[1],operationDetails:[{type:1,combination:[]}]};
  const draw = {name:'ActionDealTile',step:2,seat:0,tile:'1p',left:50,...permission};
  const s = core.emptyState();
  core.apply(s,draw);
  assert.equal(s.canDiscard,false);
  const deal = {name:'ActionNewRound',step:0,hand:['1p'],scores:[35000,35000,35000],
    doras:[],left:50,chang:0,ju:0,ben:0,...permission};
  core.apply(s,deal);
  core.apply(s,draw);
  assert.equal(s.canDiscard,false);
  assert.match(s.warning,/缺口/);
  core.apply(s,{...deal,ben:1});
  core.apply(s,{...draw,step:1,seat:1,selfSeat:1});
  assert.equal(s.canDiscard,false);
  assert.equal(s.selfSeat,0);
  assert.match(s.warning,/座位/);
});

test('advisor records confirmed riichi timing, pending declarations, furiten and table sticks', () => {
  const s = core.emptyState();
  const initial = core.action(core.envelope(actionFrame('ActionNewRound',0,[
    ...str(4,'1p'), ...num(6,25000), ...num(6,25000), ...num(6,25000), ...num(6,25000), ...num(8,2)
  ])).data);
  core.apply(s,initial);
  assert.equal(s.riichiSticks,2);
  assert.equal(s.furiten,false);
  core.apply(s,{name:'ActionDiscardTile',step:1,seat:1,tile:'3p',riichi:true,furiten:true});
  assert.equal(s.riichiPending[1],true);
  assert.equal(s.riichi[1],false);
  assert.equal(s.riichiStep[1],1);
  assert.equal(s.furiten,true);
  core.apply(s,core.action(core.envelope(actionFrame('ActionDealTile',2,[
    ...num(1,2), ...num(3,49), ...bytes(5,[...num(1,1), ...num(2,24000), ...num(3,3)])
  ])).data));
  assert.equal(s.riichi[1],true);
  assert.equal(s.riichiPending[1],false);
  assert.equal(s.riichiStep[1],1);
  assert.equal(s.riichiSticks,3);
  core.apply(s,{name:'ActionDiscardTile',step:3,seat:2,tile:'4p'});
  assert.equal(s.rivers[2][0].step,3);
  core.apply(s,{name:'ActionDiscardTile',step:4,seat:3,tile:'5s',riichi:true});
  core.apply(s,{name:'ActionHule',step:5,matchEnd:false});
  assert.equal(s.riichiPending[3],false);
  assert.equal(s.riichiStep[3],null);
  assert.equal(s.riichi[3],false);
  assert.equal(s.riichi[1],true);
});

test('closed kans preserve actual own red tiles and represent opponent red fives once', () => {
  const s = core.emptyState();
  core.apply(s,{name:'ActionNewRound',step:0,selfSeat:0,
    hand:['0p','5p','5p','5p','1s','2s','3s','4s','5s','6s','7s','8s','9s','1z'],
    scores:[35000,35000,35000],doras:[],left:50,chang:0,ju:0,ben:0});
  core.apply(s,{name:'ActionAnGangAddGang',step:1,seat:0,type:3,tile:'5p'});
  assert.deepEqual(s.melds[0][0].tiles,['0p','5p','5p','5p']);
  assert.equal(s.melds[0][0].redAssumed,false);
  assert.equal(s.hand.length,10);
  assert.equal(s.handComplete,true);
  core.apply(s,{name:'ActionAnGangAddGang',step:2,seat:1,type:3,tile:'0s'});
  assert.deepEqual(s.melds[1][0].tiles,['0s','5s','5s','5s']);
  assert.equal(s.melds[1][0].redAssumed,true);
});

test('opponent honor kans preserve four identical tiles without assuming a red five', () => {
  for (const tile of ['1z','2z','3z','4z','5z','6z','7z']) {
    const s = core.emptyState();
    core.apply(s,{name:'ActionNewRound',step:0,selfSeat:0,
      hand:['1m','2m','3m','1p','2p','3p','1s','2s','3s','4s','5s','6s','9p'],
      scores:[25000,25000,25000,25000],doras:[],left:60,chang:0,ju:3,ben:0});
    const event = core.action(core.envelope(actionFrame('ActionAnGangAddGang',1,
      [...num(1,3),...num(2,3),...str(3,tile)])).data);
    core.apply(s,event);
    assert.deepEqual(s.melds[3][0].tiles,[tile,tile,tile,tile],tile);
    assert.equal(s.melds[3][0].redAssumed,false,tile);
    assert.equal(s.handComplete,true);
    assert.equal(s.historyComplete,true);
  }
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
    assert.equal(discard.doubleRiichi, flag === 9);
    core.apply(s, discard);
    assert.equal(s.rivers[1][0].riichi, true);
    assert.deepEqual(s.riichi, [false,false,false,false]);
    assert.equal(s.doubleRiichiPending[1], flag === 9);
    assert.equal(s.doubleRiichi[1], false);
    const draw = core.action(core.envelope(actionFrame('ActionDealTile',2,
      [...num(1,2), ...num(3,59), ...bytes(5,[...num(1,1), ...num(2,24000)])])).data);
    core.apply(s, draw);
    assert.deepEqual(s.riichi, [false,true,false,false]);
    assert.equal(s.doubleRiichi[1], flag === 9);
    assert.equal(s.doubleRiichiPending[1], false);
    assert.equal(s.scores[1],24000);
    assert.equal(core.apply(s, draw),false);
    assert.equal(core.apply(s, deal),false);
    assert.equal(s.riichi[1],true);
    core.apply(s, {name:'ActionDiscardTile',step:3,seat:2,tile:'5p'});
    core.apply(s, {name:'ActionHule',step:4,matchEnd:false});
    assert.equal(s.riichi[1],true);
    core.apply(s, {...deal,ju:1});
    assert.deepEqual(s.riichi, [false,false,false,false]);
    assert.deepEqual(s.doubleRiichi, [false,false,false,false]);
  }
});

test('interrupted double riichi remains unconfirmed and unknown history stays unknown', () => {
  const s = core.emptyState();
  assert.deepEqual(s.doubleRiichi,[null,null,null,null]);
  core.apply(s,{name:'ActionDealTile',step:4,seat:2,left:40,liqiSuccess:{seat:1,score:24000,failed:false}});
  assert.equal(s.riichi[1],true);
  assert.equal(s.doubleRiichi[1],null);
  core.apply(s,{name:'ActionNewRound',step:0,selfSeat:0,hand:['1p'],scores:[25000,25000,25000,25000],
    doras:[],left:69,chang:0,ju:0,ben:0});
  core.apply(s,{name:'ActionDiscardTile',step:1,seat:1,tile:'3p',riichi:true,doubleRiichi:true});
  assert.equal(s.doubleRiichiPending[1],true);
  core.apply(s,{name:'ActionHule',step:2,matchEnd:false});
  assert.equal(s.doubleRiichi[1],false);
  assert.equal(s.doubleRiichiPending[1],false);
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

test('restored replay resumes decisions only after the next continuous live action', () => {
  const opening = {name:'ActionNewRound',step:0,selfSeat:0,
    hand:['1m','2m','3m','1p','2p','3p','4p','5p','6p','7s','8s','9s','1z'],
    scores:[25000,25000,25000,25000],doras:['1s'],left:69,chang:0,ju:1,ben:0};
  const previous = {name:'ActionDealTile',step:1,seat:1,left:68};
  const next = {name:'ActionDealTile',step:2,seat:0,tile:'1z',left:67,selfSeat:0,
    operations:[1],operationDetails:[{type:1,combination:[]}]};
  const state = core.emptyState();
  // Response step is deliberately unrelated: only the next live action verifies the boundary.
  core.applyRestore(state,{actions:[opening,previous],step:99});
  assert.equal(state.handComplete,true);
  assert.equal(state.historyComplete,false);
  assert.equal(state.canAct,false);
  assert.deepEqual(state.recovery,{status:'waiting',reason:'live'});
  assert.equal(core.apply(state,previous),false);
  assert.equal(core.apply(state,opening),false);
  assert.equal(state.historyComplete,false);
  assert.equal(core.apply(state,next),true);
  assert.equal(state.historyComplete,true);
  assert.equal(state.canAct,true);
  assert.equal(state.canDiscard,true);
  assert.equal(state.warning,'');
  assert.equal(state.recovery,null);
  const reference = core.emptyState();
  for (const event of [opening,previous,next]) core.apply(reference,event);
  assert.deepEqual({...state,baseline:reference.baseline},reference);
});

test('authenticated restore retains rank and inferred seat without reopening replayed operations', () => {
  const auth = core.authGame(authResponse(),4000000007), state = core.emptyState();
  Object.assign(state,{match:auth.match,selfSeat:auth.selfSeat,gameId:'game-1'});
  const opening = {name:'ActionNewRound',step:0,
    hand:['1p','1p','2p','3p','4p','5p','6p','7p','8p','9p','1s','1s','1z'],
    scores:Array(4).fill(25000),doras:['1m'],left:69,chang:1,ju:3,ben:0};
  const discard = {name:'ActionDiscardTile',step:1,seat:3,tile:'1p',selfSeat:2,
    operations:[3],operationDetails:[{type:3,combination:['1p|1p']}]};
  core.applyRestore(state,{actions:[opening,discard],step:2});
  assert.deepEqual(state.match,auth.match);
  assert.equal(state.selfSeat,2);
  assert.equal(state.round.isFinal,true);
  assert.equal(state.round.isExtension,false);
  assert.equal(state.handComplete,true);
  assert.equal(state.gameId,'game-1');
  assert.equal(state.historyComplete,false);
  assert.equal(state.canAct,false);
  assert.deepEqual(state.operations,[]);
  assert.equal(core.apply(state,opening),false);
  assert.equal(core.apply(state,discard),false);
  core.apply(state,{name:'ActionDealTile',step:2,seat:0,left:68});
  assert.equal(state.historyComplete,true);
  assert.equal(state.canAct,false);
  assert.deepEqual(state.operations,[]);
  core.apply(state,{...discard,step:3,seat:0});
  assert.equal(state.canAct,true);
  assert.equal(state.canDiscard,false);
  assert.deepEqual(state.operations,[3]);
  assert.deepEqual(state.match,auth.match);
  assert.equal(state.round.isFinal,true);
});

test('restored player-count or seat conflicts clear authenticated rank context', () => {
  const auth = core.authGame(authResponse(),4000000007);
  for (const snapshot of [false,true]) for (const [seat,count] of [[1,4],[2,3]]) {
    const state = core.emptyState();
    Object.assign(state,{match:auth.match,selfSeat:auth.selfSeat});
    const round = {selfSeat:seat,hand:['1p'],doras:[],left:40,chang:1,ju:count-1,ben:0};
    const result = snapshot ? {actions:[],step:7,snapshot:{...round,
      players:Array.from({length:count},()=>({score:25000,discards:[],melds:[]}))}} :
      {actions:[{...round,name:'ActionNewRound',step:0,scores:Array(count).fill(25000)}]};
    core.applyRestore(state,result);
    assert.equal(state.match,null);
    assert.equal(state.round.isFinal,undefined);
    assert.equal(state.round.isExtension,undefined);
    assert.equal(state.historyComplete,false);
    assert.equal(state.canAct,false);
  }
});

test('invalid restored replay or live continuation never enables decisions', async t => {
  const opening = {name:'ActionNewRound',step:0,selfSeat:0,hand:['1p','2p','3p'],
    scores:[35000,35000,35000],doras:[],left:50,chang:0,ju:1,ben:0};
  const previous = {name:'ActionDealTile',step:1,seat:1,left:49};
  const next = {name:'ActionDealTile',step:2,seat:0,tile:'1z',left:48,selfSeat:0,
    operations:[1],operationDetails:[{type:1,combination:[]}]};
  const cases = [
    ['replay gap',[opening,{...previous,step:2}],{...next,step:3}],
    ['replay duplicate',[opening,previous,previous],next],
    ['replay out of order',[opening,previous,{name:'ActionDiscardTile',step:2,seat:1,tile:'4p'},previous],{...next,step:3}],
    ['replay unsupported',[opening,{name:'ActionUnknown',step:1,unsupported:true}],next],
    ['replay hand conflict',[opening,{name:'ActionDiscardTile',step:1,seat:0,tile:'9m'}],next],
    ['live gap',[opening,previous],{...next,step:3}],
    ['live unsupported',[opening,previous],{...next,name:'ActionUnknown',unsupported:true}],
    ['live seat conflict',[opening,previous],{...next,seat:1,selfSeat:1}],
  ];
  for (const [name,actions,continuation] of cases) {
    await t.test(name, () => {
      const state = core.emptyState();
      core.applyRestore(state,{actions,step:actions.at(-1).step});
      core.apply(state,continuation);
      assert.equal(state.historyComplete,false);
      assert.equal(state.canAct,false);
      assert.equal(state.canDiscard,false);
      assert.equal(state.recovery.status,'failed');
    });
  }
  const snapshot = core.emptyState();
  core.applyRestore(snapshot,{actions:[],step:1,snapshot:{selfSeat:0,hand:['1p','2p','3p'],
    doras:[],left:49,chang:0,ju:1,ben:0,players:[{score:35000,discards:[],melds:[]}]}});
  core.apply(snapshot,next);
  assert.equal(snapshot.historyComplete,false);
  assert.equal(snapshot.canAct,false);
  assert.deepEqual(snapshot.recovery,{status:'waiting',reason:'snapshot'});
});

test('complete terminal recovery permits round settlement without opening a decision', () => {
  for (const name of ['ActionHule','ActionNoTile','ActionLiuJu']) {
    const state = Object.assign(core.emptyState(),{gameId:'game-1',recovery:{status:'waiting',reason:'restore'}});
    const opening = {name:'ActionNewRound',step:0,selfSeat:0,hand:['1p'],
      scores:[25000,25000,25000,25000],doras:[],chang:0,ju:0,ben:0};
    core.applyRestore(state,{actions:[opening,{name,step:1,matchEnd:false}],step:2});
    assert.equal(state.phase,'between_rounds');
    assert.equal(state.recovery,null);
    assert.equal(state.gameId,'game-1');
    assert.equal(state.canAct,false); assert.equal(state.operationTiming,null);
    core.applyRestore(state,{actions:[opening,{name,step:3,matchEnd:false}],step:4});
    assert.equal(state.recovery.status,'failed', 'terminal actions cannot repair a replay gap');
  }
});

test('a continuous live action cannot bypass a newer in-flight restore', () => {
  const state = core.emptyState();
  core.applyRestore(state,{actions:[{name:'ActionNewRound',step:0,selfSeat:0,hand:['1p'],
    scores:Array(4).fill(25000),chang:0,ju:0,ben:0}],step:1});
  state.recovery = {status:'waiting',reason:'restore'};
  core.apply(state,{name:'ActionDealTile',step:1,seat:0,tile:'2p',selfSeat:0,
    operations:[1],operationDetails:[{type:1,combination:[]}],
    operationTiming:{timeFixed:5000,timeAdd:20000,receivedAt:9000}});
  assert.equal(state.historyComplete,false); assert.equal(state.canAct,false);
  assert.deepEqual(state.recovery,{status:'waiting',reason:'restore'});
});

test('snapshot recovery waits for a new round and empty recovery retains its waiting state', () => {
  const state = Object.assign(core.emptyState(),{gameId:'game-1',recovery:{status:'waiting',reason:'restore'}});
  core.applyRestore(state,{actions:[],step:0});
  assert.deepEqual(state.recovery,{status:'waiting',reason:'restore'});
  core.applyRestore(state,{actions:[],step:5,snapshot:{selfSeat:0,hand:['1p'],doras:[],left:40,
    chang:0,ju:0,ben:0,players:Array.from({length:4},()=>({score:25000,discards:[],melds:[]}))}});
  assert.deepEqual(state.recovery,{status:'waiting',reason:'snapshot'});
  assert.equal(state.gameId,'game-1');
  core.apply(state,{name:'ActionDealTile',step:6,seat:0,tile:'2p',selfSeat:0,
    operations:[1],operationDetails:[{type:1,combination:[]}],
    operationTiming:{timeFixed:5000,timeAdd:20000,receivedAt:8000}});
  assert.equal(state.canAct,false);
  assert.deepEqual(state.recovery,{status:'waiting',reason:'snapshot'});
  core.apply(state,{name:'ActionNewRound',step:0,selfSeat:0,hand:['2p'],scores:Array(4).fill(25000),
    chang:0,ju:1,ben:0,operations:[1],operationDetails:[{type:1,combination:[]}],
    operationTiming:{timeFixed:5000,timeAdd:20000,receivedAt:9000}});
  assert.equal(state.recovery,null); assert.equal(state.canAct,true);
  assert.equal(state.operationTiming.receivedAt,9000); assert.equal(state.gameId,'game-1');
});

test('reconnected socket restores advice with a fresh key after continuous live actions', async () => {
  const posts = [], keys = [];
  class Socket extends EventTarget {
    constructor(url) {super(); this.url=url; this.readyState=1;}
    send() {return 'sent';}
  }
  const window = {WebSocket:Socket, __mjStatsOverlay:{invalidateAdvice(){},expectAdvice(key){keys.push(key);}},
    webkit:{messageHandlers:{mjStatistics:{postMessage:raw=>posts.push(JSON.parse(raw))}}}};
  vm.runInNewContext(collectorCode,{window,location:{hostname:'game.maj-soul.com'},TextDecoder,performance,
    Uint8Array,ArrayBuffer,Blob,URL,setInterval:fn=>fn,clearInterval(){},console:{log(){}}});
  const feed = async (socket,frame) => {
    socket.dispatchEvent(new MessageEvent('message',{data:frame.buffer}));
    await new Promise(setImmediate);
  };
  const authenticate = async (socket,id) => {
    socket.send(rpcFrame(2,id,'.lq.FastTest.authGame',[...num(1,11),...str(3,'private-reconnect-game')]));
    await feed(socket,rpcFrame(3,id,'',authResponse({modeId:24,mode:12,seats:[11,22,4000000007]})));
    assert.equal(window.__mjMonitor.getSnapshot().state.match.modeId,24);
  };
  const opening = [...str(4,'1p'),...str(4,'2p'),...str(4,'3p'),...num(6,35000),...num(6,35000),
    ...num(6,35000),...bytes(7,[...num(1,0),...bytes(2,num(1,1))]),...num(13,50)];
  const old = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-old');
  await authenticate(old,40);
  await feed(old,actionFrame('ActionNewRound',0,opening));
  assert.equal(posts.at(-1).state.canAct,true);
  assert.equal(posts.at(-1).state.recovery,null);
  const originalGameId = posts.at(-1).state.gameId;
  assert.equal(typeof originalGameId,'string');
  const originalKey = keys.at(-1);
  old.dispatchEvent(new Event('close'));
  assert.equal(window.__mjMonitor.getSnapshot().state.canAct,false);
  assert.equal(window.__mjMonitor.getSnapshot().state.match,null);
  assert.equal(posts.at(-1).recovery.status,'waiting');
  const game = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-new');
  assert.equal(window.__mjMonitor.getSnapshot().state.match,null);
  await authenticate(game,41);
  game.send(new Uint8Array([2,42,0,...str(1,'.lq.FastTest.syncGame'),...bytes(2,[])]));
  const previous = [...num(1,1),...num(3,49)];
  const raw = (name,step,data) => bytes(2,[...num(1,step),...str(2,name),...bytes(3,data)]);
  await feed(game,new Uint8Array([3,42,0,...bytes(2,[...num(3,2),...bytes(4,[
    ...raw('ActionNewRound',0,opening),...raw('ActionDealTile',1,previous)])])]));
  assert.equal(posts.at(-1).state.handComplete,true);
  assert.equal(posts.at(-1).state.historyComplete,false);
  assert.equal(posts.at(-1).state.canAct,false);
  assert.deepEqual(posts.at(-1).state.recovery,{status:'waiting',reason:'live'});
  assert.equal(posts.at(-1).state.gameId,originalGameId);
  assert.equal(posts.at(-1).state.operationTiming,null);
  assert.equal(posts.at(-1).state.match.modeId,24);
  assert.equal(posts.at(-1).state.selfSeat,0);
  assert.equal(posts.at(-1).state.round.isFinal,false);
  assert.match(posts.at(-2).message,/syncGame.*等待连续实时动作确认恢复边界/);
  const restoredKey = keys.at(-1), count = posts.length;
  await feed(game,actionFrame('ActionDealTile',1,previous));
  assert.equal(posts.length,count);
  assert.equal(window.__mjMonitor.getSnapshot().state.historyComplete,false);
  await feed(game,actionFrame('ActionDealTile',2,[...num(1,0),...str(2,'4p'),...num(3,48),
    ...bytes(4,[...num(1,0),...bytes(2,num(1,1))])]));
  const latest = posts.at(-1);
  assert.equal(latest.state.historyComplete,true);
  assert.equal(latest.state.canAct,true);
  assert.equal(latest.state.canDiscard,true);
  assert.equal(latest.state.warning,'');
  assert.equal(latest.state.recovery,null);
  assert.equal(latest.state.match.modeId,24);
  assert.equal(keys.at(-1),`${latest.session}:${latest.serial}`);
  assert.notEqual(keys.at(-1),originalKey);
  assert.notEqual(keys.at(-1),restoredKey);
  assert.equal(window.__mjMonitor.getSnapshot().errors,0);
  assert.doesNotMatch(JSON.stringify(posts),/private-reconnect-game/);
  window.__mjMonitor.uninstall();
});

test('an authenticated lobby with no active game clears only pending recovery and publishes a waiting reset', async () => {
  const posts = [];
  class Socket extends EventTarget {
    constructor(url) {super(); this.url=url; this.readyState=1;}
    send() {}
  }
  const window = {WebSocket:Socket,webkit:{messageHandlers:{mjStatistics:{postMessage:raw=>posts.push(JSON.parse(raw))}}}};
  vm.runInNewContext(collectorCode,{window,location:{hostname:'game.maj-soul.com'},TextDecoder,performance,
    Uint8Array,ArrayBuffer,Blob,URL,setInterval:fn=>fn,clearInterval(){},console:{log(){}}});
  const monitor = window.__mjMonitor;
  const initialPosts = posts.length;
  monitor.onLobbyRecovery();
  assert.equal(posts.length,initialPosts, 'ordinary initial loading is untouched');
  const game = new window.WebSocket('wss://sample.maj-soul.com/game-gateway');
  const feed = async frame => {
    game.dispatchEvent(new MessageEvent('message',{data:frame.buffer}));
    await new Promise(setImmediate);
  };
  await feed(actionFrame('ActionNewRound',0,[...str(4,'1p'),...Array(4).fill(0).flatMap(()=>num(6,25000)),
    ...bytes(7,[...num(1,0),...bytes(2,num(1,1))])]));
  const playing = JSON.stringify(monitor.getSnapshot()), playingPosts = posts.length;
  monitor.onLobbyRecovery();
  assert.equal(JSON.stringify(monitor.getSnapshot()),playing);
  assert.equal(posts.length,playingPosts, 'an active game cannot be reset by this callback');
  game.dispatchEvent(new Event('close'));
  assert.equal(monitor.getSnapshot().state.recovery.status,'waiting');
  monitor.onLobbyRecovery();
  const reset = monitor.getSnapshot();
  assert.deepEqual(JSON.parse(JSON.stringify(reset.state)),{...core.emptyState(),phase:'waiting',warning:''});
  assert.equal(reset.turns,0); assert.equal(reset.received,0); assert.equal(reset.errors,0);
  assert.equal(posts.at(-1).phase,'waiting'); assert.equal(posts.at(-1).reset,true);
  assert.equal(posts.at(-1).recovery,null);
  const afterReset = posts.length;
  monitor.onLobbyRecovery(); assert.equal(posts.length,afterReset, 'repeated lobby evidence cannot reset twice');
  const next = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-next');
  next.dispatchEvent(new MessageEvent('message',{data:new Uint8Array([1,255]).buffer}));
  await new Promise(setImmediate);
  assert.equal(monitor.getSnapshot().state.recovery.status,'failed');
  const failed = JSON.stringify(monitor.getSnapshot()), failedPosts = posts.length;
  monitor.onLobbyRecovery();
  assert.equal(JSON.stringify(monitor.getSnapshot()),failed);
  assert.equal(posts.length,failedPosts, 'real parse errors must not be hidden by lobby recovery');
  monitor.uninstall();
});

test('replaced sockets cannot apply delayed frames or errors to the active connection', async t => {
  for (const [closed,rejection] of [[true,false],[true,true],[false,false],[false,true]]) {
    await t.test(`${closed ? 'closed' : 'open'} socket delayed ${rejection ? 'error' : 'action'}`, async () => {
      let resume;
      class DelayedBlob extends Blob {
        arrayBuffer() {return new Promise((resolve,reject) => {
          resume = () => rejection ? reject(new Error('old connection')) : super.arrayBuffer().then(resolve);
        });}
      }
      class Socket extends EventTarget {
        constructor(url) {super(); this.url=url; this.readyState=1;}
        send() {}
      }
      const posts = [];
      const window = {WebSocket:Socket,webkit:{messageHandlers:{mjStatistics:{postMessage:raw=>posts.push(JSON.parse(raw))}}}};
      vm.runInNewContext(collectorCode,{window,location:{hostname:'game.maj-soul.com'},TextDecoder,performance,
        Uint8Array,ArrayBuffer,Blob,URL,setInterval:fn=>fn,clearInterval(){},console:{log(){}}});
      const old = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-old');
      old.dispatchEvent(new MessageEvent('message',{data:new DelayedBlob([Buffer.from(frames[0].hex,'hex')])}));
      await new Promise(setImmediate);
      if (closed) old.dispatchEvent(new Event('close'));
      const game = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-new');
      game.send(rpcFrame(2,41,'.lq.FastTest.authGame',num(1,22)));
      game.dispatchEvent(new MessageEvent('message',{data:rpcFrame(3,41,'',authResponse({
        modeId:24,mode:12,seats:[11,22,4000000007]})).buffer}));
      game.dispatchEvent(new MessageEvent('message',{data:Uint8Array.from(Buffer.from(frames.at(-1).hex,'hex')).buffer}));
      await new Promise(setImmediate);
      const before = window.__mjMonitor.getSnapshot(), count = posts.length;
      assert.equal(before.state.match.modeId,24);
      resume();
      await new Promise(setImmediate);
      assert.deepEqual(window.__mjMonitor.getSnapshot(),before);
      assert.equal(posts.length,count);
      window.__mjMonitor.uninstall();
    });
  }
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

test('collector sends authoritative windows and manual operation invalidation to automation', async () => {
  const events = [], inputs = [], sent = [];
  let stopped = false;
  class Socket extends EventTarget {
    constructor(url) {super();this.url=url;this.readyState=1;}
    send(data) {sent.push(data);}
  }
  const window = {WebSocket:Socket, __mjAutoplay:{onEvent:e=>events.push(e),
    onInput:()=>inputs.push(true),stop:()=>{stopped=true;}},
    webkit:{messageHandlers:{mjStatistics:{postMessage(){}}}}};
  vm.runInNewContext(collectorCode,{window,location:{hostname:'game.maj-soul.com'},TextDecoder,performance,
    Uint8Array,ArrayBuffer,Blob,URL,setInterval:()=>0,clearInterval(){},console:{log(){}}});
  const game = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-zone');
  const opening = actionFrame('ActionNewRound',0,[...num(2,0),
    ...Array(14).fill('1p').flatMap(tile=>str(4,tile)),
    ...Array(4).fill(25000).flatMap(score=>num(6,score)),
    ...bytes(7,[...num(1,0),...bytes(2,num(1,1))])]);
  game.dispatchEvent(new MessageEvent('message',{data:opening.buffer}));
  await new Promise(setImmediate);
  const turn = events.find(e=>e.kind==='turn');
  assert.equal(turn.state.canAct,true);assert.equal(turn.state.lastStep,0);
  assert.ok(turn.session);assert.ok(Number.isInteger(turn.serial));
  const request=rpcFrame(2,1,'.lq.FastTest.inputOperation',[]);game.send(request);
  assert.equal(inputs.length,1);assert.equal(sent[0],request);
  assert.equal(window.__mjMonitor.getSnapshot().state.canAct,false);
  assert.equal(turn.state.canAct,true); // The published window is an immutable snapshot.
  game.dispatchEvent(new Event('close'));
  assert.equal(events.at(-1).phase,'disconnected');
  window.__mjMonitor.stop();assert.equal(stopped,true);
});

test('native listener preserves socket sends and fully detaches on uninstall', async () => {
  const posts = [], sent = [], timers = new Set();
  class Socket extends EventTarget {
    constructor(url) {super(); this.url = url; this.readyState = 1;}
    send(...args) {sent.push({socket:this,args}); return 'original-result';}
  }
  const window = {WebSocket:Socket, webkit:{messageHandlers:{mjStatistics:{postMessage:raw=>posts.push(JSON.parse(raw))}}}};
  const sandbox = {window, location:{hostname:'game.maj-soul.com'}, TextDecoder,performance, Uint8Array, ArrayBuffer, Blob, URL,
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

for (const injected of ['none', 'acknowledged', 'pending']) test(`collector uninstall coordinates transport shutdown (${injected})`, async () => {
  const posts = [], sent = [], received = [], timers = new Set();
  class Socket extends EventTarget {
    constructor(url) {super(); this.url = url; this.readyState = 1;}
    send(data) {sent.push(data);}
  }
  const window = {WebSocket:Socket, webkit:{messageHandlers:{mjStatistics:{postMessage:raw=>posts.push(JSON.parse(raw))}}}};
  const context = vm.createContext({window, core, location:{hostname:'game.maj-soul.com',href:'https://game.maj-soul.com/1/'},
    TextEncoder, TextDecoder, performance, Uint8Array, ArrayBuffer, Blob, URL, MessageEvent,
    setTimeout:fn=>{timers.add(fn);return fn;}, clearTimeout:fn=>timers.delete(fn),
    setInterval:fn=>{timers.add(fn);return fn;}, clearInterval:fn=>timers.delete(fn), console:{log(){}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/unity_transport.js'), 'utf8'), context);
  vm.runInContext(collectorCode, context);
  const game = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-zone');
  game.addEventListener('message', event=>received.push(core.envelope(new Uint8Array(event.data))));
  const feed = async data => {
    game.dispatchEvent(new MessageEvent('message', {data:data.buffer}));
    await new Promise(setImmediate);
  };
  game.send(rpcFrame(2, 7, '.lq.FastTest.authGame', num(1,23)));
  await feed(rpcFrame(3, 7, '', []));
  let work, wireId;
  if (injected !== 'none') {
    work = window.__mjUnityTransport.request('.lq.FastTest.confirmNewRound', new Uint8Array());
    wireId = core.envelope(sent.at(-1)).id;
    if (injected === 'acknowledged') {await feed(rpcFrame(3, wireId, '', [])); await work;}
  }
  window.__mjMonitor.uninstall();
  assert.equal(window.WebSocket, Socket);
  if (injected === 'pending') await assert.rejects(work, /已停止/);
  assert.equal(timers.size, 0);
  const before = sent.length;
  await assert.rejects(window.__mjUnityTransport.request('.lq.FastTest.confirmNewRound', new Uint8Array()), /已停止/);
  assert.equal(sent.length, before);
  if (injected === 'pending') {
    const count = received.length;
    await feed(rpcFrame(3, wireId, '', []));
    assert.equal(received.length, count, 'a late automation ACK never reaches Unity');
    game.send(rpcFrame(2, wireId, '.lq.FastTest.heartbeat', []));
    const remapped = core.envelope(sent.at(-1)).id;
    await feed(rpcFrame(3, remapped, '', []));
    assert.equal(received.at(-1).id, wireId, 'native IDs remain correlated after shutdown');
  } else assert.equal(game.send, Socket.prototype.send);
});

test('browser correlates authGame separately from restore and clears stale rank metadata', async () => {
  const posts = [], sent = [];
  let invalidations = 0;
  class Socket extends EventTarget {
    constructor(url) {super(); this.url = url; this.readyState = 1;}
    send(data) {sent.push(data); return 'original';}
  }
  const window = {WebSocket:Socket,__mjStatsOverlay:{invalidateAdvice(){invalidations++;}},
    webkit:{messageHandlers:{mjStatistics:{postMessage:raw=>posts.push(JSON.parse(raw))}}}};
  vm.runInNewContext(collectorCode,{window,location:{hostname:'game.maj-soul.com'},TextDecoder,performance,
    Uint8Array,ArrayBuffer,Blob,URL,setInterval:()=>0,clearInterval(){},console:{log(){}}});
  const game = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-zone');
  const receive = async (socket, data) => {
    socket.dispatchEvent(new MessageEvent('message',{data:data.buffer}));
    await new Promise(setImmediate);
  };
  const authenticate = (socket,id,uuid='private-game-uuid') => {
    const request = rpcFrame(2,id,'.lq.FastTest.authGame',[...num(1,4000000007),
      ...str(2,'private-token'),...str(3,uuid)]);
    assert.equal(socket.send(request),'original'); assert.equal(sent.at(-1),request);
  };
  const state = () => window.__mjMonitor.getSnapshot().state;
  const reply = id => rpcFrame(3,id,'',authResponse());
  authenticate(game,42);
  await receive(game,reply(41));
  assert.equal(state().match,null);
  await receive(game,reply(42));
  const originalGameId = state().gameId;
  assert.equal(originalGameId,'game-1');
  assert.equal(state().recovery,null);
  assert.equal(state().match.levelId,10403); assert.equal(state().selfSeat,2);
  assert.equal(state().lastStep,null); assert.equal(state().phase,'connected');
  assert.equal(posts.filter(p=>p.kind==='turn').length,0);
  const opening = actionFrame('ActionNewRound',0,[...num(1,1),...num(2,3),...str(4,'1p'),
    ...Array(4).fill(0).flatMap(()=>num(6,25000)),...num(13,60)]);
  await receive(game,opening);
  assert.equal(state().round.isFinal,true); assert.equal(state().match.modeId,12);
  assert.equal(state().selfSeat,2);
  game.send(rpcFrame(2,43,'.lq.FastTest.syncGame',[]));
  assert.deepEqual(JSON.parse(JSON.stringify(state().recovery)),{status:'waiting',reason:'restore'});
  assert.equal(state().canAct,false); assert.equal(state().lastAction,null);
  assert.equal(posts.at(-1).recovery.status,'waiting', 'same-socket sync closes the old window before its response');
  await receive(game,actionFrame('ActionNewRound',1,[...num(1,1),...num(2,3),...num(3,1),...str(4,'1p'),
    ...Array(4).fill(0).flatMap(()=>num(6,25000)),...bytes(7,[...num(1,2),...bytes(2,num(1,1))])]));
  assert.equal(state().canAct,false, 'a queued new round cannot reopen a window while sync is in flight');
  assert.equal(state().operationTiming,null);
  assert.equal(state().recovery.reason,'restore');
  await receive(game,rpcFrame(3,43,'',[...num(3,1)]));
  assert.equal(state().match.modeId,12); assert.equal(state().canAct,false);
  // A second game authenticating on the same socket invalidates the previous game.
  authenticate(game,44);
  assert.equal(state().gameId,null, 'identity is bound only by a successful authentication');
  assert.equal(state().recovery.reason,'authentication');
  assert.equal(posts.at(-1).recovery.reason,'authentication');
  assert.equal(state().match,null); assert.equal(state().round,null);
  await receive(game,rpcFrame(3,44,'',authResponse({category:1})));
  assert.equal(state().match,null);
  // Reusing a request id for a different method must cancel the old correlation.
  authenticate(game,45);
  game.send(rpcFrame(2,45,'.lq.FastTest.heartbeat',[]));
  await receive(game,reply(45)); assert.equal(state().match,null);
  authenticate(game,46); authenticate(game,47);
  await receive(game,reply(46)); assert.equal(state().match,null);
  await receive(game,reply(47)); assert.equal(state().match.modeId,12);
  assert.equal(state().gameId,originalGameId);
  // A newly opened connection clears the old match before receiving any actions.
  const previousInvalidations = invalidations;
  const next = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-next');
  assert.equal(invalidations,previousInvalidations+1);
  assert.equal(state().match,null);
  await receive(game,opening); assert.equal(state().round,null);
  authenticate(next,48);
  await receive(next,reply(48)); assert.equal(state().match.modeId,12);
  await receive(game,reply(47)); assert.equal(state().match.modeId,12);
  // Auth failure, malformed data, disconnect, stop and whole-match end fail closed.
  authenticate(next,49);
  await receive(next,rpcFrame(3,49,'',bytes(1,num(1,1001))));
  assert.equal(state().match,null);
  authenticate(next,50); await receive(next,reply(50));
  await receive(next,new Uint8Array([1,255]));
  assert.equal(state().match,null);
  authenticate(next,51); await receive(next,reply(51));
  await receive(next,new Uint8Array([1,...str(1,'.lq.NotifyGameEndResult'),...bytes(2,[])]));
  assert.equal(state().match,null); assert.equal(state().phase,'ended');
  await receive(next,reply(51)); assert.equal(state().match,null);
  authenticate(next,52); await receive(next,reply(52));
  next.dispatchEvent(new Event('close')); assert.equal(state().match,null);
  const final = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-final');
  authenticate(final,53,'private-new-game'); await receive(final,reply(53));
  assert.notEqual(state().gameId,originalGameId, 'a different authenticated game has a different opaque identity');
  window.__mjMonitor.stop(); assert.equal(state().match,null);
  assert.doesNotMatch(JSON.stringify(posts),/4000000007|private-token|private-game-uuid|private-new-game|private-nickname|accountId/);
});

test('sending a decision clears stale advice immediately and preserves the original RPC unchanged', async () => {
  const posts = [], sent = [];
  let invalidations = 0;
  class Socket extends EventTarget {
    constructor(url) {super(); this.url = url; this.readyState = 1;}
    send(...args) {sent.push({socket:this,args}); return 'original-result';}
  }
  const window = {WebSocket:Socket, __mjStatsOverlay:{invalidateAdvice(){invalidations++;}},
    webkit:{messageHandlers:{mjStatistics:{postMessage:raw=>posts.push(JSON.parse(raw))}}}};
  const sandbox = {window, location:{hostname:'game.maj-soul.com'}, TextDecoder,performance, Uint8Array, ArrayBuffer, Blob, URL,
    setInterval:fn=>fn, clearInterval(){}, console:{log(){}}};
  vm.runInNewContext(collectorCode,sandbox);
  const game = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-zone');
  const feed = async frame => {
    game.dispatchEvent(new MessageEvent('message',{data:frame.buffer}));
    await new Promise(setImmediate);
  };
  for (const [index, method] of ['inputOperation','inputChiPengGang'].entries()) {
    await feed(actionFrame('ActionNewRound',0,[...num(2,index), ...str(4,'1p'), ...str(4,'5p'),
      ...num(6,35000), ...num(6,35000), ...num(6,35000),
      ...bytes(7,[...num(1,0), ...bytes(2,num(1,1)), ...bytes(2,[...num(1,7), ...str(2,'1p')])]), ...num(13,50)]));
    assert.equal(window.__mjMonitor.getSnapshot().state.canAct,true);
    const before = invalidations;
    const heartbeat = new Uint8Array([2,10,0,...str(1,'.lq.FastTest.heartbeat'),...bytes(2,[])]);
    assert.equal(game.send(heartbeat),'original-result');
    assert.equal(invalidations,before);
    assert.equal(window.__mjMonitor.getSnapshot().state.canAct,true);
    const decision = new Uint8Array([2,11,0,...str(1,`.lq.FastTest.${method}`),...bytes(2,num(1,1))]);
    assert.equal(game.send(decision,'extra'),'original-result');
    assert.equal(sent.at(-1).socket,game);
    assert.equal(sent.at(-1).args[0],decision);
    assert.equal(sent.at(-1).args[1],'extra');
    assert.equal(invalidations,before+1);
    const state = window.__mjMonitor.getSnapshot().state;
    assert.equal(state.canAct,false);
    assert.equal(state.canDiscard,false);
    assert.equal(state.canDoubleRiichi,false);
    assert.equal(state.lastAction,null);
    assert.equal(state.operations.length,0);
    assert.equal(state.operationDetails.length,0);
    assert.equal(state.forbiddenDiscards.length,0);
  }
  window.__mjMonitor.uninstall();
});

test('parse errors, disconnection and stopping all close an active decision window', async () => {
  for (const ending of ['error','close','stop']) {
    class Socket extends EventTarget {
      constructor(url) {super(); this.url = url; this.readyState = 1;}
      send() {}
    }
    const window = {WebSocket:Socket, __mjStatsOverlay:{invalidateAdvice(){}},
      webkit:{messageHandlers:{mjStatistics:{postMessage(){}}}}};
    const sandbox = {window, location:{hostname:'game.maj-soul.com'}, TextDecoder,performance, Uint8Array, ArrayBuffer, Blob, URL,
      setInterval:fn=>fn, clearInterval(){}, console:{log(){}}};
    vm.runInNewContext(collectorCode,sandbox);
    const game = new window.WebSocket('wss://sample.maj-soul.com/game-gateway-zone');
    const opening = actionFrame('ActionNewRound',0,[...str(4,'1p'), ...num(6,35000), ...num(6,35000),
      ...num(6,35000), ...bytes(7,[...num(1,0), ...bytes(2,num(1,1))]), ...num(13,50)]);
    game.dispatchEvent(new MessageEvent('message',{data:opening.buffer}));
    await new Promise(setImmediate);
    assert.equal(window.__mjMonitor.getSnapshot().state.canAct,true);
    if (ending === 'error') {
      game.dispatchEvent(new MessageEvent('message',{data:new Uint8Array([1,0]).buffer}));
      await new Promise(setImmediate);
    } else if (ending === 'close') game.dispatchEvent(new Event('close'));
    else window.__mjMonitor.stop();
    const state = window.__mjMonitor.getSnapshot().state;
    assert.equal(state.canAct,false);
    assert.equal(state.canDiscard,false);
    assert.equal(state.canDoubleRiichi,false);
    assert.equal(state.lastAction,null);
    assert.equal(state.operations.length,0);
    window.__mjMonitor.uninstall();
  }
});

test('native bridge publishes every action and one initial deal without requiring own discard operation', async () => {
  const posts = [], timers = new Set(), sent = [];
  class Socket extends EventTarget {
    constructor(url) {super(); this.url = url; this.readyState = 1;}
    send(data) {sent.push(data); return 'ok';}
  }
  const window = {WebSocket:Socket, webkit:{messageHandlers:{mjStatistics:{postMessage:raw=>posts.push(JSON.parse(raw))}}}};
  const sandbox = {window, location:{hostname:'game.maj-soul.com'}, TextDecoder,performance, Uint8Array, ArrayBuffer, Blob, URL,
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
      const sandbox = {window, location:{hostname:'game.maj-soul.com'}, TextDecoder,performance, Uint8Array, ArrayBuffer, Blob, URL,
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
