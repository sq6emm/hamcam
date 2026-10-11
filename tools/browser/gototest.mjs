// Point-to field test (azimuth, az/el, locator, callsign, errors) against tools/ctltest/stack.sh - moves the (fake) rotator.
import puppeteer from 'puppeteer-core';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new', args: ['--no-sandbox', '--user-data-dir=/tmp/pgt'] });
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1100 });
await p.setExtraHTTPHeaders({ 'X-Forwarded-For': '192.168.12.38' });
p.on('pageerror', e => { if (!/VideoRTC/.test(e.message)) console.log('PAGE ERROR', e.message); });
await p.goto('http://127.0.0.1:8098/', { waitUntil: 'load' }); await sleep(4000);
console.log('field hidden before Control:', await p.$eval('#gotoIn', e => e.hidden));
await p.click('#ctl'); console.log('field visible with Control:', await p.$eval('#gotoIn', e => !e.hidden));
for (const v of ['213', '200/12', 'JO80HK', 'sp6gwb', 'NOSUCHCALL1', 'x!y', '400']) {
  await p.click('#gotoIn', { clickCount: 3 }); await p.type('#gotoIn', v); await p.keyboard.press('Enter'); await sleep(2500);
  const txt = await p.evaluate(() => [...document.querySelectorAll('#ctlmarks text')].map(t => t.textContent).join(''));
  console.log(`${v.padEnd(12)} -> msg: ${await p.$eval('#msg', e => e.textContent)}   | overlay: ${txt}`);
}
await p.$eval('#bar', e => e.scrollLeft = 0); await (await p.$('#bar')).screenshot({ path: '/out/bar_ctl.png' });
await b.close();
