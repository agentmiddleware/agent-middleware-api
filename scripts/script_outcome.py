"""Shared exit-code contract for operator verification scripts.

Every script that verifies the trust plane ends with one of four codes, so an
operator or CI can tell earned success apart from every other outcome without
reading the log:

* EXIT_OK (0): every named check held.
* EXIT_FAILED (1): at least one named check failed.
* EXIT_SETUP (2): the run never started (bad usage, unsafe target, missing
  credentials, unreachable server).
* EXIT_INCOMPLETE (3): no check failed, but success was not earned. Either
  every check was skipped, or cleanup left resources behind that the operator
  must remove by hand.

Code 3 exists because exit 0 on an all-skipped run reads as a pass while
nothing was verified, and exit 0 after a failed cleanup reads as clean while
keys may still be live.
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_SETUP = 2
EXIT_INCOMPLETE = 3


def exit_code(*, failed: int, held: int, incomplete: int) -> int:
    """Map check counts to the contract above.

    ``failed`` counts checks that did not hold. ``held`` counts checks that
    did. ``incomplete`` counts work that was neither held nor failed: skipped
    checks and cleanup items left behind. A run with zero held checks earns
    no success even when nothing failed.
    """
    if failed:
        return EXIT_FAILED
    if incomplete or held == 0:
        return EXIT_INCOMPLETE
    return EXIT_OK
