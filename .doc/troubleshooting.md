# 트러블슈팅 가이드

> 운영 중 자주 발생할 만한 이슈와 대응. 우선순위는 사용자 영향 큰 것 위에서.
>
> ⚠️ **SQL 예시는 개발자/DB 접근 권한자용**. 운영자(팀장/간사)가 직접 실행하지 말고 개발자에게 전달.

## 인증 / 로그인

### 사용자가 비밀번호를 모름
- **방법 A**: `/admin`에서 **"초대 발송"** → 사용자가 직접 새 비번 설정
- **방법 B**: `/admin`에서 **"PW초기화"** → 일회용 비번 다이얼로그 → 별도 채널 전달

### 카카오 로그인 후 "계정 연결 필요" 화면
- 사용자가 카카오 ID로는 처음 접근. 기존 이메일+비번을 입력해 카카오 계정 연결.
- 사용자가 비번을 모르면 위 "비밀번호를 모름" 절차 → 새 비번 설정 후 다시 카카오 로그인.

### "유효하지 않은 로그인 요청입니다" (카카오 콜백)
- state JWT 만료(10분) 또는 변조. 처음부터 다시 로그인 시도.
- 반복되면 백엔드 로그에서 `event=kakao_callback_invalid_state` 확인.

### 로그인 실패가 반복
- Render 로그: `event=auth_login_failed reason=user_not_found` 또는 `bad_password`
- user_not_found: 이메일 오타 또는 계정 미등록
- bad_password: 비번 분실 → 위 절차

## 카카오 알림

### 동의 항목 미완료 (간사 본인)
- `/admin` 상단 빨간 배너 → **"추가 동의받기"** 클릭
- 필수 scope: `profile_nickname`, `friends`, `talk_message` 모두 ON

### 카카오 발신자 토큰 만료 (일괄 발송 시)
- 결과 다이얼로그 상단에 노란 배너: "카카오 발신자 상태 문제로 수동 전환됨"
- 모든 카카오 매칭 사용자도 manual fallback으로 처리됨
- **대응**: 발신 간사가 다시 카카오 OAuth 로그인 → 토큰 갱신 → 일괄 재발송

### 카카오 메시지 수신자에게 도달 안 됨
- 수신자가 발신 간사를 카카오 친구로 추가 안 했을 가능성
- 수신자의 카카오 메시지 수신 동의 누락
- **확인**: 사용자 행 **"진단"** 버튼 (개별 사용자의 카카오 scope 진단)
- **대응**: 친구 추가 + 동의 재요청 → 재발송

### 카카오 quota(30,000건/일) 초과
- 응답에 `error: "8002"` 또는 quota 관련 메시지
- **대응**: 다음날 재시도. 50명 발송이라 quota 초과 거의 없음.

## 초대 링크 / 비밀번호 셋업

### 사용자가 "유효하지 않거나 만료된 링크" 화면 봄
- 토큰 72h 경과 또는 이미 사용됨 또는 재발송으로 무효화됨
- **대응**: `/admin`에서 해당 사용자 **"초대 발송"** 단건 클릭 → 새 링크 생성

### 사용자가 비번 설정 완료했는지 확인하고 싶음
- 현재 UI에는 직접 표시 없음
- DB 직접 확인:
  ```sql
  SELECT u.email, u.must_change_password, t.consumed_at
  FROM users u
  LEFT JOIN password_setup_tokens t
    ON t.user_id = u.id AND t.purpose = 'initial_setup'
  WHERE u.id = ?;
  ```
- `consumed_at IS NOT NULL` + `must_change_password = false` → 완료
- 또는 사용자에게 직접 카카오/전화 확인

## 권한 / 데이터

### 검토위원이 본인 담당 건물 안 보임
- `Building.reviewer_id`가 NULL이어서 강제 필터에 걸림
- **대응**: 백필 스크립트 실행
  ```bash
  cd backend && source .venv/bin/activate
  python -m scripts.backfill_reviewer_id
  # dry-run 결과 확인 후
  python -m scripts.backfill_reviewer_id --apply
  ```
- unresolved 건은 [first-onboarding-checklist.md](./first-onboarding-checklist.md) 6단계 참조

### 동명이인으로 백필 매핑 실패
- 스크립트 출력 `매핑 불가 — 동명이인 다수`
- **대응**: 운영자가 수동으로 SQL UPDATE
  ```sql
  UPDATE buildings SET reviewer_id = ? WHERE id = ?;
  ```

### 검토위원이 다른 건물에 접근 시도 → 404
- 정상 동작. 권한 정책에 의해 본인 담당 외 건물은 존재 자체 노출 안 함.
- 사용자가 잘못된 링크 받았다면 발신자 확인.

## 시스템 / 인프라

### 백엔드 5xx 에러 급증
- Render 대시보드 → 로그에서 `event=request_unhandled_exception` 검색
- request_id로 특정 요청 추적
- DB 연결 끊김 가능성 → `database.py`의 `pool_pre_ping=True`로 자동 복구되지만 1회 실패는 발생

### S3 다운로드 URL이 유효하지 않음
- presigned URL 만료(1시간) 또는 객체 삭제됨
- **대응**: 파일 다시 업로드 또는 검토서 재제출

### 카카오 link_session 만료 cron 실패
- Render 로그: `event=purge_loop_failed`
- 로직상 실패해도 다음 30분 후 재시도. 운영 영향 없음.
- 반복되면 `services/password_setup.py`의 `purge_expired_setup_tokens` 또는 `services/kakao.py`의 `purge_expired_link_sessions` 직접 디버깅.

## 일반 원칙

- **로그에서 먼저 찾기**: Render 대시보드에서 `event=` 키워드로 grep
- **request_id 추적**: 모든 응답에 `X-Request-ID` 헤더 부여 — 사용자 문의 시 이걸 받으면 로그 매칭 쉬움
- **DB 변경 전 백업**: Supabase 자동 백업 외에 큰 변경 전 수동 dump 권장
