import os
import time
import random
import logging
from collections import defaultdict
from datetime import date

import yaml
import requests
from pathlib import Path
from dotenv import load_dotenv


logger = logging.getLogger(__name__)


class ProviderError(Exception):
    pass


class ProviderConfigError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    pass


DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEFAULT_MAX_ATTEMPTS = 3
REQUEST_TIMEOUT = 120


class RateLimiter:
    """Sliding-window rate limiter for API request quotas (RPM / TPM / RPD).

    Designed for Gemini Free Tier limits where each model has its own
    independent quota pool. Only active when free_mode is enabled.
    """

    def __init__(self, limits_config=None):
        self._limits = limits_config or {}
        # {model: [(timestamp, estimated_tokens), ...]}
        self._rpm_history = defaultdict(list)
        # {model: {date_str: count}}
        self._rpd_history = defaultdict(lambda: defaultdict(int))

    def _limits_for(self, model_name):
        limits = self._limits.get(model_name, {})
        return {
            "rpm": limits.get("rpm", float("inf")),
            "tpm": limits.get("tpm", float("inf")),
            "rpd": limits.get("rpd", float("inf")),
        }

    def _prune_rpm(self, model_name):
        now = time.time()
        cutoff = now - 60
        self._rpm_history[model_name] = [
            (t, tok) for t, tok in self._rpm_history[model_name] if t > cutoff
        ]

    def _current_rpm(self, model_name):
        self._prune_rpm(model_name)
        return len(self._rpm_history[model_name])

    def _current_tpm(self, model_name):
        self._prune_rpm(model_name)
        return sum(tok for _, tok in self._rpm_history[model_name])

    def _rpd_used(self, model_name):
        return self._rpd_history[model_name].get(date.today().isoformat(), 0)

    def wait_for_capacity(self, model_name, estimated_tokens=1000):
        """Block calling thread until capacity is available or raise on hard limits."""
        limits = self._limits_for(model_name)

        if self._rpd_used(model_name) >= limits["rpd"]:
            raise ProviderResponseError(
                f"Gemini Free Tier RPD limit ({limits['rpd']}) reached for "
                f"{model_name}. Wait until tomorrow or disable free_mode."
            )

        # Wait for RPM slot
        while self._current_rpm(model_name) >= limits["rpm"]:
            time.sleep(0.5)

        # Wait for TPM slot
        while self._current_tpm(model_name) + estimated_tokens > limits["tpm"]:
            time.sleep(0.5)

    def record_request(self, model_name, estimated_tokens=1000):
        today = date.today().isoformat()
        self._rpm_history[model_name].append((time.time(), estimated_tokens))
        self._rpd_history[model_name][today] += 1


class ProviderClient:
    """Generic OpenAI-compatible /chat/completions client.

    Works for Gemini / OpenRouter / ZenMux / OpenCode / any compatible endpoint
    by combining provider config (providers.yaml) with role->provider+model
    mapping (roles.yaml). See PROJECT_CONTEXT.md sec 5.

    Features:
    - Free mode (``free_mode=True``): uses ``free_mode_roles`` from roles.yaml
      and enforces Gemini Free Tier rate limits (RPM/TPM/RPD).
    - Fallback models: if the primary model fails with a retryable HTTP error
      (429/5xx) and ``fallback_model`` is set for the role, retries with the
      fallback model before raising.
    """

    def __init__(self, config_dir=None, max_attempts=DEFAULT_MAX_ATTEMPTS,
                 session=None, free_mode=None):
        load_dotenv()
        self.config_dir = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
        self.max_attempts = max_attempts
        self.session = session or requests.Session()
        self._providers = self._load_yaml(self.config_dir / "providers.yaml")
        self._exec_config = self._load_yaml(self.config_dir / "execution.yaml")
        self._roles_raw = self._load_yaml(self.config_dir / "roles.yaml")

        # Determine free mode: constructor arg > config file > default false
        if free_mode is not None:
            self.free_mode = free_mode
        else:
            self.free_mode = self._exec_config.get("free_mode", False)

        # Load the active role set
        if self.free_mode:
            self._roles = self._roles_raw.get("free_mode_roles")
            if not self._roles:
                raise ProviderConfigError(
                    "free_mode is enabled but 'free_mode_roles' section is "
                    "missing or empty in roles.yaml"
                )
            logger.info("Free mode enabled — using Gemini Free Tier roles")
        else:
            self._roles = self._roles_raw

        # Rate limiter (only active in free mode)
        rate_limits = self._exec_config.get("rate_limits", {})
        self._rate_limiter = RateLimiter(rate_limits) if self.free_mode else None

    @staticmethod
    def _load_yaml(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, role, messages, **opts):
        """Send a chat completion for *role*; return assistant content str.

        Parameters
        ----------
        role : str
            One of ``{thinking, execution, quick}``, resolved via roles.yaml.
        messages : list[dict]
            OpenAI-style ``[{"role": …, "content": …}, …]``.
        **opts
            Extra body fields (temperature, max_tokens, response_format, …).

        Raises
        ------
        ProviderConfigError
            Unknown role, missing provider config, or missing API key.
        ProviderResponseError
            Network failure, HTTP error, or rate-limit exhaustion.
        """
        role_cfg = self._resolve_role(role)
        provider_name = role_cfg.get("provider")
        model = role_cfg["model"]
        fallback = role_cfg.get("fallback_model")

        prov_cfg = self._resolve_provider(provider_name, role)
        base_url = str(prov_cfg["base_url"]).rstrip("/")
        api_key = self._resolve_api_key(provider_name, prov_cfg)

        try:
            return self._chat_with_model(base_url, api_key, model, messages,
                                         role=role, **opts)
        except ProviderResponseError as exc:
            if fallback and self._is_retryable_error(exc):
                logger.info(
                    "Model %s failed for role %s, falling back to %s",
                    model, role, fallback,
                )
                return self._chat_with_model(base_url, api_key, fallback,
                                             messages, role=role, **opts)
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_role(self, role):
        if role not in self._roles:
            raise ProviderConfigError(
                f"Unknown role {role!r}. Available: {list(self._roles)}"
            )
        return self._roles[role]

    def _resolve_provider(self, provider_name, role):
        if provider_name not in self._providers:
            raise ProviderConfigError(
                f"Provider {provider_name!r} (for role {role!r}) "
                f"not in providers.yaml"
            )
        return self._providers[provider_name]

    @staticmethod
    def _resolve_api_key(provider_name, prov_cfg):
        key_env = prov_cfg.get("api_key_env")
        api_key = os.environ.get(key_env) if key_env else None
        if not api_key:
            raise ProviderConfigError(
                f"API key env var {key_env!r} for provider "
                f"{provider_name!r} is not set. "
                f"Add it to your .env (see .env.example)."
            )
        return api_key

    def _chat_with_model(self, base_url, api_key, model, messages,
                         role=None, **opts):
        url = f"{base_url}/chat/completions"
        payload = {"model": model, "messages": messages, **opts}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Estimate token count for rate limiting (rough: 4 chars ≈ 1 token)
        est_tokens = max(1, sum(len(m.get("content", "")) for m in messages) // 4)

        if self._rate_limiter:
            self._rate_limiter.wait_for_capacity(model, est_tokens)

        result = self._post_with_retry(url, payload, headers, role=role,
                                       model_name=model)

        if self._rate_limiter:
            self._rate_limiter.record_request(model, est_tokens)

        return result

    @staticmethod
    def _is_retryable_error(error):
        s = str(error)
        return any(code in s for code in ("429", "500", "502", "503"))

    def _post_with_retry(self, url, payload, headers, role=None, model_name=None):
        last_exc = None
        label = f"role={role}, model={model_name}" if model_name else "request"
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = self.session.post(
                    url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT
                )
            except requests.RequestException as e:
                last_exc = ProviderResponseError(
                    f"Network error for {label} "
                    f"(attempt {attempt}/{self.max_attempts}): {e}"
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
                f"HTTP {resp.status_code} for {label} "
                f"(non-retryable): {resp.text[:300]}"
            )
        raise last_exc or ProviderResponseError(
            f"Retry loop exhausted for {label}"
        )

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
            raise ProviderResponseError(
                f"No choices in response for {label}: {data}"
            )
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
