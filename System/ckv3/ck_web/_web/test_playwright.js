const { chromium } = require('playwright');

(async () => {
  try {
    console.log('[INFO] Launching Chromium...');

    const browser = await chromium.launch({
      headless: true,
      chromiumSandbox: false,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
      ],
    });

    const page = await browser.newPage({
      viewport: { width: 1280, height: 800 },
    });

    console.log('[INFO] Navigating to baidu.com...');
    await page.goto('https://www.baidu.com', {
      waitUntil: 'networkidle',
      timeout: 30000,
    });

    const fileName = `baidu-${Date.now()}.png`;
    await page.screenshot({
      path: fileName,
      fullPage: true,
    });

    console.log(`[OK] Screenshot saved as ${fileName}`);

    await browser.close();
    console.log('[OK] Browser closed, test success ✅');

  } catch (err) {
    console.error('[ERROR] Playwright test failed ❌');
    console.error(err);
    process.exit(1);
  }
})();