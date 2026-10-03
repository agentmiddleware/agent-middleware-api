// QA-only adapter: existing browser scripts receive a loopback-only browser.
// Install playwright in QA_NODE_MODULES (defaults to the sweep's temporary tools).
import { pathToFileURL } from 'node:url';
const modules = process.env.QA_NODE_MODULES || '/private/tmp/amw-qa-browser/node_modules';
const pw = await import(pathToFileURL(`${modules}/playwright/index.mjs`).href);
async function protect(context) {
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    return ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
      ? route.continue() : route.abort('blockedbyclient');
  });
  return context;
}
function guarded(type) {
  return { async launch(options) {
    const browser = await type.launch(options);
    const newContext = browser.newContext.bind(browser);
    const newPage = browser.newPage.bind(browser);
    browser.newContext = async options => protect(await newContext({...options, serviceWorkers: 'block'}));
    browser.newPage = async options => {
      const page = await newPage({...options, serviceWorkers: 'block'});
      await protect(page.context());
      return page;
    };
    return browser;
  }};
}
export const chromium = guarded(pw.chromium);
export const firefox = guarded(pw.firefox);
export const webkit = guarded(pw.webkit);
