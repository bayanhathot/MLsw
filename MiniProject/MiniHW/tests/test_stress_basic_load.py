"""
Small stress test using pytest + requests.
This is intentionally light so it does not overload Gemini or your laptop.
It sends several requests quickly and checks that the server keeps responding.
"""
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

BASE_URL = "http://localhost:5000"
TIMEOUT = 10


def register_one_user(index):
    username = f"stress_{index}_{uuid.uuid4().hex[:8]}"
    password = "simple_password_123"
    response = requests.post(
        f"{BASE_URL}/register",
        json={"username": username, "password": password},
        timeout=TIMEOUT,
    )
    return response.status_code, response.text


def test_register_endpoint_under_small_parallel_load():
    total_requests = 10
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(register_one_user, i) for i in range(total_requests)]
        results = [future.result() for future in as_completed(futures)]

    for status_code, body in results:
        assert status_code == 201, body
