const { chromium } = require('playwright');

(async () => {
  let browser;
  try {
    console.log('[INFO] Launching Chromium...');

    browser = await chromium.launch({
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--no-zygote',
        // 关键：务必移除 --single-process
        '--disable-software-rasterizer',
        '--disable-features=IsolateOrigins,site-per-process',
      ],
    });

    console.log('[OK] Browser launched, creating context...');
    const context = await browser.newContext();
    
    console.log('[INFO] Creating new page...');
    const page = await context.newPage();

    console.log('[INFO] Navigating...');
    await page.goto('https://www.baidu.com', { waitUntil: 'domcontentloaded' });
    console.log('[OK] Page title:', await page.title());

  } catch (err) {
    console.error('[ERROR] Playwright test failed ❌');
    console.error(err);
  } finally {
    if (browser) await browser.close();
  }
})();