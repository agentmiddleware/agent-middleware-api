# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend.spec.cjs >> malformed receipt payload fails closed
- Location: docs/qa/2026-10-02/frontend.spec.cjs:62:1

# Error details

```
Error: browserType.launch: Failed to launch the browser process.
Browser logs:

<launching> /private/tmp/amw-qa-playwright-browsers/firefox-1543/firefox/Nightly.app/Contents/MacOS/firefox -no-remote -headless -profile /var/folders/jq/nbt0s6qs6njf4yfc0w30wmxh0000gn/T/playwright_firefoxdev_profile-5znwg9 -juggler-pipe -silent
<launched> pid=24335
[pid=24335][err] *** You are running in headless mode.
[pid=24335] <process did exit: exitCode=null, signal=SIGABRT>
[pid=24335] starting temporary directories cleanup
Call log:
  - <launching> /private/tmp/amw-qa-playwright-browsers/firefox-1543/firefox/Nightly.app/Contents/MacOS/firefox -no-remote -headless -profile /var/folders/jq/nbt0s6qs6njf4yfc0w30wmxh0000gn/T/playwright_firefoxdev_profile-5znwg9 -juggler-pipe -silent
  - <launched> pid=24335
  - [pid=24335][err] *** You are running in headless mode.
  - [pid=24335] <process did exit: exitCode=null, signal=SIGABRT>
  - [pid=24335] starting temporary directories cleanup
  - [pid=24335] <gracefully close start>
  - [pid=24335] <kill>
  - [pid=24335] <skipped force kill spawnedProcess.killed=false processClosed=true>
  - [pid=24335] finished temporary directories cleanup
  - [pid=24335] <gracefully close end>

```