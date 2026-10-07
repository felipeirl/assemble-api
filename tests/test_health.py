def test_health_returns_ok_without_auth(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_laya_and_queues(client, container):
    container.reply_queue.hold = True
    container.reply_queue.pending.append(lambda: None)

    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["laya"] == "warm"
    assert body["queues"]["chat"]["waiting"] == 1
    assert set(body["queues"]) == {"chat", "assembles", "memory"}


def test_ready_is_503_while_laya_loads(client, container):
    container.guardrail.is_warm = False

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["laya"] == "loading"
