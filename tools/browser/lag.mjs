// Measure lag between video motion and overlay azimuth in the browser during a move.
import puppeteer from 'puppeteer-core';
const [url, secs] = [process.argv[2], parseFloat(process.argv[3] || '30')];
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new',
  args: ['--no-sandbox', '--disable-crash-reporter', '--disable-breakpad', '--user-data-dir=/tmp/prof', '--autoplay-policy=no-user-gesture-required'] });
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1000 });
await p.goto(url, { waitUntil: 'load' });
await p.waitForFunction(() => { const v = document.querySelector('ham-video')?.video; return v && v.videoWidth > 0 && v.currentTime > 1; }, { timeout: 30000 });
const out = await p.evaluate(async (ms) => {
  const v = document.querySelector('ham-video').video;
  const W = 320, H = 240, c = document.createElement('canvas'); c.width = W; c.height = H;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  const rows = [Math.round(H * 0.40), Math.round(H * 0.62)];      // band below the horizon, away from the boom
  let prev = null, cum = 0; const res = []; const t0 = performance.now(); let lastT = null;
  function profile() {
    ctx.drawImage(v, 0, 0, W, H);
    const d = ctx.getImageData(0, rows[0], W, rows[1] - rows[0]).data; const prof = new Float32Array(W);
    for (let y = 0; y < rows[1] - rows[0]; y++) for (let x = 0; x < W; x++) { const i = (y * W + x) * 4; prof[x] += d[i] + d[i + 1] + d[i + 2]; }
    let m = 0; for (const q of prof) m += q; m /= W; for (let x = 0; x < W; x++) prof[x] -= m;
    return prof;
  }
  function shift(a, bb) {             // best integer shift of bb vs a (+ = scene moved right), with parabolic refinement
    let best = 0, bestV = -1e30; const sc = [];
    for (let s = -15; s <= 15; s++) { let acc = 0; for (let x = 20; x < W - 20; x++) acc += a[x] * bb[x + s]; sc.push(acc); if (acc > bestV) { bestV = acc; best = s; } }
    const i = best + 15; if (i > 0 && i < sc.length - 1) { const y0 = sc[i - 1], y1 = sc[i], y2 = sc[i + 1]; const den = y0 - 2 * y1 + y2; if (den) return best + 0.5 * (y0 - y2) / den; }
    return best;
  }
  await new Promise(res2 => {
    v.requestVideoFrameCallback(function f(now, meta) {
      const t = performance.now() - t0; const prof = profile();
      if (prev) cum += shift(prev, prof);
      prev = prof; res.push([t, cum, document.getElementById('az').textContent]);
      if (t < ms) v.requestVideoFrameCallback(f); else res2();
    });
  });
  return res;
}, secs * 1000);
console.log(JSON.stringify(out));
await b.close();
