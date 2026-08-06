def register_and_login(client, username, email, password="strongpassword"):
    client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )


def test_search_requires_authentication(client):
    response = client.get("/users/search", params={"q": "anyone"})

    assert response.status_code == 401


def test_search_excludes_self(client):
    register_and_login(client, "alice", "alice@example.com")

    response = client.get("/users/search", params={"q": "alice"})

    assert response.status_code == 200
    assert response.json() == []


def test_search_finds_other_users_with_none_status(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    response = client.get("/users/search", params={"q": "bob"})

    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["username"] == "bob"
    assert results[0]["friend_status"] == "none"


def test_get_own_profile_reports_self(client):
    register_and_login(client, "alice", "alice@example.com")

    response = client.get("/users/alice")

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "alice"
    assert body["friend_status"] == "self"


def test_get_other_profile_reports_none(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    response = client.get("/users/bob")

    assert response.status_code == 200
    assert response.json()["friend_status"] == "none"


def test_get_profile_for_unknown_user_is_404(client):
    register_and_login(client, "alice", "alice@example.com")

    response = client.get("/users/does-not-exist")

    assert response.status_code == 404
