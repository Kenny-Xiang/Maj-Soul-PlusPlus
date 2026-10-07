// WebKit suspends animation frames for hidden pages even when process suspension
// is disabled. The native host pulses pending frames while autoplay is enabled.
(() => {
  if (location.hostname !== 'game.maj-soul.com' || window.__mjBackground) return;
  const request = window.requestAnimationFrame.bind(window);
  const cancel = window.cancelAnimationFrame.bind(window);
  const pending = new Map();
  let pulsing = false;
  window.requestAnimationFrame = callback => {
    // Preserve native callback validation and request IDs for cancellation.
    if (typeof callback !== 'function') return request(callback);
    const entry = {callback};
    const id = request(time => {
      if (pending.get(id) !== entry) return;
      pending.delete(id);
      callback.call(window, time);
    });
    pending.set(id, entry);
    return id;
  };
  window.cancelAnimationFrame = id => {pending.delete(id); cancel(id);};
  const active = () => window.document.hidden === true &&
    window.__mjAutoplay?.getStatus().enabled === true && window.__mjUnityTransport?.isUnity();
  window.__mjBackground = {pulse() {
    if (pulsing || !active()) return;
    pulsing = true;
    try {
      const time = performance.now();
      // Newly requested frames wait for the next pulse; never replay missed time.
      for (const [id, entry] of [...pending]) {
        if (!active()) break;
        if (pending.get(id) !== entry) continue;
        pending.delete(id); cancel(id);
        try {entry.callback.call(window, time);}
        catch (error) {console.error('[后台游戏帧]', error);}
      }
      if (active()) window.__mjAutoplay.tick();
    } finally {pulsing = false;}
  }};
})();
