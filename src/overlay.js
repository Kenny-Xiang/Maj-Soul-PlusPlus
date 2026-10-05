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
    .advice { margin:0 0 9px; padding-bottom:9px; border-bottom:1px solid rgba(220,235,255,.18); }
    .advice-title { color:#aee6d1; font-weight:600; }
    .advice-message { color:#c7d4e2; }
    .advice-warning { color:#ffe1a4; font-weight:600; line-height:1.35; overflow-wrap:anywhere; margin:4px 0; }
    .recommendation { display:flex; align-items:baseline; flex-wrap:wrap; gap:5px 12px; }
    .best-tile { color:#ffe1a4; font-size:1.8em; font-weight:700; line-height:1.3; }
    .best-action { font-size:1.45em; }
    .efficiency { color:#c7e7ff; }
    .metrics { display:flex; flex-wrap:wrap; gap:2px 14px; margin:4px 0; }
    .metrics > div { white-space:nowrap; }
    .metric-label { display:inline; color:#bacbd9; }
    .metric-value { display:inline; color:#f4f7fc; font-weight:600; margin-left:4px; }
    .alternatives, .reasons { color:#d0dfec; overflow-wrap:anywhere; }
    .alternatives { line-height:1.35; }
    .reasons { margin-top:3px; }
    @media (max-width:850px) {
      .heading, .columns { grid-template-columns:minmax(0,3fr) minmax(0,2fr); column-gap:16px; }
      .panel { padding:9px 12px; }
      .recording, .heading > :last-child { padding-left:10px; }
    }
    @media (max-width:650px) {
      .metrics { display:block; }
      .metrics > div { display:inline; margin-right:8px; }
      .metrics .metric-label, .metrics .metric-value { display:inline; }
      .metrics .metric-value::before { content:' '; }
      .alternatives { display:none; }
    }
  </style><section class="panel" aria-label="最新牌局统计">
    <div class="heading"><span class="label">Maj-Soul++ · 牌局统计</span><span class="label">行动建议</span></div>
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
    return `${candidate.replacementDraw ? '补牌后预计 ' : ''}${shantenLabel(candidate)} · 有效未见 ${number(candidate.ukeire, ' 张')}`;
  }
  function riskLabel(candidate) {
    if (candidate.replacementDraw) return '操作风险';
    if (candidate.followupDiscard) return '后续弃牌风险';
    return ['wait', 'pass', 'abort'].includes(candidate.action) ? null : '本次放铳率';
  }
  function displayReasons(candidate) {
    const reasons = [...new Set(candidate.reasons || [])].filter(reason =>
      !candidate.abortAfterRiichi || !/^立直后不能自由弃和/.test(reason));
    if (candidate.furiten && !candidate.replacementDraw && !reasons.some(reason => /振听/.test(reason))) {
      reasons.unshift('整副牌振听，所有等待均只估自摸');
    }
    const important = reason => /振听|无役|未找到有役|役尚未确定|尚未确认荣和役|合法的听口|第四杠|第四家立直|不能自由/.test(reason);
    const generic = /^(当前(?:进攻|弃和|已立直)：|(?:听牌|\d+ 向听)；有效未见牌|枚举有效进张|二向听以上按近似|逐次比较继续保听|终局互斥核算|未见牌包含)/;
    return {warnings: reasons.filter(important),
      context: reasons.filter(reason => !important(reason) && !generic.test(reason)).slice(0, 1)};
  }
  function alternativeLabel(candidate, best) {
    const differences = [];
    if (candidate.action !== 'abort') {
      if (candidate.shanten !== best.shanten || candidate.replacementDraw !== best.replacementDraw) {
        differences.push(`${candidate.replacementDraw ? '补牌后预计 ' : ''}${shantenLabel(candidate)}`);
      } else if (Number.isFinite(candidate.ukeire) && Number.isFinite(best.ukeire) && candidate.ukeire !== best.ukeire) {
        differences.push(`有效未见${candidate.ukeire > best.ukeire ? '多' : '少'} ${Math.abs(candidate.ukeire - best.ukeire).toLocaleString('zh-CN', {maximumFractionDigits:1})} 张`);
      }
      if (riskLabel(candidate) && (percent(candidate.dealInProbability) !== percent(best.dealInProbability) || riskLabel(candidate) !== riskLabel(best))) {
        differences.push(`${riskLabel(candidate)} ${percent(candidate.dealInProbability)}（估计）`);
      }
      if (candidate.expectedWinPoints !== best.expectedWinPoints) differences.push(`打点 ${number(candidate.expectedWinPoints)}（估计）`);
    }
    return [`备选 ${actionName(candidate)}`, ...differences.slice(0, 2)].join(' · ');
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
      row(advice, result.status === 'unavailable' ? 'advice-warning' : 'advice-message', result.message || '等待可分析的手牌');
      return;
    }
    const strategy = best.abortAfterRiichi ? '四家立直流局'
      : { attack: '进攻', fold: '弃和', locked: '立直续打', replacement: '补牌后分别决策' }[best.currentStrategy];
    const title = result.status === 'analysis' ? '当前手牌评估' : '当前建议';
    row(advice, 'advice-title', strategy ? `${title} · ${strategy}` : title);
    const recommendation = row(advice, 'recommendation', '');
    row(recommendation, 'best-tile' + (best.action && best.action !== 'discard' ? ' best-action' : ''), actionName(best));
    const reasons = displayReasons(best);
    for (const reason of reasons.warnings) row(advice, 'advice-warning', reason);
    if (result.warnings?.length) row(advice, 'advice-warning', `仅比较已核实动作 · ${result.warnings.join('；')}`);
    if (best.action !== 'abort') {
      row(recommendation, 'efficiency', efficiencyLabel(best));
      const metrics = row(advice, 'metrics', '');
      const metricValues = [['胡牌得点（估计）', number(best.expectedWinPoints)]];
      if (result.status !== 'analysis' && riskLabel(best)) metricValues.unshift([`${riskLabel(best)}（估计）`, percent(best.dealInProbability)]);
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
    }).slice(0, 1);
    if (reasons.context.length) row(advice, 'reasons', reasons.context.join('；'));
    for (const candidate of alternatives) row(advice, 'alternatives', alternativeLabel(candidate, best));
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
      lines.shift(); // The full timestamp and action counters remain in the log.
      caption.textContent = '';
      caption.hidden = true;
      game.replaceChildren(); details.replaceChildren();
      for (let text of lines) {
        const recording = /^(状态|完整性|说明|触发)：/.test(text);
        if (text === '状态：正在对局' || text === '完整性：已取得手牌基线；本小局动作连续') continue;
        if (text.startsWith('触发：')) {
          const errors = /解析错误 ([1-9]\d*) 次/.exec(text);
          if (!errors) continue;
          text = `解析错误 ${errors[1]} 次，统计可能不完整`;
        }
        const row = document.createElement('div');
        row.className = 'line' + (/^本人/.test(text) ? ' hand' : recording ? ' advice-warning' : '');
        row.textContent = text;
        (recording ? details : game).appendChild(row);
      }
    } else {
      // A queued status may precede an already-published newer browser turn.
      clearAdvice();
      caption.textContent = packet.text;
      caption.hidden = false;
      caption.className = 'caption' + (packet.phase === 'disconnected' || !packet.phase ? ' advice-warning' : '');
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
