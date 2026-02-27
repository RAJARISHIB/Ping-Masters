"""Unit tests for EMI plan catalog loader and default application."""

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from common.emi_plan_catalog import EmiPlanCatalog


class EmiPlanCatalogTests(unittest.TestCase):
    """Validate catalog loading and default merge behavior."""

    def setUp(self) -> None:
        """Build catalog from repository plan file."""
        self.catalog = EmiPlanCatalog(path=str(BACKEND_ROOT / "settings" / "emi_plans.json"))

    def test_catalog_loads_plan_rows(self) -> None:
        """Catalog should load at least one enabled plan."""
        plans = self.catalog.list_plan_models(include_disabled=False)
        self.assertGreater(len(plans), 0)

    def test_apply_plan_defaults_sets_key_values(self) -> None:
        """Applying defaults should inject installment and threshold fields."""
        merged, plan = self.catalog.apply_plan_defaults(
            payload={"emi_plan_id": "bnpl_pay_in_4", "currency": "INR"},
            force=True,
        )
        self.assertIsNotNone(plan)
        self.assertEqual(merged["installment_count"], 4)
        self.assertEqual(merged["tenure_days"], 60)
        self.assertEqual(merged["ltv_bps"], 7000)


if __name__ == "__main__":
    unittest.main()
