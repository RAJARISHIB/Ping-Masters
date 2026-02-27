"""Unit tests for Firestore-ready domain models."""

from datetime import datetime, timedelta, timezone
import unittest

from pydantic import ValidationError

from backend.models.collaterals import CollateralModel
from backend.models.enums import LiquidationActionType, LoanStatus, RiskTier
from backend.models.exceptions import ModelNotFoundError, ModelValidationError, VersionConflictError
from backend.models.installments import InstallmentModel
from backend.models.liquidation_logs import LiquidationLogModel
from backend.models.loans import LoanModel
from backend.models.risk_scores import RiskScoreModel
from backend.models.users import UserModel


class ModelValidationTests(unittest.TestCase):
    """Test model happy paths and business rules."""

    def test_user_model_happy_path(self) -> None:
        """Create a valid user model."""
        user = UserModel(
            user_id="usr_1",
            email="test@example.com",
            phone="9999999999",
            full_name="Test User",
            notification_channels=["Email", "whatsapp", "email"],
            wallet_address=[
                {"name": "Primary", "wallet_id": "0x1234567890"},
                {"name": "Backup", "wallet_id": "0xabcdef1234"},
            ],
        )
        self.assertEqual(user.user_id, "usr_1")
        self.assertEqual(user.notification_channels, ["email", "whatsapp"])
        self.assertEqual(user.wallet_address[0].name, "Primary")

    def test_loan_threshold_validation(self) -> None:
        """Reject invalid threshold relationships."""
        with self.assertRaises(ValidationError):
            LoanModel(
                loan_id="loan_1",
                user_id="usr_1",
                merchant_id="mer_1",
                principal_minor=10000,
                tenure_days=30,
                installment_count=4,
                ltv_bps=7000,
                borrow_limit_minor=7000,
                danger_limit_bps=9000,
                liquidation_threshold_bps=8500,
            )

    def test_dispute_requires_pause_marker(self) -> None:
        """Require penalties pause timestamp when dispute is open."""
        with self.assertRaises(ValidationError):
            LoanModel(
                loan_id="loan_2",
                user_id="usr_1",
                merchant_id="mer_1",
                principal_minor=10000,
                tenure_days=30,
                installment_count=4,
                ltv_bps=7000,
                borrow_limit_minor=7000,
                danger_limit_bps=7500,
                liquidation_threshold_bps=9000,
                status=LoanStatus.DISPUTE_OPEN,
            )

    def test_collateral_recovery_rule(self) -> None:
        """Reject collateral with over-recovered amounts."""
        with self.assertRaises(ValidationError):
            CollateralModel(
                collateral_id="col_1",
                user_id="usr_1",
                loan_id="loan_1",
                vault_address="0xabc12345",
                chain_id=97,
                deposit_tx_hash="0xtxhash1234",
                asset_symbol="BNB",
                deposited_units=1000,
                collateral_value_minor=25000,
                oracle_price_minor=25,
                recoverable_minor=5000,
                recovered_minor=6000,
            )

    def test_installment_schedule_validation(self) -> None:
        """Validate ordered installment sequences and expected sum."""
        due_at = datetime.now(timezone.utc)
        installments = [
            InstallmentModel(
                installment_id="ins_1",
                loan_id="loan_1",
                user_id="usr_1",
                sequence_no=1,
                due_at=due_at,
                amount_minor=2500,
            ),
            InstallmentModel(
                installment_id="ins_2",
                loan_id="loan_1",
                user_id="usr_1",
                sequence_no=2,
                due_at=due_at + timedelta(days=7),
                amount_minor=2500,
            ),
        ]
        InstallmentModel.validate_schedule(installments, expected_total_minor=5000)

        with self.assertRaises(ModelValidationError):
            InstallmentModel.validate_schedule(installments, expected_total_minor=4000)

    def test_liquidation_partial_recovery_guardrail(self) -> None:
        """Reject seized amount beyond needed amount."""
        with self.assertRaises(ValidationError):
            LiquidationLogModel(
                log_id="log_1",
                loan_id="loan_1",
                user_id="usr_1",
                collateral_id="col_1",
                triggered_at=datetime.now(timezone.utc),
                trigger_reason="PAYMENT_MISSED",
                health_factor_at_trigger=0.82,
                missed_amount_minor=1000,
                penalty_minor=100,
                needed_minor=1100,
                seized_minor=1200,
                action_type=LiquidationActionType.PARTIAL_RECOVERY,
                initiated_by_role="LIQUIDATOR",
            )

    def test_risk_score_explainability_shape(self) -> None:
        """Ensure risk score supports explanation and recommendation fields."""
        score = RiskScoreModel(
            risk_score_id="risk_1",
            user_id="usr_1",
            score=640,
            tier=RiskTier.MEDIUM,
            default_probability_bps=1800,
            top_factors=["late_payment_count", "high_utilization"],
            recommendation_minor=2500,
            feature_snapshot={"late_payment_count": 2},
        )
        self.assertEqual(score.top_factors[0], "late_payment_count")
        self.assertEqual(score.feature_snapshot["late_payment_count"], 2)

    def test_firestore_roundtrip_for_all_models(self) -> None:
        """Verify serialization/deserialization roundtrip for each model."""
        now = datetime.now(timezone.utc)

        user = UserModel(
            user_id="usr_2",
            email="u2@example.com",
            phone="8888888888",
            full_name="User Two",
        )
        user_copy = UserModel.from_firestore(user.to_firestore(), doc_id="doc_u2")
        self.assertEqual(user_copy.id, "doc_u2")

        loan = LoanModel(
            loan_id="loan_rt",
            user_id="usr_2",
            merchant_id="mer_2",
            principal_minor=10000,
            tenure_days=30,
            installment_count=4,
            ltv_bps=7000,
            borrow_limit_minor=7000,
            danger_limit_bps=8000,
            liquidation_threshold_bps=9000,
            outstanding_minor=6000,
            penalty_accrued_minor=500,
        )
        self.assertEqual(LoanModel.from_firestore(loan.to_firestore()).loan_id, "loan_rt")

        collateral = CollateralModel(
            collateral_id="col_rt",
            user_id="usr_2",
            loan_id="loan_rt",
            vault_address="0xabc12345",
            chain_id=97,
            deposit_tx_hash="0xtxhash5678",
            asset_symbol="USDT",
            deposited_units=10000,
            collateral_value_minor=12000,
            oracle_price_minor=1,
            recoverable_minor=5000,
            recovered_minor=1000,
        )
        self.assertEqual(CollateralModel.from_firestore(collateral.to_firestore()).collateral_id, "col_rt")

        risk = RiskScoreModel(
            risk_score_id="risk_rt",
            user_id="usr_2",
            score=700,
            tier=RiskTier.LOW,
            default_probability_bps=600,
        )
        self.assertEqual(RiskScoreModel.from_firestore(risk.to_firestore()).risk_score_id, "risk_rt")

        installment = InstallmentModel(
            installment_id="ins_rt",
            loan_id="loan_rt",
            user_id="usr_2",
            sequence_no=1,
            due_at=now + timedelta(days=7),
            amount_minor=2500,
        )
        self.assertEqual(InstallmentModel.from_firestore(installment.to_firestore()).installment_id, "ins_rt")

        liquidation = LiquidationLogModel(
            log_id="log_rt",
            loan_id="loan_rt",
            user_id="usr_2",
            collateral_id="col_rt",
            triggered_at=now,
            trigger_reason="MISSED_PAYMENT",
            health_factor_at_trigger=0.7,
            missed_amount_minor=1200,
            penalty_minor=100,
            needed_minor=1300,
            seized_minor=1200,
            action_type=LiquidationActionType.PARTIAL_RECOVERY,
            initiated_by_role="LIQUIDATOR",
        )
        self.assertEqual(LiquidationLogModel.from_firestore(liquidation.to_firestore()).log_id, "log_rt")

    def test_repository_error_types_importable(self) -> None:
        """Confirm required repository exception types are available."""
        self.assertTrue(issubclass(ModelNotFoundError, Exception))
        self.assertTrue(issubclass(VersionConflictError, Exception))


if __name__ == "__main__":
    unittest.main()
