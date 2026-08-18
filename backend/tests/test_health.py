"""헬스체크 — 배포된 커밋 확인용."""

from fastapi.testclient import TestClient


def test_헬스체크가_배포_커밋을_함께_반환한다():
    from main import app

    with TestClient(app) as client:
        for path in ("/api/health", "/"):
            body = client.get(path).json()
            assert body["status"] == "ok"
            # 로컬/CI에는 RENDER_GIT_COMMIT이 없으므로 "local"
            assert body["commit"]


def test_커밋_SHA는_짧은_형식으로_노출된다(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "53d68c4b449b2e9f3b40f8facc7a546ed56e075e")

    from config import Settings

    settings = Settings()
    assert settings.render_git_commit[:7] == "53d68c4"
