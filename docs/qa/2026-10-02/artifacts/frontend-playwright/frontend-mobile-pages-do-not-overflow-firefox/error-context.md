# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend.spec.cjs >> mobile pages do not overflow
- Location: docs/qa/2026-10-02/frontend.spec.cjs:68:1

# Error details

```
Error: browserType.launch: Failed to launch the browser process.
Browser logs:

<launching> /private/tmp/amw-qa-playwright-browsers/firefox-1543/firefox/Nightly.app/Contents/MacOS/firefox -no-remote -headless -profile /var/folders/jq/nbt0s6qs6njf4yfc0w30wmxh0000gn/T/playwright_firefoxdev_profile-rp7ThL -juggler-pipe -silent
<launched> pid=24812
[pid=24812][err] *** You are running in headless mode.
[pid=24812] <process did exit: exitCode=null, signal=SIGABRT>
[pid=24812] starting temporary directories cleanup
Call log:
  - <launching> /private/tmp/amw-qa-playwright-browsers/firefox-1543/firefox/Nightly.app/Contents/MacOS/firefox -no-remote -headless -profile /var/folders/jq/nbt0s6qs6njf4yfc0w30wmxh0000gn/T/playwright_firefoxdev_profile-rp7ThL -juggler-pipe -silent
  - <launched> pid=24812
  - [pid=24812][err] *** You are running in headless mode.
  - [pid=24812] <process did exit: exitCode=null, signal=SIGABRT>
  - [pid=24812] starting temporary directories cleanup
  - [pid=24812] <gracefully close start>
  - [pid=24812] <kill>
  - [pid=24812] <skipped force kill spawnedProcess.killed=false processClosed=true>
  - [pid=24812] finished temporary directories cleanup
  - [pid=24812] <gracefully close end>

```