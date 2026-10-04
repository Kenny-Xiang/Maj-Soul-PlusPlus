'use strict';
const gameOrigin = 'https://game.maj-soul.com';
const channel = location.hash.slice(1);
const statusLine = document.getElementById('status');
const inProgress = new Set();
const completed = new Set();
let linked = false, forwarded = 0;
function ready() {
  if (window.opener && channel) window.opener.postMessage({type:'mj-relay-ready', channel}, gameOrigin);
  else statusLine.textContent = '请从雀魂页面中的“连接终端”按钮打开此窗口。';
}
const handshakeTimer = setInterval(() => {if (!linked) ready();}, 2000);
window.addEventListener('message', async event => {
  if (event.origin !== gameOrigin || event.source !== window.opener) return;
  const packet = event.data;
  if (!packet || packet.type !== 'mj-relay-batch' || packet.channel !== channel ||
      typeof packet.batchId !== 'string' || !Array.isArray(packet.events) || packet.events.length > 20) return;
  const acknowledge = () => event.source.postMessage({type:'mj-relay-ack', channel, batchId:packet.batchId}, gameOrigin);
  if (completed.has(packet.batchId)) {acknowledge(); return;}
  if (inProgress.has(packet.batchId)) return;
  inProgress.add(packet.batchId);
  linked = true;
  try {
    const response = await fetch('/events', {method:'POST', credentials:'omit',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(packet.events), signal:AbortSignal.timeout(4000)});
    if (!response.ok) throw new Error(`接收端响应 ${response.status}`);
    completed.add(packet.batchId);
    if (completed.size > 500) completed.delete(completed.values().next().value);
    forwarded += packet.events.filter(e => e.kind === 'turn').length;
    statusLine.textContent = `连接正常，已转交 ${forwarded} 次出牌统计。`;
    acknowledge();
  } catch (error) {
    statusLine.textContent = `等待本机终端接收端恢复：${error.message}`;
  } finally {inProgress.delete(packet.batchId);}
});
ready();
