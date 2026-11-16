// The pages' tests in a real browser. Prints PASS and FAIL lines, writes the layout findings and screenshots to OUT.
//   node audit.js self     the checker itself finds each planted defect (defects.html)
//   node audit.js empty    every page of a server with nothing on it
//   node audit.js full     every page with players, plays, recordings and an app, at five widths, in both languages
//   node audit.js keys     the keyboard's marks on the site and the admin pages, held to the database (keys.json in OUT)
//   node audit.js air      the pages that change while players are on air, and the video playing
//   node audit.js maint    the owner turns maintenance on: the notice, whole, on every page that shows it; then off again
//   node audit.js down     the game server stopped: the owner's pages keep their look and say what is wrong
//   node audit.js flows    what people do: signing in, searching, the replay player, the owner's forms; every floating
//                          layer (menus, tooltips, questions) opened and measured whole and on top
//   node audit.js quiet    broadcasts off for the server with everything in place: nothing of them on the site
//   node audit.js patterns nothing said only under a mouse pointer, switches that change the page in place, the owner's
//                          forms saying what is wrong under the field
// Exit status 1 when anything failed. Reads SITE, ADMIN (addresses), PASSWORD and OUT from the environment.
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const stage = process.argv[2];
const SITE = process.env.SITE;
const ADMIN = process.env.ADMIN;
const PASSWORD = process.env.PASSWORD;
const OUT = process.env.OUT || '/out';
const P = `${SITE}/opendmtq`;
const A = `${ADMIN}/opendmtq/admin`;
const layout = fs.readFileSync(path.join(__dirname, 'layout.js'), 'utf8');
const pause = ms => new Promise(r => setTimeout(r, ms));

// The screens every page is looked at on: a phone, the narrowest tablet (an iPad mini held upright), a tablet held sideways,
// a laptop, a large monitor. Between the phone's stacked rows and a laptop's width is where a table has the least room.
const ALL_WIDTHS = [360, 744, 1024, 1280, 1920];
// For the states that only change a part of a page.
const FEW_WIDTHS = [360, 1280];
// Player numbers and song numbers from seed.php and make_content.php: 1 plays much, 4 and 5 have the longest names, 10 has no
// plays; song 25 has the longest name, song 26 has no jacket.
// The setup's steps as a host install shows them: run.sh puts a client and a folder of the client data and the song
// data in the owner's Downloads.
const SETUP = [
  ['admin-setup', `${A}/setup?step=files`],
  ['admin-setup-picker', `${A}/setup?step=files&dir=%2Fhome%2Fplayer%2FDownloads`],
  ['admin-setup-address', `${A}/setup?step=address`],
  ['admin-setup-players', `${A}/setup?step=players`],
  ['admin-setup-app', `${A}/setup?step=app`],
];
const FULL = [
  // Signed out, a page asked for: the sign-in page is all there is.
  ['sign-in-first', `${P}/ranking.php`, { anon: true }],
  ['home', `${P}/`],
  ['download', `${P}/download.php`],
  ['rankings', `${P}/ranking.php`],
  ['rankings-s', `${P}/ranking.php?sort=s_count`],
  ['rankings-month', `${P}/ranking.php?sort=month`],
  ['songs', `${P}/songs.php`],
  ['song', `${P}/song.php?id=1`],
  ['song-long-name', `${P}/song.php?id=25`],
  ['song-no-jacket', `${P}/song.php?id=26`],
  ['song-unknown', `${P}/song.php?id=8888`, { status: 404 }],
  ['player', `${P}/player.php?id=1`],
  ['player-no-plays', `${P}/player.php?id=10`],
  ['player-long-name', `${P}/player.php?id=5`],
  ['player-unknown', `${P}/player.php?id=999`, { status: 404 }],
  ['live', `${P}/live.php`, { settle: 1500 }],
  ['sign-in', `${P}/login.php?next=%2Fapk`, { anon: true }],
  ['not-found', `${SITE}/nope`, { status: 404 }],
  ['licenses', `${P}/licenses.php`],
  ['admin-sign-in', `${A}/login`, { anon: true }],
  ['admin-status', `${A}/`],
  ['admin-app', `${A}/app`],
  ['admin-songs', `${A}/songs`],
  ['admin-players', `${A}/players`],
  ['admin-accounts', `${A}/accounts`],
  ['admin-recordings', `${A}/recordings`],
  ['admin-backups', `${A}/backups`],
  ['admin-maintenance', `${A}/maintenance`],
  ['admin-requests', `${A}/logs`],
  ['admin-plays', `${A}/logs?tab=plays`],
  // Narrowed, by the player with one of the longest names: the form holds what was picked, and has a way back.
  ['admin-plays-narrowed', `${A}/logs?tab=plays&player=4&from=2020-01-01&to=2030-12-31`],
  ['admin-changes', `${A}/logs?tab=changes`],
  ['admin-not-found', `${A}/nope`, { status: 404 }],
  ...SETUP,
];
const EMPTY = [
  ['home', `${P}/`],
  // Signed out, a page asked for: the sign-in page is all there is.
  ['sign-in-first', `${P}/ranking.php`, { anon: true }],
  ['rankings', `${P}/ranking.php`],
  ['songs', `${P}/songs.php`],
  ['live', `${P}/live.php`, { settle: 800 }],
  ['download', `${P}/download.php`],
  ['no-app', `${SITE}/apk`, { status: 404 }],
  ['player-unknown', `${P}/player.php?id=1`, { status: 404 }],
  ['admin-status', `${A}/`],
  ['admin-app', `${A}/app`],
  ['admin-songs', `${A}/songs`],
  ['admin-players', `${A}/players`],
  ['admin-accounts', `${A}/accounts`],
  ['admin-recordings', `${A}/recordings`],
  ['admin-backups', `${A}/backups`],
  ['admin-requests', `${A}/logs`],
  ['admin-plays', `${A}/logs?tab=plays`],
  ['admin-changes', `${A}/logs?tab=changes`],
  ...SETUP,
];
const AIR = [
  ['home', `${P}/`, { settle: 800 }],
  ['live', `${P}/live.php`, { settle: 3000 }],
  ['live-one', `${P}/live.php?id=1`, { settle: 3000 }],
  ['rankings', `${P}/ranking.php`],
  ['player', `${P}/player.php?id=1`],
  ['admin-status', `${A}/`],
  ['admin-players', `${A}/players`],
  ['admin-accounts', `${A}/accounts`],
  ['admin-recordings', `${A}/recordings`],
];
const MAINT = [
  ['home', `${P}/`],
  // Signed out, a page asked for: the sign-in page is all there is.
  ['sign-in-first', `${P}/ranking.php`, { anon: true }],
  ['rankings', `${P}/ranking.php`],
  ['live', `${P}/live.php`, { settle: 800 }],
  ['admin-maintenance', `${A}/maintenance`],
  ['admin-status', `${A}/`],
];
// Broadcasts off for the server, with players, records and recordings: the pages that showed broadcasts, whole without
// them, and the owner's pages that say they are off.
const QUIET = [
  ['home', `${P}/`],
  ['rankings', `${P}/ranking.php`],
  ['player', `${P}/player.php?id=1`],
  ['player-long-name', `${P}/player.php?id=5`],
  ['live', `${P}/live.php`],
  ['download', `${P}/download.php`],
  ['admin-status', `${A}/`],
  ['admin-players', `${A}/players`],
  ['admin-recordings', `${A}/recordings`],
];
// The owner's pages, with the game server gone: run.sh stops it for this stage and starts it again afterwards.
const DOWN = [
  ['admin-sign-in', `${A}/login`, { anon: true }],
  ['admin-status', `${A}/`],
  ['admin-app', `${A}/app`],
  ['admin-songs', `${A}/songs`],
  ['admin-players', `${A}/players`],
  ['admin-accounts', `${A}/accounts`],
  ['admin-recordings', `${A}/recordings`],
  ['admin-backups', `${A}/backups`],
  ['admin-maintenance', `${A}/maintenance`],
  ['admin-requests', `${A}/logs`],
];
// Asked for and not there, on purpose: the jacket of song 26 (the page must go on without it).
const MISSING_ON_PURPOSE = /\/fixture26\.(png|jpg)$/;

let failed = 0;
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${stage}: ${name}${detail ? ` | ${detail}` : ''}`);
  if (!ok) failed++;
};

// One browser with its own signed-in sessions, one without.
async function open() {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium-browser', headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--autoplay-policy=no-user-gesture-required', '--mute-audio'] });
  const signed = await browser.createBrowserContext();
  const anon = await browser.createBrowserContext();
  return { browser, signed, anon };
}

async function signIn(context) {
  const page = await context.newPage();
  // (With the game server stopped, only the owner's pages are there to sign in to.)
  if (stage !== 'down') {
    await page.goto(`${P}/login.php?next=%2Fopendmtq%2F`, { waitUntil: 'domcontentloaded' });
    await typeId(page, 'input[name=user]', 'dmtq');
    await page.type('input[name=password]', PASSWORD);
    await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.keyboard.press('Enter')]);
  }
  await page.goto(`${A}/login`, { waitUntil: 'domcontentloaded' });
  await typeId(page, 'input[name=name]', 'admin');
  await page.type('input[name=password]', PASSWORD);
  await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.keyboard.press('Enter')]);
  await page.close();
}

// A page's own faults while it was open: failed requests and script errors. A page that is itself a 404 expects that.
function watch(page, url) {
  const faults = [];
  page.on('response', r => {
    const where = r.url().split('?')[0];
    if (r.status() >= 400 && r.url() !== url && !MISSING_ON_PURPOSE.test(where)) faults.push(`${r.status()} ${where.replace(/^https?:\/\/[^/]+/, '')}`);
  });
  page.on('pageerror', e => faults.push(`script: ${String(e).slice(0, 160)}`));
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) faults.push(`console: ${m.text().slice(0, 160)}`);
  });
  return faults;
}

// The owner's pages give a screen one primary button: two that one screen holds at once, on an admin page, are a finding
// (two-primaries), wherever on the page they are. A far one on a long page is no second on this screen. Only what can be
// pressed counts: a disabled one is drawn plain.
function twoPrimaries(page) {
  return page.evaluate(() => {
    if (!location.pathname.startsWith('/opendmtq/admin')) return [];
    const shown = [...document.querySelectorAll('.btn-primary')].filter(b => {
      const s = getComputedStyle(b), r = b.getBoundingClientRect();
      return !b.disabled && s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
    }).map(b => {
      const r = b.getBoundingClientRect();
      return { words: b.textContent.trim().replace(/\s+/g, ' ').slice(0, 30), top: r.top + scrollY, bottom: r.bottom + scrollY };
    });
    const found = [];
    for (let i = 0; i < shown.length; i++) {
      for (let j = i + 1; j < shown.length; j++) {
        // Both within one screen's height: a screen can show them together.
        if (Math.max(shown[i].bottom, shown[j].bottom) - Math.min(shown[i].top, shown[j].top) <= innerHeight) {
          found.push({ kind: 'two-primaries', at: `${shown[i].words} + ${shown[j].words}`, detail: `${innerWidth}x${innerHeight}` });
        }
      }
    }
    return found;
  });
}

// The checker on the page as it is now.
async function audit(page) {
  // What moves as a page arrives (style.css, "motion": bars filling, the player's row glowing) is measured where it
  // comes to rest: every animation with an end is waited for (those that loop, like the front page's sweep, are not),
  // three seconds at most.
  await page.evaluate(() => Promise.race([
    Promise.all(document.getAnimations().filter(a => a.effect && Number.isFinite(a.effect.getComputedTiming().endTime)).map(a => a.finished.catch(() => {}))),
    new Promise(done => setTimeout(done, 3000)),
  ]));
  await page.addScriptTag({ content: layout });
  return page.evaluate(() => window.layoutAudit());
}

// Every page of a list on every width, in both languages; findings grouped, so that one fault on eight views is one line.
async function sweep(contexts, pages, widths, langs = ['en', 'ko']) {
  const found = {};
  let views = 0;
  for (const [name, url, options = {}] of pages) {
    for (const width of widths) {
      for (const lang of langs) {
        const page = await (options.anon ? contexts.anon : contexts.signed).newPage();
        await page.setViewport({ width, height: width < 500 ? 740 : 900, hasTouch: width < 500, isMobile: width < 500 });
        await page.setCookie({ name: 'opendmtq_lang', value: lang, url });
        const faults = watch(page, url);
        let status = 0;
        try {
          const answer = await page.goto(url, { waitUntil: options.settle ? 'domcontentloaded' : 'networkidle2', timeout: 30000 });
          status = answer ? answer.status() : 0;
        } catch (e) {
          faults.push(`did not load: ${String(e).slice(0, 120)}`);
        }
        if (options.settle) await pause(options.settle);
        if (status !== (options.status || 200)) faults.push(`status ${status}, expected ${options.status || 200}`);
        // The layout, and on the owner's pages one primary button to a screen.
        const items = [...await audit(page), ...await twoPrimaries(page)];
        for (const f of faults) items.push({ kind: 'page-fault', at: f, detail: '' });
        for (const f of items) {
          const key = `${f.kind} | ${name} | ${f.at} | ${f.detail}`;
          (found[key] = found[key] || []).push(`${lang}${width}`);
        }
        // Pictures for people to look through: the default language on phone and laptop, the other on a phone.
        // SHOTS_ALL=1: both languages at the phone's width and the desktop's, for a look at a page in each.
        if ((process.env.SHOTS_ALL && (width === 360 || width === 1280)) || (lang === 'en' && (width === 360 || width === 1280)) || (lang === 'ko' && width === 360)) {
          await page.screenshot({ path: path.join(OUT, 'shots', `${stage}-${name}-${lang}-${width}.jpg`), type: 'jpeg', quality: 72, fullPage: true }).catch(() => {});
        }
        views++;
        await page.close();
      }
    }
  }
  const keys = Object.keys(found).sort();
  fs.appendFileSync(path.join(OUT, 'findings.txt'), keys.map(k => `${stage} | ${k} @${found[k].join(',')}\n`).join(''));
  check(`${views} views, ${keys.length} findings`, keys.length === 0, keys.slice(0, 30).map(k => `\n  ${k.slice(0, 170)} @${found[k].slice(0, 4).join(',')}`).join(''));
}

// Broadcasts off for the server: the site shows nothing of them, its live page says so in the site's own way, and the
// owner's Broadcasts page has the way to turn them on. held: a player's switch is on underneath, which the owner's
// Players page shows as kept for then.
async function broadcastsOff(contexts, held) {
  const page = await contexts.signed.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
  check('with broadcasts off the menu has no LIVE', (await page.$$('.nav a[href="/opendmtq/live.php"], .tabbar a[href="/opendmtq/live.php"]')).length === 0);
  check('nor the home page a way to watch, or a box of broadcasts', (await page.$('#watch-live')) === null && (await page.$('.broadcasts')) === null);
  await page.goto(`${P}/player.php?id=1`, { waitUntil: 'domcontentloaded' });
  check('nor a player page their past broadcasts', !(await page.$$eval('.card h2', hs => hs.some(h => /Past broadcasts/.test(h.textContent)))));
  const answer = await page.goto(`${P}/live.php?p=1`, { waitUntil: 'domcontentloaded' });
  check('a link to the live page says broadcasts are off', answer.status() === 200 && /Broadcasts are off/.test(await textOf(page, '.live-off')), await textOf(page, 'main'));
  const listed = await page.evaluate(async () => (await fetch('/opendmtq/live.php?list=1')).json());
  check("and the live page's own look says so too", listed.off === true && listed.live.length === 0, JSON.stringify(listed));
  const media = await page.evaluate(async () => (await fetch('/opendmtq/live-media.php/1/index.m3u8')).status);
  check('no broadcast is served', media === 404, String(media));
  await page.goto(`${A}/recordings`, { waitUntil: 'domcontentloaded' });
  check("the owner's Broadcasts page says they are off, with the way to turn them on",
    /Broadcasts are off/.test(await textOf(page, '#broadcasts')) && (await page.$('#broadcasts button[value="broadcasts-on"]')) !== null);
  if (held) {
    await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
    check("and the Players page that the switches wait for them", /Broadcasts are off for the whole server/.test(await textOf(page, 'main')) && /On · server off/.test(await textOf(page, 'main')));
    // The note above the search keeps room under it (it sat against the search's edge).
    const gap = await page.evaluate(() => {
      const note = document.querySelector('main .flash.note'), search = document.querySelector('#player-search');
      return note && search ? search.getBoundingClientRect().top - note.getBoundingClientRect().bottom : null;
    });
    check("and its note has room between it and the search under it", gap !== null && gap >= 8, String(gap));
  }
  await page.close();
}

// The checker itself: one of each thing it looks for must be seen.
async function self(contexts) {
  const page = await contexts.anon.newPage();
  await page.setViewport({ width: 800, height: 600 });
  await page.goto(`file://${path.join(__dirname, 'defects.html')}`, { waitUntil: 'load' });
  const kinds = new Set((await audit(page)).map(f => f.kind));
  for (const kind of ['clipped', 'sticks-out', 'overlap', 'rows', 'columns', 'past-screen', 'page-wide', 'covered', 'contrast', 'default-control', 'no-style', 'small-target', 'broken-image', 'side-scroll', 'broken-word', 'split-sentence']) {
    check(`the checker sees ${kind}`, kinds.has(kind));
  }
  // And two primary buttons on one screen of an owner's page (its address makes it one), not one of them far down the
  // page, nor one that cannot be pressed.
  const owner = await contexts.anon.newPage();
  await owner.setViewport({ width: 800, height: 600 });
  await owner.goto(`${A}/login`, { waitUntil: 'domcontentloaded' });
  const planted = async html => { await owner.setContent(html); return (await twoPrimaries(owner)).length; };
  const together = await planted('<button class="btn btn-primary">One</button><button class="btn btn-primary">Two</button>');
  const apart = await planted('<button class="btn btn-primary">One</button><div style="height:1200px"></div><button class="btn btn-primary">Two</button>');
  const waiting = await planted('<button class="btn btn-primary">One</button><button class="btn btn-primary" disabled>Two</button>');
  check('the checker sees two-primaries', together === 1 && apart === 0 && waiting === 0, `${together} ${apart} ${waiting}`);
  await owner.close();
}

const visible = (page, selector) => page.$eval(selector, e => !e.hidden && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0).catch(() => false);
const textOf = (page, selector) => page.$eval(selector, e => e.textContent).catch(() => '');
// An ID typed into a sign-in's field as a person does, over whatever the page put there: the field comes back filled with the
// ID last used on that browser (forms.js and admin.js, data-remember).
const typeId = async (page, selector, text) => {
  await page.$eval(selector, e => { e.value = ''; });
  await page.type(selector, text);
};
const noFindings = async (page, name) => {
  // The layout, and on the owner's pages one primary button to a screen, in whatever state the steps left the page.
  const items = [...await audit(page), ...await twoPrimaries(page)];
  check(`${name}: nothing wrong with the layout`, items.length === 0, items.slice(0, 6).map(f => `${f.kind} ${f.at} ${f.detail}`.slice(0, 140)).join(' ; '));
};

// What a press does, done: the page loaded again, or a change made in place (admin.js counts those, window.odqChanges).
// Thirty seconds at most.
async function settle(page, act) {
  const before = await page.evaluate(() => window.odqChanges || 0).catch(() => 0);
  const loaded = page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 30000 });
  const changed = page.waitForFunction(n => (window.odqChanges || 0) > n, { timeout: 30000, polling: 100 }, before);
  // The one that does not happen ends in an error later, which nobody waits for.
  loaded.catch(() => {});
  changed.catch(() => {});
  const never = p => p.catch(() => new Promise(() => {}));
  let timer;
  const late = new Promise((_, fail) => { timer = setTimeout(() => fail(new Error('the press neither loaded a page nor changed this one')), 30000); });
  await act();
  try {
    await Promise.race([never(loaded), never(changed), late]);
  } finally {
    clearTimeout(timer);
  }
}

// A form on the page, sent by pressing its button: the page coming back afterwards, or changed in place.
async function press(page, selector) {
  await settle(page, () => page.click(selector));
}

// A press that asks first: the question is the site's own, not the browser's, and its Continue goes on.
async function pressAndConfirm(page, selector) {
  await page.click(selector);
  await page.waitForSelector('#ask[open]');
  await settle(page, () => page.click('#ask [value=yes]'));
}

// A floating layer (a row's menu, a tooltip, a question) whole and on top: points over all of it, five by five just
// inside its edges, each in the window and each hitting the layer itself (elementFromPoint), not a card drawn over it or
// the page behind a part cut off. A layer the pointer passes through (a tooltip) takes the pointer for the measurement.
// Pictures cannot tell a menu drawn under a card's glass from one on top of it; this can.
async function wholeOnTop(page, selector) {
  return page.$eval(selector, layer => {
    const passes = getComputedStyle(layer).pointerEvents === 'none';
    if (passes) layer.style.pointerEvents = 'auto';
    const r = layer.getBoundingClientRect();
    const missed = [];
    for (let i = 0; i < 5; i++) {
      for (let j = 0; j < 5; j++) {
        const x = r.left + 3 + (r.width - 6) * i / 4, y = r.top + 3 + (r.height - 6) * j / 4;
        if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) { missed.push(`${Math.round(x)},${Math.round(y)} off the window`); continue; }
        const hit = document.elementFromPoint(x, y);
        if (!hit || !layer.contains(hit)) {
          missed.push(`${Math.round(x)},${Math.round(y)} ${hit ? hit.tagName.toLowerCase() + (hit.className && typeof hit.className === 'string' ? '.' + hit.className.split(' ')[0] : '') : 'nothing'}`);
        }
      }
    }
    if (passes) layer.style.pointerEvents = '';
    return { ok: r.width > 0 && r.height > 0 && missed.length === 0, detail: `${Math.round(r.width)}x${Math.round(r.height)} at ${Math.round(r.left)},${Math.round(r.top)}; ${missed.slice(0, 4).join(' ; ')}` };
  }).catch(e => ({ ok: false, detail: String(e).slice(0, 120) }));
}

// Every floating layer of the pages, opened as people open them, at a phone's width and a laptop's: whole and on top.
// The Players page's More on its first row, its last, the only row left after a search, and a row at the window's foot; the
// question one of its buttons asks; the tooltips of the owner's charts and of a player's days on the site.
async function floatingLayers(contexts) {
  for (const [width, height] of [[360, 740], [1280, 800]]) {
    const page = await contexts.signed.newPage();
    await page.setViewport({ width, height, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
    const at = `${width}px`;
    const shown = 'table.players tbody tr:not([style*="none"])';
    const openRow = async (which, name) => {
      // Any open panel closed first, by a press outside, as a person closes one.
      await page.evaluate(() => { for (const d of document.querySelectorAll('.row-more[open]')) d.open = false; });
      const more = await page.evaluateHandle((rows, which) => {
        const all = [...document.querySelectorAll(rows)];
        return (which === 'last' ? all[all.length - 1] : all[0]).querySelector('.row-more');
      }, shown, which);
      await more.evaluate(d => d.querySelector('summary').scrollIntoView({ block: 'nearest' }));
      await more.evaluate(d => d.querySelector('summary').click());
      await page.waitForFunction(d => d.open && d.querySelector('.row-more-in'), {}, more);
      await pause(250);
      await more.evaluate(d => d.setAttribute('data-measured', ''));
      const found = await wholeOnTop(page, '.row-more[data-measured] > .row-more-in');
      await more.evaluate(d => d.removeAttribute('data-measured'));
      check(`a player's More opens whole and on top: ${name}, ${at}`, found.ok, found.detail);
    };
    await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
    await openRow('first', 'the first row');
    await openRow('last', 'the last row');
    // A row at the window's foot: the window made just tall enough for the first row's More and a few pixels more, so that
    // its panel has no room below it.
    await page.evaluate(() => { for (const d of document.querySelectorAll('.row-more[open]')) d.open = false; scrollTo(0, 0); });
    const foot = await page.$eval(`${shown} .row-more > summary`, e => Math.ceil(e.getBoundingClientRect().bottom));
    await page.setViewport({ width, height: foot + 12, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
    await openRow('first', 'a row at the window\'s foot');
    await page.setViewport({ width, height, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
    // A search that leaves one row.
    const name = await page.$eval('table.players tbody tr:nth-child(3)', r => r.dataset.k);
    await page.$eval('#player-search', (e, v) => { e.value = v; e.dispatchEvent(new Event('input', { bubbles: true })); }, name);
    await openRow('first', 'the only row a search leaves');
    // A server with one player, as a new one has: the other rows taken off the page.
    await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => { for (const r of document.querySelectorAll('table.players tbody tr:not(:first-child)')) r.remove(); });
    await openRow('first', 'the list of a server with one player');
    // Reset's question over the open panel.
    await page.click('.row-more[open] > .row-more-in button[value=reset]');
    await page.waitForSelector('#ask[open]');
    const ask = await wholeOnTop(page, '#ask[open] > *');
    check(`the question a panel's button asks is whole and on top, ${at}`, ask.ok, ask.detail);
    await page.click('#ask [value=no]');
    await page.screenshot({ path: path.join(OUT, 'shots', `floating-players-one-row-${width}.jpg`), type: 'jpeg', quality: 72 });
    // The tooltips: a mark brought to the middle of the window and pointed at (a finger presses it: the same words), its
    // tooltip measured. The marks pointed at are those a person can reach: drawn, a few pixels at least, and the mark itself
    // under its middle (not one under the bar).
    const tipOf = async (index, of) => {
      const mark = (await page.$$('[data-tip]'))[index];
      await mark.evaluate(e => e.scrollIntoView({ block: 'center', inline: 'nearest' }));
      await pause(80);
      const box = await mark.boundingBox();
      const x = box.x + box.width / 2, y = box.y + box.height / 2;
      if (width < 700) await page.touchscreen.tap(x, y); else await page.mouse.move(x, y);
      await pause(150);
      return wholeOnTop(page, '.chart-tip:not([hidden])');
    };
    const reachable = () => page.$$eval('[data-tip]', all => all.map((e, i) => {
      const r = e.getBoundingClientRect();
      return r.width >= 4 && r.height >= 4 && getComputedStyle(e).visibility !== 'hidden' ? i : -1;
    }).filter(i => i >= 0));
    // The owner's charts on the status page: the first mark, one in the middle, the last.
    await page.goto(`${A}/`, { waitUntil: 'domcontentloaded' });
    const marks = await reachable();
    for (const index of [marks[0], marks[Math.floor(marks.length / 2)], marks[marks.length - 1]].filter((v, i, a) => v !== undefined && a.indexOf(v) === i)) {
      const tip = await tipOf(index);
      check(`a chart's tooltip on the status page is whole and on top: mark ${index + 1}, ${at}`, tip.ok, tip.detail);
    }
    // The site's: a player's days of plays, the first and the last.
    await page.goto(`${P}/player.php?id=1`, { waitUntil: 'domcontentloaded' });
    const days = await reachable();
    check(`a player's page has days to point at, ${at}`, days.length > 0);
    for (const index of [days[0], days[days.length - 1]].filter((v, i, a) => v !== undefined && a.indexOf(v) === i)) {
      const tip = await tipOf(index);
      check(`a player's day tooltip on the site is whole and on top: mark ${index + 1}, ${at}`, tip.ok, tip.detail);
    }
    await page.close();
  }
}

// The sign-in forms, the site's and the admin pages', and the Accounts page's password fields, as a person uses them, at a
// phone's width and a laptop's, in both languages: every field named by its label; Show inside the password field, the
// typed text kept clear of it, showing the password and hiding it again with the cursor left in the field; a field left
// empty said right under itself; Enter sending the form; the ID typed last back in its field the next time, the focus then
// on the password (on a computer).
async function signInForms(contexts) {
  const words = { en: ['Show', 'Hide', 'Enter your ID.', 'Enter your password.'], ko: ['보기', '숨기기', '아이디를 입력하세요.', '비밀번호를 입력하세요.'] };
  for (const [form, url, idName, who] of [['site', `${P}/login.php`, 'user', 'dmtq'], ['admin', `${A}/login`, 'name', 'admin']]) {
    for (const [width, height] of [[360, 740], [1280, 800]]) {
      for (const lang of ['en', 'ko']) {
        const at = `${form}, ${width}px, ${lang}`;
        const own = await contexts.browser.createBrowserContext();
        const page = await own.newPage();
        await page.setViewport({ width, height, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
        await page.setCookie({ name: 'opendmtq_lang', value: lang, url: SITE });
        // (The language's cookie is the host's, whatever the port: the admin pages read the same one.)
        await page.goto(url, { waitUntil: 'domcontentloaded' });
        const id = `.signin-form input[name=${idName}]`, pw = '.signin-form input[name=password]';
        const labelled = await page.$$eval('.signin-form input:not([type=hidden])', all => all.every(i => i.labels && i.labels.length && i.labels[0].textContent.trim()));
        check(`every field of the sign-in has its label (${at})`, labelled);
        // Show, inside the field at its right end, the text clear of it.
        const place = await page.evaluate(sel => {
          const f = document.querySelector(sel), b = document.querySelector('.signin-form .pw-toggle');
          if (!b || b.hidden) return null;
          const fr = f.getBoundingClientRect(), br = b.getBoundingClientRect();
          return { inside: br.left >= fr.left && br.right <= fr.right && br.top >= fr.top && br.bottom <= fr.bottom,
            clear: parseFloat(getComputedStyle(f).paddingRight) >= br.width + 4, word: b.textContent.trim() };
        }, pw);
        check(`the password field has Show inside it, the text kept clear of it (${at})`, place && place.inside && place.clear && place.word === words[lang][0], JSON.stringify(place));
        await page.type(pw, 'secret-1');
        // (A page without Show fails here and goes on to the rest.)
        const toggle = await page.$('.signin-form .pw-toggle:not([hidden])');
        if (toggle) await toggle.click();
        const shown = await page.evaluate(sel => [document.querySelector(sel).type, (document.querySelector('.signin-form .pw-toggle') || { textContent: '' }).textContent.trim(), document.activeElement === document.querySelector(sel)], pw);
        if (toggle) await toggle.click();
        const hidden = await page.$eval(pw, e => e.type);
        check(`Show shows the password as typed and hides it again, the field kept (${at})`,
          shown[0] === 'text' && shown[1] === words[lang][1] && (width < 700 || shown[2]) && hidden === 'password', JSON.stringify([shown, hidden]));
        if (width >= 700) await page.screenshot({ path: path.join(OUT, 'shots', `forms-${form}-shown-${lang}-${width}.jpg`), type: 'jpeg', quality: 80 });
        // Empty: the ID's words under the ID.
        await page.$eval(pw, e => { e.value = ''; });
        await page.$eval(id, e => { e.value = ''; });
        await page.click('.signin-form button[type=submit], .signin-form .button');
        await pause(150);
        const under = await page.$eval(`.field:has(${id.replace('.signin-form ', '')}) .field-error`, e => e.textContent.trim()).catch(() => '');
        const focus = await page.evaluate(() => document.activeElement.name);
        check(`a field left empty is said under itself, the focus on it (${at})`, (form === 'site' ? under === words[lang][2] : under !== '') && focus === idName,
          JSON.stringify([under, focus]));
        await page.screenshot({ path: path.join(OUT, 'shots', `forms-${form}-empty-${lang}-${width}.jpg`), type: 'jpeg', quality: 80 });
        await noFindings(page, `the sign-in with a field left empty (${at})`);
        // Enter sends it: a wrong password, said by the server. Only on some of the views: each wrong password counts toward
        // the sign-in's limit for this address (five in ten minutes on the admin pages), and the stages after this one sign
        // in from the same address.
        if (!(width >= 700 && lang === 'en') && !(form === 'site' && width < 700 && lang === 'ko')) {
          await own.close();
          continue;
        }
        await page.type(id, who);
        await page.type(pw, 'not-the-password');
        const sent = await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 10000 }).then(() => true, () => false), page.keyboard.press('Enter')]);
        check(`Enter in the password field sends the form (${at})`, sent[0] && /\S/.test(await textOf(page, '.signin .error')));
        await page.screenshot({ path: path.join(OUT, 'shots', `forms-${form}-wrong-${lang}-${width}.jpg`), type: 'jpeg', quality: 80 });
        // The next visit: the ID back, the focus on the password on a computer.
        await page.goto(url, { waitUntil: 'domcontentloaded' });
        await pause(100);
        const back = await page.evaluate((sel, pw) => [document.querySelector(sel).value, document.activeElement === document.querySelector(pw)], id, pw);
        check(`the ID typed last is back the next time${width >= 700 ? ', the focus on the password' : ''} (${at})`,
          back[0] === who && (width < 700 || back[1]), JSON.stringify(back));
        await own.close();
      }
    }
  }
  // The Accounts page: Show in both password fields, and two different passwords said before anything is sent.
  const page = await contexts.signed.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  await page.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
  check('both password fields of Make an account have Show', (await page.$$('.account-form .pw-toggle:not([hidden])')).length === 2);
  await page.type('.account-form input[name=name]', 'twotyped');
  await page.type('.account-form input[name=password]', 'one-password');
  await page.type('.account-form input[name=password2]', 'another-one');
  await page.click('.account-form .btn-primary');
  await pause(300);
  // Said under the second field's row (admin.js), which names the words.
  const said = await page.$eval('.account-form input[name=password2]', f => {
    const w = document.getElementById(f.getAttribute('aria-describedby') || '');
    return w ? w.textContent : '';
  }).catch(() => '');
  check('two different passwords are said before anything is sent', /not the same/.test(said) && new URL(page.url()).pathname === '/opendmtq/admin/accounts'
    && await page.evaluate(() => document.activeElement.name) === 'password2', said);
  await page.close();
}

// The pages the patterns below are looked for on: the site's and the owner's, with players, plays and recordings in place.
const PATTERN_PAGES = [
  ['home', `${P}/`], ['rankings', `${P}/ranking.php`], ['player', `${P}/player.php?id=1`], ['song', `${P}/song.php?id=1`],
  ['songs', `${P}/songs.php`], ['live', `${P}/live.php`], ['download', `${P}/download.php`],
  ['admin-status', `${A}/`], ['admin-players', `${A}/players`], ['admin-accounts', `${A}/accounts`],
  ['admin-recordings', `${A}/recordings`], ['admin-songs', `${A}/songs`], ['admin-requests', `${A}/logs`],
  ['admin-plays', `${A}/logs?tab=plays`], ['admin-changes', `${A}/logs?tab=changes`], ['admin-maintenance', `${A}/maintenance`],
  ['admin-backups', `${A}/backups`], ['admin-app', `${A}/app`],
];

// P1: nothing said only under a mouse pointer. No title anywhere on the pages (a title shows to a mouse alone: a finger and
// the keyboard never see it); every mark with words of its own (data-tip) is reached by the keyboard; and its words show,
// whole and on top, when it has the focus (gone with Escape), when a finger presses it (gone with a second press, or a press
// elsewhere), and under a mouse pointer (gone when the pointer leaves).
async function hoverOnly(contexts) {
  for (const [width, height] of [[360, 740], [1280, 800]]) {
    const touch = width < 700;
    const page = await contexts.signed.newPage();
    await page.setViewport({ width, height, ...(touch ? { isMobile: true, hasTouch: true } : {}) });
    const at = `${width}px`;
    for (const [name, url] of PATTERN_PAGES) {
      await page.goto(url, { waitUntil: 'domcontentloaded' });
      await pause(400);
      const found = await page.evaluate(() => ({
        titled: [...document.querySelectorAll('body [title]')].filter(e => !e.closest('svg') && e.tagName !== 'IFRAME')
          .map(e => `${e.tagName.toLowerCase()}${typeof e.className === 'string' && e.className ? '.' + e.className.split(' ')[0] : ''}: ${e.getAttribute('title').slice(0, 30)}`),
        unreached: [...document.querySelectorAll('[data-tip]')].filter(e => e.tabIndex < 0)
          .map(e => `${e.tagName.toLowerCase()}${typeof e.className === 'string' && e.className ? '.' + e.className.split(' ')[0] : ''}`),
        tips: document.querySelectorAll('[data-tip]').length,
      }));
      const titled = [...new Set(found.titled)];
      check(`nothing on ${name} is said only under a mouse pointer: no title, every mark's words reached by the keyboard (${at})`,
        found.titled.length === 0 && found.unreached.length === 0,
        `${found.titled.length} titles: ${titled.slice(0, 4).join(' ; ')} | ${found.unreached.length} marks out of the keyboard's reach: ${[...new Set(found.unreached)].slice(0, 3).join(' ; ')}`);
      if (!found.tips) continue;
      // The first mark and the last one on the page that a person can reach: drawn, a few pixels at least.
      const marks = await page.$$eval('[data-tip]', all => all.map((e, i) => {
        const r = e.getBoundingClientRect();
        return r.width >= 4 && r.height >= 4 && getComputedStyle(e).visibility !== 'hidden' ? i : -1;
      }).filter(i => i >= 0));
      for (const index of [marks[0], marks[marks.length - 1]].filter((v, i, a) => v !== undefined && a.indexOf(v) === i)) {
        const mark = (await page.$$('[data-tip]'))[index];
        if (!mark) continue;
        const words = await mark.evaluate(e => e.dataset.tip);
        await mark.evaluate(e => e.scrollIntoView({ block: 'center', inline: 'nearest' }));
        await pause(150);
        const shown = async () => page.evaluate(w => {
          const box = [...document.querySelectorAll('.chart-tip')].find(b => !b.hidden && getComputedStyle(b).display !== 'none');
          return !!box && box.textContent === w;
        }, words);
        const where = `${name}, mark ${index + 1}, ${at}`;
        // The keyboard: its focus shows the words, whole and on top; Escape takes them away. (By the page's own focus(): a
        // chart's mark is a drawing's part, which the test's own way to focus refuses.)
        await mark.evaluate(e => e.focus());
        await pause(150);
        const focused = await shown();
        const whole = await wholeOnTop(page, '.chart-tip:not([hidden])');
        await page.keyboard.press('Escape');
        await pause(150);
        const escaped = !(await shown());
        check(`a mark's words show on its keyboard focus, whole and on top, and go with Escape (${where})`, focused && whole.ok && escaped,
          `${focused} ${whole.detail} ${escaped}`);
        await page.evaluate(() => document.activeElement && document.activeElement.blur());
        const box = await mark.boundingBox();
        if (!box) continue;
        const x = box.x + box.width / 2, y = box.y + box.height / 2;
        if (touch) {
          // A finger: a press shows them, a second press takes them away, and a press elsewhere too.
          await page.touchscreen.tap(x, y);
          await pause(200);
          const tapped = await shown();
          await page.touchscreen.tap(x, y);
          await pause(200);
          const again = !(await shown());
          await page.touchscreen.tap(x, y);
          await pause(200);
          // Elsewhere: the nearest point of the screen where a press does nothing (no link, button, field or mark there).
          const elsewhere = await page.evaluate(() => {
            for (let y = 80; y < innerHeight - 80; y += 12) {
              for (let x = 6; x < innerWidth - 6; x += 12) {
                const hit = document.elementFromPoint(x, y);
                if (hit && !hit.closest('a, button, input, select, textarea, summary, label, [data-tip], [tabindex], video, .nav, .tabbar')) return [x, y];
              }
            }
            return null;
          });
          if (elsewhere) await page.touchscreen.tap(elsewhere[0], elsewhere[1]);
          await pause(200);
          const away = !(await shown());
          check(`a mark's words show when a finger presses it, and go with a second press or a press elsewhere (${where})`, tapped && again && away,
            `${tapped} ${again} ${away}`);
        } else {
          // A mouse: over the mark they show, away from it they go.
          await page.mouse.move(x, y);
          await pause(150);
          const over = await shown();
          await page.mouse.move(2, height - 2);
          await pause(150);
          const left = !(await shown());
          check(`a mark's words show under the mouse pointer and go when it leaves (${where})`, over && left, `${over} ${left}`);
        }
      }
    }
    await page.close();
  }
}

// P7: a switch or a small change on the owner's pages changes the page where it is, without loading the whole page again
// (which flashed it white and lost what was in view): the page's own state changes in place, the server's words come as the
// pages' message at the foot of the screen, and the page itself is the same one (a mark set on it before is still there).
// Without scripts the same buttons still work, by loading the page again.
async function sameWay(page, press, changed, arg) {
  // A mark on the page as it is, and no message left from before.
  await page.evaluate(() => { window.odqSamePage = 'yes'; for (const m of document.querySelectorAll('.flash.float')) m.remove(); });
  const navigated = page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 8000 }).then(() => 'loaded again', () => '');
  await press();
  const done = await Promise.race([navigated, page.waitForFunction(changed, { timeout: 8000 }, arg).then(() => 'changed', () => 'unchanged')]);
  // The server's words, which come with the change.
  await page.waitForSelector('.flash.float', { timeout: 5000 }).catch(() => {});
  await pause(200);
  const same = await page.evaluate(() => window.odqSamePage === 'yes').catch(() => false);
  const said = await page.$eval('.flash.float', e => e.textContent.trim()).catch(() => '');
  const now = await page.evaluate(changed, arg).catch(() => false);
  return { ok: same && now && said !== '', detail: `${done}; same page ${same}; changed ${now}; said "${said.slice(0, 60)}"` };
}

async function inPlace(contexts) {
  const page = await contexts.signed.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  // The Players page: a player's switch on, then off again, each in place.
  await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
  const sw = 'button[form="player-switch"][formaction^="/opendmtq/admin/players/3?"]';
  const stateOf = sel => document.querySelector(sel) && document.querySelector(sel).closest('tr').querySelector('.live-state').className;
  const before = await page.evaluate(stateOf, sw);
  const on = await sameWay(page, () => page.click(sw), ([sel, was]) => {
    const b = document.querySelector(sel);
    return !!b && b.closest('tr').querySelector('.live-state').className !== was;
  }, [sw, before]);
  check("a player's broadcast switch changes their row in place, with the server's words, without loading the page again", on.ok, on.detail);
  const after = await page.evaluate(stateOf, sw);
  const off = await sameWay(page, () => page.click(sw), ([sel, was]) => {
    const b = document.querySelector(sel);
    return !!b && b.closest('tr').querySelector('.live-state').className !== was;
  }, [sw, after]);
  check('and back off the same way', off.ok, off.detail);
  // The Broadcasts page: the server's switch on and off again.
  await page.goto(`${A}/recordings`, { waitUntil: 'domcontentloaded' });
  const word = () => document.querySelector('#broadcasts .auto-line b').textContent;
  const was = await page.evaluate(word);
  const flip = () => page.click('#broadcasts button[name=action][value^="broadcasts-"]').then(async () => {
    // Turning them off with someone on air asks first: yes.
    if (await page.$('#ask[open]')) await page.click('#ask [value=yes]');
  });
  const server1 = await sameWay(page, flip, w => document.querySelector('#broadcasts .auto-line b').textContent !== w, was);
  const was2 = await page.evaluate(word);
  const server2 = await sameWay(page, flip, w => document.querySelector('#broadcasts .auto-line b').textContent !== w, was2);
  check("the Broadcasts page's switch for the server changes the page in place, both ways", server1.ok && server2.ok, `${server1.detail} | ${server2.detail}`);
  // What new players start with and the quality, saved in place.
  const saved = await sameWay(page, () => page.click('#broadcasts form:has(input[name=action][value=settings]) button'), () => !!document.querySelector('.flash.float'));
  check("the Broadcasts page's settings are saved in place", saved.ok, saved.detail);
  // The Accounts page: an account switched off and on again.
  await page.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
  const stateText = () => document.querySelector('tr:has(input[value="manager"]) .account-state').textContent.trim();
  const acc = await page.evaluate(stateText);
  const accOff = await sameWay(page, () => page.click('tr:has(td.primary) form:has(input[value=off]):has(input[value="manager"]) button'),
    w => { const c = document.querySelector('tr:has(input[value="manager"]) .account-state'); return !!c && c.textContent.trim() !== w; }, acc);
  const acc2 = await page.evaluate(stateText);
  const accOn = await sameWay(page, () => page.click('tr:has(td.primary) form:has(input[value=on]):has(input[value="manager"]) button'),
    w => { const c = document.querySelector('tr:has(input[value="manager"]) .account-state'); return !!c && c.textContent.trim() !== w; }, acc2);
  check('an account is switched off and on again in place', accOff.ok && accOn.ok, `${accOff.detail} | ${accOn.detail}`);
  // The Songs page: a song hidden and shown again.
  await page.goto(`${A}/songs`, { waitUntil: 'domcontentloaded' });
  const hidden = () => !!document.querySelector('tr[data-n="2"] .mark.off');
  const hide = await sameWay(page, () => page.click('tr[data-n="2"] form:has(input[name=action][value=hide]) button'), () => !!document.querySelector('tr[data-n="2"] .mark.off'));
  const show = await sameWay(page, () => page.click('tr[data-n="2"] form:has(input[name=action][value=show]) button'), () => !document.querySelector('tr[data-n="2"] .mark.off'));
  check('a song is hidden and shown again in place', hide.ok && show.ok && !(await page.evaluate(hidden)), `${hide.detail} | ${show.detail}`);
  // The Maintenance page: on (it asks first), then off.
  await page.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
  const maintWord = () => document.querySelector('.auto-line b').textContent;
  const m1 = await page.evaluate(maintWord);
  const mOn = await sameWay(page, async () => { await page.click('button[name=action][value=on]'); await page.waitForSelector('#ask[open]'); await page.click('#ask [value=yes]'); },
    w => document.querySelector('.auto-line b').textContent !== w, m1);
  const m2 = await page.evaluate(maintWord);
  const mOff = await sameWay(page, () => page.click('button[name=action][value=off]'), w => document.querySelector('.auto-line b').textContent !== w, m2);
  check('maintenance is turned on and off again in place', mOn.ok && mOff.ok, `${mOn.detail} | ${mOff.detail}`);
  await page.screenshot({ path: path.join(OUT, 'shots', 'patterns-in-place-maintenance-1280.jpg'), type: 'jpeg', quality: 80 });
  await page.close();
  // Without scripts the switch still works: the page loads again with the change and the server's words.
  const plain = await contexts.signed.newPage();
  await plain.setJavaScriptEnabled(false);
  await plain.setViewport({ width: 1280, height: 800 });
  await plain.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
  const plainBefore = await plain.$eval(sw, b => b.textContent.trim());
  await Promise.all([plain.waitForNavigation({ waitUntil: 'domcontentloaded' }), plain.click(sw)]);
  const plainAfter = await plain.$eval(sw, b => b.textContent.trim());
  const plainSaid = await textOf(plain, '.flash');
  await Promise.all([plain.waitForNavigation({ waitUntil: 'domcontentloaded' }), plain.click(sw)]);
  check("without scripts a player's switch still works, by loading the page again", plainBefore !== plainAfter && /\S/.test(plainSaid), `${plainBefore} -> ${plainAfter}: ${plainSaid}`);
  await plain.close();
}

// P9: the owner's other forms as the sign-in is: every field named by a label; a field that cannot go as it is said right
// under it (not in a message at the top of the page), with the focus on it; the search boxes marked as what they are.
async function formsLook(contexts) {
  const FORMS = [
    ['Make an account', `${A}/accounts`, '.account-form', 'input[name=name]', 'a', '.account-form button.btn-primary'],
    ['Make token', `${A}/accounts`, '#tokens form', 'input[name=token_name]', '', '#tokens form button:not([type=button])'],
    ["the setup's account", `${A}/setup?step=players`, 'form[action$="/setup/player"]', 'input[name=name]', '!', 'form[action$="/setup/player"] button'],
    ["the recordings' limits", `${A}/recordings`, '.rec-limits', 'input[name=cap_gb]', '0', '.rec-limits button'],
    ['Add song', `${A}/songs`, 'form.upload', 'input[name=package]', null, 'form.upload button.btn-primary'],
  ];
  for (const [width, height] of [[360, 740], [1280, 800]]) {
    for (const lang of ['en', 'ko']) {
      const page = await contexts.signed.newPage();
      await page.setViewport({ width, height, ...(width < 700 ? { isMobile: true, hasTouch: true } : {}) });
      await page.setCookie({ name: 'opendmtq_lang', value: lang, url: ADMIN });
      const at = `${width}px, ${lang}`;
      for (const [name, url, form, field, bad, send] of FORMS) {
        await page.goto(url, { waitUntil: 'domcontentloaded' });
        const named = await page.$$eval(`${form} :is(input, select, textarea):not([type=hidden])`, all => all.filter(f => {
          const r = f.getBoundingClientRect();
          return r.width > 0 && !(f.labels && f.labels.length) && !f.getAttribute('aria-label') && !f.getAttribute('aria-labelledby');
        }).map(f => f.name));
        if (bad !== null) await page.$eval(`${form} ${field}`, (f, v) => { f.value = v; }, bad);
        await page.$eval(send, b => b.scrollIntoView({ block: 'center' }));
        await page.click(send);
        await pause(400);
        const said = await page.evaluate((formSel, fieldSel) => {
          const f = document.querySelector(`${formSel} ${fieldSel}`);
          const ids = (f.getAttribute('aria-describedby') || '').split(' ').filter(Boolean);
          const words = ids.map(id => document.getElementById(id)).find(Boolean);
          if (!words) return { found: false };
          // The field's own box: a file field is the drop box around it.
          const own = (f.type === 'file' ? f.closest('.drop') : f).getBoundingClientRect(), w = words.getBoundingClientRect();
          return { found: true, text: words.textContent.trim(), gap: Math.round(w.top - own.bottom), atTop: !!words.closest('main > .flash, .form-says.flash'),
            focus: document.activeElement === f, invalid: f.getAttribute('aria-invalid') === 'true' };
        }, form, field);
        check(`${name}: every field named, and what is wrong said right under the field, the focus on it (${at})`,
          named.length === 0 && said.found && said.text !== '' && said.gap >= 0 && said.gap <= 60 && !said.atTop && said.focus && said.invalid,
          `${named.length ? 'unnamed: ' + named.join(',') + '; ' : ''}${JSON.stringify(said)}`);
        if (name === 'Make an account') await page.screenshot({ path: path.join(OUT, 'shots', `patterns-form-account-${lang}-${width}.jpg`), type: 'jpeg', quality: 80 });
      }
      // The search boxes: each marked as one (its magnifier) and named for screen readers.
      for (const [name, url, box] of [['players', `${A}/players`, '#player-search'], ['songs', `${A}/songs`, 'input.search'], ["the site's songs", `${P}/songs.php`, 'input[type=search]']]) {
        await page.goto(url, { waitUntil: 'domcontentloaded' });
        const look = await page.$eval(box, b => ({ icon: getComputedStyle(b).backgroundImage, named: !!(b.getAttribute('aria-label') || (b.labels && b.labels.length)) })).catch(() => null);
        check(`the ${name} search box shows a magnifier and has a name (${at})`, !!look && /url\(/.test(look.icon) && look.named, JSON.stringify(look));
      }
      await page.close();
    }
  }
}

async function portalFlows(contexts) {
  // A stranger: the sign-in page first, whatever page was asked for, with nothing of what is inside, and that page after
  // signing in. In a browser of its own: signing in here would sign in the other signed-out pages of this run.
  const own = await contexts.browser.createBrowserContext();
  const fresh = await own.newPage();
  await fresh.setExtraHTTPHeaders({ 'Accept-Language': 'ko-KR,ko;q=0.9' });
  await fresh.goto(`${P}/ranking.php`, { waitUntil: 'domcontentloaded' });
  check('a stranger gets the sign-in page first', new URL(fresh.url()).pathname === '/opendmtq/login.php' && await visible(fresh, '.signin-form'), fresh.url());
  check('and nothing of what is inside', (await fresh.$$('.nav, .tabbar, .onair, .site-alert, .stage, main .card:not(.signin)')).length === 0);
  // English until the visitor picks otherwise, whatever the browser's language.
  check('a browser set to Korean first sees English', await fresh.$eval('html', e => e.lang) === 'en');
  await press(fresh, '.lang-switch a:not(.on)');
  check('the language switch changes the page', await fresh.$eval('html', e => e.lang) === 'ko');
  await press(fresh, '.lang-switch a:not(.on)');
  check('and back', await fresh.$eval('html', e => e.lang) === 'en');
  await typeId(fresh, 'input[name=user]', 'dmtq');
  await fresh.type('input[name=password]', PASSWORD);
  await press(fresh, '.signin-form button[type=submit]');
  check('signing in leads to the page asked for', new URL(fresh.url()).pathname === '/opendmtq/ranking.php', fresh.url());
  await own.close();
  // The front page: the big logo carries the server's version, and what the site is for comes first, the app one press
  // away (its size and date, the way to the steps) and the way to the broadcasts.
  const front = await contexts.signed.newPage();
  const arrived = await front.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
  // The release (run.sh passes 0.9.3-abc1234, as a clone past a release's tag has it): v0.9.3, the commit in its words
  // (data-tip: under a pointer, on a press, on the focus).
  check('the home page shows the version beside the logo', /v\d+\.\d+\.\d+$/.test((await textOf(front, '.stage-mark')).trim())
    && await front.$eval('.server-ver', e => e.dataset.tip) === 'abc1234', await textOf(front, '.stage-mark'));
  check('the front page offers the app and the broadcasts first',
    await front.$eval('.stage-acts .button', a => new URL(a.href).pathname).catch(() => '') === '/apk' && await visible(front, '#watch-live') && await visible(front, '.stage-meta a[href="download.php"]'));
  // The site's answers, its pages, files and JSON alike, are never shown inside another site's page, never taken for
  // another type than they say, and never tell another site the address of the page they were on (site.conf).
  const guarded = ['x-frame-options', 'x-content-type-options', 'referrer-policy'];
  const fetched = await front.evaluate(async names => Promise.all(['/opendmtq/style.css', '/opendmtq/live.js', '/opendmtq/client.php?about']
    .map(async u => { const r = await fetch(u); return names.map(n => r.headers.get(n)).join(' '); })), guarded);
  const said = [guarded.map(n => arrived.headers()[n]).join(' '), ...fetched];
  check('the site is never framed, sniffed or named to another site', said.every(s => s === 'DENY nosniff same-origin'), JSON.stringify(said));
  // The site's own files come by their versions (lib.php asset_url()), which a browser keeps a year without asking, so
  // that an upgrade's pages never meet an older stylesheet; without a version it asks each time (the admin pages' way to
  // them); fonts carry their versions in their names (site.conf).
  const kept = await front.evaluate(async () => {
    const css = document.querySelector('link[rel=stylesheet]').getAttribute('href');
    const scripts = [...document.scripts].map(x => x.getAttribute('src')).filter(Boolean);
    const said = async u => (await fetch(u, { cache: 'no-store' })).headers.get('cache-control');
    return { css, scripts, versioned: await said(css), bare: await said('/opendmtq/style.css'), font: await said('/opendmtq/fonts/dmtq-wide-800.woff2') };
  });
  check('the site names its own files by their versions, and a browser keeps them a year',
    /^\/opendmtq\/style\.css\?v=\d+$/.test(kept.css) && kept.scripts.length > 0 && kept.scripts.every(x => /^\/opendmtq\/[a-z]+\.js\?v=\d+$/.test(x))
    && kept.versioned === 'max-age=31536000, immutable' && kept.bare === 'no-cache' && kept.font === 'max-age=31536000, immutable', JSON.stringify(kept));
  // Only an answer that depends on Accept says so (Vary: Accept, site.conf): the site's files are one answer for every
  // cache, and an address with nothing there still answers a browser with the site's page and anything else short.
  const varied = await front.evaluate(async () => {
    const ask = async (u, accept) => {
      const r = await fetch(u, { cache: 'no-store', headers: accept ? { Accept: accept } : {} });
      return [r.status, (r.headers.get('vary') || '').split(',').map(v => v.trim().toLowerCase()).includes('accept'), (await r.text()).length];
    };
    return [await ask('/opendmtq/style.css'), await ask('/opendmtq/fonts/dmtq-wide-800.woff2'), await ask('/opendmtq/favicon.svg'),
      await ask('/opendmtq/no-such-page', 'text/html'), await ask('/opendmtq/no-such-page.png', 'image/png')];
  });
  check('only the answers that depend on Accept say so', varied.slice(0, 3).every(([status, vary]) => status === 200 && !vary)
    && varied[3][0] === 404 && varied[3][2] > 1000 && varied[4][0] === 404 && varied[4][2] < 400, JSON.stringify(varied));
  await front.close();
  // The download page's part for computers: the installer for Windows (the PC client), its button the site's /windows,
  // which hands a signed-in visitor the installer with this server's address on its end and sends a stranger to the
  // sign-in page first.
  const dl = await contexts.signed.newPage();
  await dl.goto(`${P}/download.php`, { waitUntil: 'domcontentloaded' });
  check('the download page offers the installer for Windows', await dl.$eval('#computer .button', a => new URL(a.href).pathname).catch(() => '') === '/windows');
  const setup = await dl.evaluate(async () => {
    const r = await fetch('/windows');
    const body = new Uint8Array(await r.arrayBuffer());
    // The installer's last bytes: the server's details, their length and the mark.
    return [r.status, r.headers.get('content-type'), r.headers.get('content-disposition'), new TextDecoder().decode(body.slice(-300))];
  });
  check('and /windows hands a signed-in visitor the installer set up for this server',
    setup[0] === 200 && /portable-executable/.test(setup[1] || '') && /OpenDMTQ-PC-Client-[0-9A-Za-z.+-]*-?windows-x64-Setup-/.test(setup[2] || '') &&
    setup[3].endsWith('OPENDMTQ-PRESET1') && setup[3].includes(`"url":"${SITE}"`), JSON.stringify(setup.slice(0, 3)));
  // A broken download goes on where it stopped, the app's (a hundred megabytes and more on a phone's network) and the
  // installer's alike (apk.php, windows.php): the headers that say so, a part as asked (the last 200 bytes, which for the
  // installer reach from its own bytes into the server's details after them), the whole again once the file is another
  // (If-Range, and If-Match as Android's downloads ask), and nothing past the end.
  const resumed = await dl.evaluate(async () => {
    const out = {};
    for (const path of ['/apk', '/windows']) {
      const whole = new Uint8Array(await (await fetch(path)).arrayBuffer());
      const head = await fetch(path, { method: 'HEAD' });
      const tag = head.headers.get('etag'), size = whole.length;
      const part = await fetch(path, { headers: { Range: `bytes=${size - 200}-`, 'If-Range': tag } });
      const got = new Uint8Array(await part.arrayBuffer());
      const other = await fetch(path, { headers: { Range: 'bytes=0-9', 'If-Range': '"another"' } });
      const otherSize = (await other.arrayBuffer()).byteLength;
      const moved = await fetch(path, { headers: { Range: 'bytes=0-9', 'If-Match': '"another"' } });
      const past = await fetch(path, { headers: { Range: `bytes=${size}-` } });
      out[path] = {
        // What a download manager reads before it trusts a part: one of bytes, a strong tag, the file's time.
        offered: head.headers.get('accept-ranges') === 'bytes' && /^"[^"]+"$/.test(tag || '') && !!head.headers.get('last-modified'),
        part: part.status === 206 && part.headers.get('content-range') === `bytes ${size - 200}-${size - 1}/${size}`
          && got.length === 200 && got.every((b, i) => b === whole[size - 200 + i]),
        another: other.status === 200 && otherSize === size,
        moved: moved.status === 412,
        past: past.status === 416 && past.headers.get('content-range') === `bytes */${size}`,
      };
    }
    return out;
  });
  check('a broken download of the app or the installer goes on where it stopped',
    Object.values(resumed).every(r => Object.values(r).every(Boolean)), JSON.stringify(resumed));
  // What the PC client asks the site (client.php): whether it is an OpenDMTQ server, then the app on offer, which only a
  // signed-in visitor gets.
  const asked = await dl.evaluate(async () => {
    const about = await (await fetch('/opendmtq/client.php?about')).json();
    const app = await fetch('/opendmtq/client.php?app');
    return [about, app.status, await app.json()];
  });
  check('the PC client finds the server and, signed in, the app on offer',
    asked[0].app === true && typeof asked[0].address === 'string' && asked[1] === 200 && /\.apk$/.test(asked[2].file || ''), JSON.stringify(asked));
  await dl.close();
  const stranger = await contexts.anon.newPage();
  await stranger.goto(`${SITE}/windows`, { waitUntil: 'domcontentloaded' });
  check('a stranger asking for /windows gets the sign-in first', new URL(stranger.url()).pathname === '/opendmtq/login.php' && new URL(stranger.url()).searchParams.get('next') === '/windows', stranger.url());
  // The client's sign-in: a wrong password says so as JSON, and the app stays closed to a stranger.
  const refused = await stranger.evaluate(async () => {
    const wrong = await fetch('/opendmtq/client.php?signin', { method: 'POST', body: new URLSearchParams({ user: 'dmtq', password: 'wrong' }) });
    const app = await fetch('/opendmtq/client.php?app');
    return [wrong.status, await wrong.json(), app.status];
  });
  check("the PC client's sign-in refuses a wrong password, and the app needs a sign-in",
    refused[0] === 401 && refused[1].error === 'wrong' && refused[2] === 403, JSON.stringify(refused));
  await stranger.close();
  // The right password, in a browser of its own: the site's cookie, which the client keeps in place of the password.
  const clientSide = await contexts.browser.createBrowserContext();
  const client = await clientSide.newPage();
  await client.goto(`${P}/client.php?about`, { waitUntil: 'domcontentloaded' });
  const signedIn = await client.evaluate(async password => {
    const r = await fetch('/opendmtq/client.php?signin', { method: 'POST', body: new URLSearchParams({ user: 'dmtq', password }) });
    const app = await fetch('/opendmtq/client.php?app');
    return [r.status, await r.json(), app.status];
  }, PASSWORD);
  check("the PC client's sign-in gives the site's cookie, and with it the app", signedIn[0] === 200 && signedIn[1].account === 'dmtq' && signedIn[2] === 200,
    JSON.stringify(signedIn));
  await clientSide.close();

  // A wrong password says so and keeps the form.
  const login = await contexts.anon.newPage();
  await login.setViewport({ width: 360, height: 740, isMobile: true, hasTouch: true });
  await login.goto(`${P}/login.php?next=%2Fapk`, { waitUntil: 'domcontentloaded' });
  await typeId(login, 'input[name=user]', 'dmtq');
  await login.type('input[name=password]', 'wrong');
  await Promise.all([login.waitForNavigation({ waitUntil: 'domcontentloaded' }), login.keyboard.press('Enter')]);
  // (The note for iPhones stands above the form, hidden elsewhere: the error is what says it.)
  check('a wrong password says so', await visible(login, '.signin .error'));
  await noFindings(login, 'wrong password on a phone');
  await login.close();

  // The text face in two files by script (style.css, unicode-range): the sign-in in English, every visitor's first page,
  // takes the Latin one alone; in Korean the Hangul one too, its Korean drawn in the site's face. Each in a browser of its
  // own, with nothing kept from before.
  const facesOf = async lang => {
    const own = await contexts.browser.createBrowserContext();
    const p = await own.newPage();
    const got = [];
    p.on('response', r => { if (/\/fonts\/dmtq-text-/.test(r.url())) got.push(r.url().split('/').pop()); });
    await p.setCookie({ name: 'opendmtq_lang', value: lang, url: SITE });
    await p.goto(`${P}/login.php`, { waitUntil: 'networkidle0' });
    const drawn = await p.evaluate(() => document.fonts.ready.then(() => document.fonts.check('16px "DMTQ Text"', '로그인')));
    await own.close();
    return [got.sort(), drawn];
  };
  const faces = [await facesOf('en'), await facesOf('ko')];
  check('a page in English takes the Latin half of the text face alone, a page in Korean the Hangul half too',
    JSON.stringify(faces[0][0]) === '["dmtq-text-2-latin.woff2"]' && JSON.stringify(faces[1][0]) === '["dmtq-text-2-hangul.woff2","dmtq-text-2-latin.woff2"]'
    && faces[1][1], JSON.stringify(faces));

  // A field left empty: the page's own check says what is missing, in the page's language, right under that field, and
  // the field takes the focus (forms.js), where the browser's bubble said it in the browser's language. The form stays.
  for (const [lang, noId, noPassword] of [['en', 'Enter your ID.', 'Enter your password.'], ['ko', '아이디를 입력하세요.', '비밀번호를 입력하세요.']]) {
    const empty = await contexts.anon.newPage();
    await empty.setViewport({ width: 360, height: 740, isMobile: true, hasTouch: true });
    await empty.setCookie({ name: 'opendmtq_lang', value: lang, url: SITE });
    await empty.goto(`${P}/login.php`, { waitUntil: 'domcontentloaded' });
    // No ID kept from this browser's earlier sign-ins: both fields empty.
    await empty.evaluate(() => localStorage.clear());
    await empty.reload({ waitUntil: 'domcontentloaded' });
    await empty.click('.signin-form button[type=submit]');
    // The words under the field they are about.
    const under = name => empty.$eval(`.field:has(input[name=${name}]) .field-error`, e => e.textContent).catch(() => '');
    const first = [await under('user'), await empty.evaluate(() => document.activeElement.name)];
    await typeId(empty, 'input[name=user]', 'dmtq');
    await empty.click('.signin-form button[type=submit]');
    const second = [await under('password'), await empty.evaluate(() => document.activeElement.name),
      await empty.$eval('input[name=password]', e => e.getAttribute('aria-invalid'))];
    check(`a field left empty is said by the site in its own words (${lang})`, first[0] === noId && first[1] === 'user'
      && second[0] === noPassword && second[1] === 'password' && second[2] === 'true' && new URL(empty.url()).pathname === '/opendmtq/login.php',
      JSON.stringify([first, second]));
    await noFindings(empty, `a field left empty on a phone (${lang})`);
    await empty.close();
  }
  // A form sent without that check (a browser without scripts) gets the same words from the server, and an empty form is
  // no guess at a password: ten of them, more than one address may fail, and the right password still signs in.
  const blank = await contexts.browser.createBrowserContext();
  const sender = await blank.newPage();
  await sender.goto(`${P}/login.php`, { waitUntil: 'domcontentloaded' });
  const blanks = await sender.evaluate(async password => {
    const said = [];
    for (let i = 0; i < 10; i++) {
      const r = await fetch('/opendmtq/login.php', { method: 'POST', body: new URLSearchParams({ user: i % 2 ? 'dmtq' : '', password: '' }) });
      // The server's words for a field left empty, under that field as the page's own check puts them.
      said.push((await r.text()).match(/<span class="field-error"[^>]*>([^<]*)</)?.[1] || '');
    }
    const right = await fetch('/opendmtq/login.php', { method: 'POST', body: new URLSearchParams({ user: 'dmtq', password }), redirect: 'manual' });
    return [said, right.type === 'opaqueredirect' || right.redirected];
  }, PASSWORD);
  check('an empty form is not counted as a wrong password', blanks[0].every((s, i) => s === (i % 2 ? 'Enter your password.' : 'Enter your ID.')) && blanks[1],
    JSON.stringify(blanks));
  await blank.close();

  // The game's own window: its score viewer is behind the sign-in, on a phone held sideways. The form, its button too, is
  // on the screen without scrolling, at a big phone's size and a small one's.
  for (const [width, height] of [[915, 412], [640, 320]]) {
    const game = await contexts.anon.newPage();
    await game.setViewport({ width, height, isMobile: true, hasTouch: true, isLandscape: true });
    await game.goto(`${P}/login.php?next=%2Fscore%2F`, { waitUntil: 'domcontentloaded' });
    const bottom = await game.$eval('.signin-form .button', b => Math.round(b.getBoundingClientRect().bottom)).catch(() => 9999);
    check(`the sign-in fits the game's window sideways (${width}x${height})`, bottom <= height, `button's foot at ${bottom}`);
    await noFindings(game, `the sign-in in the game's window (${width}x${height})`);
    await game.close();
  }

  // The rankings' This month tab: this month's players (the seed plays in the last days too), when it starts anew, and
  // under them the months before with their first three (the seed goes back months).
  const month = await contexts.signed.newPage();
  await month.setViewport({ width: 1280, height: 900 });
  await month.goto(`${P}/ranking.php?sort=month`, { waitUntil: 'domcontentloaded' });
  const onPodium = (await month.$$('.podium .pod')).length, monthsBefore = (await month.$$('.past-month')).length;
  // The day and the month are held together by a no-break space (lib.php month_moment()): \s in the text, &nbsp; in the
  // markup page.content() gives.
  const startsAnew = /Starts anew on \d+(?:\s|&nbsp;)\w+ at \d\d:\d\d/.test(await month.content());
  check("the month's tab ranks this month and keeps the months before", onPodium > 0 && monthsBefore > 0 && startsAnew, `${onPodium} on the podium, ${monthsBefore} months before, ${startsAnew}`);
  await month.close();

  // An account linked to its game player (the owner links it on the Accounts page): the site's top shows that player's
  // name leading to their page, and the rankings mark their place. Unlinked again afterwards, as the other views expect.
  const linker = await contexts.signed.newPage();
  await linker.setViewport({ width: 1280, height: 900 });
  const linkTo = async guid => {
    await linker.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
    await linker.select('form.account-link:has(input[name=name][value=dmtq]) select', guid);
    await Promise.all([linker.waitForNavigation({ waitUntil: 'domcontentloaded' }), linker.click('form.account-link:has(input[name=name][value=dmtq]) button')]);
  };
  await linkTo('1');
  await linker.goto(`${P}/ranking.php`, { waitUntil: 'domcontentloaded' });
  // The profile in the bar: the player's name (beside the badge and over the place and the account's ID), leading to their page.
  const me = await linker.$eval('.auth-who', e => [e.tagName, (e.querySelector('.who-name') || e).textContent, e.getAttribute('href') || '']).catch(() => []);
  const marked = (await linker.$$('.pod.me, .board tr.me')).length;
  check('a linked account shows its player and marks their place', me[0] === 'A' && me[1] === 'Sena' && me[2].endsWith('player.php?id=1') && marked === 1, `${me} ${marked}`);
  // Measured while linked too, where the player's own place shows: the name in the bar is a key of its own (a finger
  // can hit it), and the marked rows and podium card carry their ring.
  // Korean first and English last: a sweep leaves its last language in the browser's cookie, and the flows after this
  // one read English.
  await sweep(contexts, [['home, linked', `${P}/`], ['rankings, linked', `${P}/ranking.php`], ['this month, linked', `${P}/ranking.php?sort=month`],
                         ['a player, linked', `${P}/player.php?id=1`]], [412, 1280], ['ko', 'en']);
  // The bar fits at every width between a phone's and a desktop's: its sections never scroll sideways. With the longest
  // name linked (20 letters, player 4), the site held upright (the menu at the thumb up to 900 px) and on its side (the
  // sections in the top bar, smaller up to 1000 px, the profile its badge alone below 1100 px); the admin pages with the
  // game server's OFFLINE light on, where the profile is its badge alone (it pushed the pages 35 px out at 1280).
  await linkTo('4');
  const bar = await contexts.signed.newPage();
  const spill = async () => bar.$eval('.bar .nav', n => getComputedStyle(n).display === 'none' ? 0 : n.scrollWidth - n.clientWidth).catch(() => 0);
  const spilled = [];
  for (const [w, h] of [[760, 1000], [820, 1100], [900, 1200], [740, 400], [820, 420], [900, 500], [1024, 700], [1099, 760], [1100, 760], [1280, 800]]) {
    await bar.setViewport({ width: w, height: h });
    await bar.goto(`${P}/ranking.php`, { waitUntil: 'domcontentloaded' });
    const over = await spill();
    if (over > 1) spilled.push(`site ${w}x${h} ${over}px`);
  }
  for (const w of [740, 1024, 1180, 1200, 1240, 1241, 1280, 1600]) {
    await bar.setViewport({ width: w, height: 800 });
    await bar.goto(`${A}/`, { waitUntil: 'domcontentloaded' });
    await bar.evaluate(() => document.querySelector('.bar-end').insertAdjacentHTML('afterbegin', '<span class="state down"><i></i>OFFLINE</span>'));
    const over = await spill();
    if (over > 1) spilled.push(`admin ${w} ${over}px`);
  }
  check('the bar fits at every width, with the longest name and the OFFLINE light', spilled.length === 0, spilled.join(', '));
  await bar.close();
  await linkTo('');
  await linker.close();

  // The songs' search narrows the list, and says when nothing is left.
  const songs = await contexts.signed.newPage();
  await songs.setViewport({ width: 1280, height: 900 });
  await songs.goto(`${P}/songs.php`, { waitUntil: 'networkidle2' });
  const shown = () => songs.$$eval('#songs > *', tiles => tiles.filter(e => getComputedStyle(e).display !== 'none').length);
  const all = await shown();
  await songs.type('#search', 'Neon');
  await pause(300);
  const some = await shown();
  check('the song search narrows the list', some >= 1 && some < all, `${all} -> ${some}`);
  await songs.$eval('#search', e => { e.value = 'no such song anywhere'; e.dispatchEvent(new Event('input')); });
  await pause(300);
  check('and says when nothing is left', await shown() === 0 && await visible(songs, '#no-match'));
  await noFindings(songs, 'a song search with no result');
  // The charts by the names and in the order of the game's chart screen.
  await songs.goto(`${P}/song.php?id=1`, { waitUntil: 'domcontentloaded' });
  const names = await songs.$eval('.chart-row', row => [...row.querySelectorAll('a')].map(a => a.textContent.trim().split(' ')[0]));
  check('a song names its charts as the game does', names.join() === 'Easy,Normal,Hard,Expert', names.join());
  // The catalog beside the longest title there is (song 25's, five lines and more): no tile has a hole in it. Each one's
  // artist follows its title, its line of records follows the artist, and the tile ends there; and a row's tiles start on
  // one line.
  const catalog = await contexts.signed.newPage();
  await catalog.setViewport({ width: 1280, height: 900 });
  await catalog.goto(`${P}/songs.php`, { waitUntil: 'networkidle0' });
  const holes = await catalog.$$eval('#songs .song', tiles => tiles.map(t => {
    const box = r => t.querySelector(r).getBoundingClientRect();
    const [title, artist, records, all] = [box('.t'), box('.a'), box('.p'), t.getBoundingClientRect()];
    return { name: t.querySelector('.t').textContent.slice(0, 20), gaps: [artist.top - title.bottom, records.top - artist.bottom], end: all.bottom - records.bottom, top: Math.round(all.top) };
  }));
  const hollow = holes.filter(h => h.gaps.some(g => g > 4) || h.end > 12);
  const tops = new Set(holes.slice(0, 6).map(h => h.top));
  check('a long title leaves no hole in the song tiles beside it', holes.length > 6 && hollow.length === 0 && tops.size === 1,
    JSON.stringify(hollow.slice(0, 3)) + ` tops ${[...tops]}`);
  await catalog.close();
  await songs.close();
}

// The keyboard's mark (PAGE-36 to PAGE-39, ADM-93 to ADM-95): the PC client's player says a play was made with the keyboard,
// and the game server keeps it with the play and with the best that play set (seed.php writes them so: 민호 always, 유나 every
// fourth play). Held to what the database says (run.sh writes it to keys.json beside the report): each play and best a keyboard
// play made has the mark before its score, and no other; each total, month's score and past month's score that counts such
// bests has it with how many, worked out here from the plays themselves. Both languages, a phone's width and a laptop's.
const KEY_WORDS = { en: ['Keyboard play', n => (n === 1 ? 'Includes 1 keyboard record' : `Includes ${n} keyboard records`)],
  ko: ['키보드 플레이', n => `키보드 플레이 기록 ${n}개 포함`] };
async function keyboardMarks(contexts) {
  const truth = JSON.parse(fs.readFileSync(path.join(OUT, 'keys.json'), 'utf8'));
  // Every play [id, player, chart, score, when, keys, record] and every best [player, chart, score, keys], from the database.
  const plays = truth.plays, bests = truth.bests;
  const best = new Map(bests.map(([who, chart, score, keys]) => [`${who}-${chart}`, { score, keys: !!keys }]));
  // A month's scores as the game adds them up: each chart's top score that month (capped as the rankings cap it), the play
  // that got there first; a player's count is how many of those a keyboard play set. Months begin at midnight UTC.
  const monthKeys = (since, until) => {
    const top = new Map();
    for (const [id, who, chart, score, at, keys] of plays) {
      if (at < since || at >= until) continue;
      const capped = Math.min(Math.max(score, 0), 2147483647), k = `${who}-${chart}`, b = top.get(k);
      if (!b || capped > b.score || (capped === b.score && (at < b.at || (at === b.at && id < b.id)))) top.set(k, { score: capped, at, id, keys, who });
    }
    const out = {};
    for (const b of top.values()) if (b.keys) out[b.who] = (out[b.who] || 0) + 1;
    return out;
  };
  const monthStart = back => { const d = new Date(); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - back, 1) / 1000; };
  // How many of each player's bests a keyboard play set: what the rankings' totals count.
  const allTime = {};
  for (const [who, , , keys] of bests) if (keys) allTime[who] = (allTime[who] || 0) + 1;
  check('the stand-in players include keyboard plays and bests, and plays by touch', plays.some(p => p[5]) && plays.some(p => !p[5])
    && bests.some(b => b[3]) && bests.some(b => !b[3]) && !allTime[1], JSON.stringify(allTime));
  const wrong = [], hidden = [], shot = [], layout = [];
  // Views looked at, and marks whose place was measured: a measure of no mark at all would pass without seeing one.
  let viewsSeen = 0, marksPlaced = 0;
  // Every mark of a page with what it stands for: its row's key (player, chart, score as the row shows them) and its words.
  const read = page => page.evaluate(() => {
    const num = el => Number((el && el.textContent || '').replace(/[^0-9]/g, '')) || 0;
    const id = (a, key) => a ? Number(new URL(a.href, location.href).searchParams.get(key)) : 0;
    const mark = el => { const m = el && el.querySelector('.keys-mark'); return m ? [m.getAttribute('data-tip'), m.getAttribute('aria-label'), m.getAttribute('role')] : null; };
    // Each mark where it stands: on a line with what it marks, 4 to 8 px from it (before a score's first figure, or after a
    // name on the podium), at a phone's width too, whole and on the screen.
    const placed = [...document.querySelectorAll('.keys-mark')].map(m => {
      const r = m.getBoundingClientRect(), s = getComputedStyle(m);
      const after = !!m.closest('.pod-who');
      let text = after ? m.previousSibling : m.nextSibling;
      while (text && text.nodeType === 1 && !text.textContent.trim()) text = after ? text.previousSibling : text.nextSibling;
      const range = document.createRange();
      if (text) range.selectNodeContents(text);
      const t = text ? range.getBoundingClientRect() : { left: 0, right: 0, top: 0, bottom: 0 };
      const gap = after ? r.left - t.right : t.left - r.right, middle = (r.top + r.bottom) / 2 - (t.top + t.bottom) / 2;
      return { ok: s.display !== 'none' && s.visibility !== 'hidden' && Math.round(r.width) === 20 && Math.round(r.height) === 12 && r.left >= 0
        && r.right <= document.documentElement.clientWidth && !!text && gap >= 4 && gap <= 8 && Math.abs(middle) <= 4,
        at: `${m.parentElement.className || m.parentElement.tagName} ${Math.round(gap)}px ${Math.round(middle)}px` };
    });
    const rows = sel => [...document.querySelectorAll(sel)];
    return {
      placed,
      // A song's leaderboard: the player and the mark of each row.
      board: rows('table.board tbody tr').map(r => ({ who: id(r.querySelector('td.name a'), 'id'), mark: mark(r) })),
      // A player's page: their recent plays and best records (chart, score, mark), and the count beside the grades.
      lists: rows('.stack .card table.plays').map(t => [...t.querySelectorAll('tbody tr')].map(r => ({
        chart: id(r.querySelector('td.song-cell a'), 'chart'), score: num(r.querySelector('td.r')), mark: mark(r.querySelector('td.r')) }))),
      counted: rows('.grades .g-item').filter(g => g.querySelector('.keys-mark')).map(g => [num(g), mark(g)]),
      // The home page: the newest records (player, chart, score, mark) and the top players (player, mark).
      records: rows('#records .feed li').map(l => ({ who: id(l.querySelector('.who a'), 'id'), chart: id(l.querySelector('.what a'), 'chart'),
        score: num(l.querySelector('.feed-score > span:last-child')), mark: mark(l.querySelector('.feed-score')) })),
      top: rows('.feed.ranks li').map(l => ({ who: id(l.querySelector('.who a'), 'id'), mark: mark(l) })),
      // The rankings: the podium and the table (player, mark), and each month before (its name, its first three).
      ranked: [...rows('.podium .pod').map(p => ({ who: id(p.querySelector('.pod-name'), 'id'), mark: mark(p.querySelector('.pod-who')), pod: true })),
        ...rows('table.board tbody tr').map(r => ({ who: id(r.querySelector('td.name a'), 'id'), mark: mark(r) }))],
      months: rows('.past-month').map(m => ({ name: m.querySelector('h3').textContent.trim(),
        top: [...m.querySelectorAll('.past-top li')].map(l => ({ who: id(l.querySelector('a'), 'id'), mark: mark(l.querySelector('b')) })) })),
      // The admin pages' plays: the status page's newest and the Plays tab (player, score, mark).
      admin: rows('table.compact.recent tbody tr, table.playlog tbody tr').map(r => ({
        who: id(r.querySelector('td.who a'), 'id') || id(r.querySelector('td.primary a'), 'player'), score: num(r.querySelector('td.r')), mark: mark(r.querySelector('td.r')) })),
      all: document.querySelectorAll('.keys-mark').length,
    };
  });
  // A mark is as it should be: there when wanted (true: a play's or a best's; a number: a total's, counting that many), with
  // its words in the page's language, named for a screen reader; none when not (null).
  const same = (where, got, want, lang) => {
    const words = want === true ? KEY_WORDS[lang][0] : typeof want === 'number' && want > 0 ? KEY_WORDS[lang][1](want) : null;
    const ok = words === null ? got === null : !!got && got[0] === words && got[1] === words && got[2] === 'img';
    if (!ok) wrong.push(`${where}: ${JSON.stringify(got)}, wanted ${JSON.stringify(words)}`);
  };
  // What every row of a page should have, and the page's own marks, at a laptop's width in English, a phone's in Korean and in
  // English. In those three views the marks are where they belong and nowhere else.
  const views = [['en', 1280], ['ko', 360], ['en', 360]];
  const look = async (name, url, judge) => {
    for (const [lang, width] of views) {
      const page = await contexts.signed.newPage();
      await page.setViewport({ width, height: width < 500 ? 740 : 900, hasTouch: width < 500, isMobile: width < 500 });
      await page.setCookie({ name: 'opendmtq_lang', value: lang, url });
      await page.goto(url, { waitUntil: 'networkidle2' });
      const seen = await read(page);
      const before = wrong.length;
      judge(seen, lang, `${name} ${lang}${width}`);
      for (const p of seen.placed) if (!p.ok) hidden.push(`${name} ${lang}${width}: ${p.at}`);
      // Counted, so that the check of their places knows it measured some.
      marksPlaced += seen.placed.length;
      // The views with marks, for people to look at.
      if (seen.all) {
        await page.screenshot({ path: path.join(OUT, 'shots', `keys-${name}-${lang}-${width}.jpg`), type: 'jpeg', quality: 80, fullPage: true });
        shot.push(`${name}-${lang}-${width}`);
      }
      if (wrong.length > before) console.log(`  ${name} ${lang}${width}: ${seen.all} marks`);
      // The layout with the marks in it, as the sweeps measure every page (one check for all these views, below).
      for (const f of [...await audit(page), ...await twoPrimaries(page)]) layout.push(`${name} ${lang}${width}: ${f.kind} ${f.at} ${f.detail}`.slice(0, 160));
      viewsSeen++;
      await page.close();
    }
  };
  // Song boards: charts whose bests are some the keyboard's and some by touch, and one with none of the keyboard's.
  const charts = new Map();
  for (const [who, chart, , keys] of bests) {
    const c = charts.get(chart) || { keys: 0, touch: 0 };
    c[keys ? 'keys' : 'touch']++;
    charts.set(chart, c);
  }
  const mixed = [...charts].filter(([, c]) => c.keys && c.touch).map(([chart]) => chart).slice(0, 2);
  const plain = [...charts].filter(([, c]) => !c.keys && c.touch > 1).map(([chart]) => chart).slice(0, 1);
  let boardRows = 0;
  for (const chart of [...mixed, ...plain]) {
    await look(`song-chart-${chart}`, `${P}/song.php?id=${truth.songs[chart]}&chart=${chart}`, (seen, lang, at) => {
      for (const r of seen.board) same(`${at} player ${r.who}`, r.mark, best.get(`${r.who}-${chart}`).keys ? true : null, lang);
      boardRows += seen.board.length;
    });
  }
  check("a song's leaderboard marks the bests a keyboard play set, and no other", mixed.length === 2 && plain.length === 1 && boardRows > 6
    && wrong.length === 0, wrong.slice(0, 6).join(' ; '));
  // Players' pages: all of one's plays by keys, some of another's, none of Sena's.
  const before = wrong.length;
  for (const who of [2, 3, 1]) {
    await look(`player-${who}`, `${P}/player.php?id=${who}`, (seen, lang, at) => {
      const [recent = [], records = []] = seen.lists;
      for (const r of recent) {
        // The play of that chart and score. Two such plays that differ in the mark cannot tell the row: not judged.
        const found = plays.filter(p => p[1] === who && p[2] === r.chart && p[3] === r.score);
        if (!found.length) wrong.push(`${at} recent ${r.chart} ${r.score}: no such play`);
        else if (new Set(found.map(p => !!p[5])).size === 1) same(`${at} recent ${r.chart} ${r.score}`, r.mark, found[0][5] ? true : null, lang);
      }
      for (const r of records) same(`${at} best ${r.chart}`, r.mark, best.get(`${who}-${r.chart}`).keys ? true : null, lang);
      const count = bests.filter(b => b[0] === who && b[3]).length;
      if (count ? !(seen.counted.length === 1 && seen.counted[0][0] === count) : seen.counted.length) wrong.push(`${at} count ${JSON.stringify(seen.counted)} for ${count}`);
      for (const [, m] of seen.counted) same(`${at} count`, m, true, lang);
      if (!recent.length || !records.length) wrong.push(`${at}: no plays or records listed`);
    });
  }
  check("a player's page marks their plays and bests the keyboard made, and counts them beside the grades; none on a player who plays by touch",
    wrong.length === before, wrong.slice(before, before + 6).join(' ; '));
  // The home page: the newest records, and the top players' totals.
  const home = wrong.length;
  await look('home', `${P}/`, (seen, lang, at) => {
    for (const r of seen.records) {
      const found = plays.filter(p => p[1] === r.who && p[2] === r.chart && p[3] === r.score && p[6]);
      same(`${at} record ${r.who} ${r.chart} ${r.score}`, r.mark, found.length === 1 && found[0][5] ? true : null, lang);
    }
    for (const r of seen.top) same(`${at} top ${r.who}`, r.mark, allTime[r.who] || null, lang);
    if (!seen.records.some(r => r.mark) || !seen.top.some(r => r.mark)) wrong.push(`${at}: no mark among the records or the top players`);
  });
  check("the home page marks the newest records a keyboard play set, and the totals that count such bests with how many",
    wrong.length === home, wrong.slice(home, home + 6).join(' ; '));
  // The rankings: every tab of totals, this month (the month's own bests), and the months before.
  const ranks = wrong.length;
  // The podium of a tab that ranks another figure (S grades) shows that figure, which the count does not describe: no mark
  // there, for a player whose total has keyboard bests too (podiumKeys counts those, so that the look sees one at least).
  const podium = [];
  let podiumKeys = 0;
  for (const sort of ['total', 's_count']) {
    await look(`rankings-${sort}`, `${P}/ranking.php?sort=${sort}`, (seen, lang, at) => {
      for (const r of seen.ranked) {
        // The total's count: on every row of the table, and on the podium of the Total score tab.
        if (!r.pod || sort === 'total') {
          same(`${at} ${r.who}`, r.mark, allTime[r.who] || null, lang);
          continue;
        }
        // On the S grades tab's podium: none, whatever the total counts.
        podiumKeys += allTime[r.who] ? 1 : 0;
        if (r.mark) podium.push(`${at} podium ${r.who}: ${JSON.stringify(r.mark)}`);
      }
    });
  }
  const thisMonth = monthKeys(monthStart(0), Number.MAX_SAFE_INTEGER);
  // Months named, and month scores that should carry the mark among those looked at: the seed's keyboard plays go back weeks,
  // so there are some (this month's alone can have none in a month's first hours).
  let pastNamed = 0, monthMarks = 0;
  await look('rankings-month', `${P}/ranking.php?sort=month`, (seen, lang, at) => {
    for (const r of seen.ranked) {
      same(`${at} ${r.who}`, r.mark, thisMonth[r.who] || null, lang);
      monthMarks += thisMonth[r.who] ? 1 : 0;
    }
    // The months before with plays, newest first, as the page lists them; each by its name in English.
    const months = [];
    for (let back = 1; back <= 6; back++) {
      if (plays.some(p => p[4] >= monthStart(back) && p[4] < monthStart(back - 1))) months.push(back);
    }
    seen.months.forEach((m, i) => {
      const back = months[i], counts = monthKeys(monthStart(back), monthStart(back - 1));
      const name = new Date(monthStart(back) * 1000).toLocaleString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });
      if (lang === 'en' && m.name !== name) wrong.push(`${at} month ${i}: ${m.name}, wanted ${name}`);
      pastNamed++;
      for (const r of m.top) {
        same(`${at} ${m.name} ${r.who}`, r.mark, counts[r.who] || null, lang);
        monthMarks += counts[r.who] ? 1 : 0;
      }
    });
  });
  check("the rankings mark each total, this month's score and each past month's score that counts bests a keyboard play set, with how many",
    wrong.length === ranks && pastNamed > 0 && monthMarks > 0, wrong.slice(ranks, ranks + 6).join(' ; ') + ` ${pastNamed} months, ${monthMarks} marks`);
  check("the podium has the keyboard's count on the Total score and This month tabs alone, none beside S grades",
    podium.length === 0 && podiumKeys > 0, podium.slice(0, 6).join(' ; ') + ` (${podiumKeys} podium places with keyboard bests)`);
  // Nowhere else: pages that show no scores have no mark. The home page, looked at the same way, must have some: a look that
  // finds no mark anywhere would pass these pages without seeing anything.
  const nowhere = wrong.length;
  let control = 0;
  for (const [name, url] of [['songs', `${P}/songs.php`], ['live', `${P}/live.php`], ['download', `${P}/download.php`], ['home', `${P}/`]]) {
    const page = await contexts.signed.newPage();
    await page.setViewport({ width: 1280, height: 900 });
    await page.goto(url, { waitUntil: 'networkidle2' });
    const n = await page.$$eval('.keys-mark', ms => ms.length);
    // The home page is the look's control; every other page must have none.
    if (name === 'home') control = n;
    else if (n) wrong.push(`${name}: ${n} marks`);
    await page.close();
  }
  check('pages that show no score have no keyboard mark', wrong.length === nowhere && control > 0,
    wrong.slice(nowhere).join(' ; ') + ` (the home page, looked at the same way: ${control} marks)`);
  // The admin pages: the status page's newest plays and the Plays tab, by the player and the score of each row.
  const owner = wrong.length;
  let adminRows = 0;
  for (const [name, url] of [['admin-status', `${A}/`], ['admin-plays', `${A}/logs?tab=plays`]]) {
    await look(name, url, (seen, lang, at) => {
      for (const r of seen.admin) {
        const found = plays.filter(p => p[1] === r.who && p[3] === r.score);
        // Two plays of one player with one score that differ in the mark cannot tell the row: not judged.
        if (found.length && found.every(p => !!p[5] === !!found[0][5])) {
          same(`${at} ${r.who} ${r.score}`, r.mark, found[0][5] ? true : null, lang);
          adminRows++;
        }
      }
      if (!seen.admin.some(r => r.mark)) wrong.push(`${at}: no marked play`);
    });
  }
  check("the admin pages mark the plays a keyboard play made, on the status page and the Plays tab", wrong.length === owner && adminRows > 20,
    wrong.slice(owner, owner + 6).join(' ; ') + ` (${adminRows} rows)`);
  check("every keyboard mark stands beside what it marks, on its line, whole and on the screen, at a phone's width too",
    hidden.length === 0 && marksPlaced > 0, hidden.slice(0, 8).join(' ; ') + ` (${marksPlaced} marks measured)`);
  check(`the pages with keyboard marks: nothing wrong with the layout (${viewsSeen} views)`, layout.length === 0 && viewsSeen >= 30,
    layout.slice(0, 8).join(' ; '));
  console.log(`  pictures: ${shot.join(', ')}`);
}

// The replay player as a viewer uses it.
async function replayFlows(contexts) {
  const page = await contexts.signed.newPage();
  const errors = watch(page, `${P}/live.php`);
  await page.setViewport({ width: 1280, height: 800 });
  await page.goto(`${P}/live.php`, { waitUntil: 'domcontentloaded' });
  await pause(1500);
  // The newest recording of player 1 with its three songs; the list is newest first.
  const key = await page.$$eval('#past-list .past', links => {
    const withSongs = links.map(a => a.getAttribute('href')).filter(Boolean);
    return withSongs[withSongs.length - 1].replace(/^.*r=/, '');
  });
  await page.goto(`${P}/live.php?r=${key}`, { waitUntil: 'domcontentloaded' });
  await pause(3000);
  const now = () => page.$eval('#live-video', e => e.currentTime);
  check('a recording plays', await page.$eval('#live-video', e => !e.paused && e.currentTime > 0.3));
  check('marked as a replay', await textOf(page, '#pill-word') === 'REPLAY');
  check('with its timeline', await visible(page, '#ctl-track'));
  await page.mouse.move(500, 300);
  await pause(200);
  await page.screenshot({ path: path.join(OUT, 'shots', 'flows-replay-controls-1280.jpg'), type: 'jpeg', quality: 72 });
  await noFindings(page, 'the replay on a laptop');
  const before = await now();
  await page.click('#ctl-fwd');
  await pause(1200);
  check('+10 s', await now() > before + 9);
  await page.click('#ctl-rate');
  check('the speed button', await page.$eval('#live-video', e => e.playbackRate) === 1.25);
  await page.keyboard.press('KeyS');
  check('the speed key', await page.$eval('#live-video', e => e.playbackRate) === 1.5);
  for (let i = 0; i < 3; i++) await page.keyboard.press('KeyS');
  check('the speed comes round to normal', await page.$eval('#live-video', e => e.playbackRate) === 1);
  await page.click('#ctl-stats');
  await pause(1200);
  const stats = await textOf(page, '#live-stats');
  check('the connection details', /\d+×\d+/.test(stats) && /Mbit/.test(stats), stats.slice(0, 100));
  await page.click('#ctl-stats');
  // The first song begins where the timeline does, and needs no mark.
  check('the songs are marked on the timeline', (await page.$$('#ctl-marks .cut')).length === 2);
  check('and listed as chapters', (await page.$$('#chapter-list button, #chapter-list a')).length === 3);
  // Each with its song's jacket: the first one's picture loads, and is not the empty stand-in a song without one gets.
  const jacket = await page.waitForFunction(() => { const i = document.querySelector('#chapter-list img'); return !!i && i.complete && i.naturalWidth > 1; }, { timeout: 8000 }).then(() => true, () => false);
  check('each with its jacket', jacket, await page.$eval('#chapter-list img', i => i.currentSrc.slice(0, 90)).catch(() => 'no picture'));
  await page.$eval('#chapter-list button, #chapter-list a', e => e.click());
  await pause(800);
  // Left half-way, the page offers to go on from there.
  await page.$eval('#live-video', e => { e.currentTime = 30; });
  await pause(6000);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await pause(2500);
  check('coming back continues where it was left', await now() > 10);
  check('and says so', await visible(page, '#live-resume'));
  // To the end: what next.
  await page.$eval('#live-video', e => { e.currentTime = e.duration - 0.5; });
  await pause(2500);
  check('the end screen', await visible(page, '#live-end'));
  await page.click('#end-again');
  await pause(1500);
  check('watch again', await page.$eval('#live-video', e => !e.paused && e.currentTime < 8));
  // The list's search.
  await page.type('#past-search', 'no such thing');
  await pause(300);
  check('the recordings search says when nothing is found', await visible(page, '#past-none'));
  await page.$eval('#past-search', e => { e.value = ''; e.dispatchEvent(new Event('input')); });
  // Another recording from the list, without the page being loaded again.
  await page.evaluate(() => { window.stillHere = true; });
  await page.click('#past-list li:first-child a');
  await pause(2500);
  check('another recording from the list, without a reload', await page.evaluate(() => window.stillHere === true) && await page.$eval('#live-video', e => !e.paused));
  await page.goBack();
  await pause(1500);
  check('back returns to the one before', page.url().includes(key));
  check('the tab says whose recording it is', /Replay/.test(await page.title()) && (await page.title()).split(' · ').length === 3, await page.title());
  check('the heading says replay, not live', await textOf(page, '#mast .word') === 'REPLAY');
  // Back again, to the list with nobody on air: nothing goes on playing under the heading of another page.
  await page.goto(`${P}/live.php`, { waitUntil: 'domcontentloaded' });
  await pause(1000);
  await page.click('#past-list li:first-child a');
  await pause(2500);
  await page.goBack();
  await pause(1500);
  check('back from a recording to the list stops it', await page.$eval('#live-video', e => e.paused || !e.currentSrc) && await textOf(page, '#mast .word') === 'LIVE');
  check('no failed requests or script errors in all that', errors.length === 0, errors.slice(0, 5).join(' ; '));
  await page.close();

  // The same on a phone, with its controls in view.
  const phone = await contexts.signed.newPage();
  await phone.setViewport({ width: 360, height: 740, isMobile: true, hasTouch: true });
  await phone.goto(`${P}/live.php?r=${key}`, { waitUntil: 'domcontentloaded' });
  await pause(3000);
  await phone.tap('#live-video');
  await pause(300);
  await phone.screenshot({ path: path.join(OUT, 'shots', 'flows-replay-controls-360.jpg'), type: 'jpeg', quality: 72 });
  await noFindings(phone, 'the replay on a phone');
  // Two quick taps at the side jump ten seconds, from the controls being away as well: the first brings them back, and the
  // second must not land on the timeline that has just appeared under the finger. Upper and lower half of the picture.
  const box = await (await phone.$('#live-video')).boundingBox();
  const time = () => phone.$eval('#live-video', e => e.currentTime);
  // Playing, with sound: the controls only go away then. (The tap above may have paused it, a browser may have refused sound.)
  await phone.$eval('#live-video', e => { e.muted = false; return e.play(); });
  for (const [where, y] of [['upper', box.y + box.height * 0.3], ['lower', box.y + box.height * 0.8]]) {
    await phone.waitForFunction(() => document.getElementById('live-stage').classList.contains('idle'), { timeout: 9000 });
    const was = await time();
    await phone.touchscreen.tap(box.x + box.width * 0.85, y);
    await pause(90);
    await phone.touchscreen.tap(box.x + box.width * 0.85, y);
    await pause(900);
    const now = await time();
    check(`a double tap on the ${where} half jumps ten seconds`, now > was + 8 && now < was + 16, `${was} -> ${now}`);
    check('and it keeps playing', await phone.$eval('#live-video', e => !e.paused));
  }
  await phone.close();
}

// The owner's forms.
// A name made of the characters HTML is written with, given by the owner's own rename on the Players page: every page
// shows it as it is, escaped once (the live page said "Sena&#039;s &amp; ..." where t() escaped what h() had escaped
// already). Player 5 broadcast today (feed.py), so the live page's line about who was last on air, its list and the
// tooltips of its two weeks name them; their profile and the rankings too. Then the name they had, for the stages after.
async function escapedOnce(contexts, admin) {
  const odd = `Ann's & <Co> "1"`;
  const entity = /&(?:amp|lt|gt|quot|#0*39|#x0*27|apos);/;
  // The row's More, its name field, and Rename: as the owner does it.
  const rename = async (to) => {
    await admin.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
    const row = '.row-more[data-act^="/opendmtq/admin/players/5?"]';
    await admin.$eval(row, e => e.querySelector('summary').click());
    await admin.waitForSelector(`${row} > form.row-more-in`, { visible: true });
    const before = await admin.$eval(`${row} input[name=name]`, e => e.value);
    await admin.$eval(`${row} input[name=name]`, (e, value) => { e.value = value; e.dispatchEvent(new Event('input', { bubbles: true })); }, to);
    await press(admin, `${row} button[value=rename]`);
    return before;
  };
  const was = await rename(odd);
  const site = await contexts.signed.newPage();
  await site.setViewport({ width: 1280, height: 900 });
  await site.goto(`${P}/live.php`, { waitUntil: 'domcontentloaded' });
  // Nobody is on air in this stage: the box says who was last, and how the last two weeks went.
  const box = await site.$eval('#live-none', e => ({ text: e.textContent, tips: [...e.querySelectorAll('[data-tip]')].map(i => i.getAttribute('data-tip')) }));
  const cards = await site.$$eval('#past-list .who', bs => bs.map(b => b.textContent));
  const first = cards[0] || '';
  check('a name with & \' < > " reads as itself on the live page: who was last on air, the list, the days',
    !entity.test(box.text) && !box.tips.some(t => entity.test(t)) && box.text.includes(first) && cards.includes(odd) && box.tips[box.tips.length - 1].includes(odd),
    `${box.text.replace(/\s+/g, ' ').slice(0, 140)} | ${box.tips[box.tips.length - 1]} | ${cards.slice(0, 3)}`);
  await site.goto(`${P}/player.php?id=5`, { waitUntil: 'domcontentloaded' });
  const head = await textOf(site, '.playerhead h2');
  await site.goto(`${P}/ranking.php`, { waitUntil: 'domcontentloaded' });
  const listed = await site.$$eval('.board td.name a, .pod-name', es => es.map(e => e.textContent.trim()));
  check('and on their page, its tab and the rankings', head.trim().startsWith(odd) && (await site.title()) !== '' && listed.includes(odd),
    `${head} | ${listed.slice(0, 6)}`);
  await site.goto(`${P}/player.php?id=5`, { waitUntil: 'domcontentloaded' });
  check('the tab names them as they are', (await site.title()).startsWith(odd), await site.title());
  await site.close();
  await rename(was);
}

async function adminFlows(contexts) {
  // A wrong password says so.
  const login = await contexts.anon.newPage();
  await login.setViewport({ width: 360, height: 740, isMobile: true, hasTouch: true });
  await login.goto(`${A}/login`, { waitUntil: 'domcontentloaded' });
  await typeId(login, 'input[name=name]', 'admin');
  await login.type('input[name=password]', 'wrong');
  await Promise.all([login.waitForNavigation({ waitUntil: 'domcontentloaded' }), login.keyboard.press('Enter')]);
  check('a wrong admin password says so', /\S/.test(await textOf(login, '.flash, .error')));
  await noFindings(login, 'the admin sign-in after a wrong password');
  await login.close();

  const page = await contexts.signed.newPage();
  const errors = watch(page, `${A}/`);
  await page.setViewport({ width: 1280, height: 900 });

  // Renaming shows what happened, in a message with the site's look, and it stays done. Player 7's More, whose panel is made
  // from the page's one when it opens (admin.js): until then the row holds no form.
  await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
  const row = '.row-more[data-act^="/opendmtq/admin/players/7?"]';
  const panel = `${row} > form.row-more-in`;
  const openMore = async p => {
    await p.$eval(row, e => e.querySelector('summary').click());
    await p.waitForSelector(panel, { visible: true });
  };
  check('what is not done every day waits under More', await page.$eval(row, e => !e.open && !e.querySelector('form')));
  await openMore(page);
  await noFindings(page, 'the players page with a row opened');
  check('rename waits for a new name', await page.$eval(`${panel} button[value=rename]`, e => e.disabled));
  await page.$eval(`${panel} input[name=name]`, e => { e.value = 'Doyun Two'; e.dispatchEvent(new Event('input', { bubbles: true })); });
  await press(page, `${panel} button[value=rename]`);
  check('renaming says so', /Doyun Two/.test(await textOf(page, '.flash')));
  await noFindings(page, 'the players page with a message');
  await openMore(page);
  check('and the new name stays', await page.$eval(`${panel} input[name=name]`, e => e.value) === 'Doyun Two');
  // What cannot be undone asks in the site's own look, and Cancel leaves everything as it was.
  await page.click(`${panel} button[value=reset]`);
  await page.waitForSelector('#ask[open]');
  check('a reset asks first, and says a backup comes first', /backup/i.test(await textOf(page, '#ask p')), await textOf(page, '#ask p'));
  // The panel was made for this row: the question names its player.
  check('and names the player it is about', (await textOf(page, '#ask p')).includes('Doyun Two'), await textOf(page, '#ask p'));
  await noFindings(page, 'the question before a reset');
  await page.evaluate(() => { window.stillHere = true; });
  await page.click('#ask [value=no]');
  await pause(500);
  check('cancel leaves the page as it was', await page.evaluate(() => window.stillHere === true && !document.getElementById('ask').open));
  // From the keyboard: More opens with Enter, and the next stop is the name to change.
  await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
  await page.focus(`${row} > summary`);
  await page.keyboard.press('Enter');
  await page.waitForSelector(panel, { visible: true });
  await page.keyboard.press('Tab');
  check('More opens from the keyboard, the name the next stop', await page.evaluate(sel => document.activeElement.name === 'name'
    && document.activeElement.closest('.row-more') === document.querySelector(sel), row));
  // A row's switch sends the page's one form to its player's address: on, then off again as it was, each said in a message.
  const switchOf = `button[form="player-switch"][formaction^="/opendmtq/admin/players/7?"]`;
  await press(page, switchOf);
  const on = await textOf(page, '.flash');
  await press(page, switchOf);
  const off = await textOf(page, '.flash');
  check("a row's switch sends the page's one form for its player", /Doyun Two/.test(on) && / on/.test(on) && /Doyun Two/.test(off) && / off/.test(off),
    `${on} | ${off}`);
  await escapedOnce(contexts, page);
  // The same panel on a phone, where it opens across the row.
  const small = await contexts.signed.newPage();
  await small.setViewport({ width: 360, height: 740, isMobile: true, hasTouch: true });
  await small.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
  await openMore(small);
  await pause(200);
  await noFindings(small, 'the players page on a phone with a row opened');
  await small.screenshot({ path: path.join(OUT, 'shots', 'flows-players-more-360.jpg'), type: 'jpeg', quality: 72 });
  await small.close();
  // A page's name is a name: no script or markup in the tab.
  for (const name of ['players', 'maintenance', 'songs', 'backups', 'recordings', 'app', 'logs', '']) {
    await page.goto(`${A}/${name}`, { waitUntil: 'domcontentloaded' });
    const title = await page.title();
    check(`the tab of ${name || 'status'} says its name`, title.length < 60 && !title.includes('<'), title.slice(0, 80));
  }
  await page.goto(`${A}/players`, { waitUntil: 'domcontentloaded' });
  // The list: its search, its sort, its download.
  await page.type('#player-search', 'sena');
  await pause(200);
  check('the players search', await page.$$eval('table.players tbody tr', r => r.filter(x => !x.hidden && x.getBoundingClientRect().height > 0).length) === 1);
  await page.$eval('#player-search', e => { e.value = ''; e.dispatchEvent(new Event('input')); });
  await page.click('table.players th[data-sort="text"]');
  check('sorting by name', await page.$eval('table.players tbody tr td.primary', e => e.dataset.v) !== undefined && await page.$eval('table.players th[data-sort="text"]', e => e.hasAttribute('aria-sort')));
  const csv = await page.evaluate(async url => (await fetch(url)).text(), `${A}/players?csv=1`).catch(() => '');
  check('the players download', /Doyun Two/.test(csv), csv.slice(0, 80));
  const firstByte = await page.evaluate(async url => new Uint8Array(await (await fetch(url)).arrayBuffer())[0], `${A}/players?csv=1`).catch(() => 0);
  check('and a spreadsheet reads it as UTF-8', firstByte === 0xef, String(firstByte));

  // The plays: by a player, then by days too, and the file holds what the page found, not one page of it.
  await page.goto(`${A}/logs?tab=plays`, { waitUntil: 'domcontentloaded' });
  const playsCount = async () => Number(await textOf(page, 'section.card h2 .meta-inline'));
  const everyPlay = await playsCount();
  await page.select('.plays-filters select[name=player]', '1');
  await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.click('.plays-filters button.btn')]);
  const onePlayer = await playsCount();
  // One player's plays: whose they are is said once over the list, and no row repeats the name.
  const namesInRows = (await page.$$('table.playlog td.primary')).length, whose = await textOf(page, '.plays-of');
  check('the plays narrow to one player', onePlayer > 0 && onePlayer < everyPlay && namesInRows === 0 && /\S/.test(whose), `${onePlayer} of ${everyPlay}: ${namesInRows} names in rows, ${whose}`);
  // A week back: the player has plays from then on and from before, and the server's clock decides which day is which.
  const weekAgo = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
  await page.$eval('.plays-filters input[name=from]', (e, day) => { e.value = day; }, weekAgo);
  await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.click('.plays-filters button.btn')]);
  const lately = await playsCount();
  const whenPlayed = await page.$$eval('table.playlog td.date', c => c.map(e => e.textContent.trim()));
  check('and to days', lately > 0 && lately < onePlayer && whenPlayed.every(at => at >= weekAgo), `${lately} of ${onePlayer}, from ${weekAgo}, oldest here ${whenPlayed[whenPlayed.length - 1]}`);
  check('the form holds what was picked', await page.$eval('.plays-filters select[name=player]', e => e.value) === '1' && await page.$eval('.plays-filters input[name=from]', e => e.value) === weekAgo);
  const playsFile = await page.$eval('section.card h2 a.more', e => e.href);
  const playsCsv = await page.evaluate(async url => (await fetch(url)).text(), playsFile).catch(() => '');
  check('the plays download holds what the page found', playsCsv.trim().split('\n').length === lately + 1 && /^\ufeff?time,player_id,player,song,chart,score,grade,accuracy,new_record/.test(playsCsv), `${playsCsv.trim().split('\n').length} lines for ${lately}`);
  await page.click('.plays-filters a.btn');
  await page.waitForFunction(() => !location.search.includes('player='));
  check('and the filter can be cleared', await playsCount() === everyPlay);

  // The log of changes says it in words, under the player's name.
  await page.goto(`${A}/logs?tab=changes`, { waitUntil: 'domcontentloaded' });
  const changes = await textOf(page, '.changes');
  check('the change log says what was done, in words', /Renamed a player/.test(changes) && /Doyun Two/.test(changes), changes.slice(0, 120));
  check('and when, as a date', /\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(changes), changes.slice(0, 120));

  // An account for a friend: made on the Accounts page, its password shown once with the message to send; it signs in
  // to the site in a browser of its own, and is signed out there once switched off.
  await page.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
  await page.type('.account-form input[name=name]', 'friend1');
  await page.type('.account-form input[name=note]', 'A friend');
  await press(page, '.account-form button.btn-primary');
  const made = await textOf(page, '.account-keys code');
  check('an account is made with a password shown once', /^[a-z2-9]{10}$/.test(made) && /friend1/.test(await page.$eval('#account-message', e => e.value)), made);
  await noFindings(page, 'the accounts page with a new password');
  const theirs = await contexts.browser.createBrowserContext();
  const friend = await theirs.newPage();
  await friend.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
  await typeId(friend, 'input[name=user]', 'friend1');
  await friend.type('input[name=password]', made);
  await press(friend, '.signin-form button[type=submit]');
  check('the new account signs in to the site', new URL(friend.url()).pathname === '/opendmtq/' && await visible(friend, '.stage'), friend.url());
  await page.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
  check('the password is not shown again', !(await page.$('.account-keys')));
  await press(page, 'tr:has(td.primary) form:has(input[value=off]):has(input[value="friend1"]) button');
  await friend.goto(`${P}/ranking.php`, { waitUntil: 'domcontentloaded' });
  check('switched off, the account is signed out', new URL(friend.url()).pathname === '/opendmtq/login.php', friend.url());
  await theirs.close();

  // What shows once comes into view, with the focus, wherever its form was: Make token at the page's foot, and a row's New
  // password down the list. The page used to come back where it was, the panel above, off the screen. At a laptop's screen
  // and a phone's; the new password for an account of this check's own (dmtq's is the one every stage signs in with).
  await page.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
  await page.type('.account-form input[name=name]', 'inview');
  await press(page, '.account-form button.btn-primary');
  // The panel against the screen, and whether it has the focus.
  const panelAt = p => p.$eval('section.account-made', e => {
    const r = e.getBoundingClientRect();
    return { top: Math.round(r.top), bottom: Math.round(r.bottom), screen: innerHeight, focused: document.activeElement === e };
  }).catch(() => null);
  // The page's primary buttons that can be pressed: one on each of these screens, Make an account's. The copy buttons, Make
  // token and the setup's Next are plain, with a panel shown once or without.
  const primaries = p => p.$$eval('.btn-primary', bs => bs.filter(b => !b.disabled && b.getBoundingClientRect().height > 0)
    .map(b => b.textContent.trim()));
  const outOfView = [], notOne = [];
  for (const [size, width, height] of [['laptop', 1366, 768], ['phone', 390, 844]]) {
    const p = await contexts.signed.newPage();
    await p.setViewport({ width, height, isMobile: width < 500, hasTouch: width < 500 });
    await p.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
    const plain = await primaries(p);
    await p.$eval('#tokens input[name=token_name]', e => e.scrollIntoView({ block: 'center' }));
    await p.type('#tokens input[name=token_name]', `in view ${size}`);
    await press(p, '#tokens form button');
    const token = await panelAt(p);
    const withToken = await primaries(p);
    const row = 'table.accounts form:has(input[name=action][value=password]):has(input[name=name][value="inview"]) button';
    await p.$eval(row, e => e.scrollIntoView({ block: 'center' }));
    await pressAndConfirm(p, row);
    const password = await panelAt(p);
    const withPassword = await primaries(p);
    // The setup's Players step, before and after it makes an account.
    await p.goto(`${A}/setup?step=players`, { waitUntil: 'domcontentloaded' });
    const step = await primaries(p);
    await p.type('main form.form-row input[name=name]', `step${size}`);
    await press(p, 'main form.form-row button');
    const made = await p.$eval('section.account-made', e => {
      const r = e.getBoundingClientRect();
      return { top: Math.round(r.top), bottom: Math.round(r.bottom), screen: innerHeight, focused: document.activeElement === e };
    }).catch(() => null);
    const stepMade = await primaries(p);
    for (const [what, at] of [['Make token', token], ['New password', password], ["the setup's Make an account", made]]) {
      if (!at || at.top < 0 || at.bottom > at.screen || !at.focused) outOfView.push(`${what} at ${size}: ${JSON.stringify(at)}`);
    }
    for (const [what, found] of [['accounts', plain], ['accounts with a token', withToken], ['accounts with a password', withPassword],
      ["the setup's Players step", step], ["the setup's Players step with an account made", stepMade]]) {
      if (found.length !== 1) notOne.push(`${what} at ${size}: ${found.join(' + ') || 'none'}`);
    }
    await p.close();
  }
  check('what shows once is in view with the focus after Make token and New password, on a laptop and a phone', outOfView.length === 0,
    outOfView.join('; '));
  check("one primary button on the Accounts page and the setup's Players step, with what shows once or without", notOne.length === 0,
    notOne.join('; '));

  // The accounts' buttons stand in the same columns in every row: a button whose word depends on the account (Disable or
  // Enable, Give or Remove admin rights) is as wide as its other word too. Now with an admin, a player and a switched-off
  // account, at the narrowest tablet, a tablet on its side, both sides of the width where the buttons leave the row,
  // and a laptop, in both languages; the layout measured at each, where the player's list showed "Not linked" cut.
  const ragged = [];
  for (const lang of ['ko', 'en']) {
    await page.goto(`${A}/lang?to=${lang}&next=%2Fopendmtq%2Fadmin%2Faccounts`, { waitUntil: 'domcontentloaded' });
    for (const w of [744, 1024, 1240, 1241, 1280]) {
      await page.setViewport({ width: w, height: 900 });
      // Each row's buttons by their left edges: one set of edges for every row, or the columns are ragged.
      const lefts = await page.$$eval('table.accounts tbody tr', rows => rows.map(r => [...r.querySelectorAll('.btns .btn')].map(b => Math.round(b.getBoundingClientRect().left)).join('/')));
      if (new Set(lefts).size > 1) ragged.push(`${lang} ${w}: ${lefts.join(' ')}`);
      await noFindings(page, `the accounts at ${w} px, ${lang}`);
    }
  }
  check('the buttons of every account stand in the same columns', ragged.length === 0, ragged.join('; '));
  // Back to the width and the language the rest of these steps expect.
  await page.setViewport({ width: 1280, height: 900 });

  // An API token: made on the Accounts page and shown once, measured at every width while it is there (the list itself is
  // in every sweep of the page), in both languages; it works against the API at once, and is revoked there. The width
  // alone changes: a viewport that changes to a phone's would load the page again, and the token is shown only once.
  for (const lang of ['ko', 'en']) {
    await page.goto(`${A}/lang?to=${lang}&next=%2Fopendmtq%2Fadmin%2Faccounts`, { waitUntil: 'domcontentloaded' });
    await page.type('#tokens input[name=token_name]', `flow token ${lang}`);
    await page.select('#tokens select[name=scope]', 'write');
    await press(page, '#tokens form button');
    const secret = await textOf(page, '#token-secret');
    // The report names the token by its id alone (odq_<id>_), as the list does: none of its secret goes into a report.
    check(`a token is made on the Accounts page and shown once (${lang})`, /^odq_[0-9a-f]{12}_[A-Za-z0-9_-]{43}$/.test(secret), secret.slice(0, 17));
    for (const w of ALL_WIDTHS) {
      await page.setViewport({ width: w, height: 900 });
      await noFindings(page, `the accounts page with a new token at ${w} px, ${lang}`);
    }
    await page.setViewport({ width: 1280, height: 900 });
    if (lang !== 'en') continue;
    // Asked as a program with the token asks: from here, not from the page. The page's own failed requests are what this
    // stage counts, and a revoked token's 401 is the answer wanted.
    const ask = async sent => {
      const r = await fetch(`${ADMIN}/opendmtq/api/v1/status`, { headers: { Authorization: `Bearer ${sent}` } });
      return [r.status, (await r.json()).address || ''];
    };
    const works = await ask(secret);
    check('and works against the API at once', works[0] === 200 && works[1] !== '', String(works));
    await page.goto(`${A}/accounts`, { waitUntil: 'domcontentloaded' });
    check('and is not shown again', !(await page.$('#token-secret')));
    await pressAndConfirm(page, `table.tokens form:has(input[name=token][value="${secret.split('_')[1]}"]) button`);
    const revoked = await ask(secret);
    check('a revoked token no longer works', revoked[0] === 401 && /revoked/.test(await textOf(page, '.flash')), String(revoked));
  }

  // A backup at the press of a button; the list and the status page show it.
  await page.goto(`${A}/backups`, { waitUntil: 'domcontentloaded' });
  await press(page, 'form:has(input[name=action][value=create]) button');
  check('a backup is made and listed', /\.tar\.gz/.test(await textOf(page, 'table.data')));
  await noFindings(page, 'the backups page with a backup');
  await page.goto(`${A}/`, { waitUntil: 'domcontentloaded' });
  check('the status page knows about it', /\.tar\.gz/.test(await textOf(page, '.tiles')));

  // A file that is no song package: refused, in words, in the page's look.
  await page.goto(`${A}/songs`, { waitUntil: 'domcontentloaded' });
  const bad = '/tmp/not-a-package.zip';
  fs.writeFileSync(bad, 'not a zip file');
  await (await page.$('input[type=file]')).uploadFile(bad);
  // With a file chosen the upload's button can be pressed, and is the page's one primary button to a screen; on the
  // Backups page too, where Back up now is that one, with a file chosen in its upload box (not sent).
  const songChosen = await twoPrimaries(page);
  const backups = await contexts.signed.newPage();
  await backups.setViewport({ width: 1280, height: 900 });
  await backups.goto(`${A}/backups`, { waitUntil: 'domcontentloaded' });
  await (await backups.$('form.upload input[type=file]')).uploadFile(bad);
  const backupChosen = await twoPrimaries(backups);
  await backups.close();
  check('one primary button to a screen with a file chosen to upload, on the Songs and the Backups pages',
    songChosen.length === 0 && backupChosen.length === 0, [...songChosen, ...backupChosen].map(f => f.at).join('; '));
  await press(page, 'form[enctype] button:not([type=button])');
  check('a bad song package is refused in words', /\S/.test(await textOf(page, '.flash')), (await textOf(page, '.flash')).slice(0, 100));
  await noFindings(page, 'the songs page after a refused package');
  // What did not happen is not in the log of changes.
  await page.goto(`${A}/logs?tab=changes`, { waitUntil: 'domcontentloaded' });
  check('a refused package is no change', !/Added a song/.test(await textOf(page, '.changes')));

  // A player's records by level count the songs players can see (player.php): with the first song hidden on the Songs
  // page, its charts go from every level's count (four of level 1 with its Easy, three of 4 and of 7, make_content.php),
  // and no level says more records than charts; shown again, the counts are as they were.
  const levelsOf = async () => {
    const p = await contexts.signed.newPage();
    await p.goto(`${P}/player.php?id=1`, { waitUntil: 'domcontentloaded' });
    const rows = await p.$$eval('.levels .level', ls => ls.map(l => [Number(l.querySelector('.level-name').textContent.replace(/\D/g, '')),
      ...l.querySelector('b').textContent.split('/').map(n => Number(n.trim()))]));
    await p.close();
    return Object.fromEntries(rows.map(([lv, held, all]) => [lv, [held, all]]));
  };
  const shownLevels = await levelsOf();
  await page.goto(`${A}/songs`, { waitUntil: 'domcontentloaded' });
  await press(page, 'form:has(input[name=song_id][value="1"]):has(input[name=action][value=hide]) button');
  const hiddenLevels = await levelsOf();
  await page.goto(`${A}/songs`, { waitUntil: 'domcontentloaded' });
  await press(page, 'form:has(input[name=song_id][value="1"]):has(input[name=action][value=show]) button');
  const backLevels = await levelsOf();
  const dropped = Object.fromEntries(Object.entries(shownLevels).map(([lv, [, all]]) => [lv, all - ((hiddenLevels[lv] || [0, 0])[1])]).filter(([, d]) => d));
  check("a player's levels count only the songs players can see",
    Object.keys(shownLevels).length > 0 && JSON.stringify(dropped) === '{"1":4,"4":3,"7":3}'
    && Object.values(hiddenLevels).every(([held, all]) => held <= all) && JSON.stringify(backLevels) === JSON.stringify(shownLevels),
    JSON.stringify({ shownLevels, hiddenLevels, dropped }));

  // A recording hidden from the public list comes back when shown again. A live page open all the while asks for that list
  // only when it changed (live.php, live_past_rev()): not at its looks while nothing changes, once right after each change.
  await page.goto(`${A}/recordings`, { waitUntil: 'domcontentloaded' });
  const hide = await page.$('button[name=action][value^="hide"]');
  check('a recording can be hidden', !!hide);
  if (hide) {
    const name = await hide.evaluate(e => e.value.split(' ')[1]);
    const key = name.replace('/', '-');
    // The viewer's page, and every look it takes: 'past' for the list of recordings, 'look' for who is on alone.
    const viewer = await contexts.signed.newPage();
    await viewer.setViewport({ width: 1280, height: 900 });
    const asked = [];
    viewer.on('request', r => { if (/\/live\.php\?list=1/.test(r.url())) asked.push(r.url().includes('past=1') ? 'past' : 'look'); });
    await viewer.goto(`${P}/live.php`, { waitUntil: 'domcontentloaded' });
    // In front, as a page someone watches: a page out of sight with nothing playing takes no looks.
    await viewer.bringToFront();
    // The sign of the list, as a look carries it.
    const rev = () => viewer.evaluate(async () => (await (await fetch('/opendmtq/live.php?list=1')).json()).past_rev);
    const before = await rev();
    // Two looks and more with nothing changed.
    await pause(11000);
    const quiet = [...asked];
    const card = shown => viewer.waitForFunction((k, on) => !!document.querySelector(`#past-list .past[data-key="${k}"]`) === on,
      { timeout: 15000 }, key, shown).then(() => true, () => false);
    // The owner's page in front for its button, then the viewer's again, which looks at once on coming back.
    await page.bringToFront();
    await press(page, 'button[name=action][value^="hide"]');
    await viewer.bringToFront();
    const hiddenRev = await rev();
    const goneThere = await card(false);
    const afterHide = asked.length;
    const list = () => contexts.signed.newPage().then(async p => {
      await p.goto(`${P}/live.php?list=1&past=1`, { waitUntil: 'domcontentloaded' });
      const text = await p.evaluate(() => document.body.textContent);
      await p.close();
      return text;
    });
    check('and is gone from the public list', !(await list()).includes(key));
    await page.bringToFront();
    await press(page, `button[name=action][value="show ${name}"]`);
    await viewer.bringToFront();
    const shownRev = await rev();
    const backThere = await card(true);
    check('and is back when shown', (await list()).includes(key));
    const pastAsked = asked.filter(a => a === 'past').length;
    check("an open live page asks for the recordings' list only when it changed",
      quiet.length >= 2 && !quiet.includes('past') && hiddenRev !== before && shownRev === before && goneThere && backThere
      && asked.slice(quiet.length, afterHide).filter(a => a === 'past').length === 1 && pastAsked === 2,
      `${quiet.join(',')} | ${asked.slice(quiet.length).join(',')} | ${before} ${hiddenRev} ${shownRev} ${goneThere} ${backThere}`);
    await viewer.close();
  }
  check('no failed requests or script errors in all that', errors.length === 0, errors.slice(0, 5).join(' ; '));
  await page.close();
  // Signing out is no error, and says so in the colour of what went well. In a browser of its own: the rest stays signed in.
  const out = await contexts.anon.newPage();
  await out.goto(`${A}/login`, { waitUntil: 'domcontentloaded' });
  await typeId(out, 'input[name=name]', 'admin');
  await out.type('input[name=password]', PASSWORD);
  await Promise.all([out.waitForNavigation({ waitUntil: 'domcontentloaded' }), out.keyboard.press('Enter')]);
  await press(out, '.auth-form button');
  check('signing out is said as what went well', await visible(out, '.signin .done') && !(await out.$('.signin .error')));
  await out.close();
}

(async () => {
  fs.mkdirSync(path.join(OUT, 'shots'), { recursive: true });
  const contexts = await open();
  if (stage !== 'self') await signIn(contexts.signed);
  if (stage === 'self') {
    await self(contexts);
  } else if (stage === 'empty') {
    await broadcastsOff(contexts, false);
    await sweep(contexts, EMPTY, FEW_WIDTHS);
  } else if (stage === 'full') {
    await sweep(contexts, FULL, ALL_WIDTHS);
  } else if (stage === 'keys') {
    await keyboardMarks(contexts);
  } else if (stage === 'air') {
    // The video really runs, and the page says who is on.
    const page = await contexts.signed.newPage();
    await page.setViewport({ width: 1280, height: 800 });
    await page.goto(`${P}/live.php?id=1`, { waitUntil: 'domcontentloaded' });
    await pause(5000);
    const a = await page.$eval('#live-video', e => e.currentTime);
    await pause(3000);
    const b = await page.$eval('#live-video', e => e.currentTime);
    check('the broadcast plays', b > a + 1.5, `${a} -> ${b}`);
    check('marked as live', await textOf(page, '#pill-word') === 'LIVE');
    check('both players are listed', (await page.$$('#live-list > *, #live-others li')).length >= 1);
    await page.close();
    // The home page's cards of who is on air: a picture of each broadcast, taken from a whole piece of its stream
    // (thumbs.js), only of the cards on the screen and then not again for minutes (it was every half minute). On a short
    // phone screen the cards start below it (the stage above them is 420 px at least, style.css .stage-in): nothing of the
    // streams is asked for until they are scrolled to.
    const home = await contexts.signed.newPage();
    await home.setViewport({ width: 360, height: 400, isMobile: true, hasTouch: true });
    const pieces = [];
    home.on('request', r => { if (/\/live-media\.php\/\d+\//.test(r.url())) pieces.push(r.url().split('?')[0]); });
    await home.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
    await home.bringToFront();
    await pause(8000);
    const below = await home.$eval('#live', e => !e.hidden && e.getBoundingClientRect().top > innerHeight).catch(() => false);
    const unseen = pieces.length;
    await home.$eval('#live', e => e.scrollIntoView({ block: 'center' }));
    const pictured = await home.waitForFunction(() => {
      const cards = [...document.querySelectorAll('#live .thumb')];
      return cards.length >= 2 && cards.every(a => a.querySelector('.thumb-pic img'));
    }, { timeout: 40000 }).then(() => true, () => false);
    const taken = pieces.length;
    // Longer than the half minute pictures were taken again after.
    await pause(35000);
    check('the home page takes pictures of the broadcasts on the screen only, and not again for minutes',
      below && unseen === 0 && pictured && taken > 0 && pieces.length === taken, `${below} ${unseen} ${pictured} ${taken} ${pieces.length}`);
    await home.close();
    await sweep(contexts, AIR, FEW_WIDTHS);
  } else if (stage === 'maint') {
    // On, by the owner's own form; a long message, so that it has to wrap.
    const page = await contexts.signed.newPage();
    await page.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
    await page.$eval('textarea', e => { e.value = 'Back at 21:00. Moving the server to a bigger disk, with a longer notice than usual so that it has to wrap over several lines on a phone.'; });
    await pressAndConfirm(page, 'button[name=action][value=on]');
    await page.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
    check('the public site shows the notice', /Back at 21:00/.test(await textOf(page, '.site-alert')));
    await sweep(contexts, MAINT, FEW_WIDTHS);
    await page.goto(`${A}/maintenance`, { waitUntil: 'domcontentloaded' });
    await press(page, 'button[name=action][value=off]');
    await page.goto(`${P}/`, { waitUntil: 'domcontentloaded' });
    check('and goes when it is turned off', (await page.$('.site-alert')) === null);
    await page.close();
  } else if (stage === 'down') {
    const page = await contexts.signed.newPage();
    await page.goto(`${A}/`, { waitUntil: 'domcontentloaded' });
    check('the status page says the game server is not answering', /\S/.test(await textOf(page, '.site-alert')));
    // Its stylesheet is the copy it kept while the server was there, not the plain one for a server never seen.
    check('and keeps the look it had', await page.$eval('head', () => getComputedStyle(document.querySelector('.card, .stat')).clipPath !== 'none'));
    await page.close();
    await sweep(contexts, DOWN, FEW_WIDTHS);
  } else if (stage === 'flows') {
    await floatingLayers(contexts);
    await signInForms(contexts);
    await portalFlows(contexts);
    await replayFlows(contexts);
    await adminFlows(contexts);
  } else if (stage === 'patterns') {
    await hoverOnly(contexts);
    await inPlace(contexts);
    await formsLook(contexts);
  } else if (stage === 'quiet') {
    await broadcastsOff(contexts, true);
    await sweep(contexts, QUIET, ALL_WIDTHS);
  } else {
    throw new Error(`no stage ${stage}`);
  }
  await contexts.browser.close();
  process.exit(failed ? 1 : 0);
})().catch(e => {
  console.error(`FAIL ${stage}: the test itself stopped | ${String(e.stack || e).slice(0, 600)}`);
  process.exit(1);
});
