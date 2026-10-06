// Game input passes through except for automation buttons; values are inserted as text.
(() => {
  if (location.hostname !== 'game.maj-soul.com' || window.__mjStatsOverlay) return;
  const host = document.createElement('div');
  host.id = 'mj-statistics-overlay';
  host.style.cssText = 'position:fixed;top:12px;left:16px;right:16px;z-index:2147483647;pointer-events:none;user-select:none';
  const shadow = host.attachShadow({mode:'open'});
  shadow.innerHTML = `<style>
    :host { color-scheme:dark; }
    * { box-sizing:border-box; pointer-events:none; }
    .panel { padding:10px 14px; border:1px solid rgba(210,230,255,.22); border-radius:12px;
      background:rgba(12,22,36,.64); color:#f4f7fc; box-shadow:0 4px 20px rgba(0,0,0,.18);
      font:13px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif; }
    .automation { display:flex; align-items:center; flex-wrap:wrap; gap:4px 7px; margin-bottom:6px; }
    .automation button { pointer-events:auto; cursor:pointer; font:inherit; line-height:1.4;
      color:#f4f7fc; background:rgba(185,217,249,.1); border:1px solid rgba(185,217,249,.3);
      border-radius:5px; padding:2px 7px; }
    .automation button[aria-checked="true"], .automation button[aria-pressed="true"] {
      color:#c6f4df; border-color:#91ccb3; background:rgba(70,145,115,.25); }
    .automation button:focus-visible { outline:2px solid #ffdfa0; outline-offset:2px; }
    .automation-mode-label, .automation-next { color:#bacbd9; font-size:.9em; }
    .automation-status { color:#c7d4e2; overflow-wrap:anywhere; min-width:0; }
    .automation-status[data-phase="paused"], .automation-status[data-phase="unavailable"] { color:#ffe1a4; }
    .heading, .columns { display:grid; grid-template-columns:minmax(0,2fr) minmax(0,1fr); column-gap:28px; }
    .heading { margin-bottom:4px; font-weight:600; }
    .label { color:#b9d9f9; white-space:nowrap; }
    .caption { font-weight:400; color:#e0e8f0; overflow-wrap:anywhere; padding-bottom:4px; }
    .recording, .heading > :last-child { border-left:1px solid rgba(220,235,255,.12); padding-left:14px; }
    .line { white-space:pre-wrap; overflow-wrap:anywhere; break-inside:avoid; padding-bottom:2px; }
    .hand { color:#ffdfa0; font-weight:600; }
    .advice { margin:0 0 4px; }
    .advice-title { color:#aee6d1; font-weight:600; }
    .advice-message { color:#c7d4e2; }
    .advice-warning { color:#ffe1a4; font-weight:600; line-height:1.35; overflow-wrap:anywhere; margin:3px 0; }
    .recommendation { display:flex; align-items:baseline; flex-wrap:wrap; gap:5px 12px; }
    .best-tile { color:#ffe1a4; font-size:1.8em; font-weight:700; line-height:1.3; }
    .best-action { font-size:1.45em; }
    .efficiency { color:#c7e7ff; }
    .metrics { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:3px; margin:4px 0; }
    .metrics > div { grid-column:span 2; padding:2px 5px; border-radius:5px; background:rgba(185,217,249,.07); line-height:1.25; }
    .metrics > div:nth-last-child(-n+2) { grid-column:span 3; }
    .metric-label { color:#bacbd9; font-size:.8em; overflow-wrap:anywhere; }
    .metric-value { color:#f4f7fc; font-size:1.15em; font-weight:600; font-variant-numeric:tabular-nums; }
    .metrics > div:nth-last-child(-n+2) .metric-label, .metrics > div:nth-last-child(-n+2) .metric-value { display:inline; }
    .metrics > div:nth-last-child(-n+2) .metric-value { margin-left:4px; }
    .alternatives, .reasons { color:#d0dfec; overflow-wrap:anywhere; }
    .alternatives, .comparison-head { display:grid; grid-template-columns:1.2fr 1.3fr 1fr .8fr; gap:5px; align-items:baseline; }
    .alternatives { line-height:1.3; padding:1px 0; font-variant-numeric:tabular-nums; }
    .alternatives > :last-child, .comparison-head > :last-child { text-align:right; }
    .comparison-head { color:#bacbd9; font-size:.8em; }
    .alternative-action { color:#ffdfa0; }
    .reasons { margin-top:3px; line-height:1.3; }
    .progress, .comparison { margin-top:4px; padding-top:4px; border-top:1px solid rgba(220,235,255,.14); }
    .section-title { color:#b9d9f9; font-weight:600; margin-bottom:2px; line-height:1.2; }
    .progress-heading { display:flex; flex-wrap:wrap; align-items:baseline; gap:0 8px; }
    .progress-heading .progress-note { margin:0 0 3px; }
    .tile-list { display:flex; flex-wrap:wrap; gap:3px 5px; }
    .tile-chip { padding:0 5px; border:1px solid rgba(185,217,249,.18); border-radius:4px; color:#e3edf8; }
    .progress-note { color:#bacbd9; font-size:.85em; margin-top:3px; }
    @media (max-width:850px) {
      .heading, .columns { grid-template-columns:minmax(0,3fr) minmax(0,2fr); column-gap:16px; }
      .panel { padding:9px 12px; }
      .recording, .heading > :last-child { padding-left:10px; }
      .metrics { grid-template-columns:repeat(2,minmax(0,1fr)); gap:3px; margin:5px 0; }
      .metrics > div, .metrics > div:nth-last-child(-n+2) { grid-column:span 1; }
    }
    @media (max-width:650px) {
      .metrics .metric-value { font-size:1.1em; }
      .progress, .comparison { margin-top:4px; padding-top:4px; }
      .tile-list { gap:2px; }
    }
  </style><section class="panel" aria-label="最新牌局统计">
    <div class="automation" aria-label="自动打牌控制">
      <button type="button" class="automation-toggle" role="switch" aria-checked="false">自动打牌：关闭</button>
      <span class="automation-mode-label">对局模式</span>
      <button type="button" class="automation-four" aria-pressed="true">四麻</button>
      <button type="button" class="automation-three" aria-pressed="false">三麻</button>
      <span class="automation-mode-label">对局长度</span>
      <button type="button" class="automation-east" aria-pressed="true">东风</button>
      <button type="button" class="automation-south" aria-pressed="false">南风</button>
      <span class="automation-next">下场生效</span>
      <span class="automation-status" role="status" aria-live="polite">待机</span>
    </div>
    <div class="heading"><span class="label">Maj-Soul++ · 牌局统计</span><span class="label">行动建议</span></div>
    <div class="columns"><div class="game"></div><div class="recording">
      <div class="advice" aria-live="polite" hidden></div>
      <div class="caption">等待对局 · 发牌及场上动作后自动更新</div><div class="details"></div>
    </div></div></section>`;
  const panel = shadow.querySelector('.panel'), caption = shadow.querySelector('.caption');
  const game = shadow.querySelector('.game'), details = shadow.querySelector('.details');
  const advice = shadow.querySelector('.advice');
  const automationToggle = shadow.querySelector('.automation-toggle');
  const automationFour = shadow.querySelector('.automation-four'), automationThree = shadow.querySelector('.automation-three');
  const automationEast = shadow.querySelector('.automation-east'), automationSouth = shadow.querySelector('.automation-south');
  const automationStatus = shadow.querySelector('.automation-status');
  let automationEnabled = false;
  let adviceKey = null, expectedAdviceKey = null;
  function updateAutomation(status) {
    if (!status) return;
    automationEnabled = status.enabled === true;
    automationToggle.setAttribute('aria-checked', String(automationEnabled));
    automationToggle.textContent = `自动打牌：${automationEnabled ? '开启' : '关闭'}`;
    automationFour.setAttribute('aria-pressed', String(status.playerCount !== 3));
    automationThree.setAttribute('aria-pressed', String(status.playerCount === 3));
    automationEast.setAttribute('aria-pressed', String(status.roundCount !== 2));
    automationSouth.setAttribute('aria-pressed', String(status.roundCount === 2));
    automationStatus.dataset.phase = status.phase || 'idle';
    automationStatus.textContent = status.message || (automationEnabled ? '等待行动' : '待机');
    fit();
  }
  function changeAutomation(method, value) {
    const controller = window.__mjAutoplay;
    if (typeof controller?.[method] !== 'function') {
      automationStatus.dataset.phase = 'unavailable';
      automationStatus.textContent = '自动打牌暂不可用';
      fit();
      return;
    }
    controller[method](value);
    updateAutomation(controller.getStatus?.());
  }
  automationToggle.addEventListener('click', () => changeAutomation('setEnabled', !automationEnabled));
  automationFour.addEventListener('click', () => changeAutomation('setPlayerCount', 4));
  automationThree.addEventListener('click', () => changeAutomation('setPlayerCount', 3));
  automationEast.addEventListener('click', () => changeAutomation('setRoundCount', 1));
  automationSouth.addEventListener('click', () => changeAutomation('setRoundCount', 2));
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
  function tileCount(value) {
    return Number.isFinite(value) ? value.toLocaleString('zh-CN', {maximumFractionDigits:1}) : '—';
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
    return `${candidate.replacementDraw ? '补牌后预计 ' : ''}${shantenLabel(candidate)} · 有效未见 ${tileCount(candidate.ukeire)} 张`;
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
  function renderAlternative(parent, candidate, analysis) {
    const alternative = row(parent, 'alternatives', '');
    row(alternative, 'alternative-action', actionName(candidate));
    const abort = candidate.action === 'abort';
    row(alternative, '', abort ? '—' : `${candidate.replacementDraw ? '预计 ' : ''}${shantenLabel(candidate)} / ${tileCount(candidate.ukeire)}张`);
    const context = candidate.replacementDraw ? '操作 ' : candidate.followupDiscard ? '后续 ' : '';
    row(alternative, 'alternative-risk', !analysis && riskLabel(candidate) ? context + percent(candidate.dealInProbability) : '—');
    row(alternative, '', abort ? '—' : number(candidate.expectedWinPoints));
  }
  function renderProgress(best) {
    if (best.action === 'abort' || best.abortAfterRiichi) return;
    const progress = row(advice, 'progress', '');
    const ready = best.shanten === 0 && !best.replacementDraw;
    const heading = row(progress, 'progress-heading', '');
    row(heading, 'section-title', ready ? '听口明细' : '有效进张明细');
    if (best.replacementDraw) {
      row(progress, 'progress-note', '补牌后再确定进张，当前数值为各补牌分支的加权估计');
      return;
    }
    const tiles = ready ? best.winningTiles : best.improvingTiles;
    if (!tiles?.length) {
      row(progress, 'progress-note', tiles
        ? (ready ? '没有实体上合法的听口' : '暂无可降低向听的未见进张') : '暂无进张明细');
      return;
    }
    row(heading, 'progress-note', '张数为未见牌，含他家手牌与王牌');
    const list = row(progress, 'tile-list', '');
    for (const tile of tiles) {
      const constraint = !ready ? '' : !tile.ronPoints && !tile.tsumoPoints ? ' · 无役'
        : !tile.ronPoints ? ' · 仅自摸' : !tile.tsumoPoints ? ' · 仅荣和' : '';
      row(list, 'tile-chip', `${tileName(tile.tile)} × ${number(tile.count)}${constraint}`);
    }
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
    const rank = result.rankContext, profile = rank?.profile;
    const preference = {protect:'偏重保位', push:'增加追分意愿', balanced:'均衡攻守'}[rank?.preference];
    const players = {3:'三人', 4:'四人'}[profile?.playerCount], length = {1:'东', 2:'南'}[profile?.roundCount];
    if (rank?.active === true && rank.objective === 'rank-points' && preference && players && length &&
        profile.roomName && profile.rankName) {
      row(advice, 'advice-message rank-context',
        `排位上升 · ${profile.roomName} · ${players}${length} · ${profile.rankName} · ${preference}`);
    }
    const recommendation = row(advice, 'recommendation', '');
    row(recommendation, 'best-tile' + (best.action && best.action !== 'discard' ? ' best-action' : ''), actionName(best));
    const reasons = displayReasons(best);
    for (const reason of reasons.warnings) row(advice, 'advice-warning', reason);
    if (result.warnings?.length) row(advice, 'advice-warning', `仅比较已核实动作 · ${result.warnings.join('；')}`);
    if (best.action !== 'abort') {
      row(recommendation, 'efficiency', efficiencyLabel(best));
      const metrics = row(advice, 'metrics', '');
      const metricValues = [['后续胡牌率（估计）', percent(best.winProbability)],
        ['胡牌得点（估计）', number(best.expectedWinPoints)]];
      if (result.status !== 'analysis' && riskLabel(best)) {
        const context = best.replacementDraw ? '操作' : best.followupDiscard ? '后续弃牌' : '本次';
        metricValues.unshift([`${riskLabel(best)}（估计）`, percent(best.dealInProbability)],
          [`${best.replacementDraw ? '操作' : ''}放铳输点（估计）`, number(best.dealInPoints)],
          [`${context}预期损失（估计）`, number(best.expectedDealInLoss)]);
      }
      for (const [label, value] of metricValues) {
        const metric = row(metrics, '', '');
        row(metric, 'metric-label', label);
        row(metric, 'metric-value', value);
      }
    }
    const seen = new Set([actionKey(best)]);
    const ranked = Number.isInteger(result.rankedCandidateCount)
      ? (result.candidates || []).slice(0, Math.max(0, result.rankedCandidateCount)) : (result.candidates || []);
    const alternatives = ranked.filter(candidate => {
      const key = actionKey(candidate);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, 2);
    if (reasons.context.length) row(advice, 'reasons', reasons.context.join('；'));
    renderProgress(best);
    if (alternatives.length) {
      const comparison = row(advice, 'comparison', '');
      row(comparison, 'section-title', '备选对比');
      const heading = row(comparison, 'comparison-head', '');
      for (const label of ['行动', '向听 / 未见', '风险估计', '打点估计']) row(heading, '', label);
      for (const candidate of alternatives) renderAlternative(comparison, candidate, result.status === 'analysis');
    }
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
  window.__mjStatsOverlay = {invalidateAdvice, expectAdvice, updateAutomation, update(packet) {
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
  updateAutomation(window.__mjAutoplay?.getStatus?.());
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true});
  else mount();
  addEventListener('resize', fit);
  document.addEventListener('fullscreenchange', mount);
})();
