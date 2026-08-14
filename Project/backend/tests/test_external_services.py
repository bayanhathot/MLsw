import time

import httpx

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
