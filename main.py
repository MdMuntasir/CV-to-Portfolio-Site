"""CLI entry point for CV-to-portfolio generator."""

import argparse
import logging
import sys
from pathlib import Path

from core.pipeline import run_pipeline
from core.provider_client import (
    ProviderClient,
    ProviderConfigError,
    ProviderResponseError,
)
from core.state import RunStateError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="portfolio-generator",
        description="Generate a static portfolio website from a CV (PDF or pasted text).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate a new portfolio from a CV")
    gen.add_argument("--cv", type=str, default=None, help="Path to a PDF CV file")
    gen.add_argument("--cv-text", type=str, default=None, help="CV text pasted directly")
    gen.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output directory for the generated site (default: output/<run_id>)",
    )
    gen.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="Override max provider retry attempts",
    )

    res = sub.add_parser("resume", help="Resume a previously failed run")
    res.add_argument("--run-id", type=str, required=True, help="Run ID to resume")
    res.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output directory (default: output/<run_id>)",
    )

    return parser


def _check_pdf(path_str):
    if not path_str:
        return None
    p = Path(path_str)
    if not p.is_file():
        print(f"Error: File not found — {p.resolve()}")
        sys.exit(1)
    if p.suffix.lower() != ".pdf":
        print(f"Error: File must be a PDF — {p}")
        sys.exit(1)
    try:
        with open(p, "rb") as fh:
            fh.read(5)
    except Exception as e:
        print(f"Error: Cannot read PDF file — {e}")
        sys.exit(1)
    return str(p.resolve())


def _pick_output(args_output, run_id):
    if args_output:
        return str(Path(args_output).resolve())
    return None


def cmd_generate(args):
    if not args.cv and not args.cv_text:
        print(
            "Error: Provide either --cv <path.pdf> or --cv-text \"<text>\" (or both)."
        )
        sys.exit(1)

    cv_pdf = _check_pdf(args.cv)
    cv_text = args.cv_text

    client_kwargs = {}
    if args.max_attempts is not None:
        client_kwargs["max_attempts"] = args.max_attempts

    try:
        client = ProviderClient(**client_kwargs)
    except ProviderConfigError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

    try:
        run_state = run_pipeline(
            client,
            cv_pdf=cv_pdf,
            cv_text=cv_text,
            output_dir=_pick_output(args.output, None),
        )
        sys.exit(0)
    except ProviderConfigError as e:
        print(f"\nAPI Key Error: {e}")
        print("  -> Set the required key in your .env file (see .env.example).")
        sys.exit(1)
    except ProviderResponseError as e:
        print(f"\nProvider Error: {e}")
        print("  -> This may be a transient issue. Retry with 'resume' if a run dir exists.")
        sys.exit(1)
    except RunStateError as e:
        print(f"\nRun State Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)


def cmd_resume(args):
    run_id = args.run_id.strip()
    run_dir = Path.cwd() / "runs" / run_id
    if not run_dir.is_dir():
        print(f"Error: Run directory not found — {run_dir}")
        print("  -> Check that the run ID is correct.")
        sys.exit(1)

    try:
        from core.pipeline import run_pipeline as _rp

        client = ProviderClient()
        _rp(
            client,
            resume_run_id=run_id,
            output_dir=_pick_output(args.output, run_id),
        )
        sys.exit(0)
    except ProviderConfigError as e:
        print(f"\nAPI Key Error: {e}")
        print("  -> Set the required key in your .env file (see .env.example).")
        sys.exit(1)
    except ProviderResponseError as e:
        print(f"\nProvider Error: {e}")
        print("  -> The run directory has been preserved. Re-run 'resume' after fixing.")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error during resume: {e}")
        sys.exit(1)


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "resume":
        cmd_resume(args)


if __name__ == "__main__":
    main()
