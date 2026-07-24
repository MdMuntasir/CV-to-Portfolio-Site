import logging
import json
import shutil
from pathlib import Path
from core.state import RunStateError, extract_json

logger = logging.getLogger(__name__)

EXEC_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "execution.yaml"

EXEC_SYSTEM_PROMPT = (
    "You are an expert web developer generating files for a static portfolio website. "
    "You will receive a build phase with instructions and relevant context files. "
    "Output ONLY a JSON object with a single key \"files\" containing an array of file "
    "objects. Each file object must have:\n"
    "- \"path\": relative path from site root (e.g., \"index.html\", \"styles/main.css\")\n"
    "- \"content\": full file content as a string\n\n"
    "Requirements:\n"
    "- Produce valid HTML5, CSS3, and vanilla ES6 JavaScript only.\n"
    "- No frameworks, no build tools, no external dependencies (CDN links OK for fonts/icons).\n"
    "- Files must be complete and ready to open directly in a browser.\n"
    "- Follow the UI/UX spec exactly: colors, typography, spacing, responsive breakpoints.\n"
    "- Ensure accessibility (semantic HTML, ARIA where needed, contrast ratios).\n"
    "- Mobile-first responsive design.\n"
    "- Write clean, organized code with comments for maintainability.\n"
    "- Output ONLY the JSON object. No markdown, no explanation, no extra text."
)


def _load_exec_config():
    import yaml
    with open(EXEC_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _find_next_phase(phases):
    for phase in phases:
        if phase.get("status") == "pending":
            deps = phase.get("dependencies", [])
            if not deps:
                return phase
            all_done = True
            for dep_id in deps:
                dep = next((p for p in phases if p["id"] == dep_id), None)
                if not dep or dep.get("status") != "done":
                    all_done = False
                    break
            if all_done:
                return phase
    return None


def _phase_done(phases, phase_id):
    for p in phases:
        if p["id"] == phase_id:
            p["status"] = "done"
            p.pop("error", None)
            break


def _phase_failed(phases, phase_id, error_msg):
    for p in phases:
        if p["id"] == phase_id:
            p["status"] = "failed"
            p["error"] = error_msg
            break


def _read_site_file(run_state, rel_path):
    site_dir = run_state.run_dir / "site"
    file_path = site_dir / rel_path
    if file_path.is_file():
        try:
            return file_path.read_text(encoding="utf-8")
        except Exception:
            pass
    return None


def _collect_context_files(run_state, phase):
    target_files = phase.get("target_files", [])
    context = {}
    for rel_path in target_files:
        content = _read_site_file(run_state, rel_path)
        if content:
            context[rel_path] = content
    return context


def _write_site_files(run_state, files):
    site_dir = run_state.run_dir / "site"
    site_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        rel_path = f.get("path", "").strip()
        content = f.get("content", "")
        if not rel_path:
            continue
        dest = site_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def run_execute_loop(client, run_state):
    config = _load_exec_config()
    max_phases = config.get("max_phases", 10)
    max_retries = config.get("max_retries_per_phase", 2)
    max_total_calls = config.get("max_total_calls", 25)

    phases = run_state.load_todo()
    
    # Reset failed phases back to pending for resumability (if retries not exhausted)
    for p in phases:
        if p.get("status") == "failed":
            retries = p.get("retries", 0)
            if retries < max_retries:
                p["status"] = "pending"
                logger.info("Resetting phase %s from failed to pending for retry", p["id"])
            else:
                logger.warning("Phase %s failed and exhausted retries, leaving as failed", p["id"])
    
    run_state.save_todo(phases)

    total_calls = 0
    completed_phases = 0

    while completed_phases < max_phases:
        phase = _find_next_phase(phases)
        if not phase:
            logger.info("All phases completed")
            break

        phase_id = phase["id"]
        retries = phase.get("retries", 0)

        if retries > max_retries:
            logger.error("Phase %s exceeded max retries (%d)", phase_id, max_retries)
            _phase_failed(phases, phase_id, f"Max retries exceeded ({max_retries})")
            run_state.save_todo(phases)
            break

        logger.info("Executing phase: %s (attempt %d/%d)", phase_id, retries + 1, max_retries + 1)

        context_files = _collect_context_files(run_state, phase)
        context_str = ""
        if context_files:
            context_str = "\n\n".join(
                f"--- {path} ---\n{content}" for path, content in context_files.items()
            )

        messages = [
            {"role": "system", "content": EXEC_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"PHASE: {phase['title']}\n"
                    f"PHASE ID: {phase_id}\n"
                    f"INSTRUCTIONS:\n{phase['instructions']}\n\n"
                    f"TARGET FILES: {phase.get('target_files', [])}\n\n"
                    f"PREVIOUS FILES CONTEXT:\n{context_str if context_str else '(none)'}"
                ),
            },
        ]

        try:
            total_calls += 1
            if total_calls > max_total_calls:
                raise RuntimeError(f"Max total LLM calls exceeded ({max_total_calls})")

            raw = client.chat("execution", messages, max_tokens=8000)
            result = extract_json(raw)
            files = result.get("files", [])

            if not files:
                raise ValueError("Execution model returned no files")

            _write_site_files(run_state, files)
            _phase_done(phases, phase_id)
            run_state.save_todo(phases)
            completed_phases += 1
            logger.info("Phase %s completed, wrote %d files", phase_id, len(files))

        except Exception as e:
            logger.exception("Phase %s failed: %s", phase_id, e)
            phase["retries"] = retries + 1
            _phase_failed(phases, phase_id, str(e))
            run_state.save_todo(phases)

    run_state.save_todo(phases)
    return {"phases_completed": completed_phases, "total_calls": total_calls}