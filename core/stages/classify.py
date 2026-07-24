from core.state import call_with_json_repair


CLASSIFY_SYSTEM_PROMPT = (
    "You are a portfolio type classifier. "
    "Read the CV summary below and determine the most appropriate portfolio "
    "website type for this person. Choose from categories like: "
    "\"developer/technical\", \"creative/visual\", \"academic/research\", "
    "\"business/consulting\", \"minimal/resume-style\", or any other fitting type. "
    "Justify your choice with specific evidence from the CV."
)


def run_classify(client, run_state):
    summary = run_state.read_markdown("summary.md")

    messages = [
        {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Respond with a JSON object:\n"
                "{\n"
                '  "portfolio_type": "the chosen type",\n'
                '  "rationale": "detailed explanation"\n'
                "}\n\n"
                f"CV SUMMARY:\n---\n{summary}\n---"
            ),
        },
    ]
    result = call_with_json_repair(client, "thinking", messages)
    run_state.write_json("portfolio_type.json", result)
    return result
