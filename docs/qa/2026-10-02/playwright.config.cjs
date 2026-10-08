const path = require('node:path');
const {defineConfig} = require(process.env.QA_NODE_MODULES
  ? `${process.env.QA_NODE_MODULES}/@playwright/test` : '/private/tmp/amw-qa-browser/node_modules/@playwright/test');
module.exports = defineConfig({
  testDir: __dirname,
  testMatch: ['frontend.spec.cjs', 'ux-regressions.spec.cjs'],
  outputDir: path.join(__dirname, 'artifacts/frontend-playwright'),
  reporter: [['list'], ['json', {outputFile: path.join(__dirname, 'artifacts/frontend-playwright.json')}]],
  workers: 1,
  timeout: 30000,
  use: {baseURL: 'http://127.0.0.1:8765', viewport: {width: 1440, height: 1000},
    reducedMotion: 'reduce', serviceWorkers: 'block', screenshot: 'only-on-failure'},
  projects: ['chromium', 'firefox', 'webkit'].map(browserName => ({name: browserName, use: {browserName}})),
});
