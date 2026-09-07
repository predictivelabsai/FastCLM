from starlette.testclient import TestClient


def test_public_landing_health_and_developer_surface(fresh_db):
    from web_app import app

    with TestClient(app) as client:
        landing = client.get("/")
        assert landing.status_code == 200
        assert "Know what you agreed" in landing.text
        assert "Sign In" in landing.text
        assert 'href="/developers"' in landing.text
        assert 'href="/api/v1/docs"' in landing.text
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["product"] == "FastCLM"
        developers = client.get("/developers")
        assert "organisation-scoped" in developers.text
        assert client.get("/api/v1/status").status_code == 200
        assert client.get("/api/v1/contracts").status_code == 503


def test_signup_creates_authenticated_workspace(fresh_db):
    from web_app import app

    with TestClient(app) as client:
        response = client.post("/signup", data={"name": "Taylor", "organisation": "Taylor Studio", "email": "taylor@example.test", "password": "Secure-password1!"})
        assert response.status_code == 200
        assert response.url.path == "/app"
        assert "The agreements that need attention" in response.text
