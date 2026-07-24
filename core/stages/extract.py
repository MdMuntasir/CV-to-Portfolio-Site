from pypdf import PdfReader


EXTRACT_SYSTEM_PROMPT = (
    "You are a CV text summarizer. "
    "Given the full text of a CV below, produce a clean, de-duplicated summary "
    "highlighting the key skills, experience, education, and achievements. "
    "Remove redundancies, fix obvious OCR/formatting issues, and organize the "
    "information clearly. Output only the summary as plain markdown text."
)


def run_extract(client, run_state, cv_pdf=None, cv_text=None):
    if cv_pdf:
        reader = PdfReader(cv_pdf)
        pages = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
        raw_text = "\n\n".join(pages)
    elif cv_text:
        raw_text = cv_text
    else:
        raise ValueError("Either cv_pdf or cv_text must be provided")

    run_state.write_markdown("full_text.md", raw_text)

    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": f"CV TEXT:\n---\n{raw_text}\n---"},
    ]
    summary = client.chat("quick", messages)
    run_state.write_markdown("summary.md", summary)

    return {"full_text": raw_text, "summary": summary}
