// Record the displayed azimuth (#az) every animation frame for N seconds
import puppeteer from 'puppeteer-core';
const [url, secs] = [process.argv[2], parseFloat(process.argv[3] || '40')];
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new',
  args: ['--no-sandbox', '--disable-crash-reporter', '--disable-breakpad', '--user-data-dir=/tmp/prof', '--autoplay-policy=no-user-gesture-required'] });
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1000 });
await p.goto(url, { waitUntil: 'load' }); await new Promise(r => setTimeout(r, 3000));
const samples = await p.evaluate(async (ms) => {
  const out = []; const t0 = performance.now();
  await new Promise(res => { function f() { out.push([performance.now() - t0, document.getElementById('az').textContent]); if (performance.now() - t0 < ms) requestAnimationFrame(f); else res(); } requestAnimationFrame(f); });
  return out;
}, secs * 1000);
console.log(JSON.stringify(samples));
await b.close();
