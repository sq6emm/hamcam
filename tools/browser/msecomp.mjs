// MSE delay compensation check: opens the page with WebRTC and with WebRTC disabled (forces MSE), samples the buffer lag
// and the compensation value (window.__mseExtra, published only when window.__hook is set). Usage: node msecomp.mjs [url]
import puppeteer from 'puppeteer-core';
for (const mode of ['webrtc', 'mse']) {
  const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new', args: ['--no-sandbox', `--user-data-dir=/tmp/p-${mode}`, '--autoplay-policy=no-user-gesture-required'] });
  const p = await b.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  if (mode === 'mse') await p.evaluateOnNewDocument(() => { window.RTCPeerConnection = undefined; });
  // expose the module-scoped value for the test only: wrap setInterval callbacks is overkill -> read via a tiny hook
  await p.evaluateOnNewDocument(() => { window.__hook = true; });
  await p.goto('process.argv[2] || "http://127.0.0.1:8097/"', { waitUntil: 'load' });
  const samples = [];
  for (let i = 0; i < 6; i++) {
    await new Promise(r => setTimeout(r, 2500));
    samples.push(await p.evaluate(() => { const v = document.querySelector('ham-video').video;
      return { mode: v.srcObject ? 'WebRTC' : (v.src ? 'MSE' : 'none'), lag: v.buffered.length ? +(v.buffered.end(v.buffered.length - 1) - v.currentTime).toFixed(2) : null,
               comp: window.__mseExtra != null ? +window.__mseExtra.toFixed(2) : null, az: document.getElementById('az').textContent }; }));
  }
  console.log(mode.padEnd(6), JSON.stringify(samples.slice(2)), errs.length ? 'ERRORS ' + errs.join(' | ') : 'no errors');
  await b.close();
}
