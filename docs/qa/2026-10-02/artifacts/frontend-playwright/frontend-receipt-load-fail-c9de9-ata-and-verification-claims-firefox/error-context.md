# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend.spec.cjs >> receipt load failure removes published data and verification claims
- Location: docs/qa/2026-10-02/frontend.spec.cjs:54:1

# Error details

```
Error: browserType.launch: Failed to launch the browser process.
Browser logs:

<launching> /private/tmp/amw-qa-playwright-browsers/firefox-1543/firefox/Nightly.app/Contents/MacOS/firefox -no-remote -headless -profile /var/folders/jq/nbt0s6qs6njf4yfc0w30wmxh0000gn/T/playwright_firefoxdev_profile-kEMNii -juggler-pipe -silent
<launched> pid=24330
[pid=24330][err] *** You are running in headless mode.
[pid=24330] <process did exit: exitCode=null, signal=SIGABRT>
[pid=24330] starting temporary directories cleanup
Call log:
  - <launching> /private/tmp/amw-qa-playwright-browsers/firefox-1543/firefox/Nightly.app/Contents/MacOS/firefox -no-remote -headless -profile /var/folders/jq/nbt0s6qs6njf4yfc0w30wmxh0000gn/T/playwright_firefoxdev_profile-kEMNii -juggler-pipe -silent
  - <launched> pid=24330
  - [pid=24330][err] *** You are running in headless mode.
  - [pid=24330] <process did exit: exitCode=null, signal=SIGABRT>
  - [pid=24330] starting temporary directories cleanup
  - [pid=24330] <gracefully close start>
  - [pid=24330] <kill>
  - [pid=24330] <skipped force kill spawnedProcess.killed=false processClosed=true>
  - [pid=24330] finished temporary directories cleanup
  - [pid=24330] <gracefully close end>

```