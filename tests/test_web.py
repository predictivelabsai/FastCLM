from starlette.testclient import TestClient


def test_public_landing_health_and_developer_surface(fresh_db, caplog):
    from web_app import app

    with TestClient(app) as client:
        landing = client.get("/")
        assert landing.status_code == 200
        assert "Ask your contracts" in landing.text
        assert 'src="/static/product-demo.gif"' in landing.text
        assert "Sign In" in landing.text
        assert client.get("/favicon.ico").status_code == 200
        assert 'href="/developers"' in landing.text
        assert 'href="/api/docs"' in landing.text
        assert '"@type":"SoftwareApplication"' in landing.text
        health = client.get("/healthz?never_log=this-secret-query")
        assert health.status_code == 200
        assert health.json()["product"] == "FastCLM"
        assert health.json()["database"]["dialect"] == "sqlite"
        assert health.json()["database"]["latency_ms"] >= 0
        assert health.headers["x-request-id"]
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "fastclm_http_requests_total" in metrics.text
        assert 'method="GET",status="200"' in metrics.text
        assert "this-secret-query" not in caplog.text
        developers = client.get("/developers")
        assert "organisation-scoped" in developers.text
        assert 'href="/swagger.json"' in developers.text
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/contracts").status_code == 503
        assert client.get("/api/docs").status_code == 200
        assert client.get("/swagger.json").status_code == 200
        assert "clm.fastsme.com/developers" in client.get("/sitemap.xml").text
        robots = client.get("/robots.txt").text
        assert "Disallow: /app" in robots
        assert "Disallow: /skills" in robots
        assert "Disallow: /api/" in robots


def test_signup_creates_authenticated_workspace(fresh_db):
    from web_app import app

    with TestClient(app) as client:
        response = client.post("/signup", data={"name": "Taylor", "organisation": "Taylor Studio", "email": "taylor@example.test", "password": "Secure-password1!"})
        assert response.status_code == 200
        assert response.url.path == "/app"
        assert "Ask, investigate, compare" in response.text
        legal_content = client.get("/legal-content")
        assert legal_content.status_code == 200
        assert "Prove which exact wording counsel reviewed" in legal_content.text
        assert "Current approved" in legal_content.text
