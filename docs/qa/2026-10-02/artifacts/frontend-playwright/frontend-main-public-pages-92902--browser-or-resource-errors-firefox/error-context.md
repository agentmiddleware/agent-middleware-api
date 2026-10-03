# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend.spec.cjs >> main public pages load without browser or resource errors
- Location: docs/qa/2026-10-02/frontend.spec.cjs:9:1

# Error details

```
Error: browserType.launch: Failed to launch the browser process.
Browser logs:

<launching> /private/tmp/amw-qa-playwright-browsers/firefox-1543/firefox/Nightly.app/Contents/MacOS/firefox -no-remote -headless -profile /var/folders/jq/nbt0s6qs6njf4yfc0w30wmxh0000gn/T/playwright_firefoxdev_profile-xPXXEd -juggler-pipe -silent
<launched> pid=24308
[pid=24308][err] *** You are running in headless mode.
[pid=24308] <process did exit: exitCode=null, signal=SIGABRT>
[pid=24308] starting temporary directories cleanup
Call log:
  - <launching> /private/tmp/amw-qa-playwright-browsers/firefox-1543/firefox/Nightly.app/Contents/MacOS/firefox -no-remote -headless -profile /var/folders/jq/nbt0s6qs6njf4yfc0w30wmxh0000gn/T/playwright_firefoxdev_profile-xPXXEd -juggler-pipe -silent
  - <launched> pid=24308
  - [pid=24308][err] *** You are running in headless mode.
  - [pid=24308] <process did exit: exitCode=null, signal=SIGABRT>
  - [pid=24308] starting temporary directories cleanup
  - [pid=24308] <gracefully close start>
  - [pid=24308] <kill>
  - [pid=24308] <skipped force kill spawnedProcess.killed=false processClosed=true>
  - [pid=24308] finished temporary directories cleanup
  - [pid=24308] <gracefully close end>

```