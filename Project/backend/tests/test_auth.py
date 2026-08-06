def register_user(client, username="zonix_user", email="user@example.com"):
    return client.post(
        "/auth/register",
        json={
            "username": username,
            "email": email,
            "password": "strongpassword",
        },
    )


def test_register_login_me_and_logout(client):
    register_response = register_user(client)

    assert register_response.status_code == 201
    assert register_response.json()["email"] == "user@example.com"
    assert "hashed_password" not in register_response.json()

    login_response = client.post(
        "/auth/login",
        json={
            "email": "user@example.com",
            "password": "strongpassword",
        },
    )

    assert login_response.status_code == 200
    assert login_response.json() == {"message": "Login successful"}
    assert "HttpOnly" in login_response.headers["set-cookie"]

    me_response = client.get("/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "zonix_user"

    logout_response = client.post("/auth/logout")
    assert logout_response.status_code == 200
    assert client.get("/auth/me").status_code == 401


def test_duplicate_registration_is_rejected(client):
    assert register_user(client).status_code == 201

    duplicate_response = register_user(client)

    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["detail"] == "Email is already registered."


def test_wrong_password_is_rejected(client):
    assert register_user(client).status_code == 201

    response = client.post(
        "/auth/login",
        json={
            "email": "user@example.com",
            "password": "not-the-password",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_me_requires_authentication(client):
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated."
