const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const ORIGIN = 'http://127.0.0.1:17361';
const phaseNames = {waiting:'等待对局', connected:'发现牌局连接，等待动作', playing:'正在对局',
  between_rounds:'小局结束，等待下一局', ended:'对局结束', disconnected:'牌局连接中断', stopped:'监听已停止'};
const clean = x => String(x ?? '').replace(/[\x00-\x1f\x7f-\x9f]/g, '').slice(0, 500);
const tile = t => /^([0-9])([mpsz])$/.test(t || '') ? (t[1] === 'z' ? ['','东','南','西','北','白','发','中'][Number(t[0])] :
  `${t[0] === '0' ? '赤五' : t[0]}${{m:'万',p:'筒',s:'索'}[t[1]]}`) : clean(t);
const tileList = a => (a || []).map(tile).join(' ') || '—';
function formatTurn(e) {
  const s = e.state, counts = new Map();
  const count = t => {if (/^[0-9][mpsz]$/.test(t)) {const key = t.replace(/^0/,'5'); counts.set(key, (counts.get(key) || 0) + 1);}};
  if (s.handComplete) s.hand.forEach(count);
  s.rivers.forEach(r => r.filter(x => !x.called).forEach(x => count(x.tile)));
  s.melds.forEach(ms => ms.forEach(m => m.tiles.forEach(count)));
  s.doras.forEach(count);
  s.north.forEach(n => {for (let i = 0; i < n; i++) count('4z');});
  const time = new Date(e.time).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false});
  const lines = [`\n${'═'.repeat(60)}`, `${time}  轮到你出牌 · 第 ${e.turnNumber} 次输出 · 动作 #${e.step}`,
    `状态：${phaseNames[s.phase] || clean(s.phase)}  本机座位：${s.selfSeat ?? '待确认'}  剩余牌：${s.left ?? '未知'}`];
  if (s.round) lines.push(`局况：${['东','南','西','北'][s.round.chang] || s.round.chang}${s.round.ju + 1}局 ${s.round.ben}本场`);
  lines.push(s.handComplete ? `本人手牌：${tileList(s.hand)}` : `本人完整手牌：尚未取得${s.lastDraw ? `；最近摸牌 ${tile(s.lastDraw)}` : ''}`);
  if (s.baseline === 'snapshot_unverified') lines.push(`待核对快照：${tileList(s.hand)}`);
  lines.push(`宝牌指示：${tileList(s.doras)}  分数：${s.scores.length ? s.scores.map(x => x ?? '?').join(' / ') : '未知'}`);
  s.rivers.slice(0, s.playerCount).forEach((r, i) => {
    const melds = s.melds[i].map(m => tileList(m.tiles)).join(' / ') || '—';
    lines.push(`座位${i} 弃牌(${r.length})：${r.map(d => tile(d.tile) + (d.riichi ? '[立直]' : '') + (d.called ? '[被鸣]' : '')).join(' ') || '—'}`);
    lines.push(`      副露：${melds}  拔北：${s.north[i]}`);
  });
  lines.push(`已知牌计数${s.historyComplete && s.handComplete ? '' : '（仅已观察部分）'}：${[...counts].sort().map(([t,n]) => `${tile(t)}×${n}`).join(' ') || '—'}`);
  lines.push(`完整性：${s.handComplete ? '已取得手牌基线' : '缺少完整手牌'}；${s.historyComplete ? '本小局动作连续' : '历史不完整或待核对'}`);
  if (s.warning) lines.push(`说明：${clean(s.warning)}`);
  lines.push(`触发：${clean(e.trigger)} · 入站 ${e.statistics.received} 条 · 解析错误 ${e.statistics.errors} 次`);
  return lines.join('\n');
}

function start() {
  const folder = path.join(__dirname, 'logs'); fs.mkdirSync(folder, {recursive:true});
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const logPath = path.join(folder, `${stamp}.jsonl`);
  const outputPath = path.join(folder, `${stamp}.txt`);
  let lastSeen = 0, connected = false;
  const seen = new Map();
  const write = value => {console.log(value); fs.appendFileSync(outputPath, value + '\n');};
  const server = http.createServer((req, res) => {
    const origin = req.headers.origin;
    if (origin && origin !== ORIGIN) {res.writeHead(403); return res.end('Origin rejected');}
    res.setHeader('Access-Control-Allow-Origin', ORIGIN);
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    res.setHeader('Access-Control-Allow-Private-Network', 'true');
    res.setHeader('Cache-Control', 'no-store');
    if (req.method === 'OPTIONS') {res.writeHead(204); return res.end();}
    if (req.method === 'GET' && req.url === '/health') {res.setHeader('Content-Type','application/json'); return res.end('{"ok":true,"version":"2.0.0","transport":"window-message-relay"}');}
    if (req.method === 'GET' && ['/relay','/relay.js'].includes(req.url)) {
      const script = req.url.endsWith('.js');
      res.setHeader('Content-Type', script ? 'application/javascript; charset=utf-8' : 'text/html; charset=utf-8');
      res.setHeader('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'");
      return res.end(fs.readFileSync(path.join(__dirname, script ? 'relay.js' : 'relay.html')));
    }
    if (req.method !== 'POST' || req.url !== '/events') {res.writeHead(404); return res.end();}
    let raw = '', length = 0;
    req.on('data', chunk => {length += chunk.length; if (length > 1024 * 1024) req.destroy(); else raw += chunk;});
    req.on('end', () => {
      try {
        const events = JSON.parse(raw);
        if (!Array.isArray(events) || events.length > 20) throw new Error('invalid batch');
        for (const e of events) {
          if (typeof e.session !== 'string' || !Number.isSafeInteger(e.serial) || !['heartbeat','status','error','turn'].includes(e.kind)) throw new Error('invalid event');
          if (e.kind === 'turn' && (!e.state || !Array.isArray(e.state.rivers) || !e.statistics)) throw new Error('invalid state');
        }
        lastSeen = Date.now();
        if (!connected) {connected = true; write('已连接雀魂页面。等待本机出牌机会……');}
        for (const e of events) {
          if (e.serial <= (seen.get(e.session) || 0)) continue;
          if (e.kind === 'turn') write(formatTurn(e));
          else if (e.kind !== 'heartbeat') write(`[${phaseNames[e.phase] || e.kind}] ${clean(e.message)}`);
          if (e.kind !== 'heartbeat') fs.appendFileSync(logPath, JSON.stringify(e) + '\n');
          seen.set(e.session, e.serial);
          if (seen.size > 100) seen.delete(seen.keys().next().value);
        }
        res.end('ok');
      } catch (error) {res.writeHead(400); res.end('Invalid event');}
    });
  });
  const timer = setInterval(() => {
    if (connected && Date.now() - lastSeen > 35000) {connected = false; write('页面采集器暂时没有响应：可能页面被挂起或已关闭。等待恢复连接……');}
  }, 5000);
  server.on('error', error => {console.error(`启动失败：${error.message}`); clearInterval(timer); process.exitCode = 1;});
  server.listen(17361, '127.0.0.1', () => {
    fs.writeFileSync(path.join(__dirname,'.local/current-log-path'), outputPath);
    write('雀魂对局统计 · 每次服务器提供本机出牌操作时输出一次');
    write('本地接收端：http://127.0.0.1:17361 · 通过本地中转窗口接收，无需证书');
    write(`文本记录：${outputPath}\n结构化记录：${logPath}\n按 Ctrl+C 停止终端接收。`);
  });
  process.once('SIGINT', () => {clearInterval(timer); server.close(); process.exit(0);});
  return server;
}
if (require.main === module) start();
module.exports = {formatTurn, start};
