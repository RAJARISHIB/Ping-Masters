"""Script to train deposit recommendation ML model."""

import argparse
import logging
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ml.deposit_synthetic import generate_synthetic_deposit_dataset
from backend.ml.deposit_trainer import train_and_save_deposit_model


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    """Train and persist deposit recommendation model."""
    parser = argparse.ArgumentParser(description="Train deposit recommendation model.")
    parser.add_argument("--data", type=str, default="", help="Optional input CSV path.")
    parser.add_argument("--rows", type=int, default=10000, help="Rows for synthetic generation if --data omitted.")
    parser.add_argument(
        "--output",
        type=str,
        default="backend/ml/artifacts/deposit_recommendation_model.joblib",
        help="Model artifact path.",
    )
    args = parser.parse_args()

    if args.data:
        data_path = Path(args.data)
        if not data_path.exists():
            raise FileNotFoundError("Dataset file not found: {0}".format(data_path))
        dataframe = pd.read_csv(data_path)
        logger.info("Loaded deposit training data from %s rows=%d", data_path, len(dataframe))
    else:
        dataframe = generate_synthetic_deposit_dataset(rows=args.rows)
        logger.info("Generated synthetic deposit training data rows=%d", len(dataframe))

    summary = train_and_save_deposit_model(dataframe=dataframe, output_path=args.output)
    logger.info("Deposit model training summary: %s", summary)


if __name__ == "__main__":
    main()
