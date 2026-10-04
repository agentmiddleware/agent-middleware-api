# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend.spec.cjs >> main public pages load without browser or resource errors
- Location: docs/qa/2026-10-02/frontend.spec.cjs:9:1

# Error details

```
Error: browserType.launch: Target page, context or browser has been closed
Browser logs:

<launching> /private/tmp/amw-qa-playwright-browsers/webkit-2359/pw_run.sh --inspector-pipe --headless --no-startup-window
<launched> pid=24833
[pid=24833][err] /private/tmp/amw-qa-playwright-browsers/webkit-2359/pw_run.sh: line 7: 24840 Abort trap: 6              DYLD_FRAMEWORK_PATH="$DYLIB_PATH" DYLD_LIBRARY_PATH="$DYLIB_PATH" "$PLAYWRIGHT" "$@"
Call log:
  - <launching> /private/tmp/amw-qa-playwright-browsers/webkit-2359/pw_run.sh --inspector-pipe --headless --no-startup-window
  - <launched> pid=24833
  - [pid=24833][err] /private/tmp/amw-qa-playwright-browsers/webkit-2359/pw_run.sh: line 7: 24840 Abort trap: 6              DYLD_FRAMEWORK_PATH="$DYLIB_PATH" DYLD_LIBRARY_PATH="$DYLIB_PATH" "$PLAYWRIGHT" "$@"
  - [pid=24833] <gracefully close start>
  - [pid=24833] <kill>
  - [pid=24833] <will force kill>
  - [pid=24833] exception while trying to kill process: Error: kill EPERM
  - [pid=24833] <process did exit: exitCode=134, signal=null>
  - [pid=24833] starting temporary directories cleanup
  - [pid=24833] finished temporary directories cleanup
  - [pid=24833] <gracefully close end>

```