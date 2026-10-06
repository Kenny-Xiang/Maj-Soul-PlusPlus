// DOM contract checks without a native WebKit process; layout is checked in test_overlay.py.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/overlay.js'), 'utf8');

class Element {
  constructor() { this.children = []; this.style = {}; this.dataset = {}; this.className = ''; this.hidden = false; this.text = ''; }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren() { this.children = []; this.text = ''; }
  set textContent(text) { this.replaceChildren(); this.text = text; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
  getBoundingClientRect() { return {height: 200}; }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [
      ...(child.className.split(' ').includes(selector.slice(1)) ? [child] : []),
      ...child.querySelectorAll(selector)
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0]; }
  attachShadow() { this.shadowRoot = new Element(); return this.shadowRoot; }
  set innerHTML(html) {
    // Only overlay's static template is parsed; dynamic values must use textContent.
    this.replaceChildren();
    for (const match of html.matchAll(/<(?:div|section)[^>]*class="([^"]+)"[^>]*>/g)) {
      const element = new Element(); element.className = match[1]; this.appendChild(element);
    }
  }
}

function overlay() {
  const body = new Element(), context = {window: {}, location: {hostname: 'game.maj-soul.com'}, innerHeight: 760,
    document: {body, readyState: 'complete', createElement: () => new Element(), addEventListener() {}}, addEventListener() {}};
  vm.runInNewContext(source, context);
  const root = body.children[0].shadowRoot, api = context.window.__mjStatsOverlay;
  return {api, root, show(advice, text = normalText, key = 'test:1') {
    api.expectAdvice(key); api.update({kind: 'turn', adviceKey: key, text, advice});
  }};
}
const normalText = '2026/10/05 22:00:00 · 第 8 次更新 · 动作 #30\n最新动作：摸牌\n状态：正在对局\n本人手牌：中\n完整性：已取得手牌基线；本小局动作连续\n触发：ActionDealTile · 入站 70 条 · 解析错误 0 次';
const candidate = {action: 'discard', actionId: 'discard:7z', tile: '7z', shanten: 0, ukeire: 4,
  currentStrategy: 'attack', expectedWinPoints: 5200, dealInProbability: .036, winProbability: .3,
  score: 900, expectedDealInLoss: 180, dealInPoints: 5000, reasons: [
    '当前进攻：与弃和路线按同一终局净收益比较；新窗口重新评估', '听牌；有效未见牌 4 张',
    '对各家均有现物或实体枚数安全依据']};
const result = best => ({status: 'ready', best, candidates: [best]});

test('normal overlay keeps action and decision metrics without recording diagnostics', () => {
  const {show, root} = overlay(); show(result(candidate));
  const advice = root.querySelector('.advice').textContent;
  for (const text of ['打 中', '进攻', '听牌', '有效未见 4 张', '本次放铳率（估计）', '3.6%', '胡牌得点（估计）', '5,200']) assert.ok(advice.includes(text), text);
  for (const text of ['后续胡牌率', '攻守评分', '预期损失', '放铳输点', '当前进攻：', '有效未见牌']) assert.ok(!advice.includes(text), text);
  assert.equal(root.querySelector('.caption').hidden, true);
  assert.equal(root.querySelector('.details').textContent, '');
  assert.equal(root.querySelector('.game').textContent, '最新动作：摸牌本人手牌：中');
});

test('verified rank objective shows the actual room, format, rank and preference outside candidate reasons', () => {
  const {show, root} = overlay();
  const rankContext = {active:true,objective:'rank-points',preference:'protect',riskWeight:1.7,
    profile:{roomName:'玉之间',rankName:'雀豪2星',playerCount:4,roundCount:2}};
  for (const status of ['ready','analysis']) {
    show({...result(candidate),status,rankContext});
    assert.equal(root.querySelector('.rank-context').textContent,'排位上升 · 玉之间 · 四人南 · 雀豪2星 · 偏重保位');
    assert.equal(root.querySelector('.reasons').textContent,'对各家均有现物或实体枚数安全依据');
    assert.doesNotMatch(root.querySelector('.rank-context').textContent,/riskWeight|1\.7|权重/);
  }
  for (const [preference, label] of [['push','增加追分意愿'],['balanced','均衡攻守']]) {
    show({...result(candidate),rankContext:{...rankContext,preference,
      profile:{roomName:'王座间',rankName:'魂天Lv3',playerCount:3,roundCount:1}}});
    assert.equal(root.querySelector('.rank-context').textContent,`排位上升 · 王座间 · 三人东 · 魂天Lv3 · ${label}`);
  }
  for (const unknown of [null, {}, {...rankContext,active:false}, {...rankContext,objective:'points'},
    {...rankContext,preference:'unknown'}, {...rankContext,profile:null},
    {...rankContext,profile:{...rankContext.profile,roundCount:0}}]) {
    show({...result(candidate),rankContext:unknown});
    assert.equal(root.querySelector('.rank-context'),undefined);
    assert.equal(root.querySelector('.best-tile').textContent,'打 中');
  }
});

test('furiten and no-yaku constraints outrank generic reasons and are never clipped', () => {
  const {show, root} = overlay();
  const best = {...candidate, furiten: true, reasons: [...candidate.reasons,
    '整副牌振听，所有等待均只估自摸', '当前等待无役，不能仅凭宝牌和牌',
    '终局互斥核算他家自摸及流局收支；终局概率和他家听牌仍未校准']};
  show(result(best));
  const warnings = root.querySelector('.advice').querySelectorAll('.advice-warning').map(e => e.textContent);
  assert.deepEqual(warnings, ['整副牌振听，所有等待均只估自摸', '当前等待无役，不能仅凭宝牌和牌']);
  assert.doesNotMatch(source, /line-clamp|\.reasons\s*\{[^}]*display:\s*none/);
  show(result({...candidate, furiten: true}));
  assert.match(root.querySelector('.advice-warning').textContent, /振听/);
});

test('risk labels describe the action being evaluated and omit risk for a pure pass or hand analysis', () => {
  const {show, root} = overlay();
  for (const [fields, label, action] of [
    [{action: 'pon', calledTile: '5z', followupDiscard: '1z'}, '后续弃牌风险（估计）', '碰 白 · 再打 东'],
    [{action: 'kita', replacementDraw: true, shanten: 1.6}, '操作风险（估计）', '拔北'],
    [{action: 'pass', followupDiscard: '4z'}, '后续弃牌风险（估计）', '跳过 · 随后摸切 北']
  ]) {
    show(result({...candidate, ...fields}));
    assert.ok(root.querySelector('.metrics').textContent.includes(label));
    assert.equal(root.querySelector('.best-tile').textContent, action);
  }
  for (const action of ['pass', 'wait', 'abort']) {
    show(result({...candidate, action}));
    assert.doesNotMatch(root.querySelector('.advice').textContent, /放铳率|弃牌风险|操作风险/);
  }
  show({...result(candidate), status: 'analysis'});
  assert.doesNotMatch(root.querySelector('.advice').textContent, /放铳率/);
});

test('fourth riichi keeps the abort constraint and removes the obsolete forced-play explanation', () => {
  const {show, root} = overlay();
  const best = {...candidate, action: 'riichi', abortAfterRiichi: true, reasons: [...candidate.reasons,
    '立直后不能自由弃和，和牌与强制摸切放铳共用存活概率',
    '第四家立直：宣言牌未被荣和则途中流局，无后续和牌机会或听牌料',
    '四家立直后无后续摸切']};
  show(result(best));
  assert.match(root.querySelector('.advice-warning').textContent, /第四家立直.*途中流局/);
  assert.match(root.querySelector('.advice-title').textContent, /四家立直流局/);
  assert.doesNotMatch(root.querySelector('.advice').textContent, /共用存活概率|不能自由弃和|立直续打/);
});

test('only one unique alternative is shown, retaining riichi versus dama identity', () => {
  const {show, root} = overlay();
  const best = {...candidate, action: 'riichi', actionId: 'riichi:7z'};
  const candidates = [best, {...best}, candidate, {...candidate, tile: '6z', actionId: 'discard:6z'}];
  const advice = {...result(best), candidates};
  const before = JSON.stringify(advice); show(advice);
  const alternatives = root.querySelector('.advice').querySelectorAll('.alternatives');
  assert.equal(alternatives.length, 1);
  assert.equal(alternatives[0].textContent, '备选 打 中');
  assert.equal(JSON.stringify(advice), before, 'display must not truncate or mutate candidate accounting');
  show({...result(candidate), candidates: [candidate, {...candidate, tile: '6z', actionId: 'discard:6z', ukeire: 2, dealInProbability: .044}]});
  assert.equal(root.querySelector('.alternatives').textContent, '备选 打 发 · 有效未见少 2 张 · 本次放铳率 4.4%（估计）');
  const replacement = {...candidate, action: 'kita', replacementDraw: true, ukeire: 4.3};
  show({...result(replacement), candidates: [replacement, {...replacement, action: 'ankan', actionId: 'ankan:7z', ukeire: 4, dealInProbability: .0361}]});
  assert.equal(root.querySelector('.alternatives').textContent, '备选 暗杠 中 · 有效未见少 0.3 张');
});

test('incomplete history, missing hand, parser errors and every unverified action remain prominent', () => {
  const {show, root, api} = overlay();
  const text = normalText.replace('已取得手牌基线；本小局动作连续', '缺少完整手牌；历史不完整或待核对').replace('解析错误 0 次', '解析错误 2 次');
  show({...result(candidate), warnings: ['暗杠 暂不推荐：操作组合信息缺失', '吃 暂不推荐：操作未核实']}, text);
  const warnings = root.querySelector('.details').querySelectorAll('.advice-warning').map(e => e.textContent);
  assert.deepEqual(warnings, ['完整性：缺少完整手牌；历史不完整或待核对', '解析错误 2 次，统计可能不完整']);
  assert.match(root.querySelector('.advice-warning').textContent, /暗杠.*吃/);
  show({status: 'unavailable', message: '缺少完整手牌，暂停推荐'});
  assert.equal(root.querySelector('.advice-warning').textContent, '缺少完整手牌，暂停推荐');
  api.update({kind: 'status', phase: 'disconnected', text: '连接中断 · 以下统计可能已过时'});
  assert.match(root.querySelector('.caption').className, /advice-warning/);
  assert.equal(root.querySelector('.caption').hidden, false);
  assert.equal(root.querySelector('.advice').hidden, true);
});

test('literal text and stale advice protections survive simplified rendering', () => {
  const {show, root, api} = overlay();
  const best = {...candidate, tile: '<img src="invalid">', reasons: ['<img src="invalid">']};
  show(result(best));
  assert.equal(root.querySelector('.best-tile').textContent, '打 <img src="invalid">');
  assert.equal(root.querySelector('.reasons').textContent, '<img src="invalid">');
  api.expectAdvice('test:2');
  api.update({kind: 'advice', adviceKey: 'test:1', advice: result(candidate)});
  assert.equal(root.querySelector('.advice').hidden, true);
  api.update({kind: 'turn', adviceKey: 'test:2', text: normalText, advice: result(candidate)});
  assert.equal(root.querySelector('.advice').hidden, false);
  api.invalidateAdvice();
  api.update({kind: 'turn', adviceKey: 'test:2', text: normalText, advice: result(candidate)});
  assert.equal(root.querySelector('.advice').hidden, true);
  assert.match(source, /pointer-events:none/);
});
