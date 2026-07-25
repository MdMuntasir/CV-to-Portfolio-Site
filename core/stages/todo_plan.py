from core.state import call_with_json_repair


TODO_SYSTEM_PROMPT = (
    "You are a project planner breaking down a portfolio website build "
    "into ordered phases. Based on the UI/UX spec and full CV text below, "
    "create a detailed build plan. Each phase must be concrete and actionable "
    "by an automated code-generation model.\n\n"
    "HARD CONSTRAINT: The output must be implementable as PLAIN HTML + CSS + "
    "vanilla JavaScript only. NO frameworks (React, Vue, Svelte, etc.), NO "
    "build tools (Vite, Webpack, etc.), NO npm packages, NO TypeScript. The "
    "generated site must open directly in a browser from the file system. "
    "Features requiring a build step or server-side runtime (e.g., MDX, "
    "serverless functions, real-time GitHub API calls, WebAssembly, Mermaid.js "
    "interactive rendering, Prism.js syntax highlighting) are PROHIBITED. "
    "External libraries are NOT allowed — only CDN links for Google Fonts and "
    "icon SVGs (e.g., Lucide, Feather). NO Prism.js, NO Mermaid.js, NO "
    "Chart.js, NO external CSS frameworks. Use only: semantic HTML5, CSS3 "
    "(custom properties, flexbox/grid, animations, conic-gradient for skill "
    "rings), vanilla ES6+ JS (fetch, IntersectionObserver, localStorage). "
    "Code snippets in project cards must be plain <pre><code> with CSS-only "
    "styling (no syntax highlighting library). Architecture diagrams must be "
    "static SVG or ASCII art — no interactive Mermaid rendering."
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
                "IMPORTANT: Do NOT include Prism.js, Mermaid.js, Chart.js, or "
                "any external JS libraries in target_files. Only plain HTML, "
                "CSS, and vanilla JS files. Code snippets use plain <pre><code> "
                "with CSS styling. Architecture diagrams use static SVG.\n\n"
                f"UI/UX SPEC:\n{_json.dumps(ui_ux_spec, indent=2)}\n\n"
                f"FULL CV TEXT:\n---\n{full_text}\n---"
            ),
        },
    ]
    result = call_with_json_repair(client, "thinking", messages)
    run_state.save_todo(result.get("phases", result))
    return result
