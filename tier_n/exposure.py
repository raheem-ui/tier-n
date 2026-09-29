"""Deterministic revenue-at-risk math.

The LLM never invents dollar figures. It may only propose an adjusted
disruption length (backed by a cited memory); the numbers are recomputed here.
"""
from dataclasses import dataclass, field

from .data import products, suppliers_by_id


@dataclass
class SupplierExposure:
    supplier_id: str
    supplier_name: str
    parts: list[str]
    products: list[str]
    inventory_days: int
    gap_days: int
    revenue_at_risk_usd: int


@dataclass
class Exposure:
    disruption_days: int
    suppliers: list[SupplierExposure] = field(default_factory=list)
    by_product_usd: dict[str, int] = field(default_factory=dict)

    @property
    def total_usd(self) -> int:
        return sum(self.by_product_usd.values())


def compute_exposure(affected_supplier_ids: list[str], disruption_days: int) -> Exposure:
    """Revenue at risk = daily product revenue x supply share lost x days short.

    Days short = disruption length minus the supplier's inventory buffer. Loss per
    product is capped at the longest gap among its affected suppliers, so two
    suppliers feeding the same product can't count more than a full stoppage.
    """
    catalog = suppliers_by_id()
    prods = products()
    disruption_days = max(0, int(disruption_days))
    exposure = Exposure(disruption_days=disruption_days)

    weighted_days: dict[str, float] = {}
    max_gap: dict[str, int] = {}
    for sid in affected_supplier_ids:
        s = catalog.get(sid)
        if s is None:
            continue
        gap = max(0, disruption_days - s["inventory_days"])
        at_risk = 0
        for pid in s["products"]:
            daily = prods[pid]["daily_revenue_usd"]
            at_risk += round(daily * s["share_of_bom_supply"] * gap)
            weighted_days[pid] = weighted_days.get(pid, 0.0) + s["share_of_bom_supply"] * gap
            max_gap[pid] = max(max_gap.get(pid, 0), gap)
        exposure.suppliers.append(
            SupplierExposure(
                supplier_id=sid,
                supplier_name=s["name"],
                parts=s["parts"],
                products=s["products"],
                inventory_days=s["inventory_days"],
                gap_days=gap,
                revenue_at_risk_usd=at_risk,
            )
        )

    for pid, days in weighted_days.items():
        exposure.by_product_usd[pid] = round(prods[pid]["daily_revenue_usd"] * min(days, max_gap[pid]))
    return exposure
