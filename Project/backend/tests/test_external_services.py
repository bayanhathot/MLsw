import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

import httpx
import pytest

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
    raises), and -- D4 -- most callers genuinely queue for a slot and reach
    the model rather than shedding to the deterministic fallback: this
    used to shed almost everything (the old acquire timeout was a hardcoded
    0.05s, far shorter than this mock's own 0.2s delay per call), which is
    exactly the defect D4 fixed."""

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    prompt_parser.reset_ollama_stats()

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

    # D4: real queueing means most of these 20 calls reach the model instead
    # of shedding immediately -- the pre-fix version of this test only
    # asserted results were valid PromptIntents (true for a shed fallback
    # too), so it never actually caught nearly everything being shed.
    stats = prompt_parser.get_ollama_stats()
    print(f"[llm-concurrency] attempted={stats['attempted']} succeeded={stats['succeeded']} "
          f"shed={stats['shed']}")
    assert stats["succeeded"] >= 8
    assert stats["timed_out"] == 0  # every attempt the mock served was a clean 200


def test_ollama_stats_count_a_successful_call(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    prompt_parser.reset_ollama_stats()

    def ok(*args, **kwargs):
        return httpx.Response(
            200,
            json={
                "response": '{"mood":"balanced","energy":"medium","vocals":"neutral","genres":[],"search_query":"x"}'
            },
            request=httpx.Request("POST", "http://x"),
        )

    monkeypatch.setattr(httpx.Client, "post", ok)
    prompt_parser.parse_prompt("chill lofi beats")

    stats = prompt_parser.get_ollama_stats()
    assert stats["attempted"] == 1
    assert stats["succeeded"] == 1
    assert stats["timed_out"] == 0
    assert stats["shed"] == 0
    assert stats["success_rate"] == 1.0
    assert stats["mean_latency_ms"] is not None


def test_ollama_stats_count_a_timeout_as_attempted_but_not_succeeded(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    prompt_parser.reset_ollama_stats()

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx.Client, "post", timeout)
    prompt_parser.parse_prompt("chill lofi beats")

    stats = prompt_parser.get_ollama_stats()
    assert stats["attempted"] == 1
    assert stats["succeeded"] == 0
    assert stats["timed_out"] == 1
    assert stats["shed"] == 0
    assert stats["success_rate"] == 0.0
    assert stats["mean_latency_ms"] is None  # no successful call to average


def test_ollama_stats_count_a_shed_call_without_counting_it_as_attempted(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    # Keep this test fast regardless of OLLAMA_QUEUE_WAIT_SECONDS's default --
    # every slot is held for the whole test, so parse_prompt must genuinely
    # shed, not queue.
    monkeypatch.setenv("OLLAMA_QUEUE_WAIT_SECONDS", "0.05")
    # D6b: parse_prompt prefers the Redis-backed distributed semaphore when
    # Redis is configured/reachable -- this test exercises the
    # process-local _ollama_slots fallback specifically (it holds that
    # semaphore directly to force a shed), so it forces that path regardless
    # of whether this environment happens to have a real Redis available.
    monkeypatch.setattr(prompt_parser, "get_sync_redis_client", lambda: None)
    prompt_parser.reset_ollama_stats()

    acquired = prompt_parser._ollama_slots.acquire(timeout=0)
    assert acquired  # sanity: we actually hold every slot below
    held = [acquired]
    try:
        while prompt_parser._ollama_slots.acquire(timeout=0):
            held.append(True)

        prompt_parser.parse_prompt("chill lofi beats")
    finally:
        for _ in held:
            prompt_parser._ollama_slots.release()

    stats = prompt_parser.get_ollama_stats()
    assert stats["shed"] == 1
    assert stats["attempted"] == 0  # a shed call never reached Ollama


# --- D6b: Ollama concurrency/stats shared across BACKEND_WORKERS replicas --


@pytest.mark.skipif(
    not os.getenv("REDIS_URL", "").strip(),
    reason="a real cross-replica proof requires a real REDIS_URL",
)
def test_distributed_ollama_semaphore_enforces_the_limit_across_simulated_replicas(monkeypatch):
    """Each _acquire_ollama_slot() call below simulates a *different*
    replica racing for the same cluster-wide limit -- no shared Python
    object between them, only the real Redis-backed semaphore
    (_OLLAMA_SEMAPHORE_KEY). Proves OLLAMA_MAX_CONCURRENCY is enforced
    cluster-wide, not per-replica: 3 simulated replicas contending for a
    limit of 2 must see exactly 2 acquire and 1 shed, and a release must
    free the slot back up for a subsequent acquire."""

    monkeypatch.setenv("OLLAMA_MAX_CONCURRENCY", "2")
    redis_client = prompt_parser.get_sync_redis_client()
    redis_client.delete(prompt_parser._OLLAMA_SEMAPHORE_KEY)

    releases = [prompt_parser._acquire_ollama_slot(0.2) for _ in range(3)]
    acquired = [r for r in releases if r is not None]
    assert len(acquired) == 2  # the cluster-wide limit, not 3
    assert releases.count(None) == 1  # the third replica genuinely shed

    for release in acquired:
        release()

    # The limit is enforced again correctly after releasing -- not
    # permanently exhausted by the earlier contention.
    release = prompt_parser._acquire_ollama_slot(0.2)
    assert release is not None
    release()


@pytest.mark.skipif(
    not os.getenv("REDIS_URL", "").strip(),
    reason="a real cross-replica proof requires a real REDIS_URL",
)
def test_cluster_ollama_stats_aggregate_across_simulated_replicas(monkeypatch):
    """_record_ollama_call/_record_ollama_shed increment the same Redis hash
    regardless of which "replica" (here: which reset_ollama_stats-scoped
    process-local state) calls them -- get_cluster_ollama_stats() must
    report the sum across all of them, not any one replica's own local
    counters."""

    prompt_parser.reset_ollama_stats()  # also clears the Redis hash

    prompt_parser._record_ollama_call(100.0, True)
    prompt_parser._record_ollama_call(50.0, False)
    prompt_parser._record_ollama_shed()

    # A fresh, separate reset of only the process-local counters -- a real
    # second replica's own _ollama_stats dict would likewise start at zero
    # while the Redis-backed cluster counters keep accumulating.
    with prompt_parser._last_call_lock:
        prompt_parser._ollama_stats.update(
            {"attempted": 0, "succeeded": 0, "timed_out": 0, "shed": 0,
             "latency_count": 0, "latency_sum_ms": 0.0, "latency_max_ms": 0.0}
        )
    prompt_parser._record_ollama_call(200.0, True)

    cluster = prompt_parser.get_cluster_ollama_stats()
    assert cluster is not None
    assert cluster["attempted"] == 3
    assert cluster["succeeded"] == 2
    assert cluster["timed_out"] == 1
    assert cluster["shed"] == 1
    assert cluster["mean_latency_ms"] == pytest.approx((100.0 + 200.0) / 2, abs=0.1)


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
