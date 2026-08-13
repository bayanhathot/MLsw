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
