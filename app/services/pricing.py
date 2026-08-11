"""What a registered tool costs, in one place.

The governed invoke path and the quote endpoint must agree on the price of a
tool to the credit, or a "locked" quote would lock a number the charge never
uses. Both call through here.

Two numbers are in play and they are not the same thing:

- **credits** — what the caller is told and what the permit budget is measured
  in (``credits_per_unit`` on the registration, falling back to the category's
  default price).
- **units** — what ``AgentMoney.charge`` takes, which multiplies back up by the
  category's default price. ``charge_units_for`` is the conversion, and it is
  what lets a quote pin the charged credits even if the tool's registered
  price has moved since the quote was issued.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.schemas.billing import ServiceCategory
from app.services.agent_money import DEFAULT_PRICING


def tool_price(service: dict[str, Any], category: ServiceCategory) -> Decimal:
    """Current price in credits for one call of a registered tool."""
    default_price = DEFAULT_PRICING[category][1]
    exact_price = service.get("credits_per_unit_exact")
    if exact_price is not None:
        return Decimal(str(exact_price))
    return Decimal(str(service.get("credits_per_unit", default_price)))


def charge_units_for(credits: Decimal, category: ServiceCategory) -> Decimal:
    """Convert a credit amount into the units ``AgentMoney.charge`` expects."""
    default_price = DEFAULT_PRICING[category][1]
    return credits / default_price
