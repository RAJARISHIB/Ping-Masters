"""Script to train next-installment default prediction model."""

import argparse
import logging
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ml.default_synthetic import generate_synthetic_default_dataset
from backend.ml.default_trainer import train_and_save_default_model


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    """Train and save default prediction model artifact."""
    parser = argparse.ArgumentParser(description="Train calibrated GBDT default prediction model.")
    parser.add_argument("--data", type=str, default="", help="Optional input CSV path.")
    parser.add_argument("--rows", type=int, default=12000, help="Synthetic rows if --data omitted.")
    parser.add_argument(
        "--output",
        type=str,
        default="backend/ml/artifacts/default_prediction_model.joblib",
        help="Output model artifact path.",
    )
    parser.add_argument("--high-threshold", type=float, default=0.60, help="HIGH tier threshold.")
    parser.add_argument("--medium-threshold", type=float, default=0.30, help="MEDIUM tier threshold.")
    args = parser.parse_args()

    if args.data:
        data_path = Path(args.data)
        if not data_path.exists():
            raise FileNotFoundError("Dataset not found: {0}".format(data_path))
        dataframe = pd.read_csv(data_path)
        logger.info("Loaded default training data from %s rows=%d", data_path, len(dataframe))
    else:
        dataframe = generate_synthetic_default_dataset(rows=args.rows)
        logger.info("Generated synthetic default training data rows=%d", len(dataframe))

    summary = train_and_save_default_model(
        dataframe=dataframe,
        output_path=args.output,
        high_threshold=args.high_threshold,
        medium_threshold=args.medium_threshold,
    )
    logger.info("Default model training summary: %s", summary)


if __name__ == "__main__":
    main()
