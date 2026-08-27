import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def cleanup_run(run_dir):
    run_dir = Path(run_dir)
    if run_dir.is_dir():
        shutil.rmtree(run_dir)
        logger.info("Cleaned up run directory: %s", run_dir)


def finalize_site(run_state, output_dir=None):
    if output_dir is None:
        output_dir = _OUTPUT_DIR / run_state.run_id
    output_dir = Path(output_dir)

    site_dir = run_state.run_dir / "site"
    if not site_dir.is_dir():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    for item in site_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, output_dir / item.name)
        elif item.is_dir():
            shutil.copytree(item, output_dir / item.name, dirs_exist_ok=True)

    for md_file in ("full_text.md", "summary.md"):
        src = run_state.run_dir / md_file
        if src.is_file():
            shutil.copy2(src, output_dir / md_file)

    logger.info("Finalized site to: %s", output_dir)
    return output_dir


def finalize_and_cleanup(run_state, output_dir=None):
    try:
        finalize_site(run_state, output_dir)
        cleanup_run(run_state.run_dir)
        return True
    except Exception as e:
        logger.error("Finalization failed, keeping run directory: %s", e)
        return False