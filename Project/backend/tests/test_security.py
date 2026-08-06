from app.core.security import create_access_token, decode_access_token


def test_access_token_round_trip():
    token = create_access_token(subject="42")

    assert decode_access_token(token) == "42"
    assert decode_access_token("not-a-jwt") is None
