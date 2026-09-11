"""Pod orchestration: compose existing wallet + key primitives, atomically.

A pod is a sponsor wallet tagged as a pod (``metadata_json: {"kind": "pod",
"pod_name": ...}``) plus N agent wallets — one per member — each with its
own wallet-scoped API key. All of it is provisioned from one
``POST /v1/pods`` call.

Composition, not a new primitive
---------------------------------
Every money movement here is an existing, tested operation
(``AgentMoney.create_sponsor_wallet``, ``AgentMoney.create_agent_wallet``,
``APIKeyService.create_key``). This module adds no new ledger entries, no
new spend-authorization path, and no new key format. If those primitives are
correct, a pod is correct.

Atomicity, honestly scoped
---------------------------
Each underlying call is its own DB transaction (that's how
``AgentMoney``/``WalletEngine`` already work — see
``app/services/wallet_engine.py``). This module does not add cross-call
distributed-transaction machinery. Instead it fails *before* creating
anything if the requested member budgets cannot possibly succeed (over-
allocation against the pod total), which is the failure mode a caller will
actually hit. A failure *during* member provisioning (e.g. a transient DB
error after member 1 of 3 succeeded) leaves a partial pod: the sponsor
wallet and any already-created members are real and spendable, and the
error response names which members were completed so a caller can inspect
or extend the pod rather than silently losing state. This is a documented
limitation, not a claim of full atomicity — see docs/pods.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .agent_money import AgentMoney, WalletNotFoundError, get_agent_money
from .api_key_service import APIKeyService, get_api_key_service

POD_METADATA_KIND = "pod"


class PodError(Exception):
    """Base error for pod orchestration failures."""


class PodNotFoundError(PodError):
    def __init__(self, pod_id: str):
        self.pod_id = pod_id
        super().__init__(f"Pod not found: {pod_id}")


class PodBudgetError(PodError):
    """Requested member budgets cannot fit inside the pod's total budget."""


class PodPartiallyProvisionedError(PodError):
    """A member failed mid-provisioning; earlier members were already created."""

    def __init__(
        self,
        pod_id: str,
        completed_agent_ids: list[str],
        failed_agent_id: str,
        original_error: Exception,
    ):
        self.pod_id = pod_id
        self.completed_agent_ids = completed_agent_ids
        self.failed_agent_id = failed_agent_id
        self.original_error = original_error
        super().__init__(
            f"Pod {pod_id} partially provisioned: "
            f"{len(completed_agent_ids)} member(s) succeeded before "
            f"{failed_agent_id!r} failed ({original_error})."
        )


@dataclass
class PodMemberSpec:
    agent_id: str
    key_name: str
    budget_credits: Decimal | None


@dataclass
class ProvisionedMember:
    agent_id: str
    wallet_id: str
    budget_credits: Decimal
    key_id: str
    key_prefix: str
    api_key: str


@dataclass
class ProvisionedPod:
    pod_id: str
    pod_name: str
    budget_credits: Decimal
    members: list[ProvisionedMember]


def _split_budget_evenly(
    total: Decimal, unset_count: int, already_allocated: Decimal
) -> Decimal:
    remaining = total - already_allocated
    if unset_count == 0:
        return Decimal("0")
    # Truncate to 8 decimal places (wallet precision) rather than round up,
    # so an even split never over-allocates past the pod total.
    share = (remaining / unset_count).quantize(Decimal("0.00000001"))
    return share if share >= 0 else Decimal("0")


def _resolve_member_budgets(
    total_budget: Decimal, members: list[PodMemberSpec]
) -> list[Decimal]:
    """Resolve each member's budget, splitting the remainder evenly where unset.

    Raises PodBudgetError before anything is created if explicit member
    budgets alone already exceed the pod total.
    """
    explicit_sum = sum(
        (m.budget_credits for m in members if m.budget_credits is not None),
        Decimal("0"),
    )
    if explicit_sum > total_budget:
        raise PodBudgetError(
            f"Member budgets sum to {explicit_sum} which exceeds the pod's "
            f"total budget of {total_budget}."
        )

    unset_count = sum(1 for m in members if m.budget_credits is None)
    even_share = _split_budget_evenly(total_budget, unset_count, explicit_sum)

    return [
        m.budget_credits if m.budget_credits is not None else even_share
        for m in members
    ]


class PodService:
    """Orchestrates pod creation and budget reporting on top of AgentMoney."""

    def __init__(
        self,
        money: AgentMoney | None = None,
        keys: APIKeyService | None = None,
    ):
        self._money = money or get_agent_money()
        self._keys = keys or get_api_key_service()

    async def create_pod(
        self,
        pod_name: str,
        budget_credits: Decimal,
        members: list[PodMemberSpec],
    ) -> ProvisionedPod:
        member_budgets = _resolve_member_budgets(budget_credits, members)

        sponsor = await self._money.create_sponsor_wallet(
            sponsor_name=f"pod:{pod_name}",
            email=f"pod+{pod_name}@pods.local",
            initial_credits=budget_credits,
            require_kyc=False,
            metadata={"kind": POD_METADATA_KIND, "pod_name": pod_name},
        )

        provisioned: list[ProvisionedMember] = []
        for member, member_budget in zip(members, member_budgets):
            agent_id = member.agent_id or f"pod-member-{len(provisioned)}"
            try:
                agent_wallet = await self._money.create_agent_wallet(
                    sponsor_wallet_id=sponsor.wallet_id,
                    agent_id=agent_id,
                    budget_credits=member_budget,
                )
                key = await self._keys.create_key(
                    wallet_id=agent_wallet.wallet_id,
                    key_name=member.key_name,
                )
            except Exception as exc:  # noqa: BLE001 - re-raised typed, with context
                raise PodPartiallyProvisionedError(
                    pod_id=sponsor.wallet_id,
                    completed_agent_ids=[m.agent_id for m in provisioned],
                    failed_agent_id=agent_id,
                    original_error=exc,
                ) from exc

            provisioned.append(
                ProvisionedMember(
                    agent_id=agent_id,
                    wallet_id=agent_wallet.wallet_id,
                    budget_credits=member_budget,
                    key_id=key["key_id"],
                    key_prefix=key["key_prefix"],
                    api_key=key["api_key"],
                )
            )

        return ProvisionedPod(
            pod_id=sponsor.wallet_id,
            pod_name=pod_name,
            budget_credits=budget_credits,
            members=provisioned,
        )

    async def get_pod_budget(self, pod_id: str) -> dict:
        """Aggregate budget status for a pod. Raises PodNotFoundError if the
        wallet doesn't exist, or PodError if it exists but isn't a pod."""
        wallet = await self._money.get_wallet(pod_id)
        if wallet is None:
            raise PodNotFoundError(pod_id)

        metadata = wallet.metadata or {}
        if metadata.get("kind") != POD_METADATA_KIND:
            raise PodError(f"Wallet {pod_id} exists but is not a pod.")

        try:
            swarm = await self._money.get_swarm_budget(pod_id)
        except WalletNotFoundError as exc:
            raise PodNotFoundError(pod_id) from exc

        return {
            "pod_id": pod_id,
            "pod_name": metadata.get("pod_name", ""),
            "total_budget": wallet.lifetime_credits,
            "remaining_at_pod": swarm["parent_balance"],
            "allocated_to_members": swarm["total_delegated"],
            "members": [
                {
                    "agent_id": child.agent_id,
                    "wallet_id": child.wallet_id,
                    "status": child.status,
                    "balance": child.balance,
                    "lifetime_debits": child.lifetime_debits,
                }
                for child in swarm["children"]
            ],
        }


_pod_service: PodService | None = None


def get_pod_service() -> PodService:
    global _pod_service
    if _pod_service is None:
        _pod_service = PodService()
    return _pod_service
