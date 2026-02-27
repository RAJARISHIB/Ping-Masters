"""Script to generate synthetic installment-event data for default model."""

import argparse
import logging
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ml.default_synthetic import generate_synthetic_default_dataset


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    """Generate and export synthetic default prediction dataset."""
    parser = argparse.ArgumentParser(description="Generate default prediction synthetic dataset.")
    parser.add_argument("--rows", type=int, default=12000, help="Number of rows.")
    parser.add_argument(
        "--output",
        type=str,
        default="backend/ml/artifacts/default_training_data.csv",
        help="Output CSV path.",
    )
    args = parser.parse_args()

    dataframe = generate_synthetic_default_dataset(rows=args.rows)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(output_path, index=False)
    logger.info("Default training data written to %s rows=%d", output_path, len(dataframe))


if __name__ == "__main__":
    main()
