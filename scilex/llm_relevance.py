"""LLM-based abstract screening (opt-in) through OpenRouter.

Each paper receives a ``llm_relevance_score`` in [0, 1] estimating how relevant
its title and abstract are to a free-text research topic. Scores are cached on
disk by (DOI or title, model, topic hash) so a paper is never paid for twice.
Papers scoring under an optional threshold can be excluded from the corpus.

Configuration lives under the ``llm_screening`` key of ``scilex.config.yml``;
the API key is read from ``api.config.yml`` (``openrouter: {api_key: ...}``)
or the ``OPENROUTER_API_KEY`` environment variable.
"""

import hashlib
import json
import logging
import os
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import pandas as pd
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from scilex.constants import is_valid, normalize_doi

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SCORE_COLUMN = "llm_relevance_score"
CACHE_FILENAME = "llm_relevance_cache.json"
PROGRESS_EVERY = 25  # requests between progress reports and cache saves
API_KEY_ENV_VAR = "OPENROUTER_API_KEY"

DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_WORKERS = 16
MAX_WORKERS = 64
DEFAULT_MAX_PAPERS = 500
DEFAULT_PRICE_INPUT_PER_M = 0.091
DEFAULT_PRICE_OUTPUT_PER_M = 0.182
# Rough heuristic: one token is about four characters of English text.
CHARS_PER_TOKEN = 4
PROMPT_OVERHEAD_TOKENS = 150
EXPECTED_OUTPUT_TOKENS = 20
MAX_ABSTRACT_CHARS = 3000

SYSTEM_PROMPT = (
    "You screen scientific papers for a systematic literature review. "
    "Given a research topic and a paper's title and abstract, rate how relevant "
    "the paper is to the topic from 0.0 (unrelated) to 1.0 (directly on topic). "
    'Answer with strict JSON only, for example {"score": 0.75}.'
)

_JSON_OBJECT = re.compile(r"\{[^{}]*\}")

# One HTTP session per worker thread: keep-alive reuses the TLS connection
# instead of a new handshake for every paper.
_thread_local = threading.local()


def _get_session() -> requests.Session:
    """Return the calling thread's HTTP session (created on first use)."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session


class LLMScreeningError(RuntimeError):
    """Raised when LLM screening cannot run (missing key, empty topic...)."""


class _RetryableLLMError(Exception):
    """Transient failure (HTTP 429/5xx, network, unparsable answer)."""


class LLMAccessError(LLMScreeningError):
    """OpenRouter refused the key (HTTP 401/402/403): every request would fail."""


# Statuses that concern the key or account, not the paper: no point retrying
# or sending the remaining papers.
_ACCESS_DENIED_STATUSES = (401, 402, 403)


def _error_message(response: requests.Response) -> str:
    """Return OpenRouter's error message (e.g. "Key limit exceeded"), if any."""
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = response.text[:300]
    return f"HTTP {response.status_code}: {message}"


@dataclass
class LLMScreeningConfig:
    """Settings of the ``llm_screening`` configuration block."""

    enabled: bool = False
    topic: str = ""
    model: str = DEFAULT_MODEL
    threshold: float | None = None
    max_papers: int = DEFAULT_MAX_PAPERS
    workers: int = DEFAULT_WORKERS
    price_input_per_m: float = DEFAULT_PRICE_INPUT_PER_M
    price_output_per_m: float = DEFAULT_PRICE_OUTPUT_PER_M

    @classmethod
    def from_dict(cls, raw: dict | None) -> "LLMScreeningConfig":
        """Build the settings from the (possibly missing) config block."""
        raw = raw or {}
        threshold = raw.get("threshold")
        return cls(
            enabled=bool(raw.get("enabled", False)),
            topic=str(raw.get("topic") or "").strip(),
            model=str(raw.get("model") or DEFAULT_MODEL),
            threshold=None if threshold is None else float(threshold),
            max_papers=int(raw.get("max_papers", DEFAULT_MAX_PAPERS)),
            workers=min(MAX_WORKERS, max(1, int(raw.get("workers", DEFAULT_WORKERS)))),
            price_input_per_m=float(
                raw.get("price_input_per_m", DEFAULT_PRICE_INPUT_PER_M)
            ),
            price_output_per_m=float(
                raw.get("price_output_per_m", DEFAULT_PRICE_OUTPUT_PER_M)
            ),
        )


def resolve_api_key(api_config: dict | None) -> str | None:
    """Return the OpenRouter key from api_config, else from the environment."""
    configured = ((api_config or {}).get("openrouter") or {}).get("api_key")
    return configured or os.environ.get(API_KEY_ENV_VAR) or None


def topic_hash(topic: str) -> str:
    """Short stable hash of a topic, used in cache keys."""
    return hashlib.sha256(topic.strip().encode("utf-8")).hexdigest()[:12]


def paper_identifier(title, doi) -> str:
    """Cache identifier of a paper: normalized DOI, else lowercase title."""
    normalized = normalize_doi(doi) if is_valid(doi) else None
    if normalized:
        return f"doi:{normalized}"
    return f"title:{str(title).strip().lower()}"


def cache_key(title, doi, model: str, topic: str) -> str:
    """Cache key of one score: (paper, model, topic hash)."""
    return f"{paper_identifier(title, doi)}|{model}|{topic_hash(topic)}"


class ScoreCache:
    """Thread-safe JSON disk cache of relevance scores."""

    def __init__(self, path: str | None):
        self.path = path
        self._lock = threading.Lock()
        self._scores: dict[str, float] = {}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    self._scores = json.load(handle)
            except (json.JSONDecodeError, OSError) as error:
                logger.warning(f"Could not load LLM cache {path}: {error}")

    def get(self, key: str) -> float | None:
        """Return the cached score or None."""
        with self._lock:
            return self._scores.get(key)

    def set(self, key: str, score: float) -> None:
        """Store a score (in memory; call ``save`` to persist)."""
        with self._lock:
            self._scores[key] = score

    def save(self) -> None:
        """Persist the cache atomically."""
        if not self.path:
            return
        with self._lock:
            temporary_path = f"{self.path}.tmp"
            try:
                with open(temporary_path, "w", encoding="utf-8") as handle:
                    json.dump(self._scores, handle)
                os.replace(temporary_path, self.path)
            except OSError as error:
                logger.warning(f"Could not save LLM cache {self.path}: {error}")

    def __len__(self) -> int:
        return len(self._scores)


def build_user_prompt(topic: str, title, abstract) -> str:
    """Compose the user message for one paper."""
    title_text = str(title).strip() if is_valid(title) else "(no title)"
    abstract_text = (
        str(abstract).strip()[:MAX_ABSTRACT_CHARS]
        if is_valid(abstract)
        else "(no abstract)"
    )
    return (
        f"Research topic:\n{topic}\n\n"
        f"Title: {title_text}\n\nAbstract: {abstract_text}\n\n"
        'Return JSON: {"score": <number between 0 and 1>}'
    )


def parse_score(content: str) -> float:
    """Extract a score in [0, 1] from an LLM answer.

    Accepts strict JSON, JSON wrapped in prose or code fences, and a bare
    number. Values in (1, 10] or (1, 100] are not rescaled: out-of-range
    answers are rejected so a misread scale never silently passes.

    Raises:
        ValueError: If no valid score is found.
    """
    text = (content or "").strip()
    candidates = [text, *_JSON_OBJECT.findall(text)]
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        value = parsed.get("score") if isinstance(parsed, dict) else parsed
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            continue
        try:
            score = float(value)
        except ValueError:
            continue
        if 0.0 <= score <= 1.0:
            return score
    raise ValueError(f"No valid score in LLM answer: {text[:80]!r}")


def _stop_retrying(retry_state) -> bool:
    """Stop after 4 attempts, or at once when the call's cancel event is set."""
    cancel_event = retry_state.kwargs.get("cancel_event")
    if cancel_event is not None and cancel_event.is_set():
        return True
    return stop_after_attempt(4)(retry_state)


@retry(
    retry=retry_if_exception_type(_RetryableLLMError),
    stop=_stop_retrying,
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)
def request_score(
    title,
    abstract,
    topic: str,
    model: str,
    api_key: str,
    timeout: int = 60,
    cancel_event: threading.Event | None = None,
) -> float:
    """Ask OpenRouter for the relevance score of one paper (with retries).

    Retries stop as soon as ``cancel_event`` (passed by keyword) is set.
    """
    payload = {
        "model": model,
        "temperature": 0,
        # Room for a short answer even if a model reasons despite the switch below.
        "max_tokens": 200,
        # Reasoning models (e.g. deepseek-v4-flash) otherwise spend the whole
        # token budget thinking and return an empty or truncated answer.
        "reasoning": {"enabled": False},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(topic, title, abstract)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = _get_session().post(
            OPENROUTER_URL, headers=headers, json=payload, timeout=timeout
        )
    except requests.exceptions.RequestException as error:
        raise _RetryableLLMError(str(error)) from error
    if response.status_code == 429 or response.status_code >= 500:
        raise _RetryableLLMError(_error_message(response))
    if response.status_code in _ACCESS_DENIED_STATUSES:
        raise LLMAccessError(_error_message(response))
    if response.status_code >= 400:
        raise requests.HTTPError(_error_message(response), response=response)
    try:
        content = response.json()["choices"][0]["message"]["content"]
        return parse_score(content)
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise _RetryableLLMError(f"Unusable LLM answer: {error}") from error


def estimate_cost(
    df: pd.DataFrame, config: LLMScreeningConfig
) -> tuple[int, float, float]:
    """Estimate (input tokens, output tokens, USD) to score every row of ``df``."""
    topic_tokens = len(config.topic) // CHARS_PER_TOKEN
    input_tokens = 0
    for _, row in df.iterrows():
        title = str(row.get("title", "")) if is_valid(row.get("title")) else ""
        abstract = (
            str(row.get("abstract", ""))[:MAX_ABSTRACT_CHARS]
            if is_valid(row.get("abstract"))
            else ""
        )
        input_tokens += (
            PROMPT_OVERHEAD_TOKENS
            + topic_tokens
            + (len(title) + len(abstract)) // CHARS_PER_TOKEN
        )
    output_tokens = EXPECTED_OUTPUT_TOKENS * len(df)
    cost = (
        input_tokens * config.price_input_per_m
        + output_tokens * config.price_output_per_m
    ) / 1_000_000
    return input_tokens, output_tokens, cost


def score_dataframe(
    df: pd.DataFrame,
    config: LLMScreeningConfig,
    api_key: str,
    cache_path: str | None = None,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    """Add the ``llm_relevance_score`` column (NaN when not scored).

    ``progress_callback(done, total)`` is called every ``PROGRESS_EVERY``
    requests; the score cache is saved at the same pace, so an interrupted run
    keeps what was already paid for.

    Setting ``cancel_event`` stops sending requests; scores already obtained
    are cached and the rest stay unscored. The same happens, with one error
    logged, when OpenRouter refuses the key (exhausted credits or key limit).

    Cached scores are reused. At most ``config.max_papers`` uncached papers are
    sent to the LLM; the estimated cost is logged before any request.
    """
    df = df.copy()
    cache = ScoreCache(cache_path)
    keys = [
        cache_key(row.get("title"), row.get("DOI"), config.model, config.topic)
        for _, row in df.iterrows()
    ]
    scores: list[float | None] = [cache.get(key) for key in keys]
    pending = [position for position, score in enumerate(scores) if score is None]
    skipped = max(0, len(pending) - config.max_papers)
    to_score = pending[: config.max_papers]

    _, _, cost = estimate_cost(df.iloc[to_score], config)
    logger.info(
        f"LLM screening: {len(df)} papers, {len(df) - len(pending)} cached, "
        f"{len(to_score)} to score with {config.model} "
        f"(estimated cost ~${cost:.4f})"
    )
    if skipped:
        logger.warning(
            f"LLM screening: max_papers={config.max_papers} reached, "
            f"{skipped} papers left unscored (kept in the corpus)"
        )

    # Set by the user's cancel_event or by a refused key; stops all workers.
    stop_event = threading.Event()
    access_errors: list[LLMAccessError] = []

    def should_stop() -> bool:
        if cancel_event is not None and cancel_event.is_set():
            stop_event.set()
        return stop_event.is_set()

    def score_position(position: int) -> tuple[int, float | None]:
        if should_stop():
            return position, None
        row = df.iloc[position]
        try:
            value = request_score(
                row.get("title"),
                row.get("abstract"),
                config.topic,
                config.model,
                api_key,
                cancel_event=cancel_event,
            )
        except LLMAccessError as error:
            access_errors.append(error)
            stop_event.set()
            return position, None
        except Exception as error:
            logger.warning(f"LLM scoring failed for {row.get('title')!r}: {error}")
            return position, None
        cache.set(keys[position], value)
        return position, value

    if to_score:
        total = len(to_score)
        workers = min(config.workers, total)
        # Results are collected in completion order, so one slow request no
        # longer holds back the progress bar or the periodic cache saves.
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(score_position, position) for position in to_score
            ]
            for done, future in enumerate(as_completed(futures), start=1):
                position, value = future.result()
                scores[position] = value
                if done % PROGRESS_EVERY == 0 or done == total:
                    cache.save()
                    logger.info(f"LLM screening: {done}/{total} scored")
                    if progress_callback:
                        progress_callback(done, total)
                if should_stop():
                    for pending_future in futures:
                        pending_future.cancel()
                    break
        cache.save()
        if access_errors:
            unscored = sum(score is None for score in scores)
            logger.error(
                f"LLM screening stopped: OpenRouter refused the API key "
                f"({access_errors[0]}). {unscored} papers left unscored "
                f"(kept in the corpus)."
            )

    df[SCORE_COLUMN] = pd.Series(scores, index=df.index, dtype="float64")
    return df


def apply_llm_screening(
    df: pd.DataFrame,
    config: LLMScreeningConfig,
    api_config: dict | None = None,
    cache_path: str | None = None,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    """Score papers and drop those under ``config.threshold`` (if set).

    Unscored papers (errors, over ``max_papers``) are kept: a failure never
    silently removes a paper.

    Raises:
        LLMScreeningError: If the topic or the API key is missing.
    """
    if df.empty:
        return df
    if not config.topic:
        raise LLMScreeningError("llm_screening.topic is required")
    api_key = resolve_api_key(api_config)
    if not api_key:
        raise LLMScreeningError(
            f"No OpenRouter key: set openrouter.api_key in keys.yml (API keys screen "
            f"in the app) or {API_KEY_ENV_VAR}, or disable llm_screening in scilex.yml"
        )
    scored = score_dataframe(
        df, config, api_key, cache_path, cancel_event, progress_callback
    )
    if config.threshold is not None:
        keep = scored[SCORE_COLUMN].isna() | (scored[SCORE_COLUMN] >= config.threshold)
        logger.info(
            f"LLM threshold {config.threshold}: {int(keep.sum())}/{len(scored)} kept"
        )
        scored = scored[keep]
    return scored.reset_index(drop=True)
