/** Browser smoke test: the dashboard and every module page, at three widths.
 *
 * Catches what template/CSS contract tests cannot: console errors, missing
 * workspace chrome, and horizontal overflow at real viewport widths.
 *
 * Usage (session cookie never passed on the command line):
 *   BARK_URL=https://bark.warx.org BARK_COOKIE_FILE=/tmp/cookie.txt \
 *     node scripts/browser_smoke.mjs
 *
 * The cookie file holds just the session cookie value. Run it against the
 * instance you are about to trust; a green run is evidence, not proof.
 */

import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';

const BASE = (process.env.BARK_URL || 'https://bark-dev.warx.org').replace(/\/$/, '');
const HOST = new URL(BASE).host;
const COOKIE = readFileSync(process.env.BARK_COOKIE_FILE || '/tmp/dev_cookie.txt', 'utf8').trim();
const GUILD = process.env.BARK_GUILD || '';
const WIDTHS = (process.env.BARK_WIDTHS || '1600,1280,390').split(',').map(Number);
const PORT = Number(process.env.BARK_CDP_PORT || 9350);

const chrome = spawn('/usr/bin/chromium', [
  '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=/tmp/bark-smoke-${Date.now()}`, 'about:blank',
], {stdio: 'ignore'});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
for (let i = 0; i < 60; i++) {
  try { if ((await fetch(`http://127.0.0.1:${PORT}/json/version`)).ok) break; } catch { /* retry */ }
  await sleep(250);
}
const target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, {method: 'PUT'})).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });

let nextId = 0;
const pending = new Map();
let pageErrors = [];
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
  if (m.method === 'Runtime.exceptionThrown') {
    pageErrors.push(m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text || 'exception');
  }
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
    pageErrors.push((m.params.args || []).map((a) => a.value ?? a.description ?? '').join(' '));
  }
});
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = ++nextId;
  pending.set(id, (m) => (m.error ? rej(new Error(`${method}: ${JSON.stringify(m.error)}`)) : res(m.result)));
  ws.send(JSON.stringify({id, method, params}));
});
const evalJs = async (expression) =>
  (await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true})).result?.value;

await send('Page.enable');
await send('Runtime.enable');
await send('Network.enable');
await send('Network.setCookie', {name: 'session', value: COOKIE, domain: HOST, path: '/', secure: BASE.startsWith('https'), httpOnly: true});

const PROBE = `(() => ({
  title: document.title,
  containers: document.querySelectorAll('.page-container').length,
  notFound: /not found|page not found/i.test(document.body.innerText.slice(0, 400)),
  overflowPx: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
}))()`;

const results = [];
function record(label, width, probe, errors) {
  const problems = [];
  if (!probe) problems.push('no probe result');
  else {
    if (!probe.title) problems.push('empty title');
    if (probe.containers === 0) problems.push('no .page-container');
    if (probe.notFound) problems.push('page-not-found text');
    if (probe.overflowPx > 2) problems.push(`h-overflow ${probe.overflowPx}px`);
  }
  if (errors.length) problems.push(`${errors.length} console error(s): ${errors[0].slice(0, 90)}`);
  results.push({label, width, ok: problems.length === 0, problems});
  console.log(`  ${problems.length ? 'FAIL' : 'PASS'}  ${label.padEnd(34)} ${String(width).padStart(4)}px  ${problems.join('; ')}`);
}

try {
  const guilds = await (await fetch(`${BASE}/api/v1/guilds`, {headers: {cookie: `session=${COOKIE}`}})).json();
  const list = guilds?.data?.guilds || guilds?.data || [];
  if (!list.length) throw new Error('no guilds visible with this session — cookie rejected?');
  const gid = GUILD || list[0]?.id;
  console.log(`Bark browser smoke — ${BASE} (guild ${gid})\n`);

  await send('Emulation.setDeviceMetricsOverride', {width: 1600, height: 1100, deviceScaleFactor: 1, mobile: false});
  await send('Page.navigate', {url: `${BASE}/guild/${gid}/modules`});
  await sleep(3500);
  const moduleRoutes = await evalJs(
    `[...new Set([...document.querySelectorAll('a[href*="/modules/"]')].map(a => new URL(a.href).pathname))]`,
  );
  const routes = [`/guild/${gid}`, `/guild/${gid}/modules`, ...(moduleRoutes || [])];
  console.log(`Visiting ${routes.length} routes x ${WIDTHS.length} widths\n`);

  for (const route of routes) {
    for (const width of WIDTHS) {
      pageErrors = [];
      await send('Emulation.setDeviceMetricsOverride', {
        width, height: 1100, deviceScaleFactor: 1, mobile: width < 500,
      });
      await send('Page.navigate', {url: BASE + route});
      await sleep(width < 500 ? 3000 : 2400);
      const probe = await evalJs(PROBE);
      record(route, width, probe, pageErrors);
    }
  }
} catch (e) {
  console.log('ERROR:', e.message);
  results.push({ok: false, problems: [e.message]});
} finally {
  try { ws.close(); } catch { /* ignore */ }
  chrome.kill('SIGKILL');
}

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);