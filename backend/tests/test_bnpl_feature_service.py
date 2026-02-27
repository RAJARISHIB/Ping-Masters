"""Unit tests for BNPL feature orchestration service."""

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.config import load_settings
from ml.orchestrator import MlPayloadOrchestrator
from services.bnpl_feature_service import BnplFeatureService
from services.protocol_api_service import ProtocolApiService


class BnplFeatureServiceTests(unittest.TestCase):
    """Validate high-value BNPL feature flows."""

    def setUp(self) -> None:
        """Build service with in-memory fallback storage."""
        settings = load_settings()
        protocol = ProtocolApiService()
        protocol.update_prices(usd_price=30000000000, inr_price=2500000000000)
        orchestrator = MlPayloadOrchestrator(
            ml_enabled=False,
            risk_inference=None,
            default_inference=None,
            deposit_inference=None,
        )
        self.service = BnplFeatureService(
            settings=settings,
            protocol_service=protocol,
            user_repository=None,
            firebase_manager=None,
            ml_orchestrator=orchestrator,
        )

    def _create_plan(self) -> dict:
        """Create a helper loan plan."""
        return self.service.create_bnpl_plan(
            user_id="usr_101",
            merchant_id="mer_201",
            principal_minor=10000,
            currency="INR",
            installment_count=4,
            tenure_days=120,
            ltv_bps=7000,
            danger_limit_bps=8000,
            liquidation_threshold_bps=9000,
            grace_window_hours=24,
            late_fee_flat_minor=100,
            late_fee_bps=200,
        )

    def test_create_plan_generates_valid_schedule(self) -> None:
        """Plan creation should generate matching installment total."""
        result = self._create_plan()
        self.assertIn("loan", result)
        self.assertIn("installments", result)
        self.assertEqual(len(result["installments"]), 4)
        total = sum(item["amount_minor"] for item in result["installments"])
        self.assertEqual(total, 10000)

    def test_lock_collateral_updates_safety_meter(self) -> None:
        """Locked collateral should produce a non-zero safety meter."""
        plan = self._create_plan()
        loan_id = plan["loan"]["loan_id"]
        lock = self.service.lock_security_deposit(
            loan_id=loan_id,
            user_id="usr_101",
            asset_symbol="BNB",
            deposited_units=1000000000000000000,
            collateral_value_minor=18000,
            oracle_price_minor=2500000,
            vault_address="0xabc1230000000000000000000000000000000000",
            chain_id=97,
            deposit_tx_hash="0xdeadbeef00112233445566778899aabb",
        )
        self.assertIn("collateral", lock)
        self.assertIn("safety_meter", lock)
        self.assertGreater(lock["safety_meter"]["health_factor"], 0.0)

    def test_partial_recovery_seizes_only_needed(self) -> None:
        """Partial recovery must not seize more than needed amount."""
        plan = self._create_plan()
        loan_id = plan["loan"]["loan_id"]
        installment_id = plan["installments"][0]["installment_id"]
        self.service.lock_security_deposit(
            loan_id=loan_id,
            user_id="usr_101",
            asset_symbol="BNB",
            deposited_units=1000000000000000000,
            collateral_value_minor=25000,
            oracle_price_minor=2500000,
            vault_address="0xabc1230000000000000000000000000000000000",
            chain_id=97,
            deposit_tx_hash="0xfeedbeef00112233445566778899aabb",
        )
        recovery = self.service.execute_partial_recovery(
            loan_id=loan_id,
            installment_id=installment_id,
            initiated_by_role="LIQUIDATOR",
            notes="unit test",
        )
        log = recovery["liquidation_log"]
        self.assertLessEqual(log["seized_minor"], log["needed_minor"])

    def test_pause_blocks_risky_actions(self) -> None:
        """Emergency pause should block plan creation."""
        self.service.set_pause_state(paused=True, reason="maintenance", role="ADMIN", actor="tester")
        with self.assertRaises(ValueError):
            self._create_plan()

    def test_dispute_flow_sets_and_resolves_status(self) -> None:
        """Dispute flow should transition loan states correctly."""
        plan = self._create_plan()
        loan_id = plan["loan"]["loan_id"]
        opened = self.service.open_dispute(loan_id=loan_id, reason="delivery issue", actor="usr_101")
        self.assertEqual(opened["loan"]["status"], "DISPUTE_OPEN")
        resolved = self.service.resolve_dispute(
            loan_id=loan_id,
            resolution="merchant refunded",
            actor="admin",
            restore_active=True,
        )
        self.assertEqual(resolved["loan"]["status"], "ACTIVE")

    def test_create_plan_with_emi_plan_id_applies_defaults(self) -> None:
        """EMI plan id should stamp plan metadata and defaults into loan."""
        result = self.service.create_bnpl_plan(
            user_id="usr_301",
            merchant_id="mer_401",
            principal_minor=120000,
            currency="INR",
            installment_count=2,
            tenure_days=45,
            ltv_bps=5000,
            danger_limit_bps=6500,
            liquidation_threshold_bps=7500,
            grace_window_hours=6,
            late_fee_flat_minor=100,
            late_fee_bps=50,
            emi_plan_id="bnpl_pay_in_4",
            use_plan_defaults=True,
        )
        loan = result["loan"]
        self.assertEqual(loan["emi_plan_id"], "bnpl_pay_in_4")
        self.assertEqual(int(loan["installment_count"]), 4)
        self.assertEqual(int(loan["tenure_days"]), 60)

    def test_idempotent_plan_creation_replay(self) -> None:
        """Same idempotency key should return the original plan response."""
        first = self.service.create_bnpl_plan(
            user_id="usr_401",
            merchant_id="mer_501",
            principal_minor=20000,
            currency="INR",
            installment_count=4,
            tenure_days=120,
            ltv_bps=7000,
            danger_limit_bps=8000,
            liquidation_threshold_bps=9000,
            grace_window_hours=24,
            late_fee_flat_minor=100,
            late_fee_bps=200,
            idempotency_key="idem_plan_123",
        )
        second = self.service.create_bnpl_plan(
            user_id="usr_401",
            merchant_id="mer_501",
            principal_minor=20000,
            currency="INR",
            installment_count=4,
            tenure_days=120,
            ltv_bps=7000,
            danger_limit_bps=8000,
            liquidation_threshold_bps=9000,
            grace_window_hours=24,
            late_fee_flat_minor=100,
            late_fee_bps=200,
            idempotency_key="idem_plan_123",
        )
        self.assertEqual(first["loan"]["loan_id"], second["loan"]["loan_id"])

    def test_invalid_state_transition_rejected(self) -> None:
        """State machine should reject invalid transitions."""
        plan = self._create_plan()
        loan_id = plan["loan"]["loan_id"]
        with self.assertRaises(ValueError):
            self.service.transition_loan_state(
                loan_id=loan_id,
                new_status="CANCELLED",
                actor="tester",
                reason="invalid from active",
            )


if __name__ == "__main__":
    unittest.main()
