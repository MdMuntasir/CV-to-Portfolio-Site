from core.state import call_with_json_repair


TODO_SYSTEM_PROMPT = (
    "You are a project planner breaking down a portfolio website build "
    "into ordered phases. Based on the UI/UX spec and full CV text below, "
    "create a detailed build plan. Each phase must be concrete and actionable "
    "by an automated code-generation model."
)


def run_todo_plan(client, run_state):
    full_text = run_state.read_markdown("full_text.md")
    ui_ux_spec = run_state.read_json("ui_ux_spec.json")

    import json as _json

    messages = [
        {"role": "system", "content": TODO_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Return a JSON object with a single key \"phases\" containing "
                "an ordered list of phase objects (5-8 phases). Each phase has:\n"
                '- "id": unique string (e.g. "phase_1")\n'
                '- "title": short name\n'
                '- "instructions": detailed build instructions\n'
                '- "target_files": list of file paths this phase creates\n'
                '- "status": "pending"\n'
                '- "dependencies": list of phase IDs that must come first\n'
                '- "notes": "" (or additional context)\n\n'
                "Cover these build phases: HTML structure, CSS styling, "
                "section-by-section implementation, responsive design, "
                "interactivity/animations, content population, and polish.\n\n"
                f"UI/UX SPEC:\n{_json.dumps(ui_ux_spec, indent=2)}\n\n"
                f"FULL CV TEXT:\n---\n{full_text}\n---"
            ),
        },
    ]
    result = call_with_json_repair(client, "thinking", messages)
    run_state.save_todo(result.get("phases", result))
    return result
