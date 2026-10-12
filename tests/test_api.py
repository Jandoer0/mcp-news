"""Дымовые тесты веб-API и статики через TestClient."""
import pytest
from starlette.testclient import TestClient

from mcp_news.api.app import create_app


@pytest.fixture()
def client():
    return TestClient(create_app(start_background=False))


def test_sources_crud(client):
    assert client.get("/api/sources").status_code == 200
    r = client.post("/api/sources", json={"kind": "telegram", "name": "durov"})
    assert r.status_code == 201
    assert client.get("/api/sources").json()[0]["name"] == "durov"
    # DELETE по пути (чинит ранее отсутствовавшее удаление из веб-UI).
    assert client.delete("/api/sources/durov").status_code == 200


def test_ui_and_static(client):
    assert client.get("/ui").status_code == 200
    assert "/static/app.js" in client.get("/ui").text
    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "text/javascript" in js.headers["content-type"]
    assert client.get("/static/styles.css").status_code == 200


def test_topics_flow(client):
    r = client.post("/api/topics", json={"name": "T1", "tag": "g1"})
    assert r.status_code == 201
    assert client.get("/api/topics").json()[0]["name"] == "T1"


def test_config(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    assert "providers" in r.json()


def test_posts_state_combined(client):
    """Единый эндпоинт состояния: editor + tags одним ответом."""
    # Источник + пост
    client.post("/api/sources", json={"kind": "telegram", "name": "durov"})
    posts = client.get("/api/posts").json()["posts"]
    assert posts == []  # лента пуста — эндпоинт просто отвечает структурой
    r = client.get("/api/posts/state?ids=1,2,3")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"editor", "tags"}
