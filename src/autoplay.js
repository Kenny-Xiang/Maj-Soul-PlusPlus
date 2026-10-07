// Own the user's automation intent; adapters perform one verified client action.
(() => {
  if (location.hostname !== 'game.maj-soul.com' || window.__mjAutoplay) return;
  let enabled = false, playerCount = 4, roundCount = 1, phase = 'idle', message = '待机';
  let current = null, pending = null, submitted = null, executing = false, stopped = false, cancelling = null;
  let lastStatus = '';
  let lastLogState = '';
  let clientLoadingSince = null, initialRoundSince = null;
  let recovery = null;
  let pace = 1, observed = null, threatVersion = 0, handledThreat = 0, continuation = null, lastWindow = null;
  const now = () => performance.now();
  // Initial pacing parameters, not a fit to human play. Sample once per window.
  const ranges = {forced:[450,900], win:[650,1200], followup:[550,1100], pass:[650,1300],
    clear:[1000,2000], normal:[1400,2700], deliberate:[2200,3800], reassess:[2600,4500]};
  const delay = () => 800 + Math.random() * 800;
  const roundKey = event => JSON.stringify([event.session, event.state.round]);
  const sameTiles = (a, b) => JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());
  const budgetExceeded = advice => advice?.status === 'unavailable' &&
    advice.reason === 'search_budget_exceeded' && advice.recoverable === true;
  function observe(event) {
    const state = event.state, round = roundKey(event);
    const threats = (state.riichi || []).map((value, seat) => seat === state.selfSeat ? false :
      !!(value || state.riichiPending?.[seat]));
    const melds = (state.melds || []).map((value, seat) => seat === state.selfSeat ? 0 : value.length);
    if (!observed || observed.round !== round || state.phase !== 'playing') {
      threatVersion = handledThreat = 0; continuation = null;
    } else if (enabled && (threats.some((value, seat) => value && !observed.threats[seat]) ||
        melds.some((count, seat) => count > (observed.melds[seat] || 0)) ||
        (state.doras || []).length > observed.doras)) threatVersion++;
    observed = {round, threats, melds, doras:(state.doras || []).length};
    if (!continuation) return;
    const action = event.action;
    if (continuation.round !== round || state.lastStep !== continuation.step ||
        action?.name !== 'ActionChiPengGang' || action.seat !== state.selfSeat ||
        action.type !== continuation.type || !Array.isArray(action.tiles) || !Array.isArray(action.froms) ||
        action.froms.length !== action.tiles.length || !sameTiles(action.tiles, continuation.tiles) ||
        !sameTiles(action.tiles.filter((tile, i) => action.froms[i] === state.selfSeat), continuation.consumed) ||
        action.froms.filter(seat => seat === continuation.fromSeat).length !== 1) continuation = null;
    else continuation.confirmed = true;
  }
  function plan(turn) {
    if (turn.timing || !['ready','win'].includes(turn.advice?.status)) return;
    const advice = turn.advice, best = advice.best, state = turn.state;
    let category = 'normal';
    const complete = !advice.warnings?.length;
    if (advice.status === 'win') category = 'win';
    else if (complete && best?.action === 'discard' && state.canDiscard &&
        (state.riichi?.[state.selfSeat] || state.riichiPending?.[state.selfSeat]) &&
        state.operations?.length === 1 && state.operations[0] === 1 && best.tile === state.lastDraw) category = 'forced';
    else if (turn.threat > handledThreat) category = 'reassess';
    else if (complete && continuation?.confirmed && continuation.round === turn.round &&
        state.lastStep === continuation.step && best?.action === 'discard' &&
        best.tile === continuation.tile) category = 'followup';
    else if (complete && best) {
      const alternate = advice.rankedCandidateCount === undefined || advice.rankedCandidateCount >= 2 ?
        advice.candidates?.[1] : null;
      const gap = best.decisionBasis?.scoreGap;
      const components = Object.values(best.decisionBasis?.componentAdvantages || {});
      const tradeoff = alternate && (alternate.action !== best.action ||
        alternate.currentStrategy !== best.currentStrategy ||
        alternate.metricContext !== best.metricContext ||
        components.some(value => value > 50) && components.some(value => value < -50));
      if (Number.isFinite(gap) && gap >= 0 && gap < 100 && tradeoff) category = 'deliberate';
      else if (alternate && Number.isFinite(gap) && gap >= 100) category = best.action === 'pass' ? 'pass' : 'clear';
    }
    const [low, high] = ranges[category];
    const targetMs = Math.round(pace * (low + (high - low) * turn.sample * turn.sample));
    turn.target = turn.startedAt + targetMs;
    turn.timing = {category, targetMs, adviceReadyMs:Math.max(0, now() - turn.startedAt)};
  }
  function restartTiming(turn, startedAt) {
    turn.startedAt = startedAt; turn.sample = Math.random(); turn.timing = null;
    turn.target = startedAt; plan(turn);
  }
  function status(nextPhase, nextMessage) {
    phase = nextPhase; message = nextMessage;
    const value = getStatus(), signature = JSON.stringify(value);
    if (signature !== lastStatus) {
      lastStatus = signature;
      window.__mjStatsOverlay?.updateAutomation?.(value);
    }
    const logState = JSON.stringify([enabled, playerCount, roundCount, phase]);
    if (logState !== lastLogState) {
      lastLogState = logState; window.__mjMonitor?.reportAutomation?.(value);
    }
  }
  function getStatus() {
    const timing = current?.timing;
    return {enabled, playerCount, roundCount, phase, message, ...(timing ? {timing:{...timing,
      elapsedMs:Math.max(0, (current.sentAt ?? now()) - current.startedAt)}} : {})};
  }
  function cancelMatch() {
    try {
      const result = window.__mjLobby?.cancel();
      if (result?.pending) cancelling ??= now();
      else {
        cancelling = null;
        if (result?.ok === false) throw new Error(result.reason || '客户端拒绝取消');
      }
    } catch (error) {
      cancelling = null;
      status('paused', `已停止自动操作；取消匹配失败：${error.message}`);
    }
  }
  function pause(reason) {
    const wasEnabled = enabled;
    enabled = false; pending = null; clientLoadingSince = initialRoundSince = null; continuation = null; lastWindow = null;
    status('paused', reason);
    if (wasEnabled) cancelMatch();
  }
  function setEnabled(value) {
    if (stopped) return;
    if (!value) {
      const wasEnabled = enabled;
      enabled = false; pending = null; clientLoadingSince = initialRoundSince = null; continuation = null; lastWindow = null;
      status('idle', '已关闭 · 手动操作');
      if (wasEnabled) cancelMatch();
      return;
    }
    if (enabled) return;
    if (cancelling !== null) { status('waiting', '正在取消上一轮匹配，请稍后开启'); return; }
    if (window.__mjUnityTransport?.isUnity() && window.__mjUnityActions?.snapshot().pending) {
      status('waiting', '等待上次操作确认，请稍后开启'); return;
    }
    enabled = true; pending = null; submitted = null; clientLoadingSince = initialRoundSince = null;
    pace = .95 + Math.random() * .1; handledThreat = threatVersion;
    if (current && !current.sent) { restartTiming(current, now()); lastWindow = current; }
    status('waiting', '已开启 · 检查当前对局');
    tick();
  }
  function setPlayerCount(value) {
    if (![3, 4].includes(value) || value === playerCount) return;
    playerCount = value;
    // An existing queue belongs to its selected mode; the next queue uses this preference.
    pending = null;
    status(phase, '模式已更新 · 下一场生效');
  }
  function setRoundCount(value) {
    if (![1, 2].includes(value) || value === roundCount) return;
    roundCount = value;
    pending = null;
    status(phase, '场次已更新 · 下一场生效');
  }
  function onEvent(event) {
    if (stopped || !['turn', 'status', 'error'].includes(event.kind)) return;
    const nextRecovery = event.kind === 'turn' ? event.state.recovery : event.recovery;
    if (nextRecovery !== undefined) recovery = nextRecovery;
    else if (event.phase === 'disconnected') recovery = {status:'waiting', reason:'connection'};
    if (event.reset) recovery = null;
    if (recovery?.status === 'waiting') {
      submitted = null; continuation = lastWindow = null; initialRoundSince = null;
    }
    const previous = lastWindow;
    current = null; pending = null;
    if (event.reset) {
      observed = continuation = lastWindow = null; threatVersion = handledThreat = 0;
    }
    if (event.kind === 'turn') {
      observe(event);
      const windowKey = JSON.stringify([event.session, event.state]);
      const sameWindow = previous?.windowKey === windowKey;
      current = {key: `${event.session}:${event.serial}`, state: event.state,
        round:roundKey(event), windowKey, threat:threatVersion, advice:null, sent:false};
      if (sameWindow) Object.assign(current, {startedAt:previous.startedAt, sample:previous.sample,
        target:previous.target, timing:previous.timing, sent:previous.sent, sentAt:previous.sentAt,
        expired:previous.expired});
      else {
        const receivedAt = event.state.operationTiming?.receivedAt;
        restartTiming(current, Number.isFinite(receivedAt) && receivedAt >= 0 && receivedAt <= now() ? receivedAt : now());
      }
      lastWindow = current;
      if (enabled && event.state.phase === 'playing' &&
          (!event.state.handComplete || !event.state.historyComplete) && recovery?.status !== 'waiting') {
        pause('已暂停：牌局基线不完整，需恢复后重新开启');
      }
    } else if (enabled && (event.kind === 'error' || event.phase === 'stopped')) {
      pause('已暂停：连接或牌局解析异常');
    }
    if (enabled && recovery?.status === 'failed') pause(`已暂停：${recovery.reason}`);
    if (enabled && recovery?.status === 'waiting')
      status('reconnecting', '正在重新连接并恢复牌局 · 自动打牌保持开启');
  }
  function onAdvice(packet) {
    if (!current || current.sent || current.expired || packet.adviceKey !== current.key || recovery?.status === 'waiting') return;
    current.advice = packet.advice;
    plan(current);
    if (enabled && current.state.canAct && packet.advice?.status === 'unavailable') {
      if (budgetExceeded(packet.advice)) status('waiting', '本次建议计算超时 · 自动保持开启，等待可用建议或下一次行动');
      else pause(`已暂停：${packet.advice.message || '当前建议不可用'}`);
    }
  }
  function onInput() {
    if (enabled && !executing && recovery?.status !== 'waiting' && !current?.expired && !budgetExceeded(current?.advice)) {
      const client = current && window.__mjUnityActions?.snapshot(current.state);
      if (!Number.isFinite(client?.remainingMs) || client.remainingMs > 0)
        pause('已暂停：游戏客户端已提交操作');
    }
    if (current) current.sent = true;
    pending = null;
  }
  function run(key, action, label) {
    const request = submitted = {key, at: now()}; pending = null;
    const accepted = result => {
      if (result?.ok === false) throw Object.assign(new Error(result.reason || '客户端拒绝操作'),
        {recoverable:result.recoverable === true});
    };
    const failed = error => {
      if (!enabled || submitted !== request) return;
      if (error.recoverable) {
        submitted = pending = null;
        status('reconnecting', '连接恢复中 · 等待确认当前状态');
      } else pause(`已暂停：${error.message}`);
    };
    executing = true;
    try {
      const result = action();
      accepted(result);
      if (result?.then) result.then(accepted).catch(failed);
      if (enabled && submitted === request) status('submitted', label);
    } catch (error) {failed(error);} finally {executing = false;}
  }
  function schedule(key, action, label) {
    if (!key) { pause('已暂停：无法确认当前操作标识'); return; }
    if (submitted?.key === key) {
      if (now() - submitted.at > 15000) pause('已暂停：等待客户端确认超时，请检查游戏界面');
      return;
    }
    if (!pending || pending.key !== key) pending = {key, target: now() + delay()};
    if (now() < pending.target) {
      status('delaying', `${label} · ${(Math.max(0, pending.target - now()) / 1000).toFixed(1)} 秒`);
      return;
    }
    run(key, action, `${label} · 等待确认`);
  }
  function tick() {
    if (stopped) return;
    if (cancelling !== null) {
      if (now() - cancelling >= 5000) {
        cancelling = null; status('paused', '自动已关闭；取消匹配未确认，请在游戏中检查');
      } else cancelMatch();
    }
    if (!enabled) return;
    try {
      const lobby = window.__mjLobby?.snapshot(playerCount, roundCount);
      if (!lobby) { pause('已暂停：大厅控制器未就绪'); return; }
      if (lobby.phase !== 'playing') initialRoundSince = null;
      if (lobby.phase === 'blocked') { pause(lobby.message || '已暂停：当前界面不支持自动操作'); return; }
      if (recovery?.status === 'failed') {pause(`已暂停：${recovery.reason}`); return;}
      if (recovery?.status === 'waiting') {
        status('reconnecting', '正在重新连接并恢复牌局 · 自动打牌保持开启'); return;
      }
      if (window.__mjUnityTransport?.isUnity() && window.__mjUnityActions?.snapshot().pending) {
        status('submitted', '等待服务器回应及牌局动作确认'); return;
      }
      if (lobby.clientLoading) {
        clientLoadingSince ??= now();
        if (now() - clientLoadingSince >= 90000) {
          pause('已暂停：90 秒内未识别到支持的游戏客户端，请检查页面加载或客户端兼容性');
          return;
        }
      } else clientLoadingSince = null;
      if (lobby.phase === 'lobby') {
        if (!lobby.actionKey) { pending = null; status('waiting', lobby.message || '等待大厅就绪'); return; }
        schedule(lobby.actionKey, () => window.__mjLobby.start(playerCount, lobby.actionKey, roundCount), lobby.message || '准备匹配');
        return;
      }
      if (lobby.phase === 'settlement') {
        if (!lobby.actionKey) { pending = null; status('settlement', lobby.message || '等待结算动画'); return; }
        schedule(lobby.actionKey, () => window.__mjLobby.finish(lobby.actionKey), lobby.message || '继续对局');
        return;
      }
      pending = null;
      if (lobby.phase !== 'playing') {
        status(lobby.phase, lobby.message || '等待游戏就绪');
        return;
      }
      const turn = current;
      if (!turn || turn.state.phase === 'connected' && turn.state.baseline === null) {
        initialRoundSince ??= now();
        if (now() - initialRoundSince >= 30000)
          status('waiting', '开局信息加载较慢 · 自动保持开启，等待完整牌局信息');
        else status('waiting', '正在进入对局 · 等待开局牌局信息');
        return;
      }
      initialRoundSince = null;
      if (turn.state.phase === 'playing' && (!turn.state.handComplete || !turn.state.historyComplete)) {
        pause('已暂停：牌局基线不完整，需恢复后重新开启'); return;
      }
      if (turn.expired) {status('waiting', '本次操作窗口已结束 · 自动保持开启，等待下一次行动'); return;}
      if (!turn.state.canAct || turn.sent) {
        status('waiting', '对局中 · 等待合法操作窗口');
        return;
      }
      if (turn.advice?.status === 'unavailable' && !budgetExceeded(turn.advice)) {
        pause(`已暂停：${turn.advice.message || '当前建议不可用'}`); return;
      }
      const client = window.__mjUnityActions?.snapshot(turn.state);
      if (!client?.available) { pause('已暂停：游戏操作接口不可用'); return; }
      if (client.recoverable) {status('reconnecting', client.reason || '等待恢复后的牌局状态'); return;}
      if (Number.isFinite(client.remainingMs) && client.remainingMs <= 0) {
        turn.expired = true;
        status('waiting', '本次操作窗口已结束 · 自动保持开启，等待下一次行动'); return;
      }
      if (client.blocked) { pause(`已暂停：${client.reason}`); return; }
      if (!client.canAct) {
        if (client.remainingMs !== null && client.remainingMs <= 350 || now() - turn.startedAt > 10000)
          pause(`已暂停：${client.reason || '操作界面未能及时就绪'}`);
        else status('waiting', client.reason || '等待游戏操作界面');
        return;
      }
      if (!Number.isFinite(client.remainingMs) || client.remainingMs <= 0) {
        pause('已暂停：无法确认剩余操作时间'); return;
      }
      if (!turn.advice || !['ready', 'win'].includes(turn.advice.status)) {
        if (client.remainingMs <= 350) {
          turn.expired = true;
          status('waiting', '本次截止前未取得可用建议 · 自动保持开启，等待下一次行动');
        } else if (budgetExceeded(turn.advice)) status('waiting', '本次建议计算超时 · 自动保持开启，等待可用建议或下一次行动');
        else status('computing', '正在等待行动建议');
        return;
      }
      const wait = Math.min(turn.target - now(), client.remainingMs - 350);
      if (wait > 0) { status('delaying', `按建议操作 · ${(wait / 1000).toFixed(1)} 秒`); return; }
      turn.sent = true; turn.sentAt = now(); handledThreat = turn.threat;
      turn.timing.deadlineLimited = now() < turn.target;
      const choice = turn.advice.best;
      continuation = ['chi','pon'].includes(choice?.action) && choice.followupDiscard && Array.isArray(choice.consumed) ?
        {round:turn.round, step:turn.state.lastStep + 1, type:choice.action === 'chi' ? 0 : 1,
          tile:choice.followupDiscard, tiles:[...choice.consumed, choice.calledTile],
          consumed:[...choice.consumed], fromSeat:choice.fromSeat, confirmed:false} : null;
      run(turn.key, () => window.__mjUnityActions.execute(turn.advice, turn.state), '已提交建议操作');
    } catch (error) { pause(`已暂停：${error.message}`); }
  }
  function manual(event) {
    if (!enabled || !event.isTrusted || event.composedPath().some(element => element.id === 'mj-statistics-overlay')) return;
    pause('已暂停：手动接管');
  }
  const timer = setInterval(tick, 100);
  addEventListener('pointerdown', manual, true);
  addEventListener('keydown', manual, true);
  window.__mjAutoplay = {getStatus, setEnabled, setPlayerCount, setRoundCount, onEvent, onAdvice, onInput, tick,
    stop() {
      setEnabled(false); stopped = true; clearInterval(timer);
      removeEventListener('pointerdown', manual, true); removeEventListener('keydown', manual, true);
    }};
  status('idle', '待机');
})();
