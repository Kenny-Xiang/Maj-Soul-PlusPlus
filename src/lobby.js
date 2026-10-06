// Client UI adapter verified against https://game.maj-soul.com/1/v0.11.252.w/code.js.
// Keep the client's session, matching notifications and settlement transitions intact.
(() => {
  if (location.hostname !== 'game.maj-soul.com' || window.__mjLobby) return;
  let ownedMode = null, refreshNeeded = true, refreshing = null, generation = 0;
  let accountId = null, connected = false;
  let endVisible = false, endGeneration = 0;
  const rooms = new Map([[1, '铜之间'], [2, '银之间'], [3, '金之间'], [4, '玉之间'], [6, '王座间']]);
  const roomRows = new Map([[1, 1], [2, 4], [3, 7], [4, 10], [6, 15]]);
  const result = (phase, message, extra = {}) => ({phase, message, ...extra});
  const client = () => ({manager:window.GameMgr?.Inst, ui:window.uiscript,
    net:window.game?.LobbyNetMgr?.Inst, desktop:window.view?.DesktopMgr?.Inst,
    modes:window.cfg?.desktop?.matchmode});
  const enabled = value => value?.enable === true;

  function syncAccount(manager, net) {
    const nextId = manager?.logined && Number.isInteger(manager.account_id) &&
      manager.account_id > 0 && manager.account_id <= 0xffffffff ? manager.account_id : null;
    const nextConnected = net?.isOK === true;
    if (accountId !== nextId || connected !== nextConnected) {
      if (accountId !== nextId) {ownedMode = null; endVisible = false;}
      accountId = nextId; connected = nextConnected;
      generation++; refreshNeeded = true; refreshing = null;
    }
  }

  function chooseMode(playerCount, account, modes) {
    const rank = account?.[playerCount === 3 ? 'level3' : 'level']?.id;
    if (![3, 4].includes(playerCount) || !Number.isInteger(rank) ||
        Math.floor(rank / 10000) !== (playerCount === 3 ? 2 : 1) ||
        !Number.isInteger(account?.gold) || account.gold < 0 || typeof modes?.forEach !== 'function') return null;
    const rows = [], candidates = [];
    modes.forEach(mode => rows.push(mode));
    for (const mode of rows) {
      // The same limits are read by UI_Lobby.page_rank / page_east_north.
      // Room availability comes from the room's representative row, not its East/South child.
      const room = rows.find(row => row.id === roomRows.get(mode.room));
      if (!Number.isInteger(mode.id) || mode.mode !== (playerCount === 3 ? 11 : 1) ||
          !rooms.has(mode.room) || room?.is_open !== 1 ||
          !Number.isInteger(mode.level_limit) || !Number.isInteger(mode.level_limit_ceil) ||
          !Number.isInteger(mode.glimit_floor) || !Number.isInteger(mode.glimit_ceil)) continue;
      if (mode.level_limit && rank < mode.level_limit ||
          mode.level_limit_ceil && rank > mode.level_limit_ceil ||
          account.gold < mode.glimit_floor || mode.glimit_ceil !== -1 && account.gold > mode.glimit_ceil) continue;
      candidates.push(mode);
    }
    return candidates.sort((a, b) => b.room - a.room || a.id - b.id)[0] || null;
  }

  function snapshot(playerCount = 4) {
    const {manager, ui, net, desktop, modes} = client();
    syncAccount(manager, net);
    if (!manager || !ui) return result('loading', '等待游戏客户端加载');
    if (!manager.logined) return result('login', '请先在游戏窗口登录');
    if (accountId === null) return result('blocked', '无法确认当前账号，请重新登录');
    const end = ui.UI_GameEnd?.Inst, nowEnd = enabled(end);
    if (nowEnd && !endVisible) endGeneration++;
    endVisible = nowEnd;
    if (nowEnd || manager.ingame) {refreshNeeded = true; ownedMode = null;}
    const blockers = ['UI_SecondConfirm', 'UI_Popout', 'UI_Restart', 'UI_Force_Update',
      'UI_AnotherLogin', 'UI_Disconnect', 'UI_Maintain_Notice', 'UI_Freeze', 'UI_ShiMingRenZheng'];
    if (blockers.some(name => enabled(ui[name]?.Inst)) || ui.UIMgr?.Inst?._error_root?.numChildren > 0)
      return result('blocked', '游戏提示需要处理，请处理后重新开启自动打牌');
    if (nowEnd) {
      if (desktop?.mode !== window.view?.EMJMode?.play)
        return result('blocked', '当前不是正在进行的对局');
      const ready = !end.locking && end.btns?.visible === true &&
        end.btn_next?.visible === true && end.btn_next.disabled !== true && typeof end.onConfirm === 'function';
      return result('settlement', ready ? '准备继续结算' : '等待结算动画', ready ? {
        actionKey:`end:${endGeneration}:${end.step}:${end.rewardIndex}`, action:'finish',
      } : {});
    }
    if (manager.ingame) return result('playing', '对局进行中');
    if (enabled(ui.UI_PiPeiChengGong?.Inst)) return result('matching', '匹配成功，等待进入对局');
    const queue = ui.UI_PiPeiYuYue?.Inst;
    if (queue?.current_count > 0 || enabled(ui.UI_PiPei?.Inst))
      return result('matching', '正在匹配', {modeId:ownedMode});
    if (ownedMode !== null) return result('blocked', '匹配未成功或已被取消，请重新开启自动打牌');
    if (!net?.isOK || enabled(ui.UI_Loading?.Inst) || enabled(ui.UI_Reconnect?.Inst) || refreshing)
      return result('loading', refreshing ? '正在刷新段位与金币' : '等待连接或场景加载');
    if (manager.account_data?.room_id || ui.UI_WaitingRoom?.Inst?.inRoom || ui.UI_Match_Room?.Inst?.inRoom)
      return result('blocked', '请先退出当前房间并返回大厅');
    if (!enabled(ui.UI_Lobby?.Inst) || ui.UI_Lobby.Inst.locking)
      return result('loading', '等待返回大厅');
    if (typeof queue?.addMatch !== 'function' || typeof queue?.cancelPiPei !== 'function' ||
        typeof queue?.getMatchID !== 'function' || typeof queue?.matchLocking !== 'function')
      return result('blocked', '当前客户端的匹配接口未识别');
    if (refreshNeeded) {
      if (typeof manager.updateAccountInfo !== 'function' || typeof window.Laya?.Handler?.create !== 'function')
        return result('blocked', '当前客户端的账号刷新接口未识别');
      return result('lobby', '准备刷新段位与金币', {actionKey:`refresh:${accountId}:${generation}`, action:'refresh'});
    }
    const mode = chooseMode(playerCount, manager.account_data, modes);
    if (!mode) return result('blocked', '当前段位、金币或开放状态下没有可进入的东风场');
    const rank = manager.account_data[playerCount === 3 ? 'level3' : 'level'].id;
    return result('lobby', `准备匹配${rooms.get(mode.room)} · ${playerCount === 3 ? '三麻' : '四麻'}东风`, {
      actionKey:`match:${accountId}:${generation}:${playerCount}:${mode.id}:${rank}:${manager.account_data.gold}`,
      action:'match', modeId:mode.id, roomName:rooms.get(mode.room),
    });
  }

  function start(playerCount = 4, actionKey) {
    const state = snapshot(playerCount), {manager, ui} = client();
    if (state.phase !== 'lobby' || !actionKey || state.actionKey !== actionKey)
      return {ok:false, reason:'大厅状态已经变化，取消本次操作'};
    if (state.action === 'refresh') {
      const request = refreshing = {}, expectedAccount = accountId, expectedGeneration = generation;
      const before = manager.account_refresh_time;
      return new Promise(resolve => {
        let finished = false;
        const done = value => {
          if (finished) return;
          finished = true;
          if (refreshing === request) refreshing = null;
          clearTimeout(timer); resolve(value);
        };
        const timer = setTimeout(() => done({ok:false, reason:'刷新账号状态超时'}), 10000);
        try {
          manager.updateAccountInfo(window.Laya.Handler.create(null, () => {
            if (finished) return;
            const live = client(); syncAccount(live.manager, live.net);
            if (accountId !== expectedAccount || generation !== expectedGeneration || !connected)
              return done({ok:false, reason:'账号或连接已变化，取消旧账号刷新'});
            if (manager.account_refresh_time === before) return done({ok:false, reason:'未能刷新段位与金币'});
            refreshNeeded = false; generation++; done({ok:true});
          }));
        } catch (error) {done({ok:false, reason:`账号刷新失败：${error.message}`});}
      });
    }
    // addMatch synchronously records the queued mode and uses the existing notification handlers.
    ownedMode = state.modeId;
    try {
      if (!ui.UI_PiPeiYuYue.Inst.addMatch(state.modeId)) {ownedMode = null; return {ok:false, reason:'客户端拒绝开始匹配'};}
      return {ok:true, modeId:state.modeId};
    } catch (error) {return {ok:false, reason:`开始匹配失败：${error.message}`};}
  }

  function finish(actionKey) {
    const state = snapshot();
    if (state.phase !== 'settlement' || !actionKey || state.actionKey !== actionKey)
      return {ok:false, reason:'结算状态已经变化，取消本次操作'};
    client().ui.UI_GameEnd.Inst.onConfirm();
    return {ok:true};
  }

  function cancel() {
    const {manager, ui, net} = client(), queue = ui?.UI_PiPeiYuYue?.Inst;
    syncAccount(manager, net);
    if (ownedMode === null) return {ok:true};
    if (manager?.ingame || enabled(ui?.UI_PiPeiChengGong?.Inst)) {ownedMode = null; return {ok:true};}
    if (!connected) return {ok:true, pending:true};
    if (typeof queue?.getMatchID !== 'function' || typeof queue?.cancelPiPei !== 'function' ||
        typeof queue?.matchLocking !== 'function') return {ok:false, reason:'当前客户端无法取消匹配'};
    if (queue.getMatchID(ownedMode) === -1) {ownedMode = null; return {ok:true};}
    if (!queue.matchLocking(ownedMode)) queue.cancelPiPei(ownedMode);
    return {ok:true, pending:true};
  }

  window.__mjLobby = {snapshot, start, finish, cancel};
})();
