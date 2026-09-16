import re
import logging
from pathlib import Path

from core.validate import validate_file

logger = logging.getLogger(__name__)

EXEC_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "execution.yaml"

# Weak models reliably break JSON-escaped file content (regex/CSS \s \d, nested
# quotes, stray backslashes). Delimiter format removes escaping entirely —
# there is nothing for a small model to get wrong.
FILE_START_RE = re.compile(r"===FILE:\s*(.+?)\s*===\r?\n")
FILE_END = "===ENDFILE==="

EXEC_SYSTEM_PROMPT = (
    "You are an expert web developer generating files for a static portfolio "
    "website. You will receive a build phase with instructions and relevant "
    "context files.\n\n"
    "OUTPUT FORMAT — STRICT, FOLLOW EXACTLY:\n"
    "Output each file as one block in exactly this form, and nothing else "
    "before, between, or after the blocks (no markdown fences, no JSON, no "
    "commentary, no explanation):\n\n"
    "===FILE: relative/path.ext===\n"
    "<full file content here, verbatim, byte for byte — no escaping of any "
    "kind, no quoting rules to worry about>\n"
    "===ENDFILE===\n\n"
    "One block per file. Never use the literal strings \"===FILE:\" or "
    "\"===ENDFILE===\" anywhere inside actual file content.\n\n"
    "HARD CONSTRAINT: The output must be implementable as PLAIN HTML + CSS + "
    "vanilla JavaScript only. NO frameworks (React, Vue, Svelte, etc.), NO "
    "build tools (Vite, Webpack, etc.), NO npm packages, NO TypeScript. The "
    "generated site must open directly in a browser from the file system. "
    "Features requiring a build step or server-side runtime (e.g., MDX, "
    "serverless functions, real-time GitHub API calls, WebAssembly, Mermaid.js "
    "interactive rendering) are PROHIBITED. Use only: semantic HTML5, CSS3 "
    "(custom properties, flexbox/grid, animations), vanilla ES6+ JS (fetch, "
    "IntersectionObserver, localStorage). External resources allowed ONLY via "
    "CDN links (Google Fonts, icon SVGs).\n\n"
    "Requirements:\n"
    "- Produce valid HTML5, CSS3, and vanilla ES6 JavaScript only.\n"
    "- No frameworks, no build tools, no external dependencies (CDN links OK "
    "for fonts/icons).\n"
    "- Files must be complete and ready to open directly in a browser.\n"
    "- Follow the UI/UX spec exactly: colors, typography, spacing, responsive "
    "breakpoints.\n"
    "- Ensure accessibility (semantic HTML, ARIA where needed, contrast "
    "ratios).\n"
    "- Mobile-first responsive design.\n"
    "- Write clean, organized code with comments for maintainability.\n"
    "- When a target file already exists in CONTEXT, you are FULLY REWRITING "
    "it — you must carry forward every section/feature it already had, then "
    "add the new content. Never silently drop existing sections, ids, or "
    "functionality. If unsure what existed before, check the CONTEXT files.\n"
)

REPAIR_MSG = (
    "Your previous response did not follow the required output format, or no "
    "files were found in it. Resend the SAME content using EXACTLY this "
    "format — nothing outside the blocks:\n\n"
    "===FILE: relative/path.ext===\n"
    "<file content>\n"
    "===ENDFILE===\n"
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


def _has_deadlock(phases):
    """True if pending phases remain but none are runnable (broken dep graph)."""
    pending = [p for p in phases if p.get("status") == "pending"]
    if not pending:
        return False
    return _find_next_phase(phases) is None


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


def _collect_context_files(run_state, phase):
    site_dir = run_state.run_dir / "site"
    context = {}
    if site_dir.is_dir():
        for f in sorted(site_dir.rglob("*")):
            if f.is_file():
                rel = f.relative_to(site_dir).as_posix()
                try:
                    context[rel] = f.read_text(encoding="utf-8")
                except Exception:
                    pass
    return context


def _collect_cv_artifacts(run_state):
    artifacts = {}
    for name in ("ui_ux_spec.json", "summary.md"):
        path = run_state.run_dir / name
        if path.is_file():
            try:
                artifacts[f"[CV_ARTIFACT] {name}"] = path.read_text(encoding="utf-8")
            except Exception:
                pass
    return artifacts


def _parse_files(raw_text):
    """Parse ===FILE: path=== ... ===ENDFILE=== blocks. No JSON, no escaping."""
    files = []
    for m in FILE_START_RE.finditer(raw_text):
        path = m.group(1).strip()
        body_start = m.end()
        end_idx = raw_text.find(FILE_END, body_start)
        if end_idx == -1:
            continue
        content = raw_text[body_start:end_idx]
        # strip exactly one trailing newline the template puts before ===ENDFILE===
        if content.endswith("\n"):
            content = content[:-1]
        if path:
            files.append({"path": path, "content": content})
    return files


def _generate_files(client, messages, max_tokens):
    raw = client.chat("execution", messages, max_tokens=max_tokens)
    files = _parse_files(raw)
    if files:
        return files

    logger.warning("No files parsed from execution response, attempting format repair")
    raw2 = client.chat(
        "execution",
        messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": REPAIR_MSG},
        ],
        max_tokens=max_tokens,
    )
    files2 = _parse_files(raw2)
    if files2:
        return files2

    raise ValueError(
        "Execution model returned no parseable files after format-repair retry. "
        f"Tail of last response: {raw2[-200:]!r}"
    )


def _validate_and_stage(site_dir, files):
    """Validate each file; reject the whole phase if anything looks broken.

    All-or-nothing on purpose — partial writes leave the site in a state that
    is hard to reason about on the next retry.
    """
    problems = []
    staged = []
    for f in files:
        rel_path = f.get("path", "").strip()
        content = f.get("content", "")
        if not rel_path:
            continue

        ok, err = validate_file(rel_path, content)
        if not ok:
            problems.append(f"{rel_path}: {err}")
            continue

        existing = site_dir / rel_path
        if existing.is_file():
            try:
                old_len = len(existing.read_text(encoding="utf-8"))
                new_len = len(content)
                if old_len > 200 and new_len < old_len * 0.5:
                    problems.append(
                        f"{rel_path}: rewrite shrank from {old_len} to {new_len} chars — "
                        f"looks like earlier content was dropped, not carried forward"
                    )
                    continue
            except Exception:
                pass

        staged.append({"path": rel_path, "content": content})
    return staged, problems


def _write_site_files(run_state, files):
    site_dir = run_state.run_dir / "site"
    site_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        dest = site_dir / f["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f["content"], encoding="utf-8")


def run_execute_loop(client, run_state):
    config = _load_exec_config()
    max_phases = config.get("max_phases", 10)
    max_retries = config.get("max_retries_per_phase", 3)
    max_total_calls = config.get("max_total_calls", 25)
    max_tokens = config.get("max_tokens_execution", 32000)

    phases = run_state.load_todo()

    for p in phases:
        if p.get("status") == "failed":
            retries = p.get("retries", 0)
            if retries < max_retries:
                p["status"] = "pending"
                logger.info("Resetting phase %s from failed to pending for retry", p["id"])
            else:
                logger.warning("Phase %s failed and exhausted retries, leaving as failed", p["id"])

    run_state.save_todo(phases)

    site_dir = run_state.run_dir / "site"
    total_calls = 0
    completed_phases = 0

    while completed_phases < max_phases:
        if _has_deadlock(phases):
            logger.error("Dependency deadlock: pending phases exist but none are runnable")
            break

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

        logger.info("Executing phase: %s (attempt %d/%d)", phase_id, retries + 1, max_retries)

        context_files = _collect_context_files(run_state, phase)
        cv_artifacts = _collect_cv_artifacts(run_state)

        parts = []
        if context_files:
            parts.append(
                "\n\n".join(f"--- {path} ---\n{content}" for path, content in context_files.items())
            )
        if cv_artifacts:
            parts.append(
                "\n\n".join(f"--- {path} ---\n{content}" for path, content in cv_artifacts.items())
            )
        context_str = "\n\n".join(parts) if parts else "(none)"

        prior_error = phase.get("error")
        error_note = (
            f"\nPREVIOUS ATTEMPT FAILED — YOU MUST FIX THIS SPECIFIC ISSUE:\n{prior_error}\n"
            if prior_error else ""
        )

        messages = [
            {"role": "system", "content": EXEC_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"PHASE: {phase['title']}\n"
                    f"PHASE ID: {phase_id}\n"
                    f"INSTRUCTIONS:\n{phase['instructions']}\n\n"
                    f"TARGET FILES: {phase.get('target_files', [])}\n"
                    f"{error_note}\n"
                    f"CONTEXT:\n{context_str}"
                ),
            },
        ]

        try:
            total_calls += 1
            if total_calls > max_total_calls:
                raise RuntimeError(f"Max total LLM calls exceeded ({max_total_calls})")

            files = _generate_files(client, messages, max_tokens)
            if not files:
                raise ValueError("Execution model returned no files")

            staged, problems = _validate_and_stage(site_dir, files)
            if problems:
                raise ValueError("Validation failed:\n" + "\n".join(problems))
            if not staged:
                raise ValueError("No valid files survived validation")

            _write_site_files(run_state, staged)
            _phase_done(phases, phase_id)
            run_state.save_todo(phases)
            completed_phases += 1
            logger.info("Phase %s completed, wrote %d files", phase_id, len(staged))

        except Exception as e:
            logger.exception("Phase %s failed: %s", phase_id, e)
            phase["retries"] = retries + 1
            _phase_failed(phases, phase_id, str(e))
            run_state.save_todo(phases)

    run_state.save_todo(phases)

    failed_phases = [p for p in phases if p.get("status") == "failed" and p.get("retries", 0) <= max_retries]
    if failed_phases:
        return {
            "phases_completed": completed_phases,
            "total_calls": total_calls,
            "success": False,
            "failed_phases": [p["id"] for p in failed_phases],
        }

    return {"phases_completed": completed_phases, "total_calls": total_calls, "success": True}
