'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/game_actions.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
const enumNames = ['dapai','eat','peng','an_gang','ming_gang','add_gang','liqi','zimo','rong','jiuzhongjiupai','babei'];
const standardHand = ['1m','2m','3m','4m','5m','6m','1p','2p','3p','4s','5s','7z','7z','1z'];

// Fake client boundaries model the public 0.11.252.w entry-point contracts.
// They exercise real entry selection, request arguments, UI effects and callbacks;
// these tests never load the game, authenticate or open a WebSocket.
function client(options = {}) {
  const hand = options.hand || standardHand;
  const ops = options.ops || [{type:1, combination:[]}];
  const calls = [], sent = [], timers = new Map();
  let timerId = 0;
  const state = {phase:'playing', canAct:true, canDiscard:ops.some(op => op.type === 1),
    handComplete:true, historyComplete:true, selfSeat:0, playerCount:options.players || 4,
    lastStep:12, round:{chang:0, ju:1, ben:0}, hand:[...hand],
    lastDraw:options.drawn === false ? null : hand.at(-1), riichi:[false,false,false,false],
    operations:ops.map(op => op.type), operationDetails:plain(ops), forbiddenDiscards:[],
    lastAction:options.lastAction || {name:'ActionDealTile', seat:0, tile:hand.at(-1), step:12},
    melds:options.melds || [[],[],[],[]]};
  const tile = (value, index = 0) => ({index, val:{toString:() => value, baida:false}, valid:true,
    is_open:false, mySelf:{active:true}});
  const role = {hand:hand.map(tile), can_discard:state.canDiscard, during_liqi:false,
    needCheckMouse:() => true, setChoosePai(value) {calls.push('setChoosePai'); this._choose_pai = value;},
    resetMouseState() {calls.push('resetMouseState'); this._choose_pai = null;},
    DoDiscardTile() {
      calls.push('DoDiscardTile');
      const selected = this._choose_pai;
      if (this.during_liqi) {
        if (!desktop.Action_LiQi(selected.val, selected === this.last_tile, selected.is_open)) return;
        this.during_liqi = false;
      } else desktop.Action_QiPai(selected.val, selected === this.last_tile, false, selected.is_open);
      this._prediscard_index = selected.index;
      selected.mySelf.active = false; this._choose_pai = null; this.can_discard = false;
    }};
  role.last_tile = options.drawn === false ? null : role.hand.at(-1);
  const timer = {me:{visible:true}, _start:1000, _fix:5, _add:20, timeuse:2};
  const agent = {sendReq2MJ(service, method, payload, callback) {
    sent.push({service, method, payload:plain(payload), callback});
    if (!options.defer) callback(null, {});
    return true;
  }};
  const desktop = {active:true, mode:0, gameing:true, mainrole:role, operation_showing:true,
    current_step:12, seat:0, player_count:state.playerCount, index_change:0, index_ju:1, index_ben:0,
    game_config:{category:2, mode:{mode:state.playerCount === 3 ? 12 : 2}},
    oplist:plain(ops), lastpai_seat:state.lastAction.seat, lastqipai:tile(state.lastAction.tile),
    WhenDoOperation() {calls.push('WhenDoOperation'); this.oplist = []; this.operation_showing = false;
      role.can_discard = false; timer.me.visible = false;},
    Action_QiPai(value, moqie, auto, isOpen) {
      calls.push('Action_QiPai');
      agent.sendReq2MJ('FastTest','inputOperation',{type:1,tile:value.toString(),moqie,timeuse:timer.timeuse,tile_state:isOpen ? 1 : 0}, () => {});
      this.WhenDoOperation();
    },
    Action_LiQi(value, moqie, isOpen) {
      calls.push('Action_LiQi');
      if (!own.liqi_data.some(allowed => allowed.replace(/^0/,'5') === value.toString().replace(/^0/,'5'))) return false;
      agent.sendReq2MJ('FastTest','inputOperation',{type:7,tile:value.toString(),moqie,timeuse:timer.timeuse,tile_state:isOpen ? 1 : 0}, () => {});
      this.WhenDoOperation(); return true;
    }};
  const combinations = type => plain(ops.find(op => op.type === type)?.combination || []);
  function send(method, payload) {
    agent.sendReq2MJ('FastTest',method,{...payload,timeuse:timer.timeuse}, () => {});
    desktop.WhenDoOperation();
  }
  const own = {enable:true, liqi_data:combinations(7), com_add_gang:combinations(6), com_an_gang:combinations(4),
    onBtn_Liqi() {calls.push('onBtn_Liqi'); role.during_liqi = true;},
    onClickDetail(index) {calls.push(`ownDetail:${index}`); this.enable = false;
      send('inputOperation',{type:index < this.com_add_gang.length ? 6 : 4,
        index:index < this.com_add_gang.length ? index : index - this.com_add_gang.length});},
    onBtn_Zimo() {calls.push('onBtn_Zimo'); send('inputOperation',{type:8,index:0});},
    onBtn_BaBei() {calls.push('onBtn_BaBei'); send('inputOperation',{type:11,moqie:role.last_tile?.val.toString() === '4z'});},
    onBtn_Liuju() {calls.push('onBtn_Liuju'); send('inputOperation',{type:10,index:0});},
    onBtn_Cancel() {calls.push('ownCancel'); if (!role.can_discard) send('inputOperation',{cancel_operation:true}); this.enable = false;}};
  const reaction = {enable:true, _data:{chi:combinations(2), peng:combinations(3)},
    onBtn_Chi() {calls.push('onBtn_Chi'); if (this._data.chi.length > 1) this.choosed_op = 2; else send('inputChiPengGang',{type:2,index:0});},
    onBtn_Peng() {calls.push('onBtn_Peng'); if (this._data.peng.length > 1) this.choosed_op = 3; else send('inputChiPengGang',{type:3,index:0});},
    onClickDetail(index) {calls.push(`callDetail:${index}`);
      agent.sendReq2MJ('FastTest','inputChiPengGang',{type:this.choosed_op,index}, () => {}); desktop.WhenDoOperation();},
    onBtn_Gang() {calls.push('onBtn_Gang'); send('inputChiPengGang',{type:5,index:0});},
    onBtn_Hu() {calls.push('onBtn_Hu'); send('inputChiPengGang',{type:9,index:0});},
    onBtn_Cancel() {calls.push('reactionCancel'); send('inputChiPengGang',{cancel_operation:true});}};
  const window = {view:{DesktopMgr:{Inst:desktop}, EMJMode:{play:0}}, app:{NetAgent:agent},
    uiscript:{UI_DesktopInfo:{Inst:{_timecd:timer}}, UI_LiQiZiMo:{Inst:own}, UI_ChiPengHu:{Inst:reaction}},
    Laya:{timer:{currTimer:3200}}, mjcore:{E_PlayOperation:Object.fromEntries(enumNames.map((name,index) => [name,index+1]))}};
  vm.runInNewContext(source, {window, location:{hostname:'game.maj-soul.com'},
    setTimeout(callback) {timers.set(++timerId, callback); return timerId;}, clearTimeout(id) {timers.delete(id);}});
  return {api:window.__mjGameActions, window, state, desktop, role, timer, agent, own, reaction, calls, sent, timers,
    run:best => window.__mjGameActions.execute({status:'ready',best},state)};
}

test('snapshot uses the visible client deadline and checks the exact board', () => {
  const c = client();
  assert.deepEqual(plain(c.api.snapshot(c.state)), {available:true,inGame:true,canAct:true,blocked:false,remainingMs:22800,clientStep:12,reason:''});
  c.window.Laya.timer.currTimer = 3600;
  assert.equal(c.api.snapshot(c.state).remainingMs, 22400);
  c.desktop.current_step = 11;
  assert.equal(c.api.snapshot(c.state).canAct, false);
  assert.equal(c.api.snapshot(c.state).blocked, false);
  c.desktop.current_step = 12; c.timer.me.visible = false;
  assert.equal(c.api.snapshot(c.state).remainingMs, null);
  assert.equal(c.api.snapshot(c.state).canAct, false);
});

test('incompatible client controls require stopping while animation and acknowledgements can wait', () => {
  for (const change of [c => {c.desktop.auto_hule = true;}, c => {c.desktop.game_config.category = 1;},
    c => {c.window.mjcore.E_PlayOperation.dapai = 21;}, c => {c.state.hand[0] = '9p';}]) {
    const c = client(); change(c);
    assert.equal(c.api.snapshot(c.state).blocked,true);
  }
});

test('physical red and ordinary fives are distinct and real discard updates the visual state', async () => {
  const c = client({hand:[...standardHand.slice(0,12),'0p','5p']});
  const original = c.agent.sendReq2MJ;
  await c.run({action:'discard',tile:'0p'});
  assert.deepEqual(c.sent[0].payload, {type:1,tile:'0p',moqie:false,timeuse:2,tile_state:0});
  assert.deepEqual(c.calls, ['setChoosePai','DoDiscardTile','Action_QiPai','WhenDoOperation','resetMouseState']);
  assert.equal(c.role._prediscard_index,12); assert.equal(c.role.hand[12].mySelf.active,false);
  assert.equal(c.role.can_discard,false); assert.equal(c.role._choose_pai,null);
  assert.equal(c.agent.sendReq2MJ,original); assert.equal(c.timers.size,0);
  assert.throws(() => c.run({action:'discard',tile:'5p'}), /等待客户端显示/);
});

test('duplicate tiles prefer the drawn instance and locked riichi never discards another tile', async () => {
  const c = client({hand:[...standardHand.slice(0,13),'7z']});
  c.state.riichi[0] = true;
  assert.throws(() => c.run({action:'discard',tile:'1m'}), /只能摸切/);
  await c.run({action:'discard',tile:'7z'});
  assert.equal(c.sent[0].payload.moqie,true); assert.equal(c.role._prediscard_index,13);
});

test('riichi selects through the real UI, submits the chosen physical tile and cleans the hand', async () => {
  const c = client({hand:[...standardHand.slice(0,12),'0p','5p'],ops:[{type:1,combination:[]},{type:7,combination:['0p']}]});
  await c.run({action:'riichi',tile:'5p'});
  assert.equal(c.sent.length,1); assert.equal(c.sent[0].payload.type,7);
  assert.equal(c.sent[0].payload.tile,'5p'); assert.equal(c.sent[0].payload.moqie,true);
  assert.equal(c.calls[0],'onBtn_Liqi'); assert.ok(c.calls.includes('Action_LiQi'));
  assert.equal(c.role.during_liqi,false); assert.equal(c.role.hand[13].mySelf.active,false);
});

test('multi-combination chi/pon select the exact server index including red fives', async () => {
  for (const [action,type,called,combos,consumed] of [
    ['chi',2,'4p',['2p|3p','3p|0p','5p|6p'],['0p','3p']],
    ['pon',3,'5p',['5p|5p','0p|5p'],['5p','0p']],
  ]) {
    const c = client({hand:['2p','3p','0p','5p','5p','6p',...standardHand.slice(0,7)], drawn:false,
      ops:[{type,combination:combos}],lastAction:{name:'ActionDiscardTile',seat:3,tile:called,step:12}});
    await c.run({action,calledTile:called,fromSeat:3,consumed,followupDiscard:'1m'});
    assert.equal(c.sent.length,1); assert.equal(c.sent[0].method,'inputChiPengGang');
    assert.deepEqual(c.sent[0].payload,{type,index:1});
    assert.ok(c.calls.includes('callDetail:1'));
  }
});

test('daiminkan submits once and leaves the replacement draw for a new decision', async () => {
  const c = client({hand:['0p','5p','5p',...standardHand.slice(0,10)], drawn:false,
    ops:[{type:5,combination:['0p|5p|5p']}],lastAction:{name:'ActionDiscardTile',seat:1,tile:'5p',step:12}});
  await c.run({action:'daiminkan',consumed:['5p','0p','5p'],calledTile:'5p',fromSeat:1});
  assert.deepEqual(c.sent[0].payload,{type:5,index:0,timeuse:2}); assert.equal(c.sent.length,1);
});

test('ankan offsets the shared client detail index but sends its own server index', async () => {
  const c = client({hand:['1m','1m','1m','1m','2p','2p','2p','2p',...standardHand.slice(6,12)],
    ops:[{type:1,combination:[]},{type:6,combination:['5p|5p|5p|0p']},
      {type:4,combination:['1m|1m|1m|1m','2p|2p|2p|2p']}]});
  await c.run({action:'ankan',consumed:['2p','2p','2p','2p']});
  assert.ok(c.calls.includes('ownDetail:2')); assert.deepEqual(c.sent[0].payload,{type:4,index:1,timeuse:2});
});

test('shouminkan reconstructs the full combination using the existing pon and exact added tile', async () => {
  const c = client({hand:['0p',...standardHand.slice(0,10)],
    melds:[[{type:1,tiles:['5p','5p','5p']}],[],[],[]],
    ops:[{type:1,combination:[]},{type:6,combination:['5p|5p|5p|0p']}]});
  await c.run({action:'shouminkan',consumed:['0p'],meldIndex:0});
  assert.deepEqual(c.sent[0].payload,{type:6,index:0,timeuse:2});
});

test('win is a top-level action and routes tsumo/ron to their different client endpoints', async () => {
  for (const [action,type,method,button] of [['tsumo',8,'inputOperation','onBtn_Zimo'],['ron',9,'inputChiPengGang','onBtn_Hu']]) {
    const c = client({ops:[{type,combination:[]}]});
    await c.api.execute({status:'win',action},c.state);
    assert.equal(c.sent[0].method,method); assert.equal(c.sent[0].payload.type,type);
    assert.ok(c.calls.includes(button));
  }
});

test('kita keeps moqie identity and nine-terminals uses the offered operation', async () => {
  for (const drawn of [true,false]) {
    const c = client({players:3,hand:[...standardHand.slice(0,13),'4z'],drawn,
      ops:[{type:1,combination:[]},{type:11,combination:[]}]});
    await c.run({action:'kita'});
    assert.deepEqual(c.sent[0].payload,{type:11,moqie:drawn,timeuse:2});
  }
  const c = client({ops:[{type:1,combination:[]},{type:10,combination:[]}]});
  await c.run({action:'abort'}); assert.deepEqual(c.sent[0].payload,{type:10,index:0,timeuse:2});
});

test('pass distinguishes reaction from optional locked-hand actions and never replaces discarding', async () => {
  for (const [type,method] of [[3,'inputChiPengGang'],[4,'inputOperation'],[11,'inputOperation']]) {
    const c = client({ops:[{type,combination:[]}],players:type === 11 ? 3 : 4});
    await c.run({action:'pass'});
    assert.equal(c.sent[0].method,method); assert.deepEqual(c.sent[0].payload,{cancel_operation:true,timeuse:2});
  }
  const c = client(); assert.throws(() => c.run({action:'pass'}), /不能用跳过/); assert.equal(c.sent.length,0);
});

test('invalid, stale, incomplete or unsupported client state never sends a request', () => {
  const changes = [
    c => {c.state.historyComplete = false;}, c => {c.state.lastStep++;},
    c => {c.state.selfSeat = 1;}, c => {c.state.playerCount = 3;}, c => {c.state.round.ben++;},
    c => {c.state.hand[0] = '9p';}, c => {c.state.operationDetails[0].combination = ['1z'];},
    c => {c.desktop.duringReconnect = true;}, c => {c.desktop.timestoped = true;},
    c => {c.desktop.mode = 1;}, c => {c.desktop.game_config.category = 1;},
    c => {c.desktop.auto_moqie = true;}, c => {c.role.needCheckMouse = () => false;},
    c => {c.role.mouse_downed = true;}, c => {c.window.mjcore.E_PlayOperation.dapai = 20;},
    c => {c.timer.me.visible = false;}, c => {c.window.Laya.timer.currTimer = 26000;},
    c => {c.state.forbiddenDiscards = ['1z'];}, c => {c.role.last_tile.valid = false;},
  ];
  for (const change of changes) {
    const c = client(); change(c);
    assert.throws(() => c.run({action:'discard',tile:'1z'})); assert.equal(c.sent.length,0);
  }
  for (const status of ['analysis','unavailable','waiting']) {
    const c = client();
    assert.throws(() => c.api.execute({status,best:{action:'discard',tile:'1z'}},c.state), /不可执行/);
    assert.equal(c.sent.length,0);
  }
});

test('client combination reordering and mismatched call targets cannot change the selected action', () => {
  for (const change of [c => c.reaction._data.chi.reverse(), c => {c.desktop.lastpai_seat = 2;}]) {
    const c = client({hand:['2p','3p','0p',...standardHand.slice(0,10)],drawn:false,
      ops:[{type:2,combination:['2p|3p','3p|0p']}],lastAction:{name:'ActionDiscardTile',seat:3,tile:'4p',step:12}});
    change(c);
    assert.throws(() => c.run({action:'chi',consumed:['0p','3p'],calledTile:'4p',fromSeat:3}));
    assert.equal(c.sent.length,0);
  }
});

test('requests are validated before sending and the shared sender is always restored', async () => {
  const c = client(); const original = c.agent.sendReq2MJ;
  c.role.DoDiscardTile = () => c.agent.sendReq2MJ('FastTest','inputOperation',{type:1,tile:'9p',moqie:true,tile_state:0}, () => {});
  await assert.rejects(c.run({action:'discard',tile:'1z'}), /请求内容/);
  assert.equal(c.sent.length,0); assert.equal(c.agent.sendReq2MJ,original); assert.equal(c.timers.size,0);
});

test('transport/server errors, missing submissions and missing acknowledgements reject without retries', async () => {
  for (const [error,response] of [['disconnected',null],[null,{error:{code:1001}}]]) {
    const c = client({defer:true}); const result = c.run({action:'discard',tile:'1z'});
    c.sent[0].callback(error,response);
    await assert.rejects(result,/游戏拒绝操作/); assert.equal(c.sent.length,1); assert.equal(c.timers.size,0);
  }
  const c = client({defer:true}); const result = c.run({action:'discard',tile:'1z'});
  c.timers.values().next().value(); await assert.rejects(result,/回执超时/);
  c.sent[0].callback(null,{}); assert.equal(c.sent.length,1);
  const d = client(); d.role.DoDiscardTile = () => {};
  await assert.rejects(d.run({action:'discard',tile:'1z'}),/没有提交/); assert.equal(d.sent.length,0);
});

test('an outstanding acknowledgement blocks any second operation even after a new board arrives', async () => {
  const c = client({defer:true}); const result = c.run({action:'discard',tile:'1z'});
  c.desktop.oplist = plain(c.state.operationDetails); c.desktop.operation_showing = true;
  c.role.can_discard = true; c.timer.me.visible = true;
  assert.throws(() => c.run({action:'discard',tile:'1m'}),/等待上次操作/);
  assert.equal(c.sent.length,1); c.sent[0].callback(null,{}); await result;
});

test('a UI failure after a synchronous success callback still fails the action', async () => {
  const c = client(); const original = c.role.resetMouseState;
  c.role.resetMouseState = () => {original.call(c.role); throw new Error('visual update failed');};
  await assert.rejects(c.run({action:'discard',tile:'1z'}), /visual update failed/);
  assert.equal(c.sent.length,1);
});
