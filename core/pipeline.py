import logging

from core.state import RunState, RunStateError
from core.stages.extract import run_extract
from core.stages.classify import run_classify
from core.stages.ui_ux_spec import run_ui_ux_spec
from core.stages.todo_plan import run_todo_plan

logger = logging.getLogger(__name__)


def run_pipeline(client, cv_pdf=None, cv_text=None, resume_run_id=None):
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
    ]

    for name, fn in stages:
        logger.info("Stage [%s] starting", name)
        fn()
        logger.info("Stage [%s] complete", name)

    logger.info("Pipeline finished — run dir: %s", run_state.run_dir)
    return run_state
