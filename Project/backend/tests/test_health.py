def test_root_health_endpoint(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "zonix-backend",
        "status": "running",
        "message": "Zonix backend is running",
    }


def test_database_health_endpoint(client):
    response = client.get("/db-health")

    assert response.status_code == 200
    assert response.json() == {
        "database": "connected",
        "result": 1,
    }
