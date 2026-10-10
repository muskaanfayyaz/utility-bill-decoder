import os
import zipfile
import sys
from pathlib import Path
from source.validate import validate_level1_csv, validate_level2_csv

MAX_ZIP_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB limit per Section 7


def package_submission(zip_filename: str = "your-submission.zip") -> Path:
    root_dir = Path(".")
    source_dir = root_dir / "source"
    output_dir = root_dir / "output"
    demo_dir = root_dir / "demo"

    # Pre-checks
    if not source_dir.exists():
        raise FileNotFoundError("Missing source/ directory.")
    if not output_dir.exists():
        raise FileNotFoundError("Missing output/ directory.")

    level1_csv = output_dir / "level1.csv"
    level2_csv = output_dir / "level2.csv"

    if not level1_csv.exists():
        raise FileNotFoundError(f"Missing required output file: {level1_csv}")
    if not level2_csv.exists():
        raise FileNotFoundError(f"Missing required output file: {level2_csv}")

    print("Validating output CSVs prior to packaging...")
    l1_errs = validate_level1_csv(level1_csv, expected_count=10)
    l2_errs = validate_level2_csv(level2_csv, expected_count=120)

    if l1_errs or l2_errs:
        error_msg = "\n".join(l1_errs + l2_errs)
        raise RuntimeError(f"CSV Validation failed prior to packaging:\n{error_msg}")

    print("CSV validation passed: level1.csv (10 rows), level2.csv (120 rows).")

    # Build ZIP archive
    zip_path = root_dir / zip_filename
    if zip_path.exists():
        zip_path.unlink()

    forbidden_patterns = [".env", "__pycache__", ".git", ".pytest_cache", ".pyc", ".cache"]

    print(f"Creating submission ZIP: {zip_path.name}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Add source files
        for file in sorted(source_dir.rglob("*")):
            if file.is_file():
                # Strictly exclude real .env, caches, and pyc
                if any(p in file.as_posix() for p in forbidden_patterns) and file.name != ".env.example":
                    continue
                rel_path = file.relative_to(root_dir)
                zipf.write(file, arcname=str(rel_path).replace("\\", "/"))

        # Add output files
        for file in sorted(output_dir.rglob("*")):
            if file.is_file() and file.suffix.lower() == ".csv":
                rel_path = file.relative_to(root_dir)
                zipf.write(file, arcname=str(rel_path).replace("\\", "/"))

        # Add demo files if any
        if demo_dir.exists():
            for file in sorted(demo_dir.rglob("*")):
                if file.is_file() and file.suffix.lower() in [".mp4", ".mov", ".webm"]:
                    rel_path = file.relative_to(root_dir)
                    zipf.write(file, arcname=str(rel_path).replace("\\", "/"))

    size_bytes = zip_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    print(f"Package created: {zip_path.name} ({size_mb:.2f} MB)")

    if size_bytes > MAX_ZIP_SIZE_BYTES:
        raise ValueError(
            f"Submission ZIP exceeds 15 MB limit! Current size: {size_mb:.2f} MB. "
            "Please compress demo video or remove large assets."
        )

    print("Submission ZIP successfully created and verified.")
    return zip_path


if __name__ == "__main__":
    package_submission()
