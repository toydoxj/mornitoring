"""테스트용 초기 데이터 시드 (개발 환경 전용).

운영 DB 실수 방지를 위해:
1. 환경변수 ENVIRONMENT가 "development" 또는 "test"일 때만 실행
2. 비밀번호는 랜덤 생성 후 stdout에 출력 (하드코딩 금지)
3. 운영에서 실행 시 즉시 종료
"""

import os
import secrets
import sys

from database import SessionLocal
from models.user import User, UserRole
from routers.auth import get_password_hash


def _generate_seed_password() -> str:
    """시드 사용자용 1회성 비밀번호 — 매번 다른 값. stdout에 출력하므로 운영자가 한 번만 봄."""
    return secrets.token_urlsafe(12)


def seed():
    # 운영 DB 실수 방지 — 환경변수 명시 없으면 거부
    env = os.environ.get("ENVIRONMENT", "").lower()
    if env not in ("development", "test"):
        print(
            "❌ ENVIRONMENT 환경변수가 'development' 또는 'test'가 아니면 seed를 실행할 수 없습니다.\n"
            "   운영 DB에 시드 데이터가 들어가는 사고를 막기 위함입니다.\n"
            "   개발 환경이면: ENVIRONMENT=development python seed.py",
            file=sys.stderr,
        )
        sys.exit(1)

    db = SessionLocal()
    try:
        # 이미 사용자가 있으면 스킵
        if db.query(User).first():
            print("이미 시드 데이터가 있습니다. 스킵합니다.")
            return

        seed_specs = [
            ("김팀장", "leader@test.com", UserRole.TEAM_LEADER, "010-1111-0001"),
            ("이총괄", "chief@test.com", UserRole.CHIEF_SECRETARY, "010-1111-0002"),
            ("박간사", "secretary@test.com", UserRole.SECRETARY, "010-1111-0003"),
            ("홍길동", "reviewer1@test.com", UserRole.REVIEWER, "010-2222-0001"),
            ("김철수", "reviewer2@test.com", UserRole.REVIEWER, "010-2222-0002"),
        ]

        users = []
        passwords: list[tuple[str, str]] = []  # (email, plain_password)
        for name, email, role, phone in seed_specs:
            pw = _generate_seed_password()
            users.append(
                User(
                    name=name,
                    email=email,
                    role=role,
                    phone=phone,
                    password_hash=get_password_hash(pw),
                    must_change_password=True,
                )
            )
            passwords.append((email, pw))

        db.add_all(users)
        db.commit()
        print(f"시드 데이터 생성 완료: 사용자 {len(users)}명")
        print("\n=== 1회용 초기 비밀번호 (지금만 표시됨) ===")
        for email, pw in passwords:
            print(f"  {email}\t{pw}")
        print("===========================================\n")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
