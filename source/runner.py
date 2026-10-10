import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from .config import validate_config, MODEL_NAME, MODEL_PROVIDER
from .client import GeminiClientWrapper
from .schemas import Level1Bill
from .extractor import BillExtractor
from .explainer import BillExplainer
from .csv_handler import (
    read_level1_template,
    read_level2_template,
    write_level1_csv,
    write_level2_csv,
)
from .validate import validate_level1_csv, validate_level2_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("wtq_runner")


def resolve_paths(
    test_dir: Path,
    bills_dir: Optional[Path] = None,
    template_dir: Optional[Path] = None,
) -> Tuple[Path, Path, Path]:
    """
    Intelligently resolves bills directory and template file paths
    from test_dir or explicit arguments.
    """
    # 1. Resolve Bills Directory
    resolved_bills = bills_dir
    if not resolved_bills:
        if (test_dir / "bills").exists() and (test_dir / "bills").is_dir():
            resolved_bills = test_dir / "bills"
        elif test_dir.exists():
            resolved_bills = test_dir
        else:
            raise FileNotFoundError(f"Test directory not found: {test_dir}")

    # 2. Resolve Templates
    resolved_l1_template: Optional[Path] = None
    resolved_l2_template: Optional[Path] = None

    candidate_l1_paths = [
        (template_dir / "level1.csv") if template_dir else None,
        test_dir / "csv" / "level1.csv",
        test_dir / "level1.csv",
    ]
    for p in candidate_l1_paths:
        if p and p.exists():
            resolved_l1_template = p
            break

    candidate_l2_paths = [
        (template_dir / "level2.csv") if template_dir else None,
        test_dir / "csv" / "level2.csv",
        test_dir / "level2.csv",
    ]
    for p in candidate_l2_paths:
        if p and p.exists():
            resolved_l2_template = p
            break

    if not resolved_l1_template:
        raise FileNotFoundError(
            f"Could not locate level1.csv template in {template_dir or test_dir}."
        )
    if not resolved_l2_template:
        raise FileNotFoundError(
            f"Could not locate level2.csv template in {template_dir or test_dir}."
        )

    return resolved_bills, resolved_l1_template, resolved_l2_template


def find_bill_image(bills_dir: Path, bill_id: str) -> Optional[Path]:
    """Finds image file matching bill_id stem across common image extensions."""
    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        candidate = bills_dir / f"{bill_id}{ext}"
        if candidate.exists():
            return candidate
    return None


def run_pipeline(
    test_dir: Path = Path("data/test"),
    bills_dir: Optional[Path] = None,
    template_dir: Optional[Path] = None,
    output_dir: Path = Path("output"),
    level1_only: bool = False,
) -> None:
    """
    Executes the complete WTQ Utility Bill Decoder pipeline.
    Preserves exact row order, required columns, and validates every output.
    """
    start_time = time.time()
    validate_config(require_api_key=True)
    logger.info(f"Initialized WTQ Bill Decoder using {MODEL_PROVIDER} ({MODEL_NAME})")

    resolved_bills_dir, l1_template_path, l2_template_path = resolve_paths(
        test_dir=test_dir,
        bills_dir=bills_dir,
        template_dir=template_dir,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    out_level1_csv = output_dir / "level1.csv"
    out_level2_csv = output_dir / "level2.csv"

    # 1. Load and validate templates
    bill_ids = read_level1_template(l1_template_path)
    logger.info(f"Loaded {len(bill_ids)} bills from level1 template ({l1_template_path.name})")

    l2_rows = read_level2_template(l2_template_path)
    logger.info(f"Loaded {len(l2_rows)} question rows from level2 template ({l2_template_path.name})")

    # 2. Check for missing images upfront
    logger.info(f"Scanning for bill images in {resolved_bills_dir}...")
    bill_images: Dict[str, Path] = {}
    missing_images: List[str] = []
    for bid in bill_ids:
        img_path = find_bill_image(resolved_bills_dir, bid)
        if not img_path:
            missing_images.append(bid)
        else:
            bill_images[bid] = img_path

    if missing_images:
        raise FileNotFoundError(
            f"Missing required bill images for {len(missing_images)} bill(s): {missing_images}. "
            f"Expected images in '{resolved_bills_dir}'."
        )
    logger.info(f"All {len(bill_images)} required bill images located successfully.")

    # 3. Initialize Engine Components
    client = GeminiClientWrapper()
    extractor = BillExtractor(client=client)
    explainer = BillExplainer(client=client)

    # 4. Level 1: Extraction
    extracted_bills: Dict[str, Level1Bill] = {}
    logger.info(f"=== [Level 1] Starting Extraction for {len(bill_ids)} bills ===")

    for idx, bid in enumerate(bill_ids, start=1):
        img_path = bill_images[bid]
        logger.info(f"[{idx}/{len(bill_ids)}] Extracting Level 1 details for '{bid}' ({img_path.name})...")
        try:
            bill_obj = extractor.extract(img_path)
            extracted_bills[bid] = bill_obj
            logger.info(
                f" -> Extracted {bid}: Provider={bill_obj.provider}, Month={bill_obj.bill_month}, "
                f"CurrentBill={bill_obj.current_bill}"
            )
        except Exception as e:
            logger.error(f"FATAL: Extraction failed on bill '{bid}': {e}")
            raise RuntimeError(
                f"Level 1 extraction failed for '{bid}'. Failing clearly per competition rules."
            ) from e

    # Write output/level1.csv
    write_level1_csv(out_level1_csv, bill_ids, extracted_bills)
    logger.info(f"Level 1 CSV generated at: {out_level1_csv}")

    # Validate Level 1 immediately
    l1_errors = validate_level1_csv(out_level1_csv, expected_count=len(bill_ids))
    if l1_errors:
        logger.error("Level 1 validation failed:")
        for err in l1_errors:
            logger.error(f"  - {err}")
        raise RuntimeError("Validation failed on generated level1.csv.")

    if level1_only:
        logger.info("level1_only flag specified. Skipping Level 2.")
        return

    # 5. Level 2: Explanations and Questions
    logger.info(f"=== [Level 2] Starting Question Answering for {len(l2_rows)} rows ===")

    # Group questions by bill_id while preserving exact ordering
    bill_questions: Dict[str, List[Tuple[str, str]]] = {bid: [] for bid in bill_ids}
    for bid, qid, qtext in l2_rows:
        if bid not in bill_questions:
            raise ValueError(
                f"Question template references bill_id '{bid}' not present in level1 template!"
            )
        bill_questions[bid].append((qid, qtext))

    answers_dict: Dict[Tuple[str, str], str] = {}

    for idx, bid in enumerate(bill_ids, start=1):
        q_list = bill_questions[bid]
        if not q_list:
            continue
        img_path = bill_images[bid]
        bill_obj = extracted_bills[bid]
        logger.info(f"[{idx}/{len(bill_ids)}] Answering {len(q_list)} questions for '{bid}'...")

        try:
            batch_answers = explainer.answer_questions_batch(img_path, bill_obj, q_list)
            for qid, qtext in q_list:
                ans = batch_answers.get(qid)
                if not ans or not ans.strip():
                    raise ValueError(f"Empty answer received for bill '{bid}', question '{qid}'")
                answers_dict[(bid, qid)] = ans.strip()
            logger.info(f" -> Successfully answered all {len(q_list)} questions for {bid}.")
        except Exception as e:
            logger.error(f"FATAL: Level 2 QA failed on bill '{bid}': {e}")
            raise RuntimeError(
                f"Level 2 processing failed for bill '{bid}'. Failing clearly per competition rules."
            ) from e

    # Write output/level2.csv
    write_level2_csv(out_level2_csv, l2_rows, answers_dict)
    logger.info(f"Level 2 CSV generated at: {out_level2_csv}")

    # Validate Level 2 CSV
    l2_errors = validate_level2_csv(out_level2_csv, expected_count=len(l2_rows))
    if l2_errors:
        logger.error("Level 2 validation failed:")
        for err in l2_errors:
            logger.error(f"  - {err}")
        raise RuntimeError("Validation failed on generated level2.csv.")

    # 6. Final Progress Summary
    elapsed_time = time.time() - start_time
    logger.info("=" * 60)
    logger.info("WTQ PIPELINE EXECUTION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total Bills Processed:   {len(bill_ids)} bills")
    logger.info(f"Total Questions Answered: {len(l2_rows)} questions")
    logger.info(f"Model Provider / Model:  {MODEL_PROVIDER} ({MODEL_NAME})")
    logger.info(f"Level 1 Output File:     {out_level1_csv} ({len(bill_ids)} rows) -> VALID")
    logger.info(f"Level 2 Output File:     {out_level2_csv} ({len(l2_rows)} rows) -> VALID")
    logger.info(f"Total Elapsed Time:      {elapsed_time:.1f} seconds")
    logger.info("=" * 60)
    logger.info("SUCCESS: All test outputs generated and validated with zero defects!")


def main():
    parser = argparse.ArgumentParser(
        description="WTQ Utility Bill Decoder - Official CLI Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--test-dir",
        type=Path,
        default=Path("data/test"),
        help="Root path of the test dataset (containing 'bills' and 'csv' subdirectories)",
    )
    parser.add_argument(
        "--bills-dir",
        type=Path,
        default=None,
        help="Optional explicit path to directory containing bill images",
    )
    parser.add_argument(
        "--template-dir",
        type=Path,
        default=None,
        help="Optional explicit path to directory containing CSV templates",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Path to output directory for completed CSV files",
    )
    parser.add_argument(
        "--level1-only",
        action="store_true",
        help="Execute only Level 1 extraction",
    )

    args = parser.parse_args()

    try:
        run_pipeline(
            test_dir=args.test_dir,
            bills_dir=args.bills_dir,
            template_dir=args.template_dir,
            output_dir=args.output_dir,
            level1_only=args.level1_only,
        )
    except Exception as e:
        logger.error(f"Execution terminated with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
