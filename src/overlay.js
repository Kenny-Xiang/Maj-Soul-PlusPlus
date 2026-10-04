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
    .heading { display:flex; justify-content:space-between; gap:16px; margin-bottom:6px; font-weight:600; }
    .label { color:#b9d9f9; white-space:nowrap; }
    .caption { font-weight:400; color:#e0e8f0; text-align:right; }
    .columns { column-count:2; column-gap:28px; column-rule:1px solid rgba(220,235,255,.12); }
    .line { white-space:pre-wrap; overflow-wrap:anywhere; break-inside:avoid; padding-bottom:2px; }
    .hand { color:#ffdfa0; font-weight:600; }
    .footnote { color:#c7d4e2; }
    .empty .heading { margin-bottom:0; }
    .empty .columns { display:none; }
  </style><section class="panel empty" aria-label="最新牌局统计">
    <div class="heading"><span class="label">Maj-Soul++ · 牌局统计</span><span class="caption">等待对局 · 发牌及场上动作后自动更新</span></div>
    <div class="columns"></div></section>`;
  const panel = shadow.querySelector('.panel'), caption = shadow.querySelector('.caption');
  const columns = shadow.querySelector('.columns');
  function fit() {
    // Balance the terminal lines into two columns, then fit the upper half of the view.
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
  window.__mjStatsOverlay = {update(packet) {
    if (packet.kind === 'turn') {
      const lines = packet.text.split('\n').filter(line => line && !/^═+$/.test(line));
      caption.textContent = lines.shift() || '牌局已更新';
      columns.replaceChildren(...lines.map(text => {
        const row = document.createElement('div');
        row.className = 'line' + (/^本人/.test(text) ? ' hand' : /^(完整性|说明|触发)/.test(text) ? ' footnote' : '');
        row.textContent = text;
        return row;
      }));
      panel.classList.remove('empty');
    } else {
      caption.textContent = packet.text;
      if (packet.reset || ['waiting','connected','playing','ended'].includes(packet.phase)) {
        columns.replaceChildren(); panel.classList.add('empty');
      }
    }
    mount();
  }};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true});
  else mount();
  addEventListener('resize', fit);
  document.addEventListener('fullscreenchange', mount);
})();
