"""Shared authority for wallet spending and velocity-freeze transitions."""

from ..schemas.billing import WalletStatus

# Spending rule: ACTIVE and PENDING_KYC wallets can spend; every other
# status (suspended, frozen, closed, operator holds) cannot. Pending KYC
# is deliberately spendable: it marks a wallet awaiting a routine
# verification check, not a freeze. Freezing funds pending verification
# is a separate, explicit step (suspend or freeze the wallet).
#
# Regulated buyers should note this: a wallet created with KYC required
# can still spend while verification is pending. If a use case needs
# funds frozen until KYC passes, set the wallet to suspended or frozen
# and release it when verification completes.
#
# Unknown/future control states fail closed until explicitly admitted here.
# Use this same allowlist in Python prechecks and atomic SQL write guards.
SPENDABLE_WALLET_STATUSES = frozenset(
    {WalletStatus.ACTIVE.value, WalletStatus.PENDING_KYC.value}
)
