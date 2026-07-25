from core.state import call_with_json_repair


UI_UX_SYSTEM_PROMPT = (
    "You are a UI/UX designer planning a portfolio website. "
    "Based on the CV summary and portfolio type below, create a comprehensive "
    "UI/UX specification. Design choices must align with the portfolio type "
    "and be justified by the CV content.\n\n"
    "HARD CONSTRAINT: The output must be implementable as PLAIN HTML + CSS + "
    "vanilla JavaScript only. NO frameworks (React, Vue, Svelte, etc.), NO "
    "build tools (Vite, Webpack, etc.), NO npm packages, NO TypeScript. The "
    "generated site must open directly in a browser from the file system. "
    "Features requiring a build step or server-side runtime (e.g., MDX, "
    "serverless functions, real-time GitHub API calls, WebAssembly) are "
    "PROHIBITED. Use only: semantic HTML5, CSS3 (custom properties, "
    "flexbox/grid, animations), vanilla ES6+ JS (fetch, IntersectionObserver, "
    "localStorage). External resources allowed ONLY via CDN links (Google "
    "Fonts, icon SVGs)."
)


def run_ui_ux_spec(client, run_state):
    summary = run_state.read_markdown("summary.md")
    portfolio_type = run_state.read_json("portfolio_type.json")

    messages = [
        {"role": "system", "content": UI_UX_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Respond with a JSON object containing these fields:\n"
                "- hero_section: { headline, subheadline, layout_notes }\n"
                "- color_palette: { primary, secondary, accent, background, text } "
                "with hex values\n"
                "- typography: { heading_font, body_font, base_size, scale }\n"
                "- theme_mood: string describing the overall design feel\n"
                "- sections: list of { name, type, layout_notes, priority }\n"
                "- icon_imagery_direction: string\n"
                "- responsive_notes: string\n\n"
                f"PORTFOLIO TYPE: {portfolio_type.get('portfolio_type', 'unknown')}\n"
                f"RATIONALE: {portfolio_type.get('rationale', '')}\n\n"
                f"CV SUMMARY:\n---\n{summary}\n---"
            ),
        },
    ]
    result = call_with_json_repair(client, "thinking", messages)
    run_state.write_json("ui_ux_spec.json", result)
    return result
