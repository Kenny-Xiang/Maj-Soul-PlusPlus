const test = require('node:test');
const assert = require('node:assert/strict');
const core = require('../src/core.cjs');
const {extractGame, projectRecord, visibleState} = require('../src/policy_replay.cjs');
const fixture = require('./fixtures/policy_replay_synthetic.json');
const copy = value => JSON.parse(JSON.stringify(value));
const start = () => copy(fixture.records[0]);
const op = (seat, type, combination = []) => ({seat, operation_list:[{type, combination}]});
const record = (name, data, userInputs) => ({name, data, ...(userInputs ? {userInputs} : {})});
const game = records => ({gameId:'synthetic', ruleset:'majsoul-standard-v1', source:{kind:'hand-authored'}, records});
const sanmaStart = () => {
  const opening = start();
  opening.data.scores = [35000,35000,35000]; opening.data.tiles3 = [];
  opening.data.tiles0 = ['1m','9m','1p','2p','3p','4p','5p','6p','1s','2s','3s','1z','4z','5z'];
  opening.data.tiles1 = ['1m','9m','0p','5p','6p','7p','8p','4s','5s','6s','5z','6z','7z'];
  opening.data.tiles2 = ['1m','9m','1p','2p','3p','7s','8s','9s','2z','3z','4z','7z','5s'];
  return opening;
};

test('red pon and post-call discard retain exact consumed tiles and pre-action windows', () => {
  const result = extractGame(fixture);
  assert.deepEqual(result.samples.map(s => s.action.action), ['discard', 'pon', 'discard']);
  const pon = result.samples[1], discard = result.samples[2];
  assert.deepEqual(pon.action, {action:'pon', tile:'5p', calledTile:'5p', fromSeat:0, consumed:['0p', '5p']});
  assert.equal(pon.state.melds[1].length, 0);
  assert.equal(pon.state.rivers[0][0].called, false);
  assert.equal(discard.state.melds[1].length, 1);
  assert.equal(discard.state.rivers[0][0].called, true);
  assert.deepEqual(discard.state.forbiddenDiscards, ['5p']);
  assert.equal(result.audit.emitted, 3);
});

test('hidden hands, future wall, outcomes, source and account data never alter earlier actor observation', () => {
  const changed = copy(fixture);
  changed.records[0].data.tiles2.reverse();
  changed.records[0].data.tiles3.fill('9s');
  changed.records[0].data.paishan = 'CHANGED_FUTURE_WALL';
  changed.records[0].data.tingpai = [{seat:2, private:'SECRET'}];
  changed.source = {secret:'SOURCE_SECRET'};
  changed.head.accounts = [{nickname:'PRIVATE_NAME'}];
  changed.records.at(-1).data.players = [{hand:['PRIVATE_REVEAL']}];
  const original = extractGame(fixture), modified = extractGame(changed);
  assert.deepEqual(modified.samples[0].state, original.samples[0].state);
  assert.deepEqual(modified.samples[1].state, original.samples[1].state);
  assert.doesNotMatch(JSON.stringify(modified.samples), /SECRET|PRIVATE|paishan|nickname|tingpai/);
});

test('other player real draw and furiten are projected out before core.apply', () => {
  const a = record('RecordDealTile', {seat:2, tile:'0s', left_tile_count:55,
    zhenting:[false, false, true, false], operation:op(2, 8)});
  const b = copy(a); b.data.tile = '9m'; b.data.zhenting[2] = false;
  assert.deepEqual(projectRecord(a, 0, 1), projectRecord(b, 0, 1));
  assert.equal(projectRecord(a, 0, 1).tile, null);
  assert.equal(projectRecord(a, 0, 1).operationDetails, undefined);
  assert.equal(projectRecord(a, 2, 1).tile, '0s');
});

test('offline decision snapshot equals the existing live core event path', () => {
  const state = core.emptyState();
  core.setMatch(state, {playerCount:4, roundCount:2});
  core.apply(state, {name:'ActionNewRound', step:0, selfSeat:1,
    hand:fixture.records[0].data.tiles1, scores:[25000,25000,25000,25000],
    chang:0, ju:0, ben:0, left:69, riichiSticks:0, doras:['9p']});
  core.apply(state, {name:'ActionDiscardTile', step:1, seat:0, tile:'5p', moqie:false,
    riichi:false, doubleRiichi:false, selfSeat:1, operations:[3],
    operationDetails:[{type:3, combination:['0p|5p']}]});
  assert.deepEqual(visibleState(state), extractGame(fixture).samples[1].state);
});

test('a winning competing call is censored, never an inferred pass', () => {
  const value = copy(fixture);
  value.records[1].data.operations.push(op(2, 9));
  const result = extractGame(value);
  assert.equal(result.audit.excluded.censored_response, 1);
  assert.equal(result.samples.some(s => s.seat === 2), false);
});

test('explicit cancellation before a competing call is retained as pass', () => {
  const value = copy(fixture);
  value.records[1].data.operations.push(op(2, 9));
  value.records[1].userInputs = [{seat:2, cpg:{cancel_operation:true}}];
  const pass = extractGame(value).samples.find(s => s.seat === 2);
  assert.equal(pass.action.action, 'pass'); assert.equal(pass.labelSource, 'explicit');
});

test('only a normally completed response window can infer pass', () => {
  const value = copy(fixture);
  value.records = value.records.slice(0, 2);
  value.records.push(record('RecordDealTile', {seat:1, tile:'9p', left_tile_count:68}));
  const result = extractGame(value);
  assert.equal(result.samples[1].action.action, 'pass');
  assert.equal(result.samples[1].labelSource, 'inferred_pass');
  value.records.pop();
  assert.equal(extractGame(value).audit.excluded.unfinished_window, 1);
});

test('conflicting explicit input is excluded rather than relabeled to accepted result', () => {
  const value = copy(fixture);
  value.records[1].userInputs = [{seat:1, cpg:{cancel_operation:true}}];
  const result = extractGame(value);
  assert.equal(result.audit.excluded.conflicting_input, 1);
  assert.equal(result.samples.some(s => s.action.action === 'pon'), false);
});

test('proto absent zero scalars and opening dealer request moqie are normalized', () => {
  const value = copy(fixture);
  for (const key of ['ju', 'chang', 'ben', 'liqibang']) delete value.records[0].data[key];
  delete value.records[0].data.operation.seat;
  delete value.records[1].data.seat;
  value.records[0].userInputs = [{operation:{type:1, tile:'5p', moqie:true}}];
  const result = extractGame(value);
  assert.equal(result.samples[0].labelSource, 'explicit');
  assert.equal(result.samples[0].action.moqie, false);
  assert.equal(result.samples[0].state.selfSeat, 0);
});

test('missing operations produce an audit exclusion and no fabricated legal set', () => {
  const value = copy(fixture); delete value.records[0].data.operation;
  const result = extractGame(value);
  assert.equal(result.audit.excluded.missing_actor_operations, 1);
  assert.equal(result.samples.some(s => s.state.lastAction.name === 'ActionNewRound'), false);
});

test('three-player absent fourth slot never creates a fourth player', () => {
  const opening = sanmaStart();
  opening.data.operation = op(0, 11);
  const result = extractGame(game([opening, record('RecordBaBei', {seat:0, moqie:false})]));
  assert.equal(result.samples[0].state.playerCount, 3);
  assert.equal(result.samples[0].action.action, 'kita');
  assert.equal(result.samples[0].state.north[0], 0);
  opening.data.tiles3 = ['1p'];
  assert.throws(() => extractGame(game([opening])), /absent seat/);
});

test('riichi declaration label precedes success and score deduction', () => {
  const opening = start(); opening.data.operation.operation_list.push({type:7, combination:['5p']});
  const records = [opening,
    record('RecordDiscardTile', {seat:0, tile:'5p', is_liqi:true}),
    record('RecordDealTile', {seat:1, tile:'9p', left_tile_count:68,
      liqi:{seat:0, score:24000, liqibang:1}, operation:op(1,1)}),
    record('RecordDiscardTile', {seat:1, tile:'9p', moqie:true})];
  const result = extractGame(game(records));
  assert.equal(result.samples[0].action.action, 'riichi');
  assert.equal(result.samples[0].state.riichi[0], false);
  assert.equal(result.samples[0].state.scores[0], 25000);
  assert.equal(result.samples[1].state.riichi[0], true);
  assert.equal(result.samples[1].state.scores[0], 24000);
  assert.equal(result.samples[1].state.riichiSticks, 1);
});

test('all winners in multi-ron get their own frozen response sample', () => {
  const opening = start();
  const result = extractGame(game([opening,
    record('RecordDiscardTile', {seat:0, tile:'5p', operations:[op(1,9), op(2,9)]}),
    record('RecordHule', {hules:[{seat:1}, {seat:2}], scores:[1000,40000,40000,19000]})]));
  const wins = result.samples.filter(s => s.action.action === 'ron');
  assert.deepEqual(wins.map(s => s.seat), [1,2]);
  assert.equal(wins.every(s => s.action.fromSeat === 0 && s.state.scores[0] === 25000), true);
});

test('ankan preserves four exact tiles and opens a separate robbing response', () => {
  const opening = start();
  opening.data.tiles0.splice(0, 4, '0p', '5p', '5p', '5p');
  opening.data.tiles0[13] = '9p';
  opening.data.operation = op(0,4,['0p|5p|5p|5p']);
  const result = extractGame(game([opening,
    record('RecordAnGangAddGang', {seat:0, type:3, tiles:'5p', operations:[op(1,9)]}),
    record('RecordHule', {hules:[{seat:1}]})]));
  assert.deepEqual(result.samples[0].action.consumed, ['0p','5p','5p','5p']);
  assert.equal(result.samples[1].action.action, 'ron');
  assert.equal(result.samples[1].state.lastAction.name, 'ActionAnGangAddGang');
});

test('kita response can be declined before replacement draw without seeing that draw', () => {
  const opening = sanmaStart();
  opening.data.operation = op(0,11);
  const result = extractGame(game([opening,
    record('RecordBaBei', {seat:0, operations:[op(1,9)]}),
    record('RecordDealTile', {seat:0, tile:'9s', left_tile_count:53})]));
  assert.equal(result.samples[1].action.action, 'pass');
  assert.equal(result.samples[1].state.lastAction.tile, '4z');
  assert.equal(result.samples[1].state.north[0], 1);
  assert.equal(result.samples[1].state.hand.includes('9s'), false);
  assert.equal(result.samples[1].state.lastDraw, null);
});

test('tsumo and voluntary nine-terminals abort are actual decisions', () => {
  for (const [type, next, action] of [[8, record('RecordHule',{hules:[{seat:0,zimo:true}]}), 'tsumo'],
    [10, record('RecordLiuJu',{type:1,seat:0}), 'abort']]) {
    const opening = start(); opening.data.operation = op(0,type);
    assert.equal(extractGame(game([opening,next])).samples[0].action.action, action);
  }
});

test('unsupported events invalidate the rest of that round and truncated windows remain excluded', () => {
  const value = game([start(), record('RecordFutureUnknown', {}),
    record('RecordDealTile', {seat:0,tile:'9p',left_tile_count:60,operation:op(0,1)}),
    record('RecordDiscardTile', {seat:0,tile:'9p',moqie:true})]);
  const result = extractGame(value);
  assert.equal(result.samples.length, 0);
  assert.equal(result.audit.excluded.incomplete_state, 1);
});

test('chi and daiminkan retain their exact consumed combinations', () => {
  for (const [type, operationType, consumed, kind] of [[0, 2, ['4p','6p'], 'chi'],
    [2, 5, ['0p','5p','5p'], 'daiminkan']]) {
    const opening = start(); opening.data.tiles1[0] = type === 0 ? '4p' : '5p';
    const result = extractGame(game([opening,
      record('RecordDiscardTile', {seat:0,tile:'5p',operations:[op(1,operationType,[consumed.join('|')])]}),
      record('RecordChiPengGang', {seat:1,type,tiles:[...consumed,'5p'],froms:[...consumed.map(() => 1),0]})]));
    assert.equal(result.samples[1].action.action, kind);
    assert.deepEqual(result.samples[1].action.consumed, consumed);
  }
});

test('shouminkan explicit request subtracts exact pon tiles instead of assuming combination order', () => {
  const value = copy(fixture);
  value.records[0].data.tiles1[3] = '5p';
  value.records[1].data.operations = [op(1,3,['5p|5p'])];
  value.records[2].data.tiles = ['5p','5p','5p'];
  value.records = value.records.slice(0,4);
  value.records.push(record('RecordDealTile', {seat:1,tile:'0p',left_tile_count:60,
    operation:op(1,6,['0p|5p|5p|5p'])}, [{seat:1,operation:{type:6,index:0}}]));
  value.records.push(record('RecordAnGangAddGang', {seat:1,type:2,tiles:'0p'}));
  const result = extractGame(value), sample = result.samples.at(-1);
  assert.deepEqual(sample.action, {action:'shouminkan',tile:'0p',consumed:['0p'],meldIndex:0});
  assert.equal(sample.labelSource, 'explicit');
  assert.equal(result.audit.excluded.conflicting_input, undefined);
});

test('riichi own-draw optional actions can be passed before forced tsumogiri', () => {
  for (const explicit of [false, true]) {
    const opening = start(); opening.data.operation.operation_list.push({type:7,combination:['5p']});
    const value = game([opening,
      record('RecordDiscardTile',{seat:0,tile:'5p',is_liqi:true}),
      record('RecordDealTile',{seat:0,tile:'1z',left_tile_count:60,
        liqi:{seat:0,score:24000,liqibang:1},operation:op(0,8)},
      explicit ? [{seat:0,operation:{cancel_operation:true}}] : undefined),
      record('RecordDiscardTile',{seat:0,tile:'1z',moqie:true})]);
    const sample = extractGame(value).samples.at(-1);
    assert.equal(sample.action.action, 'pass');
    assert.equal(sample.labelSource, explicit ? 'explicit' : 'inferred_pass');
    assert.equal(sample.state.canDiscard, false);
  }
});

test('riichi declaration interrupted by ron never appears established in the response state', () => {
  const opening = start(); opening.data.operation.operation_list.push({type:7,combination:['5p']});
  const result = extractGame(game([opening,
    record('RecordDiscardTile',{seat:0,tile:'5p',is_liqi:true,operations:[op(1,9)]}),
    record('RecordHule',{hules:[{seat:1}]})]));
  const state = result.samples[1].state;
  assert.equal(state.riichiPending[0], true); assert.equal(state.riichi[0], false);
  assert.equal(state.riichiSticks, 0); assert.equal(state.scores[0], 25000);
});

test('unknown and custom rule heads are rejected rather than labeled standard', () => {
  for (const head of [undefined, {}, {config:{category:1,mode:{mode:2}}},
    {config:{category:2,mode:{mode:2},meta:{mode_id:999}}}]) {
    assert.throws(() => extractGame({gameId:'unknown',head,records:[start()]}), /Unverified ruleset/);
  }
  const result = extractGame(fixture);
  assert.equal(result.samples[0].schemaVersion, 1);
  assert.equal(result.samples[0].ruleset, 'majsoul-standard-v1');
  assert.deepEqual(result.samples[0].state.match, {playerCount:4,roundCount:2});
});

test('wrong-seat draw cannot be evidence of normal response completion', () => {
  const value = copy(fixture); value.records = value.records.slice(0,2);
  value.records.push(record('RecordDealTile',{seat:2,tile:'9p',left_tile_count:68}));
  const result = extractGame(value);
  assert.equal(result.samples.some(s => s.action.action === 'pass'), false);
  assert.equal(result.audit.excluded.censored_response, 1);
});

test('a response uses pre-discard furiten regardless of its later ron or pass label', () => {
  const opening = start();
  const offered = record('RecordDiscardTile', {seat:0, tile:'5p',
    zhenting:[false,true,false,false], operations:[op(1,9)]});
  const win = extractGame(game([opening, offered, record('RecordHule', {hules:[{seat:1}]})]));
  const pass = extractGame(game([opening, offered,
    record('RecordDealTile', {seat:1,tile:'9p',left_tile_count:68})]));
  assert.equal(win.samples[1].state.furiten, false);
  assert.deepEqual(win.samples[1].state, pass.samples[1].state);
  assert.equal(win.samples[1].action.action, 'ron');
  assert.equal(pass.samples[1].action.action, 'pass');
});

test('a no-yaku wait does not pre-mark its pon window, but missed furiten applies afterwards', () => {
  const opening = start();
  opening.data.tiles3 = ['1m','2m','3m','4m','5m','6m','7p','8p','9p','5p','5p','6z','6z'];
  const result = extractGame(game([opening,
    record('RecordDiscardTile', {seat:0,tile:'5p',zhenting:[false,false,false,true],
      operations:[op(3,3,['5p|5p'])]}),
    record('RecordDealTile', {seat:1,tile:'9m',left_tile_count:68,zhenting:[false,false,false,true]}),
    record('RecordDiscardTile', {seat:1,tile:'6z',zhenting:[false,false,false,true],
      operations:[op(3,3,['6z|6z'])]}),
    record('RecordDealTile', {seat:2,tile:'9m',left_tile_count:67,zhenting:[false,false,false,true]}),
  ]));
  const passes = result.samples.filter(sample => sample.seat === 3);
  assert.deepEqual(passes.map(sample => sample.state.furiten), [false,true]);
  assert.equal(passes.every(sample => sample.action.action === 'pass'), true);
});

test('missed ron survives another player call until the actor draws', () => {
  const value = copy(fixture);
  value.records = value.records.slice(0,3);
  value.records[0].data.tiles2.splice(0,2,'5z','5z');
  value.records[1].data.operations.push(op(2,9));
  value.records[1].data.zhenting = [false,false,true,false];
  value.records[2].data.zhenting = [false,false,true,false];
  value.records.push(record('RecordDiscardTile', {seat:1,tile:'5z',
    zhenting:[false,false,true,false],operations:[op(2,3,['5z|5z'])]}));
  value.records.push(record('RecordDealTile', {seat:2,tile:'9p',left_tile_count:68,
    zhenting:[false,false,true,false],operation:op(2,1)}));
  value.records.push(record('RecordDiscardTile', {seat:2,tile:'9p',moqie:true,
    zhenting:[false,false,false,false]}));
  const samples = extractGame(value).samples.filter(sample => sample.seat === 2);
  assert.deepEqual(samples.map(sample => [sample.action.action,sample.state.furiten]),
    [['pass',true],['discard',false]]);
});

test('an own draw preserves discard furiten, including red and called river tiles', () => {
  for (const called of [false,true]) {
    const opening = start();
    opening.data.tiles0 = ['1m','2m','3m','1p','2p','3p','1s','2s','3s','4p','4p','4p','5p','0p'];
    const records = [opening,
      record('RecordDiscardTile', {seat:0,tile:'0p',zhenting:[true,false,false,false],
        tingpais:[{tile:'5p',haveyi:true}]})];
    if (called) records.push(record('RecordChiPengGang', {seat:1,type:1,
      tiles:['5p','5p','0p'],froms:[1,1,0],zhenting:[true,false,false,false]}));
    records.push(record('RecordDealTile', {seat:0,tile:'9m',left_tile_count:60,
      zhenting:[true,false,false,false],operation:op(0,1)}));
    records.push(record('RecordDiscardTile', {seat:0,tile:'9m',moqie:true}));
    const state = extractGame(game(records)).samples.at(-1).state;
    assert.equal(state.furiten, true);
    assert.equal(state.rivers[0][0].called, called);
  }
});

test('permanent missed-ron furiten in riichi survives an own draw', () => {
  const opening = start();
  opening.data.operation.operation_list.push({type:7,combination:['5p']});
  const records = [opening,
    record('RecordDiscardTile', {seat:0,tile:'5p',is_liqi:true,zhenting:[false,false,false,false]}),
    record('RecordDealTile', {seat:1,tile:'9m',left_tile_count:68,
      liqi:{seat:0,score:24000,liqibang:1},zhenting:[false,false,false,false]}),
    record('RecordDiscardTile', {seat:1,tile:'5m',zhenting:[true,false,false,false],operations:[op(0,9)]}),
    record('RecordDealTile', {seat:2,tile:'9m',left_tile_count:67,zhenting:[true,false,false,false]}),
    record('RecordDealTile', {seat:0,tile:'7z',left_tile_count:60,
      zhenting:[true,false,false,false],operation:op(0,8)}),
    record('RecordHule', {hules:[{seat:0,zimo:true}]}),
  ];
  const samples = extractGame(game(records)).samples;
  assert.equal(samples.find(sample => sample.action.action === 'pass').state.furiten, false);
  assert.equal(samples.at(-1).state.furiten, true);
  assert.equal(samples.at(-1).state.riichi[0], true);
});

test('unknown post-kan waits are not guessed from a stale discard-furiten cache', () => {
  const opening = start();
  opening.data.tiles0.splice(0,4,'0p','5p','5p','5p');
  opening.data.tiles0[13] = '9p';
  opening.data.operation = op(0,4,['0p|5p|5p|5p']);
  const result = extractGame(game([opening,
    record('RecordAnGangAddGang', {seat:0,type:3,tiles:'5p'}),
    record('RecordDealTile', {seat:0,tile:'9m',left_tile_count:60,
      zhenting:[true,false,false,false],operation:op(0,1)}),
    record('RecordDiscardTile', {seat:0,tile:'9m',moqie:true}),
  ]));
  assert.equal(result.samples.at(-1).state.furiten, null);
});
