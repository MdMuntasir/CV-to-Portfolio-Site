import re
import json
from datetime import datetime
from pathlib import Path


class RunStateError(Exception):
    pass


def generate_run_id():
    now = datetime.now()
    return now.strftime("run_%Y%m%d_%H%M%S")


_RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


class RunState:
    def __init__(self, run_id=None, runs_dir=None):
        self.runs_dir = Path(runs_dir) if runs_dir else _RUNS_DIR
        if run_id:
            self.run_id = run_id
            self.run_dir = self.runs_dir / run_id
            if not self.run_dir.is_dir():
                raise RunStateError(f"Run directory not found: {self.run_dir}")
        else:
            self.run_id = generate_run_id()
            self.run_dir = self.runs_dir / self.run_id
            self.run_dir.mkdir(parents=True, exist_ok=True)

    def write_json(self, filename, data):
        path = self.run_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def read_json(self, filename):
        path = self.run_dir / filename
        if not path.is_file():
            raise RunStateError(f"Artifact not found: {filename}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write_markdown(self, filename, text):
        path = self.run_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def read_markdown(self, filename):
        path = self.run_dir / filename
        if not path.is_file():
            raise RunStateError(f"Artifact not found: {filename}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def load_todo(self):
        data = self.read_json("todo.json")
        return data.get("phases", data)

    def save_todo(self, phases):
        self.write_json("todo.json", {"phases": phases})

    def get_phase(self, phase_id):
        for p in self.load_todo():
            if p["id"] == phase_id:
                return p
        raise RunStateError(f"Phase {phase_id!r} not found in todo.json")

    def update_phase(self, phase_id, **updates):
        phases = self.load_todo()
        for p in phases:
            if p["id"] == phase_id:
                p.update(updates)
                break
        else:
            raise RunStateError(f"Phase {phase_id!r} not found in todo.json")
        self.save_todo(phases)

    def write_artifact(self, filename, content):
        if filename.endswith(".json"):
            self.write_json(filename, content)
        else:
            self.write_markdown(filename, content)

    def read_artifact(self, filename):
        if filename.endswith(".json"):
            return self.read_json(filename)
        return self.read_markdown(filename)


def _scan_balanced(text, start_char, end_char):
    """Yield candidate substrings that are string/escape-aware balanced spans.

    Unlike naive brace counting, this ignores delimiters that appear inside JSON
    string literals (and their escapes), so JSON whose values contain HTML/CSS/JS
    (full of `{` `}` and quotes) is matched correctly.
    """
    start_idx = text.find(start_char)
    if start_idx < 0:
        return
    depth = 0
    in_string = False
    escaped = False
    for i in range(start_idx, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == start_char:
            depth += 1
        elif ch == end_char:
            depth -= 1
            if depth == 0:
                yield text[start_idx : i + 1]
                return


def extract_json(text):
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1)

    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for start_char, end_char in [("{", "}"), ("[", "]")]:
        for candidate in _scan_balanced(text, start_char, end_char):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    raise RunStateError("Could not extract valid JSON from response")


def call_with_json_repair(client, role, messages, **opts):
    raw = client.chat(role, messages, **opts)
    try:
        return extract_json(raw)
    except RunStateError:
        repair_msg = (
            "Your previous response was not valid JSON. "
            "Respond with ONLY valid JSON — no markdown, no explanation.\n\n"
            f"Your previous response:\n{raw}"
        )
        raw2 = client.chat(
            role,
            messages
            + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": repair_msg},
            ],
            **opts,
        )
        try:
            return extract_json(raw2)
        except RunStateError as e:
            from core.provider_client import ProviderResponseError

            def _diag(label, s):
                s = s or ""
                tail = s[-200:].replace("\n", "\\n")
                return f"{label}: len={len(s)} tail=…{tail!r}"

            raise ProviderResponseError(
                f"Failed to get valid JSON after repair retry: {e}. "
                f"{_diag('attempt1', raw)}; {_diag('attempt2', raw2)}"
            ) from e
