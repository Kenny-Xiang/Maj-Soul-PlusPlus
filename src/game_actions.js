// Client entry points verified against the public 0.11.252.w/code.js on 2026-10-06:
// https://game.maj-soul.com/1/v0.11.252.w/code.js
// ViewPlayer_Me.DoDiscardTile, UI_ChiPengHu, UI_LiQiZiMo and TimeCD.showCD.
(() => {
  'use strict';
  if (location.hostname !== 'game.maj-soul.com' || window.__mjGameActions) return;
  const types = {discard:1, chi:2, pon:3, ankan:4, daiminkan:5, shouminkan:6,
    riichi:7, tsumo:8, ron:9, abort:10, kita:11};
  const enumNames = ['dapai','eat','peng','an_gang','ming_gang','add_gang','liqi','zimo','rong','jiuzhongjiupai','babei'];
  let pending = false;
  const check = (condition, message, blocked = true) => {
    if (!condition) {const error = new Error(message); error.blocked = blocked; throw error;}
  };
  const family = tile => tile.replace(/^0/, '5');
  const sameList = (a, b) => Array.isArray(a) && Array.isArray(b) &&
    a.length === b.length && a.every((value, index) => value === b[index]);
  const sameTiles = (a, b) => Array.isArray(a) && Array.isArray(b) && sameList([...a].sort(), [...b].sort());
  function tileName(tile) {
    const value = tile?.val?.toString();
    check(typeof value === 'string' && /^(?:[0-9][mps]|[1-7]z)$/.test(value), '客户端手牌编码未能核实');
    return value;
  }
  function operations(list) {
    check(Array.isArray(list) && list.length > 0, '没有当前合法操作');
    const seen = new Set();
    return list.map(op => {
      check(Number.isInteger(op.type) && op.type >= 1 && op.type <= 11 && !seen.has(op.type), '当前操作类型不受支持');
      check(Array.isArray(op.combination) && op.combination.every(c => typeof c === 'string'), '当前操作组合不完整');
      seen.add(op.type);
      return {type:op.type, combination:[...op.combination]};
    }).sort((a, b) => a.type - b.type);
  }
  function snapshot(state) {
    const desktop = window.view?.DesktopMgr?.Inst;
    const role = desktop?.mainrole, timer = window.uiscript?.UI_DesktopInfo?.Inst?._timecd;
    const available = !!(desktop && role && timer && typeof window.app?.NetAgent?.sendReq2MJ === 'function');
    const inGame = !!(desktop?.active && desktop.mode === window.view?.EMJMode?.play);
    let remainingMs = null, reason = '', blocked = false;
    if (timer?.me?.visible === true && [timer._start, timer._fix, timer._add, window.Laya?.timer?.currTimer].every(Number.isFinite)) {
      remainingMs = Math.max(0, (timer._fix + timer._add) * 1000 - (window.Laya.timer.currTimer - timer._start));
    }
    try {
      check(available, '游戏操作接口尚未就绪', false);
      check(!desktop.active || desktop.mode === window.view?.EMJMode?.play, '自动操作不支持牌谱或观战模式');
      check(inGame && desktop.gameing === true, '等待正在进行的对局', false);
      check(!desktop.duringReconnect && !desktop.timestoped, '等待重连或暂停结束', false);
      check(!pending, '等待上次操作的服务端回执', false);
      check(desktop.game_config?.category === 2 && [1,2,11,12].includes(desktop.game_config?.mode?.mode), '自动操作仅支持普通段位场');
      check(!['auto_hule','auto_nofulu','auto_moqie','auto_babei'].some(key => desktop[key]), '请先关闭游戏内置的自动和牌、不鸣牌、摸切和拔北');
      check(desktop.operation_showing === true && desktop.oplist?.length > 0, '等待客户端显示本次操作', false);
      check(remainingMs !== null && remainingMs > 0, '等待有效的操作倒计时', false);
      check(typeof role.needCheckMouse === 'function' && role.needCheckMouse(), '客户端当前有阻挡操作的窗口');
      check(!role.mouse_downed && !role.during_drag && !role.during_anpai && !role.during_anpailiqi, '等待手动操作结束', false);
      check(enumNames.every((name, index) => window.mjcore?.E_PlayOperation?.[name] === index + 1), '客户端操作定义已变化');
      const offered = operations(desktop.oplist);
      if (state) {
        check(state.phase === 'playing' && state.canAct === true && state.handComplete && state.historyComplete, '牌局基线或合法操作窗口已失效');
        check(Number.isInteger(state.lastStep) && state.lastStep === desktop.current_step, '等待客户端处理当前牌局动作', false);
        check(state.selfSeat === desktop.seat && state.playerCount === desktop.player_count, '客户端座位或人数与建议不一致');
        check(state.round && state.round.chang === desktop.index_change && state.round.ju === desktop.index_ju && state.round.ben === desktop.index_ben, '客户端局数与建议不一致');
        check(Array.isArray(role.hand) && sameTiles(role.hand.map(tileName), state.hand), '客户端手牌与建议不一致');
        check(JSON.stringify(offered) === JSON.stringify(operations(state.operationDetails)) &&
          sameTiles(offered.map(op => op.type), state.operations), '客户端合法操作与建议不一致');
      }
    } catch (error) {reason = error.message; blocked = error.blocked !== false;}
    return {available, inGame, canAct:!reason, blocked, remainingMs,
      clientStep:Number.isInteger(desktop?.current_step) ? desktop.current_step : null, reason};
  }
  function execute(advice, state) {
    check(state && typeof state === 'object', '缺少当前牌局状态');
    const current = snapshot(state);
    check(current.canAct, current.reason);
    check(advice?.status === 'ready' || advice?.status === 'win', '当前建议不可执行');
    const choice = advice.status === 'win' ? {action:advice.action} : advice.best;
    check(choice && (choice.action in types || choice.action === 'pass'), '建议动作不受支持');
    check(advice.status !== 'win' || ['tsumo','ron'].includes(choice.action), '和牌建议格式无效');
    const desktop = window.view.DesktopMgr.Inst, role = desktop.mainrole;
    const ui = window.uiscript, agent = window.app.NetAgent;
    const type = types[choice.action], offered = operations(desktop.oplist);
    const detail = offered.find(op => op.type === type);
    check(choice.action === 'pass' || detail, '服务端未许可该动作');
    const reaction = offered.some(op => [2,3,5,9].includes(op.type));
    const method = reaction ? 'inputChiPengGang' : 'inputOperation';
    const expected = {}, action = choice.action;
    let run;
    const requireMethod = (object, name) => check(typeof object?.[name] === 'function', `客户端操作入口 ${name} 不可用`);
    const button = (object, name) => {
      check(object?.enable === true, '客户端动作面板尚未就绪');
      requireMethod(object, name);
      return () => object[name]();
    };
    function comboIndex(consumed) {
      check(Array.isArray(consumed) && consumed.length > 0, '建议动作缺少消耗牌');
      const matches = detail.combination.map((combo, index) => sameTiles(combo.split('|'), consumed) ? index : -1).filter(index => index >= 0);
      check(matches.length === 1, '建议动作与服务端组合不能唯一匹配');
      return matches[0];
    }
    function owns(consumed) {
      const hand = [...state.hand];
      for (const tile of consumed) {
        const index = hand.indexOf(tile);
        check(index >= 0, '建议动作消耗了不存在的手牌');
        hand.splice(index, 1);
      }
    }
    if (action === 'discard' || action === 'riichi') {
      check(!reaction && state.canDiscard && role.can_discard && !role.during_liqi, '当前不是可执行弃牌窗口');
      check(typeof choice.tile === 'string' && state.hand.includes(choice.tile), '建议弃牌不在手中');
      check(!(state.forbiddenDiscards || []).some(tile => family(tile) === family(choice.tile)), '建议弃牌违反食替限制');
      const last = role.last_tile;
      const tile = last && tileName(last) === choice.tile ? last : role.hand.find(tile => tileName(tile) === choice.tile);
      check(tile?.valid === true && !tile.val.baida && tile.is_open !== true, '建议弃牌当前不可选');
      check(!state.riichi?.[state.selfSeat] || tile === last && choice.tile === state.lastDraw, '立直后只能摸切本次摸牌');
      requireMethod(role, 'setChoosePai'); requireMethod(role, 'DoDiscardTile'); requireMethod(role, 'resetMouseState');
      if (action === 'riichi') {
        check(detail.combination.some(tile => family(tile) === family(choice.tile)), '建议立直弃牌未经服务端许可');
        check(sameList(ui.UI_LiQiZiMo?.Inst?.liqi_data, detail.combination), '客户端立直选项已变化');
        button(ui.UI_LiQiZiMo.Inst, 'onBtn_Liqi');
      }
      Object.assign(expected, {type, tile:choice.tile, moqie:tile === last, tile_state:0});
      run = () => {
        if (action === 'riichi') ui.UI_LiQiZiMo.Inst.onBtn_Liqi();
        check(tile.valid === true, '客户端未接受该立直弃牌');
        role.setChoosePai(tile, false);
        check(role._choose_pai === tile, '客户端未选中建议弃牌');
        role.DoDiscardTile();
        role.resetMouseState();
      };
    } else if (['chi','pon','daiminkan'].includes(action)) {
      const last = state.lastAction;
      check(reaction && last?.name === 'ActionDiscardTile' && last.step === state.lastStep &&
        last.seat === choice.fromSeat && last.tile === choice.calledTile && last.seat !== state.selfSeat,
      '鸣牌目标已失效');
      check(desktop.lastpai_seat === last.seat && tileName(desktop.lastqipai) === last.tile, '客户端鸣牌目标与建议不一致');
      owns(choice.consumed);
      const index = comboIndex(choice.consumed), panel = ui.UI_ChiPengHu?.Inst;
      Object.assign(expected, {type, index});
      if (action === 'daiminkan') {
        check(index === 0 && detail.combination.length === 1, '大明杠组合不受支持');
        run = button(panel, 'onBtn_Gang');
      } else {
        const list = panel?._data?.[action === 'chi' ? 'chi' : 'peng'];
        check(sameList(list, detail.combination), '客户端鸣牌组合已变化');
        const select = button(panel, action === 'chi' ? 'onBtn_Chi' : 'onBtn_Peng');
        if (list.length > 1) requireMethod(panel, 'onClickDetail');
        run = () => {select(); if (list.length > 1) panel.onClickDetail(index);};
      }
    } else if (action === 'ankan' || action === 'shouminkan') {
      check(!reaction, '当前不是自己的杠牌窗口');
      owns(choice.consumed);
      let consumed = choice.consumed;
      if (action === 'shouminkan') {
        const meld = state.melds?.[state.selfSeat]?.[choice.meldIndex];
        check(meld?.type === 1 && Array.isArray(meld.tiles) && meld.tiles.length === 3, '加杠缺少对应碰牌');
        consumed = [...meld.tiles, ...consumed];
      }
      const index = comboIndex(consumed), panel = ui.UI_LiQiZiMo?.Inst;
      const added = offered.find(op => op.type === 6)?.combination || [];
      const concealed = offered.find(op => op.type === 4)?.combination || [];
      check(sameList(panel?.com_add_gang, added) && sameList(panel?.com_an_gang, concealed), '客户端杠牌组合已变化');
      button(panel, 'onClickDetail');
      Object.assign(expected, {type, index});
      run = () => panel.onClickDetail(index + (action === 'ankan' ? added.length : 0));
    } else if (action === 'pass') {
      check(!state.canDiscard && !role.can_discard, '不能用跳过代替当前弃牌');
      check(reaction || offered.some(op => [4,6,7,8,10,11].includes(op.type)), '当前没有可跳过操作');
      expected.cancel_operation = true;
      run = button(reaction ? ui.UI_ChiPengHu?.Inst : ui.UI_LiQiZiMo?.Inst, 'onBtn_Cancel');
    } else {
      check((action === 'ron') === reaction, '和牌或自摸操作窗口不一致');
      expected.type = type;
      if (action === 'kita') {
        check(state.playerCount === 3 && state.hand.includes('4z'), '拔北需要三麻及手中北牌');
        expected.moqie = !!(role.last_tile && tileName(role.last_tile) === '4z');
      } else expected.index = 0;
      const names = {ron:'onBtn_Hu', tsumo:'onBtn_Zimo', kita:'onBtn_BaBei', abort:'onBtn_Liuju'};
      run = button(action === 'ron' ? ui.UI_ChiPengHu?.Inst : ui.UI_LiQiZiMo?.Inst, names[action]);
    }
    // The real UI entry points own all game and visual updates. Observe their one
    // request only during this synchronous call, then immediately restore NetAgent.
    return new Promise((resolve, reject) => {
      const original = agent.sendReq2MJ;
      let sent = false, finished = false, invoking = true, replied = false, replyError;
      const finish = error => {
        if (finished) return;
        finished = true; pending = false; clearTimeout(timeout);
        if (error) reject(error); else resolve({action, method, ...expected});
      };
      const timeout = setTimeout(() => finish(new Error('操作回执超时；已停止自动操作，请核对牌局')), 10000);
      pending = true;
      try {
        agent.sendReq2MJ = function(service, actualMethod, payload, callback) {
          check(!sent && service === 'FastTest' && actualMethod === method, '客户端请求入口与已核实动作不一致');
          check(payload && Object.entries(expected).every(([key, value]) => payload[key] === value) &&
            Object.keys(payload).every(key => key in expected || key === 'timeuse'), '客户端请求内容与建议不一致');
          if ('timeuse' in payload) check(Number.isFinite(payload.timeuse) && payload.timeuse >= 0, '客户端操作用时无效');
          sent = true;
          return original.call(this, service, actualMethod, payload, (error, response) => {
            try {
              if (typeof callback === 'function') callback(error, response);
              replyError = error || response?.error?.code ? new Error(`游戏拒绝操作：${error || response.error.code}`) : null;
              replied = true;
              if (!invoking) finish(replyError);
            } catch (failure) {finish(failure);}
          });
        };
        run();
        check(sent, '客户端没有提交预期操作');
      } catch (error) {finish(error);}
      finally {agent.sendReq2MJ = original; invoking = false;}
      if (replied) finish(replyError);
    });
  }
  window.__mjGameActions = {snapshot, execute};
})();
