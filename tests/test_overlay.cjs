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
  for (const text of ['打 中', '进攻', '听牌', '有效未见 4 张', '本次放铳率（估计）', '3.6%',
    '后续胡牌率（估计）', '30.0%', '胡牌得点（估计）', '5,200', '放铳输点（估计）',
    '5,000', '本次预期损失（估计）', '180']) assert.ok(advice.includes(text), text);
  for (const text of ['攻守评分', '当前进攻：', '有效未见牌']) assert.ok(!advice.includes(text), text);
  assert.equal(root.querySelector('.caption').hidden, true);
  assert.equal(root.querySelector('.details').textContent, '');
  assert.equal(root.querySelector('.game').textContent, '最新动作：摸牌本人手牌：中');
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

test('risk and loss labels describe the action and disappear for pure pass or hand analysis', () => {
  const {show, root} = overlay();
  for (const [fields, label, loss, action] of [
    [{action: 'chi', calledTile: '4m', consumed: ['3m', '5m'], followupDiscard: '1z'},
      '后续弃牌风险（估计）', '后续弃牌预期损失（估计）', '吃 3万4万5万 · 再打 东'],
    [{action: 'pon', calledTile: '5z', followupDiscard: '1z'},
      '后续弃牌风险（估计）', '后续弃牌预期损失（估计）', '碰 白 · 再打 东'],
    [{action: 'kita', replacementDraw: true, shanten: 1.6}, '操作风险（估计）', '操作预期损失（估计）', '拔北'],
    [{action: 'pass', followupDiscard: '4z'}, '后续弃牌风险（估计）', '后续弃牌预期损失（估计）', '跳过 · 随后摸切 北']
  ]) {
    show(result({...candidate, ...fields}));
    assert.ok(root.querySelector('.metrics').textContent.includes(label));
    assert.ok(root.querySelector('.metrics').textContent.includes(loss));
    assert.ok(root.querySelector('.metrics').textContent.includes('放铳输点（估计）'));
    assert.equal(root.querySelector('.best-tile').textContent, action);
  }
  for (const action of ['pass', 'wait', 'abort']) {
    show(result({...candidate, action}));
    assert.doesNotMatch(root.querySelector('.advice').textContent, /放铳率|弃牌风险|操作风险|预期损失|放铳输点/);
    if (action === 'abort') assert.equal(root.querySelector('.metrics'), undefined);
  }
  show({...result(candidate), status: 'analysis'});
  assert.doesNotMatch(root.querySelector('.advice').textContent, /放铳率|预期损失|放铳输点/);
  assert.match(root.querySelector('.metrics').textContent, /后续胡牌率（估计）/);
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
  assert.equal(root.querySelector('.progress'), undefined);
});

test('at most two unique alternatives are shown, retaining riichi versus dama identity', () => {
  const {show, root} = overlay();
  const best = {...candidate, action: 'riichi', actionId: 'riichi:7z'};
  const candidates = [best, {...best}, candidate, {...candidate},
    {...candidate, tile: '6z', actionId: 'discard:6z'}, {...candidate, tile: '1z', actionId: 'discard:1z'}];
  const advice = {...result(best), candidates};
  const before = JSON.stringify(advice); show(advice);
  const alternatives = root.querySelector('.advice').querySelectorAll('.alternatives');
  assert.equal(alternatives.length, 2);
  assert.equal(alternatives[0].querySelector('.alternative-action').textContent, '打 中');
  assert.equal(alternatives[1].querySelector('.alternative-action').textContent, '打 发');
  assert.deepEqual(root.querySelector('.comparison-head').children.map(element => element.textContent),
    ['行动', '向听 / 未见', '风险估计', '打点估计']);
  assert.equal(JSON.stringify(advice), before, 'display must not truncate or mutate candidate accounting');
  show({...result(candidate), candidates: [candidate, {...candidate, tile: '6z', actionId: 'discard:6z', ukeire: 2, dealInProbability: .044}]});
  assert.deepEqual(root.querySelector('.alternatives').children.map(element => element.textContent),
    ['打 发', '听牌 / 2张', '4.4%', '5,200']);
  const replacement = {...candidate, action: 'kita', replacementDraw: true, ukeire: 4.3};
  show({...result(replacement), candidates: [replacement, {...replacement, action: 'ankan', actionId: 'ankan:7z', ukeire: 4, dealInProbability: .0361}]});
  assert.deepEqual(root.querySelector('.alternatives').children.map(element => element.textContent),
    ['暗杠 中', '预计 0 向听 / 4张', '操作 3.6%', '5,200']);
  show({...result(replacement), candidates: [replacement, {...replacement, action: 'ankan', actionId: 'ankan:7z', ukeire: 4.3}]});
  assert.match(root.querySelector('.alternatives').children[1].textContent, /4\.3张/);
});

test('alternatives cannot promote unranked tail candidates after deduplication', () => {
  const {show, root} = overlay();
  const best = {...candidate, action: 'riichi', actionId: 'riichi:7z'};
  const tail = {...candidate, tile: '6z', actionId: 'discard:6z'};
  for (const [rankedCandidateCount, expected] of [[0, []], [1, []], [2, []], [3, ['打 中']]]) {
    show({...result(best), candidates: [best, {...best}, candidate, tail], rankedCandidateCount});
    assert.deepEqual(root.querySelectorAll('.alternative-action').map(element => element.textContent), expected);
  }
});

test('alternative columns preserve action risk scope and omit inapplicable metrics', () => {
  const {show, root} = overlay();
  for (const [fields, expectedRisk] of [
    [{action: 'pon', calledTile: '5z', followupDiscard: '1z'}, '后续 3.6%'],
    [{action: 'pass'}, '—'], [{action: 'abort'}, '—']
  ]) {
    const alternative = {...candidate, ...fields, actionId: fields.action};
    show({...result(candidate), candidates: [candidate, alternative]});
    const cells = root.querySelector('.alternatives').children.map(element => element.textContent);
    assert.equal(cells.length, 4);
    assert.equal(root.querySelector('.alternative-risk').textContent, expectedRisk);
    if (fields.action === 'abort') assert.deepEqual(cells.slice(1), ['—', '—', '—']);
  }
  show({...result(candidate), status: 'analysis', candidates: [candidate, {...candidate, tile: '6z', actionId: 'discard:6z'}]});
  assert.equal(root.querySelector('.alternative-risk').textContent, '—');
});

test('lower advice area lists effective draws and each wait constraint without changing the input', () => {
  const {show, root} = overlay();
  const best = {...candidate, shanten: 2, ukeire: 7,
    improvingTiles: [{tile: '0p', count: 4}, {tile: '9s', count: 3}]};
  const advice = result(best), before = JSON.stringify(advice);
  show(advice);
  const progress = root.querySelector('.advice').querySelector('.progress');
  assert.match(progress.textContent, /有效进张/);
  assert.deepEqual(progress.querySelectorAll('.tile-chip').map(element => element.textContent), ['赤5筒 × 4', '9索 × 3']);
  assert.equal(JSON.stringify(advice), before);
  const waits = {...candidate, winningTiles: [
    {tile: '3s', count: 3, ronPoints: 3900, tsumoPoints: 4000},
    {tile: '6s', count: 0, ronPoints: 3900, tsumoPoints: 4000},
    {tile: '1z', count: 2, ronPoints: 0, tsumoPoints: 2000},
    {tile: '2z', count: 1, ronPoints: 0, tsumoPoints: 0}
  ]};
  show(result(waits));
  assert.match(root.querySelector('.progress').textContent, /听口/);
  const chips = root.querySelectorAll('.tile-chip').map(element => element.textContent);
  assert.match(chips[0], /3索.*×\s*3/);
  assert.match(chips[1], /6索.*×\s*0/);
  assert.match(root.querySelector('.progress').textContent, /张数为未见牌/);
  assert.match(chips[2], /东.*×\s*2.*仅自摸/);
  assert.match(chips[3], /南.*×\s*1.*无役/);
  for (const fields of [{replacementDraw: true, action: 'kita'}, {abortAfterRiichi: true, action: 'riichi'}, {action: 'abort'}]) {
    show(result({...waits, ...fields}));
    assert.equal(root.querySelectorAll('.tile-chip').length, 0);
    if (fields.replacementDraw) assert.match(root.querySelector('.progress').textContent, /补牌后再确定进张/);
    else assert.equal(root.querySelector('.progress'), undefined);
  }
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

test('literal text and stale protections apply to progress and expanded advice metrics', () => {
  const {show, root, api} = overlay();
  const best = {...candidate, tile: '<img src="invalid">', shanten: 1,
    improvingTiles: [{tile: '<img src="invalid">', count: 2}], reasons: ['<img src="invalid">']};
  show(result(best));
  assert.equal(root.querySelector('.best-tile').textContent, '打 <img src="invalid">');
  assert.equal(root.querySelector('.reasons').textContent, '<img src="invalid">');
  assert.match(root.querySelector('.tile-chip').textContent, /<img src="invalid">/);
  api.expectAdvice('test:2');
  assert.equal(root.querySelector('.metrics'), undefined);
  assert.equal(root.querySelector('.progress'), undefined);
  api.update({kind: 'advice', adviceKey: 'test:1', advice: result(candidate)});
  assert.equal(root.querySelector('.advice').hidden, true);
  api.update({kind: 'turn', adviceKey: 'test:2', text: normalText, advice: result(best)});
  assert.equal(root.querySelector('.advice').hidden, false);
  assert.equal(root.querySelectorAll('.tile-chip').length, 1);
  api.invalidateAdvice();
  api.update({kind: 'turn', adviceKey: 'test:2', text: normalText, advice: result(candidate)});
  assert.equal(root.querySelector('.advice').hidden, true);
  assert.equal(root.querySelector('.metrics'), undefined);
  assert.equal(root.querySelector('.progress'), undefined);
  assert.match(source, /pointer-events:none/);
});
