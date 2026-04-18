# 운영 정책 요약

> 변경 시 [operator-onboarding-manual.md](./operator-onboarding-manual.md), [first-onboarding-checklist.md](./first-onboarding-checklist.md)도 같이 업데이트.

## 권한 매트릭스

| 역할 | 사용자 관리 | 건물 (전체/통계) | 본인 담당 건물 | 검토서 업로드 | 카카오 발송 | 공지 작성 | 토론 작성 | 감사 로그 |
|---|---|---|---|---|---|---|---|---|
| 팀장 | ⭕ | ⭕ | ⭕ | ⭕ | ⭕ | ⭕ | ⭕ | ⭕ |
| 총괄간사 | ⭕ | ⭕ | ⭕ | ⭕ | ⭕ | ⭕ | ⭕ | ⭕ |
| 간사 | 일부 | ⭕ | ⭕ | ⭕ | ⭕ | ⭕ | ⭕ | ❌ |
| 검토위원 | 본인만 | ❌ | ⭕ (reviewer_id 매칭만) | ⭕ (본인 건물) | ❌ | 댓글만 | ⭕ | ❌ |

**핵심 원칙**:
- 검토위원은 **본인 `reviewer_id`** 매칭 건물만 접근 (이름 기반 매칭 X — 동명이인 위험)
- 검토위원이 타 건물 ID로 접근 시 **404** 반환 (존재 자체 노출 방지)
- 토론방은 모든 인증 사용자 자유 작성 (정책 결정)

## 인증 / 토큰

| 항목 | 정책 |
|---|---|
| 로그인 access token | JWT, 24시간 유효 |
| 비밀번호 최소 길이 | 8자 |
| 카카오 OAuth state | JWT, 10분 유효 (CSRF 방어) |
| 카카오 link_session | 256bit 랜덤 PK, 10분 유효, 1회성 소비 (DoS 방어로 인증 후 마킹) |
| 비밀번호 셋업 토큰 | sha256 해시 저장, 72시간 유효, 1회성 소비, 재발송 시 이전 무효화 |
| `users.kakao_id` | partial unique (NULL 다수 허용, 동일 카카오 ID 중복 연결 차단) |

## 카카오 알림

| 항목 | 값 |
|---|---|
| 일일 quota | 30,000건/일 (검수 통과) |
| pair 일일 제한 | 자체 모니터링 (서비스 내 카운트) |
| 발신자 토큰 만료 | 자동 갱신 (5분 전부터 refresh) |
| 친구 메시지 batch | 1명씩 호출 (개별 setup_url 보장 위해) |
| 메시지 형식 | 텍스트 + 링크 |
| 발송 실패 정책 | 사용자별 manual fallback (best-effort) |

## 비밀번호 셋업 흐름

| 시점 | 동작 |
|---|---|
| 사용자 등록 | 일회용 초기 비번 응답 (과도기 fallback) |
| 등록 직후 / 일괄 등록 후 | "초대 발송"으로 setup token 발급 → 카카오/수동 전달 |
| 사용자 링크 클릭 | `/setup-password?token=...` → validate → 새 비번 입력 → consumed |
| 토큰 만료 | 72시간 후 자동 만료, 재발송 가능 |
| 재발송 | 이전 토큰 모두 무효화, 새 토큰 발급 |
| 정리 cron | 30분 주기 lifespan task (만료 즉시 + 소비 7일 후 삭제) |

## 데이터 정합성

- **검토위원-건물 매핑**: `Building.reviewer_id` (FK)만 신뢰. `assigned_reviewer_name`(이름)은 표시용
- **백필 도구**: `python -m scripts.backfill_reviewer_id` (NFKC + 공백 제거 정규화)
- **백필 시점**: 검토위원 50명 계정 + Reviewer 행 생성 직후
- **inquiry 작성자**: `submitter_id` (FK)만 신뢰. `submitter_name`은 스냅샷 표시용

## 운영 지표 (현재 가능)

- **로그 grep**: Render 대시보드에서 `event=` 키워드 검색
  - `event=request status=5` → 5xx 에러
  - `event=auth_login_failed` → 로그인 실패 (reason 필드)
  - `event=kakao_message_friend_failed` → 카카오 발송 실패
  - `event=password_setup_completed` → 비번 설정 완료
  - `event=bulk_invite_kakao_sent` → 카카오 일괄 발송 성공
- **request_id**: 모든 응답에 `X-Request-ID` 헤더 (12자 hex). 사용자 문의 시 받으면 로그 매칭 쉬움
- **카카오 발송 이력**: `/notifications` 페이지 (팀장/총괄간사)
- **감사 로그**: API `GET /api/audit-logs` (UI 없음)

## 백업 / 복구

- **DB**: Supabase 자동 백업
- **S3**: 검토서 파일 (lifecycle 정책 운영 전 확인 필요)
- **시크릿**: `JWT_SECRET_KEY`, AWS, 카카오 client secret — 모두 운영 직전 한 차례 회전 완료

## 잔여 결정 사항

- [ ] 자동 리마인더 발송 정책 (현재 미구현)
- [ ] 비번 미설정자 자동 재발송 cron (현재 수동)
- [ ] Sentry 등 외부 오류 추적 (현재 Render 로그만)
- [ ] Refresh token 도입 (현재 access 24h만)
- [ ] HttpOnly cookie 전환 (현재 localStorage)
