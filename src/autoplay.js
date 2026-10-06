// Own the user's automation intent; adapters perform one verified client action.
(() => {
  if (location.hostname !== 'game.maj-soul.com' || window.__mjAutoplay) return;
  let enabled = false, playerCount = 4, phase = 'idle', message = '待机';
  let current = null, pending = null, submitted = null, executing = false, stopped = false, cancelling = null;
  let lastStatus = '';
  let lastLogState = '';
  let clientLoadingSince = null;
  const now = () => performance.now();
  const delay = () => 1000 + Math.random() * 4000;
  function status(nextPhase, nextMessage) {
    phase = nextPhase; message = nextMessage;
    const value = getStatus(), signature = JSON.stringify(value);
    if (signature !== lastStatus) {
      lastStatus = signature;
      window.__mjStatsOverlay?.updateAutomation?.(value);
    }
    const logState = JSON.stringify([enabled, playerCount, phase]);
    if (logState !== lastLogState) {
      lastLogState = logState; window.__mjMonitor?.reportAutomation?.(value);
    }
  }
  function getStatus() { return {enabled, playerCount, phase, message}; }
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
    enabled = false; pending = null; clientLoadingSince = null;
    status('paused', reason);
    if (wasEnabled) cancelMatch();
  }
  function setEnabled(value) {
    if (stopped) return;
    if (!value) {
      const wasEnabled = enabled;
      enabled = false; pending = null; clientLoadingSince = null;
      status('idle', '已关闭 · 手动操作');
      if (wasEnabled) cancelMatch();
      return;
    }
    if (enabled) return;
    if (cancelling !== null) { status('waiting', '正在取消上一轮匹配，请稍后开启'); return; }
    if (window.__mjUnityTransport?.isUnity() && window.__mjUnityActions?.snapshot().pending) {
      status('waiting', '等待上次操作确认，请稍后开启'); return;
    }
    enabled = true; pending = null; submitted = null; clientLoadingSince = null;
    if (current && !current.sent) current.target = now() + delay();
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
  function onEvent(event) {
    if (stopped || !['turn', 'status', 'error'].includes(event.kind)) return;
    current = null; pending = null;
    if (event.kind === 'turn') {
      current = {key: `${event.session}:${event.serial}`, state: event.state,
        target: now() + delay(), advice: null, sent: false};
      if (enabled && event.state.phase === 'playing' &&
          (!event.state.handComplete || !event.state.historyComplete)) {
        pause('已暂停：牌局基线不完整，需恢复后重新开启');
      }
    } else if (enabled && (event.kind === 'error' || ['disconnected', 'stopped'].includes(event.phase))) {
      pause('已暂停：连接或牌局解析异常');
    }
  }
  function onAdvice(packet) {
    if (!current || current.sent || packet.adviceKey !== current.key) return;
    current.advice = packet.advice;
    if (enabled && current.state.canAct && packet.advice?.status === 'unavailable') {
      pause(`已暂停：${packet.advice.message || '当前建议不可用'}`);
    }
  }
  function onInput() {
    if (enabled && !executing) pause('已暂停：游戏客户端已提交操作');
    if (current) current.sent = true;
    pending = null;
  }
  function run(key, action, label) {
    const request = submitted = {key, at: now()}; pending = null;
    executing = true;
    try {
      const result = action();
      if (result?.ok === false) throw new Error(result.reason || '客户端拒绝操作');
      if (result?.then) result.then(value => {
        if (value?.ok === false) throw new Error(value.reason || '客户端拒绝操作');
      }).catch(error => {
        if (enabled && submitted === request) pause(`已暂停：${error.message}`);
      });
      if (enabled) status('submitted', label);
    } catch (error) {
      pause(`已暂停：${error.message}`);
    } finally { executing = false; }
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
      const lobby = window.__mjLobby?.snapshot(playerCount);
      if (!lobby) { pause('已暂停：大厅控制器未就绪'); return; }
      if (lobby.phase === 'blocked') { pause(lobby.message || '已暂停：当前界面不支持自动操作'); return; }
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
        schedule(lobby.actionKey, () => window.__mjLobby.start(playerCount, lobby.actionKey), lobby.message || '准备匹配');
        return;
      }
      if (lobby.phase === 'settlement') {
        if (!lobby.actionKey) { pending = null; status('waiting', lobby.message || '等待结算动画'); return; }
        schedule(lobby.actionKey, () => window.__mjLobby.finish(lobby.actionKey), lobby.message || '继续对局');
        return;
      }
      pending = null;
      if (lobby.phase !== 'playing') {
        status(lobby.phase, lobby.message || '等待游戏就绪');
        return;
      }
      const turn = current;
      if (!turn || !turn.state.canAct || turn.sent) {
        status('waiting', '对局中 · 等待合法操作窗口');
        return;
      }
      const client = window.__mjUnityActions?.snapshot(turn.state);
      if (!client?.available) { pause('已暂停：游戏操作接口不可用'); return; }
      if (client.blocked) { pause(`已暂停：${client.reason}`); return; }
      if (!client.canAct) {
        if (client.remainingMs !== null && client.remainingMs <= 350 || now() - turn.target > 10000)
          pause(`已暂停：${client.reason || '操作界面未能及时就绪'}`);
        else status('waiting', client.reason || '等待游戏操作界面');
        return;
      }
      if (!Number.isFinite(client.remainingMs) || client.remainingMs <= 0) {
        pause('已暂停：无法确认剩余操作时间'); return;
      }
      if (!turn.advice || !['ready', 'win'].includes(turn.advice.status)) {
        if (turn.advice?.status === 'unavailable') pause(`已暂停：${turn.advice.message || '当前建议不可用'}`);
        else if (client.remainingMs <= 350) pause('已暂停：截止前未取得可执行建议');
        else status('computing', '正在等待行动建议');
        return;
      }
      const wait = Math.min(turn.target - now(), client.remainingMs - 350);
      if (wait > 0) { status('delaying', `按建议操作 · ${(wait / 1000).toFixed(1)} 秒`); return; }
      turn.sent = true;
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
  window.__mjAutoplay = {getStatus, setEnabled, setPlayerCount, onEvent, onAdvice, onInput,
    stop() {
      setEnabled(false); stopped = true; clearInterval(timer);
      removeEventListener('pointerdown', manual, true); removeEventListener('keydown', manual, true);
    }};
  status('idle', '待机');
})();
