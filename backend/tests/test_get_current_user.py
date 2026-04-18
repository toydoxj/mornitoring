"""get_current_user 예외 처리 회귀.

JWT 자체는 유효해도 sub가 형식 이상이면 500 대신 401.
"""

import os

from jose import jwt


def test_jwt_with_non_numeric_sub_returns_401(client):
    """sub가 숫자로 변환 안 되는 경우 401 (이전엔 500)."""
    secret = os.environ["JWT_SECRET_KEY"]
    token = jwt.encode({"sub": "not_a_number", "role": "reviewer"}, secret, algorithm="HS256")
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


def test_jwt_with_missing_sub_returns_401(client):
    """sub가 없는 JWT → 401."""
    secret = os.environ["JWT_SECRET_KEY"]
    token = jwt.encode({"role": "reviewer"}, secret, algorithm="HS256")
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
