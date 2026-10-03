# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend.spec.cjs >> calculator valid, boundary, invalid and cleared states stay local
- Location: docs/qa/2026-10-02/frontend.spec.cjs:21:1

# Error details

```
Error: browserType.launch: Failed to launch the browser process.
Browser logs:

<launching> /private/tmp/amw-qa-playwright-browsers/firefox-1543/firefox/Nightly.app/Contents/MacOS/firefox -no-remote -headless -profile /var/folders/jq/nbt0s6qs6njf4yfc0w30wmxh0000gn/T/playwright_firefoxdev_profile-hjwDkV -juggler-pipe -silent
<launched> pid=24323
[pid=24323][err] *** You are running in headless mode.
[pid=24323] <process did exit: exitCode=null, signal=SIGABRT>
[pid=24323] starting temporary directories cleanup
Call log:
  - <launching> /private/tmp/amw-qa-playwright-browsers/firefox-1543/firefox/Nightly.app/Contents/MacOS/firefox -no-remote -headless -profile /var/folders/jq/nbt0s6qs6njf4yfc0w30wmxh0000gn/T/playwright_firefoxdev_profile-hjwDkV -juggler-pipe -silent
  - <launched> pid=24323
  - [pid=24323][err] *** You are running in headless mode.
  - [pid=24323] <process did exit: exitCode=null, signal=SIGABRT>
  - [pid=24323] starting temporary directories cleanup
  - [pid=24323] <gracefully close start>
  - [pid=24323] <kill>
  - [pid=24323] <skipped force kill spawnedProcess.killed=false processClosed=true>
  - [pid=24323] finished temporary directories cleanup
  - [pid=24323] <gracefully close end>

```