// Drives a page in headless Chrome over its DevTools protocol, for the demonstrate stage: a screenshot alone can't show
// a keyboard or focus behaviour. Cut down from sail's own demo harness.
// Usage: bun .sail/lib/browse.mjs <dir> <name> <url> [steps=<file>] [size=<width>x<height>]
// Opens <url>, waits for the page to settle, writes <dir>/<name>.png and the DOM to <dir>/<name>.html, then runs the
// steps, a JSON list run in order on one page load:
//   {"click": css}                 clicks the element
//   {"type": css, "text": text}    focuses the element and types the text, as a person would
//   {"press": key}                 presses Enter, Escape, Tab, ArrowUp, ArrowDown or Backspace on the focused element
//   {"scroll": css, "top": px}     scrolls the element
//   {"wait": css} or {"wait": ms}  waits for a selector, up to 20s, or for that long
//   {"shot": name}                 writes <dir>/<name>-<shot>.png and .html
// Every step, and each console warning or error the page logged, is appended to <dir>/transcript.txt. A selector that
// matches nothing exits 1 and names the step; the shots before it stay. Chrome is found where it installs, or named by
// SAIL_DEMO_CHROME.
import { spawn } from 'node:child_process';
import { appendFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const CHROMES = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  'google-chrome',
  'chromium',
  'chromium-browser',
];
/** The page is captured once its DOM hasn't changed for SETTLE_MS. */
const SETTLE_MS = 1000;
const CAPTURE_SECONDS = 60;
const STEP_SECONDS = 5;
const WAIT_SECONDS = 20;
const KEYS = { Backspace: 8, Tab: 9, Enter: 13, Escape: 27, ArrowUp: 38, ArrowDown: 40 };

const [dir, name, url, ...options] = process.argv.slice(2);
if (!dir || !name || !url) {
  console.error('usage: browse.mjs <dir> <name> <url> [steps=<file>] [size=<width>x<height>]');
  process.exit(2);
}
const option = (key) => options.find((each) => each.startsWith(`${key}=`))?.slice(key.length + 1);
const size = (option('size') ?? '1440x900').replace('x', ',');
mkdirSync(dir, { recursive: true });
const say = (line) => {
  console.log(line);
  appendFileSync(join(dir, 'transcript.txt'), `${line}\n`);
};

function findChrome() {
  const named = process.env.SAIL_DEMO_CHROME;
  for (const candidate of named ? [named] : CHROMES) {
    const found = candidate.startsWith('/') ? (existsSync(candidate) ? candidate : null) : Bun.which(candidate);
    if (found !== null) return found;
  }
  return undefined;
}

/** Calls on one DevTools target over its WebSocket: `send(method, params)` answers with the result. */
async function devtools(address, onEvent) {
  const socket = new WebSocket(address);
  await new Promise((done, fail) => {
    socket.onopen = done;
    socket.onerror = () => fail(new Error(`no DevTools connection at ${address}`));
  });
  let next = 1;
  const waiting = new Map();
  socket.onmessage = (event) => {
    const message = JSON.parse(String(event.data));
    if (message.id === undefined) return onEvent(message);
    const answer = waiting.get(message.id);
    if (answer === undefined) return;
    waiting.delete(message.id);
    if (message.error) answer.fail(new Error(message.error.message));
    else answer.done(message.result);
  };
  return {
    send: (method, params = {}) =>
      new Promise((done, fail) => {
        const id = next++;
        waiting.set(id, { done, fail });
        socket.send(JSON.stringify({ id, method, params }));
      }),
    close: () => socket.close(),
  };
}

async function evaluate(session, expression) {
  const answer = await session.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (answer.exceptionDetails !== undefined)
    throw new Error(answer.exceptionDetails.exception?.description ?? answer.exceptionDetails.text);
  return answer.result.value;
}

/** Waits for the DOM to go SETTLE_MS without a change, for at most `seconds`: a map may never quite settle. */
async function settle(session, seconds) {
  const until = Date.now() + seconds * 1000;
  let last = -1;
  let since = Date.now();
  while (Date.now() < until) {
    await Bun.sleep(250);
    const now = await evaluate(session, 'document.documentElement.outerHTML.length');
    if (now !== last) [last, since] = [now, Date.now()];
    else if (Date.now() - since >= SETTLE_MS) return;
  }
}

async function shot(session, stem) {
  const image = await session.send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(dir, `${stem}.png`), Buffer.from(image.data, 'base64'));
  writeFileSync(join(dir, `${stem}.html`), `${await evaluate(session, 'document.documentElement.outerHTML')}\n`);
  say(`screenshot ${join(dir, `${stem}.png`)}, dom ${stem}.html`);
}

async function press(session, key) {
  const code = KEYS[key];
  if (code === undefined) throw new Error(`no key ${key}: ${Object.keys(KEYS).join(', ')}`);
  const event = { key, code: key, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code };
  await session.send('Input.dispatchKeyEvent', { type: 'keyDown', ...event });
  await session.send('Input.dispatchKeyEvent', { type: 'keyUp', ...event });
}

async function runStep(session, step, at) {
  const head = `step ${at + 1} ${JSON.stringify(step)}`;
  const miss = () => new Error(`${head} matched nothing`);
  const on = (css, body) =>
    evaluate(session, `(() => { const e = document.querySelector(${JSON.stringify(css)}); if (e === null) return null; ${body} })()`);
  if ('click' in step) {
    if ((await on(step.click, 'e.click(); return true;')) === null) throw miss();
    await settle(session, STEP_SECONDS);
    say(`${head}: clicked`);
  } else if ('type' in step) {
    if ((await on(step.type, 'e.focus(); return true;')) === null) throw miss();
    for (const character of step.text) await session.send('Input.insertText', { text: character });
    await settle(session, STEP_SECONDS);
    say(`${head}: typed`);
  } else if ('press' in step) {
    await press(session, step.press);
    await settle(session, STEP_SECONDS);
    say(`${head}: pressed, focus on ${await evaluate(session, 'document.activeElement?.tagName ?? "nothing"')}`);
  } else if ('scroll' in step) {
    const top = await on(step.scroll, `e.scrollTop = ${step.top}; return Math.round(e.scrollTop);`);
    if (top === null) throw miss();
    say(`${head}: scrollTop ${top}`);
  } else if ('wait' in step) {
    const started = Date.now();
    if (typeof step.wait === 'number') await Bun.sleep(step.wait);
    else {
      while (!(await evaluate(session, `document.querySelector(${JSON.stringify(step.wait)}) !== null`))) {
        if (Date.now() - started > WAIT_SECONDS * 1000) throw miss();
        await Bun.sleep(100);
      }
    }
    say(`${head}: after ${Date.now() - started}ms`);
  } else if ('shot' in step) {
    await shot(session, `${name}-${step.shot}`);
  } else throw new Error(`${head}: no such step`);
}

const steps = option('steps') ? JSON.parse(readFileSync(option('steps'), 'utf8')) : [];
const browser = findChrome();
if (browser === undefined) {
  console.error('no Chrome: install it, or name it in SAIL_DEMO_CHROME');
  process.exit(2);
}
const profile = join(dir, 'chrome');
mkdirSync(profile, { recursive: true });
const portFile = join(profile, 'DevToolsActivePort');
rmSync(portFile, { force: true });
const child = spawn(
  browser,
  [
    '--headless=new',
    '--remote-debugging-port=0',
    `--user-data-dir=${profile}`,
    `--window-size=${size}`,
    '--hide-scrollbars',
    '--no-first-run',
    '--no-default-browser-check',
    '--use-mock-keychain',
    '--disable-background-networking',
    '--disable-component-update',
    '--disable-sync',
    'about:blank',
  ],
  { stdio: 'ignore', detached: true },
);
let session;
let code = 0;
try {
  const started = Date.now() + CAPTURE_SECONDS * 1000;
  while (!existsSync(portFile) || readFileSync(portFile, 'utf8').split('\n').length < 2) {
    if (Date.now() > started) throw new Error(`${browser} started no DevTools`);
    await Bun.sleep(100);
  }
  const port = readFileSync(portFile, 'utf8').split('\n')[0];
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const target = targets.find((each) => each.type === 'page');
  if (target === undefined) throw new Error('Chrome opened no page');
  session = await devtools(target.webSocketDebuggerUrl, ({ method, params }) => {
    if (method !== 'Runtime.consoleAPICalled' || !['warning', 'error'].includes(params.type)) return;
    say(`console ${params.type}: ${params.args.map((arg) => arg.value ?? arg.description ?? '').join(' ').slice(0, 500)}`);
  });
  await session.send('Page.enable');
  await session.send('Runtime.enable');
  await session.send('Page.navigate', { url });
  await settle(session, CAPTURE_SECONDS);
  say(`opened ${url} at ${size}`);
  await shot(session, name);
  for (const [at, step] of steps.entries()) await runStep(session, step, at);
} catch (error) {
  say(`failed: ${error instanceof Error ? error.message : String(error)}`);
  code = 1;
} finally {
  session?.close();
  try {
    process.kill(-child.pid, 'SIGKILL');
  } catch {}
  rmSync(profile, { recursive: true, force: true });
}
process.exit(code);
