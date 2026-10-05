"""Config-driven pricing engine. All numbers live in config/pricing.yaml."""
from typing import Callable, Dict, Optional, Tuple

import yaml


class Pricing:
    def __init__(self, path: str, overrides: Optional[Callable[[], Dict[str, int]]] = None):
        # overrides() -> {"STARTER": 450000, ...}: prices kept in bas.mn Items win over
        # the matrix (one price per tier there, whatever the business type).
        self.overrides = overrides
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.currency = cfg.get("currency", "MNT")
        self.tiers = cfg["tiers"]                       # ordered
        self.tier_names = [t["name"] for t in self.tiers]
        self.branch_bump = cfg.get("branch_bump", False)
        self.branch_threshold = cfg.get("branch_bump_threshold", 4)
        self.matrix = cfg.get("matrix", {})

    def _base_tier(self, employees: int) -> str:
        for t in self.tiers:
            cap = t.get("max_employees")
            if cap is None or employees <= cap:
                return t["name"]
        return self.tier_names[-1]

    def _bump(self, tier: str) -> str:
        i = self.tier_names.index(tier)
        return self.tier_names[min(i + 1, len(self.tier_names) - 1)]

    def tier_for(self, employees: int, branches: int) -> str:
        tier = self._base_tier(employees)
        if self.branch_bump and branches >= self.branch_threshold and tier != "Enterprise":
            tier = self._bump(tier)
        return tier

    def quote(self, employees: int, branches: int, business_type: str) -> Tuple[str, Optional[int], str]:
        """Returns (tier, price, currency). price is None for custom quotes."""
        tier = self.tier_for(employees, branches)
        override = (self.overrides() if self.overrides else {}).get(tier.upper())
        if override:
            return tier, override, self.currency
        row = self.matrix.get(tier)
        if not row:  # Enterprise or any tier with no matrix row -> custom
            return tier, None, self.currency
        price = row.get(business_type, row.get("Other"))
        return tier, price, self.currency
