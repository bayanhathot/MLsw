def register_and_login(client, username, email, password="strongpassword"):
    client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )


def test_send_request_appears_in_incoming_and_outgoing(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    response = client.post("/friends/requests", json={"addressee_username": "bob"})

    assert response.status_code == 201
    body = response.json()
    assert body["other_user"]["username"] == "bob"
    assert body["status"] == "pending"

    outgoing = client.get("/friends/requests/outgoing").json()
    assert len(outgoing) == 1
    assert outgoing[0]["other_user"]["username"] == "bob"

    incoming = second_client.get("/friends/requests/incoming").json()
    assert len(incoming) == 1
    assert incoming[0]["other_user"]["username"] == "alice"


def test_self_request_rejected(client):
    register_and_login(client, "alice", "alice@example.com")

    response = client.post("/friends/requests", json={"addressee_username": "alice"})

    assert response.status_code == 400


def test_request_to_unknown_user_rejected(client):
    register_and_login(client, "alice", "alice@example.com")

    response = client.post("/friends/requests", json={"addressee_username": "ghost"})

    assert response.status_code == 404


def test_duplicate_request_rejected(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    client.post("/friends/requests", json={"addressee_username": "bob"})
    response = client.post("/friends/requests", json={"addressee_username": "bob"})

    assert response.status_code == 409


def test_reverse_duplicate_request_rejected(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    client.post("/friends/requests", json={"addressee_username": "bob"})
    response = second_client.post("/friends/requests", json={"addressee_username": "alice"})

    assert response.status_code == 409


def test_accept_request_creates_friendship(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    request_id = client.post(
        "/friends/requests", json={"addressee_username": "bob"}
    ).json()["id"]

    response = second_client.post(f"/friends/requests/{request_id}/accept")

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"

    assert [f["username"] for f in client.get("/friends").json()] == ["bob"]
    assert [f["username"] for f in second_client.get("/friends").json()] == ["alice"]

    assert client.get("/users/bob").json()["friend_status"] == "friends"


def test_only_addressee_can_accept(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    request_id = client.post(
        "/friends/requests", json={"addressee_username": "bob"}
    ).json()["id"]

    response = client.post(f"/friends/requests/{request_id}/accept")

    assert response.status_code == 403


def test_decline_request_allows_resending(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    request_id = client.post(
        "/friends/requests", json={"addressee_username": "bob"}
    ).json()["id"]

    decline_response = second_client.post(f"/friends/requests/{request_id}/decline")
    assert decline_response.status_code == 200
    assert decline_response.json()["status"] == "declined"

    assert client.get("/users/bob").json()["friend_status"] == "none"

    resend_response = client.post("/friends/requests", json={"addressee_username": "bob"})
    assert resend_response.status_code == 201


def test_only_requester_can_cancel(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    request_id = client.post(
        "/friends/requests", json={"addressee_username": "bob"}
    ).json()["id"]

    denied = second_client.post(f"/friends/requests/{request_id}/decline")
    # bob is the addressee, so decline is allowed - use this response to confirm
    # cancel-by-non-requester is rejected separately with a fresh pending request.
    assert denied.status_code == 200

    request_id_2 = second_client.post(
        "/friends/requests", json={"addressee_username": "alice"}
    ).json()["id"]

    forbidden = second_client.delete(f"/friends/requests/{request_id_2}")
    assert forbidden.status_code == 204  # bob is the requester now, so this is allowed

    # Recreate a pending request from alice, and confirm bob (addressee) cannot cancel it.
    request_id_3 = client.post(
        "/friends/requests", json={"addressee_username": "bob"}
    ).json()["id"]

    not_allowed = second_client.delete(f"/friends/requests/{request_id_3}")
    assert not_allowed.status_code == 403


def test_unfriend_removes_relationship_both_ways(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    request_id = client.post(
        "/friends/requests", json={"addressee_username": "bob"}
    ).json()["id"]
    second_client.post(f"/friends/requests/{request_id}/accept")

    response = client.delete("/friends/bob")
    assert response.status_code == 204

    assert client.get("/friends").json() == []
    assert second_client.get("/friends").json() == []
    assert client.get("/users/bob").json()["friend_status"] == "none"
