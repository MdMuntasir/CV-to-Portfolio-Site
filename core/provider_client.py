import os
import time
import random

import yaml
import requests
from pathlib import Path
from dotenv import load_dotenv


class ProviderError(Exception):
    pass


class ProviderConfigError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    pass


DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEFAULT_MAX_ATTEMPTS = 3
REQUEST_TIMEOUT = 120


class ProviderClient:
    """Generic OpenAI-compatible /chat/completions client.

    Works for Gemini / OpenRouter / ZenMux / OpenCode / any compatible endpoint
    by combining provider config (providers.yaml) with role->provider+model
    mapping (roles.yaml). See PROJECT_CONTEXT.md sec 5.
    """

    def __init__(self, config_dir=None, max_attempts=DEFAULT_MAX_ATTEMPTS, session=None):
        load_dotenv()
        self.config_dir = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
        self.max_attempts = max_attempts
        self.session = session or requests.Session()
        self._providers = self._load_yaml(self.config_dir / "providers.yaml")
        self._roles = self._load_yaml(self.config_dir / "roles.yaml")

    @staticmethod
    def _load_yaml(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def chat(self, role, messages, **opts):
        """Send a chat completion for a given role; return assistant content str.

        role: one of {thinking, execution, quick} (resolved via roles.yaml).
        messages: OpenAI-style list of {role, content} dicts.
        opts: extra body fields (temperature, max_tokens, response_format, ...).
        Raises ProviderConfigError / ProviderResponseError on failure.
        """
        if role not in self._roles:
            raise ProviderConfigError(
                f"Unknown role {role!r}. Available: {list(self._roles)}"
            )
        role_cfg = self._roles[role]
        provider_name = role_cfg.get("provider")
        if provider_name not in self._providers:
            raise ProviderConfigError(
                f"Provider {provider_name!r} (for role {role!r}) not in providers.yaml"
            )
        prov_cfg = self._providers[provider_name]
        key_env = prov_cfg.get("api_key_env")
        api_key = os.environ.get(key_env) if key_env else None
        if not api_key:
            raise ProviderConfigError(
                f"API key env var {key_env!r} for provider {provider_name!r} is not set. "
                f"Add it to your .env (see .env.example)."
            )
        base_url = str(prov_cfg["base_url"]).rstrip("/")
        url = f"{base_url}/chat/completions"
        payload = {
            "model": role_cfg["model"],
            "messages": messages,
            **opts,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        return self._post_with_retry(url, payload, headers, role=role)

    def _post_with_retry(self, url, payload, headers, role=None):
        last_exc = None
        label = f"role={role}" if role else "request"
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = self.session.post(
                    url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT
                )
            except requests.RequestException as e:
                last_exc = ProviderResponseError(
                    f"Network error for {label} (attempt {attempt}/{self.max_attempts}): {e}"
                )
                if attempt < self.max_attempts:
                    self._backoff(attempt)
                    continue
                raise last_exc

            if resp.status_code == 200:
                return self._extract_content(resp, label)

            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                last_exc = ProviderResponseError(
                    f"HTTP {resp.status_code} for {label} "
                    f"(attempt {attempt}/{self.max_attempts}): {resp.text[:300]}"
                )
                if attempt < self.max_attempts:
                    self._backoff(attempt)
                    continue
                raise last_exc

            raise ProviderResponseError(
                f"HTTP {resp.status_code} for {label} (non-retryable): {resp.text[:300]}"
            )
        raise last_exc or ProviderResponseError(f"Retry loop exhausted for {label}")

    @staticmethod
    def _extract_content(resp, label):
        try:
            data = resp.json()
        except ValueError as e:
            raise ProviderResponseError(
                f"Non-JSON response for {label}: {resp.text[:300]}"
            ) from e
        choices = data.get("choices")
        if not choices:
            raise ProviderResponseError(f"No choices in response for {label}: {data}")
        message = choices[0].get("message", {}) or {}
        content = message.get("content")
        if content is None:
            raise ProviderResponseError(
                f"No content in response message for {label}: {data}"
            )
        return content

    @staticmethod
    def _backoff(attempt):
        delay = min(30.0, (2 ** attempt)) + random.uniform(0, 1.0)
        time.sleep(delay)
