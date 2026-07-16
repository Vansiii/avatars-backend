"""Tests for security headers, request context, and logging."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestSecurityHeaders:
    """SecurityHeadersMiddleware applies correct headers to all responses."""

    def test_x_content_type_options(self):
        response = client.get("/")
        assert response.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options(self):
        response = client.get("/")
        assert response.headers.get("x-frame-options") == "DENY"

    def test_referrer_policy(self):
        response = client.get("/")
        assert response.headers.get("referrer-policy") == "no-referrer"

    def test_permissions_policy_restricted(self):
        response = client.get("/")
        policy = response.headers.get("permissions-policy", "")
        assert "camera=()" in policy
        assert "geolocation=()" in policy
        assert "microphone=()" in policy

    def test_csp_present_api(self):
        """API routes get strict CSP."""
        response = client.get("/")
        csp = response.headers.get("content-security-policy-report-only", "")
        assert "default-src 'none'" in csp
        assert "unsafe-inline" not in csp

    def test_csp_report_only_by_default(self):
        """CSP is in report-only mode by default."""
        response = client.get("/")
        assert "content-security-policy-report-only" in response.headers
        assert "content-security-policy" not in response.headers

    def test_hsts_disabled_by_default(self):
        """HSTS is not sent when ENABLE_HSTS is False."""
        response = client.get("/")
        assert "strict-transport-security" not in response.headers


class TestRequestContext:
    """RequestContextMiddleware generates and propagates X-Request-ID."""

    def test_request_id_generated(self):
        response = client.get("/")
        assert "x-request-id" in response.headers
        assert len(response.headers["x-request-id"]) > 0

    def test_request_id_propagated(self):
        """If client sends X-Request-ID, the response echoes it."""
        rid = "test-request-123"
        response = client.get("/", headers={"X-Request-ID": rid})
        assert response.headers.get("x-request-id") == rid


class TestHealthEndpoint:
    """Health check endpoint."""

    def test_health_returns_ok(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "1.0.0"

    def test_root_returns_message(self):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data

    def test_rate_limit_rejection_keeps_security_headers(self):
        for _ in range(100):
            client.get("/")

        response = client.get("/")

        assert response.status_code == 429
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("x-frame-options") == "DENY"
