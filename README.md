# CV to Portfolio Website Generator

A CLI tool that transforms a CV (PDF or pasted text) into a complete, ready-to-open static portfolio website using AI. Built as a multi-stage LLM pipeline with resumability and configurable providers.

## Quick Start

```bash
# 1. Set up environment
python -m venv venv
venv\Scripts\activate     # Windows
# source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt

# 2. Configure API keys
cp .env.example .env
# Edit .env with at least one provider key (see config/roles.yaml for which are needed)

# 3. Generate a portfolio
python main.py generate --cv path/to/cv.pdf --output ./my-site
# Or from pasted text:
python main.py generate --cv-text "Your CV text here..." --output ./my-site
```

## Usage

```
python main.py generate --cv <path.pdf> --output <dir>
python main.py generate --cv-text "<text>" --output <dir>
python main.py resume --run-id <run_id>
```

### Options

| Command | Flag | Description |
|---------|------|-------------|
| `generate` | `--cv` | Path to a PDF CV file |
| `generate` | `--cv-text` | CV text pasted directly |
| `generate` | `--output` | Output directory (default: `output/<run_id>`) |
| `generate` | `--max-attempts` | Override provider retry attempts |
| `generate` | `--free` | Enable Gemini Free Tier mode (overrides config setting) |
| `resume` | `--run-id` | Resume a previously failed run |
| `resume` | `--output` | Output directory (default: `output/<run_id>`) |

### Gemini Free Tier Mode

Run with Gemini's free API key (get one at [Google AI Studio](https://aistudio.google.com/)):

```bash
# Via CLI flag (overrides config):
python main.py generate --cv path/to/cv.pdf --free

# Or set free_mode: true in config/execution.yaml
```

When free mode is enabled:
- Uses models from the `free_mode_roles` section in `config/roles.yaml`
- **Rate limits are automatically enforced** (RPM/TPM/RPD) — the client paces requests to stay within Gemini Free Tier quotas
- **Fallback model** support: if the primary model hits a rate limit, the configured `fallback_model` is tried (e.g., `execution` falls back from `gemini-3.5-flash` to `gemini-3.1-flash-lite`)

## Pipeline

1. **Extract** — Text extraction from PDF (or passthrough for pasted text) + summarization
2. **Classify** — Determines portfolio type (developer, creative, academic, etc.)
3. **UI/UX Spec** — Generates color palette, typography, layout, section plan
4. **Build Plan** — Creates ordered phases with dependencies
5. **Execute** — Generates HTML/CSS/JS files phase by phase
6. **Finalize** — Copies site to output directory, cleans up on success

## Configuration

- `config/providers.yaml` — Provider base URLs and API key env var names
- `config/roles.yaml` — Maps thinking/execution/quick roles to provider + model.
  Supports optional `fallback_model` per role and a `free_mode_roles` section
  for Gemini Free Tier.
- `config/execution.yaml` — Free mode toggle (`free_mode: true/false`),
  per-model rate limits (RPM/TPM/RPD), and execution loop caps
  (`max_phases`, `max_retries_per_phase`, `max_total_calls`).
- `.env` — API keys (copy from `.env.example`)

### Free mode toggle

Set `free_mode: true` in `config/execution.yaml` or pass `--free` on the CLI.
When active, roles are loaded from `free_mode_roles` in `roles.yaml`, and
the built-in `RateLimiter` enforces Gemini Free Tier quotas automatically.

### Fallback models

Each role can specify `fallback_model` (optional). If the primary model
returns a retryable error (429/5xx), the client retries the request with the
fallback model before raising — useful for staying within free-tier limits.

### Supported Providers

- **Gemini** — `GEMINI_API_KEY` env var
- **OpenRouter** — `OPENROUTER_API_KEY` env var
- **ZenMux** — `ZENMUX_API_KEY` env var
- **OpenCode** — `OPENCODE_API_KEY` env var

## Resumability

If a run fails (e.g., provider timeout, cap exceeded), the working directory is preserved under `runs/<run_id>/`. Fix the issue and resume:

```bash
python main.py resume --run-id run_20240725_143022
```

The pipeline skips completed stages and continues from the first failed/pending phase.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `API key env var ... is not set` | Add the missing key to `.env` (see `.env.example`) |
| `File not found` | Check the PDF path; use absolute or relative paths correctly |
| `Could not extract valid JSON` | The LLM returned malformed JSON; retrying usually fixes it |
| `Max total LLM calls exceeded` | Increase caps in `config/execution.yaml` |
| `HTTP 429 / 5xx` | Provider rate limit or outage; wait and retry with `resume` |
| `Gemini Free Tier RPD limit reached` | Daily request limit hit — wait until tomorrow or disable `free_mode` |
| `free_mode_roles section is missing` | Add `free_mode_roles` to `config/roles.yaml` when `free_mode` is enabled |
| Run directory preserved | On failure, `runs/<run_id>/` is kept for debugging; use `resume` to retry |

## Forward Compatibility

The pipeline is designed for future porting to Cloudflare Workers/Workflows:
- Stage functions receive `client` and `run_state` as objects — no filesystem assumptions
- Data flows via dicts/objects; `RunState` I/O can be swapped for KV/D1
- `todo.json` maps directly to a Workflow step-status model
