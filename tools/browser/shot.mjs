// Headless check of the hamcam page: wait for live video, click Screenshot, save the download.
import puppeteer from 'puppeteer-core';
const url = process.argv[2] || 'http://127.0.0.1:8097/';
const out = process.argv[3] || '/out';
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME, headless: 'new',
  args: ['--no-sandbox', '--disable-crash-reporter', '--disable-breakpad', '--user-data-dir=/tmp/prof', '--autoplay-policy=no-user-gesture-required', '--window-size=1400,1100'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 1100 });
page.on('console', async m => console.log('console:', m.type(), m.text(), JSON.stringify(await Promise.all(m.args().map(a => a.jsonValue().catch(() => '?'))))));
const cdp = await page.createCDPSession();
await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: out });
await page.goto(url, { waitUntil: 'load' });
await page.waitForFunction(() => {
  const v = document.querySelector('ham-video')?.video;
  return v && v.videoWidth > 0 && v.currentTime > 1;
}, { timeout: 30000 });
await new Promise(r => setTimeout(r, 4000));           // let stats/weather fill in
const info = await page.evaluate(() => ({
  stats: document.querySelector('#stats text')?.textContent ?? null,
  wx: document.querySelector('#wx text').textContent,
  az: document.getElementById('az').textContent,
  size: [document.querySelector('ham-video').video.videoWidth, document.querySelector('ham-video').video.videoHeight],
}));
console.log(JSON.stringify(info));
await page.screenshot({ path: `${out}/page.png` });
await page.click('#shot');
await new Promise(r => setTimeout(r, 4000));
console.log('msg:', await page.$eval('#msg', e => e.textContent));
await browser.close();
