# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend.spec.cjs >> malformed receipt payload fails closed
- Location: docs/qa/2026-10-02/frontend.spec.cjs:62:1

# Error details

```
Error: browserType.launch: Target page, context or browser has been closed
Browser logs:

<launching> /private/tmp/amw-qa-playwright-browsers/webkit-2359/pw_run.sh --inspector-pipe --headless --no-startup-window
<launched> pid=25072
[pid=25072][err] /private/tmp/amw-qa-playwright-browsers/webkit-2359/pw_run.sh: line 7: 25077 Abort trap: 6              DYLD_FRAMEWORK_PATH="$DYLIB_PATH" DYLD_LIBRARY_PATH="$DYLIB_PATH" "$PLAYWRIGHT" "$@"
Call log:
  - <launching> /private/tmp/amw-qa-playwright-browsers/webkit-2359/pw_run.sh --inspector-pipe --headless --no-startup-window
  - <launched> pid=25072
  - [pid=25072][err] /private/tmp/amw-qa-playwright-browsers/webkit-2359/pw_run.sh: line 7: 25077 Abort trap: 6              DYLD_FRAMEWORK_PATH="$DYLIB_PATH" DYLD_LIBRARY_PATH="$DYLIB_PATH" "$PLAYWRIGHT" "$@"
  - [pid=25072] <gracefully close start>
  - [pid=25072] <kill>
  - [pid=25072] <will force kill>
  - [pid=25072] exception while trying to kill process: Error: kill EPERM
  - [pid=25072] <process did exit: exitCode=134, signal=null>
  - [pid=25072] starting temporary directories cleanup
  - [pid=25072] finished temporary directories cleanup
  - [pid=25072] <gracefully close end>

```