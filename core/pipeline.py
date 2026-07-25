import logging
from pathlib import Path

from core.state import RunState, RunStateError
from core.stages.extract import run_extract
from core.stages.classify import run_classify
from core.stages.ui_ux_spec import run_ui_ux_spec
from core.stages.todo_plan import run_todo_plan
from core.stages.execute_loop import run_execute_loop
from core.cleanup import finalize_and_cleanup

logger = logging.getLogger(__name__)


def _artifact_exists(run_state, filename):
    path = run_state.run_dir / filename
    return path.is_file() and path.stat().st_size > 0


def _all_phases_done(run_state):
    """True only if todo.json exists and every phase has status 'done'."""
    if not _artifact_exists(run_state, "todo.json"):
        return False
    try:
        phases = run_state.load_todo()
    except Exception:
        return False
    if not phases:
        return False
    return all(p.get("status") == "done" for p in phases)


def _skip_stage(run_state, stage_name):
    # execute_loop is only complete when ALL todo phases are done — the presence
    # of site/index.html only means phase 1 ran, not the whole plan.
    if stage_name == "execute_loop":
        return _all_phases_done(run_state)

    artifacts = {
        "extract": ["full_text.md", "summary.md"],
        "classify": ["portfolio_type.json"],
        "ui_ux_spec": ["ui_ux_spec.json"],
        "todo_plan": ["todo.json"],
    }
    required = artifacts.get(stage_name)
    if required is None:
        return False
    return all(_artifact_exists(run_state, f) for f in required)


def run_pipeline(client, cv_pdf=None, cv_text=None, resume_run_id=None, output_dir=None):
    if resume_run_id:
        logger.info("Resuming run %s", resume_run_id)
        run_state = RunState(run_id=resume_run_id)
    else:
        run_state = RunState()
        logger.info("Starting new run %s", run_state.run_id)

    stages = [
        ("extract", lambda: run_extract(client, run_state, cv_pdf, cv_text)),
        ("classify", lambda: run_classify(client, run_state)),
        ("ui_ux_spec", lambda: run_ui_ux_spec(client, run_state)),
        ("todo_plan", lambda: run_todo_plan(client, run_state)),
        ("execute_loop", lambda: run_execute_loop(client, run_state)),
    ]

    for name, fn in stages:
        if resume_run_id and _skip_stage(run_state, name):
            logger.info("Stage [%s] already complete — skipping", name)
            continue
        logger.info("Stage [%s] starting", name)
        try:
            result = fn()
            if name == "execute_loop" and isinstance(result, dict) and not result.get("success", True):
                failed_phases = result.get("failed_phases", [])
                raise RuntimeError(f"Execute loop failed: phases {failed_phases} did not complete successfully")
            logger.info("Stage [%s] complete", name)
        except Exception as e:
            logger.error("Stage [%s] failed: %s — run dir preserved at %s", name, e, run_state.run_dir)
            raise

    logger.info("Finalizing site...")
    success = finalize_and_cleanup(run_state, output_dir)

    if success:
        logger.info("Pipeline finished successfully — site at output/%s", run_state.run_id)
    else:
        logger.warning("Pipeline finished with issues — run dir preserved at %s", run_state.run_dir)

    return run_state
