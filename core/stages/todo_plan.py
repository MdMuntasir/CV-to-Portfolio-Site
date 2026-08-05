from core.state import call_with_json_repair


TODO_SYSTEM_PROMPT = (
    "You are a project planner breaking down a static portfolio website build "
    "into ordered, atomic phases. Each phase will be executed by an automated "
    "code-generation model.\n\n"
    "CRITICAL RULES:\n"
    "1. Each phase must be SMALL and FOCUSED — create or modify at most 2 "
    "files. Do NOT bundle multiple independent features into one phase.\n"
    "2. The execution model receives ONLY the phase instructions and previously "
    "generated site files — it does NOT have access to the CV or spec "
    "documents. Therefore you MUST embed the exact text content (headlines, "
    "skill names and categories, project descriptions with full detail, "
    "experience bullets, education entries, achievement lists, contact info, "
    "etc.) directly into each phase's 'instructions' field.\n"
    "3. Each phase FULLY REWRITES its target files — there is no patching or "
    "diffing. Design a clean file structure in phase 1 that later phases can "
    "safely extend by appending new content.\n"
    "4. All phases are sequential. Each must produce a working intermediate "
    "state. Design dependencies so nothing breaks across phases.\n"
    "5. The output is plain HTML5 + CSS3 + vanilla ES6+ JS only (no "
    "frameworks, no build tools, no npm, no TypeScript). External resources "
    "only via CDN (Google Fonts, icon SVGs)."
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
                "an ordered list of phase objects (aim for 8-10 focused phases). "
                "Each phase object has:\n"
                '- "id": unique string (e.g. "phase_1_structure")\n'
                '- "title": short descriptive name\n'
                '- "instructions": detailed build instructions — INCLUDE THE '
                "EXACT CV TEXT (headlines, skill names, project descriptions, "
                "experience bullets, education entries, achievement lists, "
                "contact links) inline so the code-generation model can place "
                "it directly on the page\n"
                '- "target_files": list of files this phase creates or modifies '
                "(max 2 files)\n"
                '- "status": "pending"\n'
                '- "dependencies": list of phase IDs that must be done first\n'
                '- "notes": "" (or additional context)\n\n'
                "Suggested breakdown (adjust as needed for the specific CV):\n"
                "1) HTML skeleton + CSS reset/variables + empty JS file\n"
                "2) Hero section (headline, subtitle, canvas, CTA button)\n"
                "3) About section (biography text, optional photo)\n"
                "4) Skills section (categorized tags with exact skill names)\n"
                "5) Experience timeline (all roles with exact bullets)\n"
                "6) Project cards (all projects with exact descriptions + "
                "placeholder modal structure)\n"
                "7) Project modal interactivity (JS to open/close, populate "
                "details dynamically)\n"
                "8) Education + Achievements + Contact sections (exact data)\n"
                "9) Responsive CSS + hamburger menu markup\n"
                "10) Navigation, icons, scroll animations, meta tags, polish\n\n"
                "REMEMBER: The code-generation model CANNOT see the CV text "
                "below. You MUST copy the actual content into each phase's "
                "instructions so the builder can populate the page.\n\n"
                f"UI/UX SPEC:\n{_json.dumps(ui_ux_spec, indent=2)}\n\n"
                f"FULL CV TEXT:\n---\n{full_text}\n---"
            ),
        },
    ]
    result = call_with_json_repair(client, "thinking", messages)
    run_state.save_todo(result.get("phases", result))
    return result
