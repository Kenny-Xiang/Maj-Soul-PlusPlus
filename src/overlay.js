// Display only: game input passes through, and all values are inserted as text.
(() => {
  if (location.hostname !== 'game.maj-soul.com' || window.__mjStatsOverlay) return;
  const host = document.createElement('div');
  host.id = 'mj-statistics-overlay';
  host.style.cssText = 'position:fixed;top:12px;left:16px;right:16px;z-index:2147483647;pointer-events:none;user-select:none';
  const shadow = host.attachShadow({mode:'open'});
  shadow.innerHTML = `<style>
    :host { color-scheme:dark; }
    * { box-sizing:border-box; pointer-events:none; }
    .panel { padding:12px 16px; border:1px solid rgba(210,230,255,.22); border-radius:12px;
      background:rgba(12,22,36,.64); color:#f4f7fc; box-shadow:0 4px 20px rgba(0,0,0,.18);
      font:13px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif; }
    .heading, .columns { display:grid; grid-template-columns:minmax(0,2fr) minmax(0,1fr); column-gap:28px; }
    .heading { margin-bottom:6px; font-weight:600; }
    .label { color:#b9d9f9; white-space:nowrap; }
    .caption { font-weight:400; color:#e0e8f0; overflow-wrap:anywhere; padding-bottom:4px; }
    .recording, .heading > :last-child { border-left:1px solid rgba(220,235,255,.12); padding-left:14px; }
    .line { white-space:pre-wrap; overflow-wrap:anywhere; break-inside:avoid; padding-bottom:2px; }
    .hand { color:#ffdfa0; font-weight:600; }
    .footnote { color:#c7d4e2; }
    .advice { margin:0 0 9px; padding-bottom:9px; border-bottom:1px solid rgba(220,235,255,.18); }
    .advice-title { color:#aee6d1; font-weight:600; }
    .advice-message { color:#c7d4e2; }
    .advice-warning { color:#ffe1a4; line-height:1.35; overflow-wrap:anywhere; }
    .recommendation { display:flex; align-items:baseline; flex-wrap:wrap; gap:5px 12px; }
    .best-tile { color:#ffe1a4; font-size:1.8em; font-weight:700; line-height:1.3; }
    .best-action { font-size:1.45em; }
    .efficiency { color:#c7e7ff; }
    .metrics { display:grid; grid-template-columns:1fr 1fr; gap:2px 10px; margin:4px 0; }
    .metric-label { display:inline; color:#bacbd9; }
    .metric-value { display:inline; color:#f4f7fc; font-weight:600; margin-left:4px; }
    .alternatives, .reasons { color:#d0dfec; overflow-wrap:anywhere; }
    .alternatives { line-height:1.35; }
    .reasons { margin-top:3px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
    @media (max-width:850px) {
      .heading, .columns { grid-template-columns:minmax(0,3fr) minmax(0,2fr); column-gap:16px; }
      .panel { padding:9px 12px; }
      .recording, .heading > :last-child { padding-left:10px; }
      .reasons { display:none; }
    }
    @media (max-width:650px) {
      .metrics { display:block; }
      .metrics > div { display:inline; margin-right:8px; }
      .metrics .metric-label, .metrics .metric-value { display:inline; }
      .metrics .metric-value::before { content:' '; }
      .alternatives { display:none; }
    }
  </style><section class="panel" aria-label="最新牌局统计">
    <div class="heading"><span class="label">Maj-Soul++ · 牌局统计</span><span class="label">行动建议 · 记录状态</span></div>
    <div class="columns"><div class="game"></div><div class="recording">
      <div class="advice" aria-live="polite" hidden></div>
      <div class="caption">等待对局 · 发牌及场上动作后自动更新</div><div class="details"></div>
    </div></div></section>`;
  const panel = shadow.querySelector('.panel'), caption = shadow.querySelector('.caption');
  const game = shadow.querySelector('.game'), details = shadow.querySelector('.details');
  const advice = shadow.querySelector('.advice');
  let adviceKey = null, expectedAdviceKey = null;
  function row(parent, className, text) {
    const element = document.createElement('div');
    element.className = className;
    element.textContent = text;
    parent.appendChild(element);
    return element;
  }
  function tileName(tile) {
    const match = /^([0-9])([mpsz])$/.exec(tile || '');
    if (!match) return String(tile || '—');
    const [, number, suit] = match;
    if (suit === 'z') return ['','东','南','西','北','白','发','中'][Number(number)] || tile;
    return (number === '0' ? '赤5' : number) + {m:'万',p:'筒',s:'索'}[suit];
  }
  function number(value, suffix = '') {
    return Number.isFinite(value) ? Math.round(value).toLocaleString('zh-CN') + suffix : '—';
  }
  function percent(value) {
    return Number.isFinite(value) ? `${(Math.max(0, Math.min(1, value)) * 100).toFixed(1)}%` : '—';
  }
  function shantenLabel(candidate) {
    if (candidate.replacementDraw) return (Number.isFinite(candidate.shanten)
      ? candidate.shanten.toLocaleString('zh-CN', {maximumFractionDigits:1}) : '—') + ' 向听';
    return candidate.shanten === 0 ? (candidate.hasValidWait === false ? '形0向听·无有效听口' : '听牌') : number(candidate.shanten, ' 向听');
  }
  function actionName(candidate) {
    const tile = tileName(candidate.calledTile || candidate.tile || candidate.consumed?.[0]);
    let name;
    switch (candidate.action) {
      case 'riichi': return `立直 · 打 ${tileName(candidate.tile)}`;
      case 'chi': {
        const tiles = [...(candidate.consumed || []), ...(candidate.calledTile ? [candidate.calledTile] : [])];
        tiles.sort((a, b) => (Number(a[0]) || 5) - (Number(b[0]) || 5));
        name = `吃 ${tiles.map(tileName).join('') || tile}`;
        break;
      }
      case 'pon': name = `碰 ${tile}`; break;
      case 'daiminkan': return `大明杠 ${tile}`;
      case 'ankan': return `暗杠 ${tile}`;
      case 'shouminkan': return `加杠 ${tile}`;
      case 'kita': return '拔北';
      case 'pass': return candidate.followupDiscard
        ? `跳过 · 随后摸切 ${tileName(candidate.followupDiscard)}` : '不鸣牌 / 跳过';
      case 'abort': return '九种九牌流局';
      case 'wait': return '等待下一次行动';
      default: return `打 ${tileName(candidate.tile)}`;
    }
    return name + (candidate.followupDiscard ? ` · 再打 ${tileName(candidate.followupDiscard)}` : '');
  }
  function actionKey(candidate) {
    return candidate.actionId || JSON.stringify([candidate.action || 'discard', candidate.tile,
      candidate.consumed, candidate.calledTile, candidate.followupDiscard]);
  }
  function efficiencyLabel(candidate) {
    return `${candidate.replacementDraw ? '补牌后预计 ' : ''}${shantenLabel(candidate)} · 进张 ${number(candidate.ukeire, ' 张')}`;
  }
  function clearAdvice() {
    adviceKey = null;
    advice.replaceChildren();
    advice.hidden = true;
    fit();
  }
  function invalidateAdvice() {
    expectedAdviceKey = null;
    clearAdvice();
  }
  function expectAdvice(key) {
    clearAdvice();
    expectedAdviceKey = key;
  }
  function renderAdvice(result) {
    advice.replaceChildren();
    advice.hidden = !result;
    if (!result) return;
    advice.dataset.status = result.status || 'unavailable';
    const best = result.best || result.candidates?.[0];
    if (!['ready', 'analysis'].includes(result.status) || !best) {
      row(advice, 'advice-message', result.message || '等待可分析的手牌');
      return;
    }
    const strategy = { attack: '进攻', fold: '弃和', locked: '立直续打', replacement: '补牌后分别决策' }[best.currentStrategy];
    const title = result.status === 'analysis' ? '当前手牌评估' : '当前建议';
    row(advice, 'advice-title', strategy ? `${title} · ${strategy}` : title);
    const recommendation = row(advice, 'recommendation', '');
    row(recommendation, 'best-tile' + (best.action && best.action !== 'discard' ? ' best-action' : ''), actionName(best));
    if (best.action !== 'abort') {
      row(recommendation, 'efficiency', efficiencyLabel(best));
      const metrics = row(advice, 'metrics', '');
      const replacement = best.replacementDraw;
      const metricValues = [
        ['后续胡牌率（估计）', percent(best.winProbability)],
        ['胡牌得点（估计）', number(best.expectedWinPoints)],
        ['攻守评分', number(best.score)]
      ];
      if (result.status !== 'analysis' && best.action !== 'wait') {
        const riskLabel = replacement ? '操作风险（估计）'
          : best.followupDiscard ? '后续弃牌风险（估计）' : '本次放铳率（估计）';
        metricValues.splice(1, 0, [riskLabel, percent(best.dealInProbability)]);
        metricValues.splice(3, 0, ['放铳输点（估计）', number(best.dealInPoints)]);
        metricValues.push([replacement ? '操作预期损失（估计）' : '本次预期损失（估计）', number(best.expectedDealInLoss)]);
      }
      for (const [label, value] of metricValues) {
        const metric = row(metrics, '', '');
        row(metric, 'metric-label', label);
        row(metric, 'metric-value', value);
      }
    }
    const seen = new Set([actionKey(best)]);
    const alternatives = (result.candidates || []).filter(candidate => {
      const key = actionKey(candidate);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, result.warnings?.length ? 1 : 2);
    for (const candidate of alternatives) row(advice, 'alternatives', candidate.action === 'abort'
      ? `备选 ${actionName(candidate)}`
      : `备选 ${actionName(candidate)} · ${candidate.replacementDraw ? '补牌后预计 ' : ''}${shantenLabel(candidate)} / ${number(candidate.ukeire, '张')} · 风险 ${percent(candidate.dealInProbability)} · 打点 ${number(candidate.expectedWinPoints)}（估计）`);
    if (best.reasons?.length) row(advice, 'reasons', best.reasons.slice(0, 2).join('；'));
    if (result.warnings?.length) row(advice, 'advice-warning', `仅比较已核实动作 · ${result.warnings[0]}`);
  }
  function fit() {
    // Keep game and recording information in fixed columns within the upper half.
    panel.style.fontSize = '13px';
    panel.style.transform = '';
    const available = Math.max(40, innerHeight / 2 - 24);
    for (let size = 12.5; panel.getBoundingClientRect().height > available && size >= 8; size -= 0.5) {
      panel.style.fontSize = `${size}px`;
    }
    const scale = Math.min(1, available / panel.getBoundingClientRect().height);
    panel.style.transformOrigin = 'top center';
    panel.style.transform = scale < 1 ? `scale(${scale})` : '';
  }
  function mount() {
    const parent = document.fullscreenElement || document.body || document.documentElement;
    if (!parent) return;
    parent.appendChild(host);
    fit();
  }
  window.__mjStatsOverlay = {invalidateAdvice, expectAdvice, update(packet) {
    if (packet.kind === 'advice') {
      if (!adviceKey || packet.adviceKey !== adviceKey) return;
      renderAdvice(packet.advice);
      fit();
      return;
    }
    if (packet.kind === 'turn') {
      // Browser input can invalidate a turn before its native reply arrives.
      if (!expectedAdviceKey || packet.adviceKey !== expectedAdviceKey) return;
      adviceKey = packet.adviceKey || null;
      renderAdvice(packet.advice);
      const lines = packet.text.split('\n').filter(line => line && !/^═+$/.test(line));
      caption.textContent = lines.shift() || '牌局已更新';
      game.replaceChildren(); details.replaceChildren();
      for (const text of lines) {
        const recording = /^(状态|完整性|说明|触发)：/.test(text);
        const row = document.createElement('div');
        row.className = 'line' + (/^本人/.test(text) ? ' hand' : recording ? ' footnote' : '');
        row.textContent = text;
        (recording ? details : game).appendChild(row);
      }
    } else {
      // A queued status may precede an already-published newer browser turn.
      clearAdvice();
      caption.textContent = packet.text;
      if (packet.reset || ['waiting','connected','playing','ended'].includes(packet.phase)) {
        game.replaceChildren(); details.replaceChildren();
      }
    }
    mount();
  }};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true});
  else mount();
  addEventListener('resize', fit);
  document.addEventListener('fullscreenchange', mount);
})();
