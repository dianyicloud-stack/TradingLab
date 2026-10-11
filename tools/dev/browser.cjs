'use strict';
// Optional browser E2E only; the Web and Agent do not import this module.
const path = require('path');
const root = path.resolve(__dirname, '../..');
const moduleRoot = process.env.TRADING_LAB_PLAYWRIGHT_ROOT || path.join(root, '.dev/e2e/node_modules/playwright');
const lock = require(path.join(root, 'dev/browser-lock.json'));
const version = require(path.join(moduleRoot, 'package.json')).version;
if (version !== lock.playwright) throw Error('Playwright version mismatch: expected ' + lock.playwright);
process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.join(root, '.dev/e2e/browsers');
const playwright = require(moduleRoot);
module.exports = {chromium: {launch: async (options) => {
  const browser = await playwright.chromium.launch({
    ...options, executablePath: process.env.TRADING_LAB_CHROME || undefined
  });
  const expected = lock.browsers.find(item => item.name === 'chromium').browserVersion;
  if (browser.version() !== expected) {
    await browser.close();
    throw Error('Chromium version mismatch: expected ' + expected);
  }
  return browser;
}}};
