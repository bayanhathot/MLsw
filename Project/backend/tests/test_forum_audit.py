from conftest import register_and_login


def test_blocked_listener_cannot_reply_to_a_hidden_comment_by_id(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    post = client.post(
        "/posts", json={"title": "Safety", "body": "A public thread."}
    ).json()
    hidden = second_client.post(
        f"/posts/{post['id']}/comments", json={"body": "Bob's comment"}
    ).json()

    assert client.post("/users/bob/block").status_code == 204
    assert client.get(f"/posts/{post['id']}/comments").json() == []

    response = client.post(
        f"/posts/{post['id']}/comments",
        json={
            "body": "This must not target hidden content",
            "parent_comment_id": hidden["id"],
        },
    )
    assert response.status_code == 404


def test_post_comment_count_matches_the_viewers_block_filtered_thread(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    post = client.post(
        "/posts", json={"title": "Counts", "body": "Keep the badge honest."}
    ).json()
    second_client.post(f"/posts/{post['id']}/comments", json={"body": "visible first"})

    assert client.get(f"/posts/{post['id']}").json()["comment_count"] == 1
    assert client.post("/users/bob/block").status_code == 204
    assert client.get(f"/posts/{post['id']}/comments").json() == []
    assert client.get(f"/posts/{post['id']}").json()["comment_count"] == 0
