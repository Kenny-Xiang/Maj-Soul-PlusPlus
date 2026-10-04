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
    .recommendation { display:flex; align-items:baseline; flex-wrap:wrap; gap:5px 12px; }
    .best-tile { color:#ffe1a4; font-size:1.8em; font-weight:700; line-height:1.3; }
    .efficiency { color:#c7e7ff; }
    .metrics { display:grid; grid-template-columns:1fr 1fr; gap:2px 10px; margin:4px 0; }
    .metric-label { display:inline; color:#bacbd9; }
    .metric-value { display:inline; color:#f4f7fc; font-weight:600; margin-left:4px; }
    .alternatives, .reasons { color:#d0dfec; overflow-wrap:anywhere; }
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
    <div class="heading"><span class="label">Maj-Soul++ · 牌局统计</span><span class="label">出牌建议 · 记录状态</span></div>
    <div class="columns"><div class="game"></div><div class="recording">
      <div class="advice" aria-live="polite" hidden></div>
      <div class="caption">等待对局 · 发牌及场上动作后自动更新</div><div class="details"></div>
    </div></div></section>`;
  const panel = shadow.querySelector('.panel'), caption = shadow.querySelector('.caption');
  const game = shadow.querySelector('.game'), details = shadow.querySelector('.details');
  const advice = shadow.querySelector('.advice');
  let adviceKey = null;
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
    return candidate.shanten === 0 ? (candidate.hasValidWait === false ? '形0向听·无有效听口' : '听牌') : number(candidate.shanten, ' 向听');
  }
  function invalidateAdvice() {
    adviceKey = null;
    advice.replaceChildren();
    advice.hidden = true;
    fit();
  }
  function renderAdvice(result) {
    advice.replaceChildren();
    advice.hidden = !result;
    if (!result) return;
    advice.dataset.status = result.status || 'unavailable';
    const best = result.best || result.candidates?.[0];
    if (result.status !== 'ready' || !best) {
      row(advice, 'advice-message', result.message || '等待可分析的手牌');
      return;
    }
    row(advice, 'advice-title', '当前建议 · 启发式估计，未校准');
    const recommendation = row(advice, 'recommendation', '');
    row(recommendation, 'best-tile', `打 ${tileName(best.tile)}`);
    row(recommendation, 'efficiency', `${shantenLabel(best)} · 进张 ${number(best.ukeire, ' 张')}`);
    const metrics = row(advice, 'metrics', '');
    for (const [label, value] of [
      ['后续胡牌率（估计）', percent(best.winProbability)],
      ['本次放铳率（估计）', percent(best.dealInProbability)],
      ['胡牌得点（估计）', number(best.expectedWinPoints)],
      ['放铳输点（估计）', number(best.dealInPoints)],
      ['攻守评分', number(best.score)],
      ['本次预期损失（估计）', number(best.expectedDealInLoss)]
    ]) {
      const metric = row(metrics, '', '');
      row(metric, 'metric-label', label);
      row(metric, 'metric-value', value);
    }
    const alternatives = (result.candidates || []).filter(candidate => candidate.tile !== best.tile).slice(0, 2);
    for (const candidate of alternatives) row(advice, 'alternatives',
      `备选 ${tileName(candidate.tile)} · ${shantenLabel(candidate)} / ${number(candidate.ukeire, '张')} · 风险 ${percent(candidate.dealInProbability)} · 打点 ${number(candidate.expectedWinPoints)}（估计）`);
    if (best.reasons?.length) row(advice, 'reasons', best.reasons.slice(0, 2).join('；'));
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
  window.__mjStatsOverlay = {invalidateAdvice, update(packet) {
    if (packet.kind === 'advice') {
      if (!adviceKey || packet.adviceKey !== adviceKey) return;
      renderAdvice(packet.advice);
      fit();
      return;
    }
    if (packet.kind === 'turn') {
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
      invalidateAdvice();
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
