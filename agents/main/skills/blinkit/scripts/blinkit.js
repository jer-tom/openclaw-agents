#!/usr/bin/env node
'use strict';

const { chromium } = require('/data/.npm-global/lib/node_modules/openclaw/node_modules/playwright-core');
const fs = require('fs');
const path = require('path');

// --- Config ---
const SESSION_PATH = '/data/.openclaw/credentials/blinkit-session.json';
const CHROMIUM_PATH = '/usr/bin/chromium';
const LAUNCH_ARGS = ['--disable-gpu', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled'];
const USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

if (process.env.BLINKIT_DISABLE_SANDBOX === '1') {
  LAUNCH_ARGS.unshift('--disable-setuid-sandbox');
  LAUNCH_ARGS.unshift('--no-sandbox');
}

// --- Helpers ---
function out(data) { process.stdout.write(JSON.stringify(data) + '\n'); }
function err(msg) { process.stderr.write(msg + '\n'); }
function die(msg) { err(msg); process.exit(1); }

function loadGeo() {
  const latitude = Number(process.env.BLINKIT_LATITUDE);
  const longitude = Number(process.env.BLINKIT_LONGITUDE);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    throw new Error('Set BLINKIT_LATITUDE and BLINKIT_LONGITUDE before running Blinkit automation');
  }
  return { latitude, longitude };
}

// Playwright compat: .first/.last may not chain in all versions, use nth()
async function lastLocator(loc) {
  const c = await loc.count();
  return c > 0 ? loc.nth(c - 1) : loc.nth(0);
}

async function launch() {
  const browser = await chromium.launch({
    executablePath: CHROMIUM_PATH,
    headless: true,
    args: LAUNCH_ARGS,
  });

  const ctxOpts = {
    permissions: ['geolocation'],
    geolocation: loadGeo(),
    userAgent: USER_AGENT,
  };
  if (fs.existsSync(SESSION_PATH)) {
    ctxOpts.storageState = SESSION_PATH;
  }

  const context = await browser.newContext(ctxOpts);
  // Hide webdriver flag to bypass Cloudflare bot detection
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
  });
  const page = await context.newPage();

  await page.goto('https://blinkit.com/', { timeout: 60000, waitUntil: 'domcontentloaded' }).catch(() => {});
  await page.waitForTimeout(3000);

  // Dismiss location popup if it appears
  try {
    const locBtn = page.locator('button', { hasText: 'Detect my location' });
    await locBtn.waitFor({ state: 'visible', timeout: 3000 });
    await locBtn.click();
    await locBtn.waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {});
  } catch (_) {}

  return { browser, context, page };
}

async function saveSession(context) {
  const sessionDir = path.dirname(SESSION_PATH);
  fs.mkdirSync(sessionDir, { recursive: true, mode: 0o700 });
  try {
    fs.chmodSync(sessionDir, 0o700);
  } catch (_) {}
  await context.storageState({ path: SESSION_PATH });
  try {
    fs.chmodSync(SESSION_PATH, 0o600);
  } catch (_) {}
}

async function isLoggedIn(page) {
  try {
    if (await page.isVisible('text=My Account')) return true;
    if (await page.isVisible('.user-profile')) return true;
    if (!(await page.isVisible("text='Login'"))) return true;
    return false;
  } catch (_) {
    return false;
  }
}

async function isStoreClosed(page) {
  try {
    return await page.isVisible('text=Store is closed') ||
           await page.isVisible('text=Currently unavailable');
  } catch (_) {
    return false;
  }
}

// Navigate to search page and get search input
async function activateSearch(page) {
  if (await page.isVisible("a[href='/s/']")) {
    await page.click("a[href='/s/']");
  } else if (await page.isVisible("div[class*='SearchBar__PlaceholderContainer']")) {
    await page.click("div[class*='SearchBar__PlaceholderContainer']");
  } else if (await page.isVisible("input[placeholder*='Search']")) {
    await page.click("input[placeholder*='Search']");
  } else {
    await page.click("text='Search'", { timeout: 3000 }).catch(() => {});
  }
  return page.waitForSelector(
    "input[placeholder*='Search'], input[type='text']",
    { state: 'visible', timeout: 30000 }
  );
}

// Parse product cards from search results
async function parseResults(page, limit = 20) {
  const cards = page.locator("div[role='button']").filter({ hasText: 'ADD' }).filter({ hasText: '\u20B9' });
  const count = await cards.count();
  const results = [];

  for (let i = 0; i < Math.min(count, limit); i++) {
    const card = cards.nth(i);
    const text = await card.innerText();
    const id = (await card.getAttribute('id')) || 'unknown';

    const nameLoc = card.locator("div[class*='line-clamp-2']");
    let name;
    if (await nameLoc.count() > 0) {
      name = await nameLoc.nth(0).innerText();
    } else {
      const lines = text.split('\n').filter(l => l.trim());
      name = lines[0] || 'Unknown';
    }

    let price = 'Unknown';
    for (const part of text.split('\n')) {
      if (part.includes('\u20B9')) { price = part.trim(); break; }
    }

    results.push({ index: i, id, name, price });
  }
  return results;
}

// Click the cart button
async function openCart(page) {
  const cartBtn = page.locator("div[class*='CartButton__Button'], div[class*='CartButton__Container']");
  if (await cartBtn.count() > 0) {
    await cartBtn.nth(0).click();
    await page.waitForTimeout(2000);
    return true;
  }
  return false;
}

// Get cart drawer text
async function getCartDrawerText(page) {
  const drawer = page.locator(
    "div[class*='CartDrawer'], div[class*='CartSidebar'], div.cart-modal-rn, div[class*='CartWrapper__CartContainer']"
  );
  if (await drawer.count() > 0) {
    return await drawer.nth(0).innerText();
  }
  return null;
}

// --- Commands ---

async function cmdCheckLogin() {
  const { browser, context, page } = await launch();
  try {
    const loggedIn = await isLoggedIn(page);
    if (loggedIn) await saveSession(context);
    out({ loggedIn });
  } finally {
    await browser.close();
  }
}

async function cmdLogin(phone) {
  if (!phone) die('Usage: blinkit.js login <phone>');
  const { browser, context, page } = await launch();
  try {
    if (await isLoggedIn(page)) {
      out({ status: 'already_logged_in' });
      return;
    }

    if (await page.isVisible("text='Login'")) {
      await page.click("text='Login'");
    } else if (await page.isVisible("div[class*='ProfileButton__Container']")) {
      await page.locator("div[class*='ProfileButton__Container']").click();
    }

    const phoneInput = await page.waitForSelector(
      "input[type='tel'], input[name='mobile'], input[type='text']",
      { state: 'visible', timeout: 30000 }
    );
    await phoneInput.click();
    await phoneInput.fill(phone);
    await page.waitForTimeout(500);

    if (await page.isVisible("text='Next'")) await page.click("text='Next'");
    else if (await page.isVisible("text='Continue'")) await page.click("text='Continue'");
    else await page.keyboard.press('Enter');

    await saveSession(context);
    out({ status: 'otp_sent', message: 'OTP sent to ' + phone + '. Run: blinkit.js otp <code>' });
  } finally {
    await browser.close();
  }
}

async function cmdOtp(otp) {
  if (!otp) die('Usage: blinkit.js otp <code>');
  const { browser, context, page } = await launch();
  try {
    await page.waitForSelector('input', { timeout: 30000 });
    const inputs = page.locator('input');
    const count = await inputs.count();

    if (count >= 4) {
      for (let i = 0; i < Math.min(otp.length, 4); i++) {
        await inputs.nth(i).fill(otp[i]);
        await page.waitForTimeout(100);
      }
    } else {
      const otpInput = page.locator("input[data-test-id='otp-input'], input[name*='otp'], input[id*='otp']");
      if (await otpInput.count() > 0 && await otpInput.nth(0).isVisible()) {
        await otpInput.nth(0).fill(otp);
      } else {
        await page.fill('input', otp);
      }
    }

    await page.keyboard.press('Enter');
    await page.waitForTimeout(3000);

    const loggedIn = await isLoggedIn(page);
    if (loggedIn) await saveSession(context);
    out({ status: loggedIn ? 'logged_in' : 'pending', loggedIn });
  } finally {
    await browser.close();
  }
}

async function cmdSearch(query) {
  if (!query) die('Usage: blinkit.js search <query>');
  const { browser, page } = await launch();
  try {
    const searchInput = await activateSearch(page);
    await searchInput.fill(query);
    await page.keyboard.press('Enter');

    try {
      await page.waitForSelector("div[role='button']:has-text('ADD')", { timeout: 30000 });
    } catch (_) {}

    const results = await parseResults(page);
    out({ count: results.length, results });
  } finally {
    await browser.close();
  }
}

async function cmdAddToCart(productId, qty = 1) {
  if (!productId) die('Usage: blinkit.js add <product-id> [qty]');
  const { browser, page } = await launch();
  try {
    const card = page.locator(`div[id='${productId}']`);
    if (await card.count() === 0) {
      out({ error: 'product_not_found', productId });
      return;
    }

    const addBtn = await lastLocator(card.locator('div').filter({ hasText: 'ADD' }));
    let remaining = qty;

    if (await addBtn.isVisible()) {
      await addBtn.click();
      remaining--;
      await page.waitForTimeout(500);
    }

    if (remaining > 0) {
      await page.waitForTimeout(1000);
      let plusBtn = card.locator('.icon-plus');
      if (await plusBtn.count() > 0) {
        plusBtn = plusBtn.nth(0).locator('..');
      } else {
        plusBtn = card.locator("text='+'").nth(0);
      }

      for (let i = 0; i < remaining; i++) {
        if (await plusBtn.isVisible()) {
          await plusBtn.click();
          await page.waitForTimeout(500);
        }
        try {
          if (await page.getByText("Sorry, you can't add more of this item").isVisible({ timeout: 500 })) {
            err('Quantity limit reached');
            break;
          }
        } catch (_) {}
      }
    }

    out({ status: 'added', productId, qty });
  } finally {
    await browser.close();
  }
}

async function cmdPrepareOrder(itemsJson) {
  if (!itemsJson) die('Usage: blinkit.js prepare-order \'[{"name":"milk","qty":1}]\'');
  let items;
  try { items = JSON.parse(itemsJson); } catch (_) { die('Invalid JSON'); }

  const { browser, context, page } = await launch();
  try {
    if (await isStoreClosed(page)) { out({ error: 'store_closed' }); return; }

    const report = [];

    for (const item of items) {
      const { name, qty = 1 } = item;
      err(`Searching: ${name}...`);

      const searchInput = await activateSearch(page);
      await searchInput.fill('');
      await searchInput.fill(name);
      await page.keyboard.press('Enter');

      try {
        await page.waitForSelector("div[role='button']:has-text('ADD')", { timeout: 15000 });
      } catch (_) {
        report.push({ item: name, status: 'not_found' });
        continue;
      }

      const cards = page.locator("div[role='button']").filter({ hasText: 'ADD' }).filter({ hasText: '\u20B9' });
      if (await cards.count() === 0) {
        report.push({ item: name, status: 'not_found' });
        continue;
      }

      const card = cards.nth(0);
      const productId = (await card.getAttribute('id')) || 'unknown';
      const nameLoc = card.locator("div[class*='line-clamp-2']");
      const matchedName = (await nameLoc.count() > 0) ? await nameLoc.nth(0).innerText() : name;

      let price = 'Unknown';
      const cardText = await card.innerText();
      for (const part of cardText.split('\n')) {
        if (part.includes('\u20B9')) { price = part.trim(); break; }
      }

      // Add to cart
      const addBtn = await lastLocator(card.locator('div').filter({ hasText: 'ADD' }));
      if (await addBtn.isVisible()) {
        await addBtn.click();
        await page.waitForTimeout(500);
      }

      // Increment if qty > 1
      if (qty > 1) {
        await page.waitForTimeout(1000);
        let plusBtn = card.locator('.icon-plus');
        if (await plusBtn.count() > 0) {
          plusBtn = plusBtn.nth(0).locator('..');
        } else {
          plusBtn = card.locator("text='+'").nth(0);
        }

        for (let i = 1; i < qty; i++) {
          if (await plusBtn.isVisible()) {
            await plusBtn.click();
            await page.waitForTimeout(500);
          }
        }
      }

      report.push({ item: name, matched: matchedName, productId, price, qty, status: 'added' });
      await page.waitForTimeout(500);
    }

    // Open cart to get summary
    if (await openCart(page)) {
      const cartSummary = await getCartDrawerText(page);
      await saveSession(context);
      out({ status: 'prepared', items: report, cartSummary });
    } else {
      await saveSession(context);
      out({ status: 'prepared', items: report, cartSummary: null });
    }
  } finally {
    await browser.close();
  }
}

async function cmdCart() {
  const { browser, page } = await launch();
  try {
    if (!(await openCart(page))) { out({ error: 'no_cart_button' }); return; }
    if (await isStoreClosed(page)) { out({ error: 'store_closed' }); return; }

    const text = await getCartDrawerText(page);
    if (text) {
      out({ cart: text });
    } else if (await page.isVisible("text=/Bill details/i") || await page.isVisible("button:has-text('Proceed')")) {
      out({ cart: 'Cart open but could not scrape details' });
    } else {
      out({ cart: null, message: 'Cart appears empty or store unavailable' });
    }
  } finally {
    await browser.close();
  }
}

async function cmdClearCart() {
  const { browser, context, page } = await launch();
  try {
    if (!(await openCart(page))) { out({ status: 'empty' }); return; }

    let removed = 0;
    for (let attempt = 0; attempt < 100; attempt++) {
      const minusBtn = page.locator('.icon-minus');
      if (await minusBtn.count() === 0) break;
      await minusBtn.nth(0).locator('..').click();
      removed++;
      await page.waitForTimeout(300);
    }

    await saveSession(context);
    out({ status: 'cleared', removedClicks: removed });
  } finally {
    await browser.close();
  }
}

async function cmdPlaceOrder() {
  const { browser, context, page } = await launch();
  try {
    if (await isStoreClosed(page)) { out({ error: 'store_closed' }); return; }

    // Open cart and click Proceed
    await openCart(page);

    const proceedBtn = await lastLocator(page.locator('button, div').filter({ hasText: 'Proceed' }));
    if (await proceedBtn.isVisible()) {
      await proceedBtn.click();
      await page.waitForTimeout(3000);
    } else {
      out({ error: 'no_proceed_button', message: 'Cart may be empty' });
      return;
    }

    // Address selection — pick first saved address
    if (await page.isVisible("text='Select delivery address'")) {
      const addrItems = page.locator("div[class*='AddressList__AddressItemWrapper']");
      if (await addrItems.count() > 0) {
        await addrItems.nth(0).click();
        await page.waitForTimeout(2000);
      }
    }

    // Click Proceed again if needed (past address)
    const proceedBtn2 = await lastLocator(page.locator('button, div').filter({ hasText: 'Proceed' }));
    if (await proceedBtn2.isVisible()) {
      await proceedBtn2.click();
      await page.waitForTimeout(3000);
    }

    // Payment — find and select first saved UPI ID
    let selectedUpi = null;
    try {
      const iframeEl = await page.waitForSelector('#payment_widget', { timeout: 15000 });
      if (iframeEl) {
        const frame = await iframeEl.contentFrame();
        if (frame) {
          await frame.waitForLoadState('networkidle').catch(() => {});

          const vpas = frame.locator('text=/@/');
          const vpaCount = await vpas.count();
          if (vpaCount > 0) {
            selectedUpi = await vpas.nth(0).innerText();
            await vpas.nth(0).click();
            err(`Selected UPI: ${selectedUpi}`);
            await page.waitForTimeout(1000);
          }
        }
      }
    } catch (_) {
      err('Payment widget not found or timed out');
    }

    // Click Pay Now
    let paid = false;
    const paySpecific = page.locator("div[class*='Zpayments__Button']:has-text('Pay Now')");
    if (await paySpecific.count() > 0 && await paySpecific.nth(0).isVisible()) {
      await paySpecific.nth(0).click();
      paid = true;
    } else {
      const payText = await lastLocator(page.locator('div, button').filter({ hasText: 'Pay Now' }));
      if (await payText.isVisible()) {
        await payText.click();
        paid = true;
      } else {
        // Try inside iframe
        try {
          const iframeEl = await page.querySelector('#payment_widget');
          if (iframeEl) {
            const frame = await iframeEl.contentFrame();
            if (frame) {
              const frameBtn = frame.locator("text='Pay Now'");
              if (await frameBtn.count() > 0) {
                await frameBtn.nth(0).click();
                paid = true;
              }
            }
          }
        } catch (_) {}
      }
    }

    await saveSession(context);
    out({
      status: paid ? 'payment_initiated' : 'checkout_incomplete',
      upi: selectedUpi,
      message: paid ? 'Approve the UPI payment on your phone' : 'Could not find Pay Now button',
    });
  } finally {
    await browser.close();
  }
}

// --- CLI Router ---
async function main() {
  const [cmd, ...args] = process.argv.slice(2);
  if (!cmd) {
    err('Usage: blinkit.js <command> [args]\n\nCommands:\n  check-login\n  login <phone>\n  otp <code>\n  search <query>\n  add <product-id> [qty]\n  prepare-order <items-json>\n  cart\n  clear-cart\n  place-order');
    process.exit(1);
  }

  switch (cmd) {
    case 'check-login': return cmdCheckLogin();
    case 'login': return cmdLogin(args[0]);
    case 'otp': return cmdOtp(args[0]);
    case 'search': return cmdSearch(args.join(' '));
    case 'add': return cmdAddToCart(args[0], parseInt(args[1]) || 1);
    case 'prepare-order': return cmdPrepareOrder(args[0]);
    case 'cart': return cmdCart();
    case 'clear-cart': return cmdClearCart();
    case 'place-order': return cmdPlaceOrder();
    default: die(`Unknown command: ${cmd}`);
  }
}

main().catch(e => { err(e.message); process.exit(1); });
