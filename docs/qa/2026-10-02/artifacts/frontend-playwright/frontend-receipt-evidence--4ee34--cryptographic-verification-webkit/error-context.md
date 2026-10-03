# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend.spec.cjs >> receipt evidence loads without claiming cryptographic verification
- Location: docs/qa/2026-10-02/frontend.spec.cjs:48:1

# Error details

```
Error: browserType.launch: Target page, context or browser has been closed
Browser logs:

<launching> /private/tmp/amw-qa-playwright-browsers/webkit-2359/pw_run.sh --inspector-pipe --headless --no-startup-window
<launched> pid=25054
[pid=25054][err] /private/tmp/amw-qa-playwright-browsers/webkit-2359/pw_run.sh: line 7: 25059 Abort trap: 6              DYLD_FRAMEWORK_PATH="$DYLIB_PATH" DYLD_LIBRARY_PATH="$DYLIB_PATH" "$PLAYWRIGHT" "$@"
Call log:
  - <launching> /private/tmp/amw-qa-playwright-browsers/webkit-2359/pw_run.sh --inspector-pipe --headless --no-startup-window
  - <launched> pid=25054
  - [pid=25054][err] /private/tmp/amw-qa-playwright-browsers/webkit-2359/pw_run.sh: line 7: 25059 Abort trap: 6              DYLD_FRAMEWORK_PATH="$DYLIB_PATH" DYLD_LIBRARY_PATH="$DYLIB_PATH" "$PLAYWRIGHT" "$@"
  - [pid=25054] <gracefully close start>
  - [pid=25054] <kill>
  - [pid=25054] <will force kill>
  - [pid=25054] exception while trying to kill process: Error: kill EPERM
  - [pid=25054] <process did exit: exitCode=134, signal=null>
  - [pid=25054] starting temporary directories cleanup
  - [pid=25054] finished temporary directories cleanup
  - [pid=25054] <gracefully close end>

```