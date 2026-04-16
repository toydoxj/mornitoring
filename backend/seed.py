"""테스트용 초기 데이터 시드"""

from database import SessionLocal
from models.user import User, UserRole
from routers.auth import get_password_hash


def seed():
    db = SessionLocal()
    try:
        # 이미 사용자가 있으면 스킵
        if db.query(User).first():
            print("이미 시드 데이터가 있습니다. 스킵합니다.")
            return

        users = [
            User(
                name="김팀장",
                email="leader@test.com",
                role=UserRole.TEAM_LEADER,
                phone="010-1111-0001",
                password_hash=get_password_hash("test1234"),
            ),
            User(
                name="이총괄",
                email="chief@test.com",
                role=UserRole.CHIEF_SECRETARY,
                phone="010-1111-0002",
                password_hash=get_password_hash("test1234"),
            ),
            User(
                name="박간사",
                email="secretary@test.com",
                role=UserRole.SECRETARY,
                phone="010-1111-0003",
                password_hash=get_password_hash("test1234"),
            ),
            User(
                name="홍길동",
                email="reviewer1@test.com",
                role=UserRole.REVIEWER,
                phone="010-2222-0001",
                password_hash=get_password_hash("test1234"),
            ),
            User(
                name="김철수",
                email="reviewer2@test.com",
                role=UserRole.REVIEWER,
                phone="010-2222-0002",
                password_hash=get_password_hash("test1234"),
            ),
        ]

        db.add_all(users)
        db.commit()
        print(f"시드 데이터 생성 완료: 사용자 {len(users)}명")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
