import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

import httpx

from app.schemas import PromptIntent
from app.services import audius_service, prompt_parser


def test_audius_timeout_and_malformed_payload_return_no_candidates(monkeypatch):
    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx.Client, "get", timeout)
    assert audius_service.search_tracks("focus") == []


def test_audius_nested_provider_fields_are_sanitized(monkeypatch):
    def malformed(*args, **kwargs):
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "track/id",
                        "title": ["not", "text"],
                        "user": "not-an-object",
                        "artwork": ["not-an-object"],
                        "genre": {"not": "text"},
                    }
                ]
            },
            request=httpx.Request("GET", "https://provider.example"),
        )

    monkeypatch.setattr(httpx.Client, "get", malformed)
    result = audius_service.search_tracks("focus")
    assert result[0]["title"] == "Unknown title"
    assert result[0]["artist"] == "Unknown artist"
    assert result[0]["cover_url"] is None
    assert result[0]["genre"] is None
    assert "track%2Fid" in result[0]["audio_url"]


def test_search_tracks_serves_a_second_identical_query_from_cache(monkeypatch):
    calls = []

    def fake_uncached(prompt, limit=5):
        calls.append((prompt, limit))
        return [
            {
                "source_track_id": "1",
                "audio_url": "https://audio.example/1",
                "title": "T",
                "artist": "A",
                "duration": 90,
            }
        ]

    monkeypatch.setattr(audius_service, "_search_tracks_uncached", fake_uncached)

    first = audius_service.search_tracks("lofi", limit=5)
    second = audius_service.search_tracks("lofi", limit=5)

    assert len(calls) == 1  # the second call was served from cache, not a real fetch
    assert second == first
    assert audius_service.get_last_search_cache_hit() is True


def test_search_tracks_cache_entry_expires_after_ttl(monkeypatch):
    calls = []

    def fake_uncached(prompt, limit=5):
        calls.append((prompt, limit))
        return [
            {
                "source_track_id": str(len(calls)),
                "audio_url": "https://audio.example/x",
                "title": "T",
                "artist": "A",
                "duration": 90,
            }
        ]

    monkeypatch.setattr(audius_service, "_search_tracks_uncached", fake_uncached)
    monkeypatch.setattr(audius_service, "AUDIUS_SEARCH_CACHE_TTL_SECONDS", 0.05)

    audius_service.search_tracks("lofi", limit=5)
    assert len(calls) == 1

    time.sleep(0.1)
    audius_service.search_tracks("lofi", limit=5)
    assert len(calls) == 2  # the cache entry expired, so a real call happened again
    assert audius_service.get_last_search_cache_hit() is False


def test_ollama_call_is_skipped_for_a_required_artist_match_but_not_for_a_vibe_prompt(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")

    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        return httpx.Response(
            200,
            json={
                "response": '{"mood":"balanced","energy":"medium","vocals":"neutral","genres":[],"search_query":"x"}'
            },
            request=httpx.Request("POST", "http://x"),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    required = prompt_parser.parse_prompt("play George Wassouf")
    assert calls == []  # the LLM is never called for a required-artist match
    assert required.artist == "George Wassouf"
    assert required.artist_mode == "required"

    vibe_only = prompt_parser.parse_prompt("chill lofi beats")
    assert len(calls) == 1  # a genre/vibe-only prompt still gets refined normally
    assert vibe_only.artist_mode == "none"


def test_prompt_parser_uses_deterministic_fallback_when_llm_fails(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")

    def invalid(*args, **kwargs):
        return httpx.Response(200, json={"response": '{"invented_track":"Never Existed"}'}, request=httpx.Request("POST", "http://x"))

    monkeypatch.setattr(httpx.Client, "post", invalid)
    intent = prompt_parser.parse_prompt("energetic house workout")
    assert intent.energy == "high"
    assert intent.genres == ["house"]
    assert "Never Existed" not in intent.search_query


def test_ollama_think_mode_is_disabled_by_default_but_configurable(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    monkeypatch.delenv("OLLAMA_THINK_ENABLED", raising=False)

    payloads = []

    def fake_post(*args, **kwargs):
        payloads.append(kwargs["json"])
        return httpx.Response(
            200,
            json={
                "response": '{"mood":"balanced","energy":"medium","vocals":"neutral","genres":[],"search_query":"x"}'
            },
            request=httpx.Request("POST", "http://x"),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    prompt_parser.parse_prompt("chill lofi beats")
    assert payloads[0]["think"] is False  # unset env var -> the safer default

    monkeypatch.setenv("OLLAMA_THINK_ENABLED", "true")
    prompt_parser.parse_prompt("chill lofi beats")
    assert payloads[1]["think"] is True  # explicitly opted in via the env var


def test_ollama_keep_alive_defaults_to_never_unload_but_is_configurable(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    monkeypatch.delenv("OLLAMA_KEEP_ALIVE", raising=False)

    payloads = []

    def fake_post(*args, **kwargs):
        payloads.append(kwargs["json"])
        return httpx.Response(
            200,
            json={
                "response": '{"mood":"balanced","energy":"medium","vocals":"neutral","genres":[],"search_query":"x"}'
            },
            request=httpx.Request("POST", "http://x"),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    prompt_parser.parse_prompt("chill lofi beats")
    assert payloads[0]["keep_alive"] == "-1"  # unset env var -> never unload

    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "30m")
    prompt_parser.parse_prompt("chill lofi beats")
    assert payloads[1]["keep_alive"] == "30m"  # passed through as-is, unparsed


def test_concurrent_parse_prompt_calls_respect_the_ollama_slot_bound(monkeypatch):
    """CI-safe concurrency load test for the "Local LLM Integration"
    requirement's Concurrency bullet: fires far more than _ollama_slots'
    configured limit at the real prompt_parser.parse_prompt() concurrently,
    against an artificially slow mocked Ollama, so callers actually contend
    for slots instead of racing through sequentially. Verifies: no more
    than the configured limit are ever in-flight against "Ollama" at once,
    every caller still returns a valid PromptIntent (never hangs, never
    raises), and callers that miss a slot within the real 0.05s acquire
    timeout cleanly fall back to the deterministic parse rather than
    blocking."""

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")

    in_flight = 0
    high_water_mark = 0
    lock = threading.Lock()

    def slow_post(*args, **kwargs):
        nonlocal in_flight, high_water_mark
        with lock:
            in_flight += 1
            high_water_mark = max(high_water_mark, in_flight)
        time.sleep(0.2)  # far longer than the 0.05s slot-acquire timeout
        with lock:
            in_flight -= 1
        return httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {
                        "mood": "calm",
                        "energy": "low",
                        "vocals": "neutral",
                        "genres": ["lofi"],
                        "artist": None,
                        "artist_mode": "none",
                        "search_query": "chill lofi beats",
                    }
                )
            },
            request=httpx.Request("POST", "http://x"),
        )

    monkeypatch.setattr(httpx.Client, "post", slow_post)

    concurrency_limit = prompt_parser._ollama_slots._value
    call_count = concurrency_limit * 5

    started = perf_counter()
    with ThreadPoolExecutor(max_workers=call_count) as executor:
        results = list(
            executor.map(lambda _: prompt_parser.parse_prompt("chill lofi beats for focus"), range(call_count))
        )
    wall_clock_seconds = perf_counter() - started

    print(
        f"\n[llm-concurrency] limit={concurrency_limit} calls={call_count} "
        f"high_water_mark={high_water_mark} wall_clock={wall_clock_seconds:.2f}s"
    )

    assert all(isinstance(result, PromptIntent) for result in results)
    assert high_water_mark <= concurrency_limit
    assert high_water_mark >= 1  # sanity: the mock was actually exercised


def test_valid_llm_classification_cannot_replace_catalog_search_text(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    raw = '{"mood":"calm","energy":"low","vocals":"less","genres":["lofi","fakegenre"],"search_query":"Invented Song"}'

    def valid(*args, **kwargs):
        return httpx.Response(200, json={"response": raw}, request=httpx.Request("POST", "http://x"))

    monkeypatch.setattr(httpx.Client, "post", valid)
    intent = prompt_parser.parse_prompt("calm lofi")
    assert intent.genres == ["lofi"]
    assert intent.search_query == "calm lofi"
