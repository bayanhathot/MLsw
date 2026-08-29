from conftest import register_and_login


def _profile_stats(client, username="alice"):
    response = client.get(f"/users/{username}/profile")
    assert response.status_code == 200, response.text
    return response.json()["stats"]


def _assert_stats(client, expected, username="alice"):
    stats = _profile_stats(client, username)
    assert stats == expected
    return stats


def _create_post(client, body, *, visibility="public", anonymous=False):
    response = client.post(
        "/posts",
        json={
            "title": f"Discussion: {body}",
            "body": body,
            "kind": "discussion" if anonymous else "status",
            "visibility": visibility,
            "is_anonymous": anonymous,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_comment(client, post_id, body, *, anonymous=False):
    response = client.post(
        f"/posts/{post_id}/comments",
        json={"body": body, "is_anonymous": anonymous},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _make_friends(client, second_client, receiver_username="bob"):
    sent = client.post(f"/friends/requests/{receiver_username}")
    assert sent.status_code == 201, sent.text
    accepted = second_client.post(f"/friends/requests/{sent.json()['id']}/accept")
    assert accepted.status_code == 200, accepted.text


def test_community_profile_counters_follow_real_actions_reversals_and_user_isolation(
    client, second_client
):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    zero = {
        "received_upvotes": 0,
        "received_downvotes": 0,
        "post_count": 0,
        "comment_count": 0,
    }
    _assert_stats(client, zero)

    alice_post = _create_post(client, "Alice owns this post")
    _assert_stats(client, {**zero, "post_count": 1})

    # Another user's post must not affect Alice's authored-post counter.
    bob_post = _create_post(second_client, "Bob owns this post")
    _assert_stats(client, {**zero, "post_count": 1})

    alice_comment = _create_comment(client, bob_post["id"], "Alice comments")
    # Comments Alice writes elsewhere do not count as comments she received.
    _assert_stats(client, {**zero, "post_count": 1})
    assert _profile_stats(second_client, "bob")["comment_count"] == 1

    bob_comment = _create_comment(second_client, alice_post["id"], "Bob comments")
    _assert_stats(client, {**zero, "post_count": 1, "comment_count": 1})

    # These are votes received by Alice's content, not votes Alice casts.
    upvote = second_client.post(
        f"/posts/{alice_post['id']}/vote", json={"value": 1}
    )
    assert upvote.status_code == 200
    _assert_stats(
        client,
        {**zero, "post_count": 1, "comment_count": 1, "received_upvotes": 1},
    )

    alice_votes_for_bob = client.post(
        f"/posts/{bob_post['id']}/vote", json={"value": 1}
    )
    assert alice_votes_for_bob.status_code == 200
    _assert_stats(
        client,
        {**zero, "post_count": 1, "comment_count": 1, "received_upvotes": 1},
    )

    changed_vote = second_client.post(
        f"/posts/{alice_post['id']}/vote", json={"value": -1}
    )
    assert changed_vote.status_code == 200
    _assert_stats(
        client,
        {**zero, "post_count": 1, "comment_count": 1, "received_downvotes": 1},
    )

    removed_vote = second_client.delete(f"/posts/{alice_post['id']}/vote")
    assert removed_vote.status_code == 200
    _assert_stats(client, {**zero, "post_count": 1, "comment_count": 1})

    comment_upvote = second_client.post(
        f"/posts/comments/{alice_comment['id']}/vote", json={"value": 1}
    )
    assert comment_upvote.status_code == 200
    # The profile dashboard tracks votes received on posts, not comments.
    _assert_stats(client, {**zero, "post_count": 1, "comment_count": 1})

    deleted_comment = client.delete(
        f"/posts/{bob_post['id']}/comments/{alice_comment['id']}"
    )
    assert deleted_comment.status_code == 204
    _assert_stats(client, {**zero, "post_count": 1, "comment_count": 1})
    assert _profile_stats(second_client, "bob")["comment_count"] == 0

    # Deleting Alice's post removes the post and Bob's cascaded comment.
    assert client.delete(f"/posts/{alice_post['id']}").status_code == 204
    _assert_stats(client, zero)
    assert _profile_stats(second_client, "bob")["comment_count"] == 0
    assert bob_comment["id"] > 0


def test_friend_profile_counter_follows_accept_remove_and_other_users(
    client, second_client, third_client
):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    register_and_login(third_client, "carol", "carol@example.com")

    assert client.get("/users/alice/profile").json()["friend_count"] == 0
    sent = client.post("/friends/requests/bob")
    assert sent.status_code == 201
    # A pending request is not a friendship and must not increment the count.
    assert client.get("/users/alice/profile").json()["friend_count"] == 0

    assert (
        second_client.post(f"/friends/requests/{sent.json()['id']}/accept").status_code
        == 200
    )
    assert client.get("/users/alice/profile").json()["friend_count"] == 1
    assert second_client.get("/users/bob/profile").json()["friend_count"] == 1

    # Bob and Carol becoming friends is unrelated to Alice's own count.
    _make_friends(second_client, third_client, "carol")
    assert client.get("/users/alice/profile").json()["friend_count"] == 1

    assert client.delete("/friends/bob").status_code == 204
    assert client.get("/users/alice/profile").json()["friend_count"] == 0
    assert second_client.get("/users/bob/profile").json()["friend_count"] == 1


def test_public_profile_statistics_hide_anonymous_and_non_visible_activity(
    client, second_client, third_client
):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    register_and_login(third_client, "carol", "carol@example.com")
    _make_friends(client, third_client, "carol")

    public_post = _create_post(client, "Public named activity")
    friends_post = _create_post(
        client, "Friends-only named activity", visibility="friends"
    )
    anonymous_post = _create_post(
        client, "Public anonymous activity", anonymous=True
    )
    public_comment = _create_comment(third_client, public_post["id"], "Public named reply")
    friends_comment = _create_comment(
        third_client, friends_post["id"], "Friends-only named reply"
    )
    anonymous_comment = _create_comment(
        third_client, anonymous_post["id"], "Public anonymous reply", anonymous=True
    )
    _create_comment(client, public_post["id"], "Owner reply does not count")

    for entity, entity_id, value in (
        ("post", public_post["id"], 1),
        ("post", friends_post["id"], 1),
        ("post", anonymous_post["id"], 1),
        ("comment", public_comment["id"], -1),
        ("comment", friends_comment["id"], -1),
        ("comment", anonymous_comment["id"], -1),
    ):
        path = (
            f"/posts/{entity_id}/vote"
            if entity == "post"
            else f"/posts/comments/{entity_id}/vote"
        )
        response = third_client.post(path, json={"value": value})
        assert response.status_code == 200, response.text

    # Owners see all of their own activity, including anonymous work.
    assert _profile_stats(client) == {
        "received_upvotes": 3,
        "received_downvotes": 0,
        "post_count": 3,
        "comment_count": 3,
    }
    # Strangers see only named activity on public posts.
    stranger_stats = _profile_stats(second_client)
    assert stranger_stats == {
        "received_upvotes": 1,
        "received_downvotes": 0,
        "post_count": 1,
        "comment_count": 1,
    }
    assert second_client.get("/users/alice/stats").json() == stranger_stats
    # Accepted friends additionally see named friends-only activity, but
    # anonymous activity is never associated with the profile publicly.
    friend_stats = _profile_stats(third_client)
    assert friend_stats == {
        "received_upvotes": 2,
        "received_downvotes": 0,
        "post_count": 2,
        "comment_count": 2,
    }

    assert third_client.delete("/friends/alice").status_code == 204
    assert _profile_stats(third_client) == stranger_stats
