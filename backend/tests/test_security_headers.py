from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

def test_security_headers_are_present():
    response = client.get("/")
    
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert response.headers.get("Permissions-Policy") == "geolocation=(), microphone=(), camera=()"
    assert response.headers.get("X-XSS-Protection") == "0"
    
    assert "Content-Security-Policy" not in response.headers
    assert "Strict-Transport-Security" not in response.headers