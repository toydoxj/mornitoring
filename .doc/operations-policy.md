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

상세 절차·복구 명령·리허설 체크리스트: **[`backup-recovery.md`](./backup-recovery.md)**

- **DB 1차**: Supabase 자동 일일 스냅샷 (벤더 내부)
- **DB 2차**: GitHub Actions(`.github/workflows/db-backup.yml`) → 매일 KST 03:10 `pg_dump -Fc` → AWS S3 오프사이트 업로드 (SHA-256 + 메타 JSON 동반)
  - 배포/마이그레이션 직전에는 Actions → Run workflow 로 `label=pre-migration` 수동 백업 권장
- **S3 첨부 버킷**: Versioning ON + Lifecycle (noncurrent 90일 → Glacier → 1년 Expire)
- **시크릿**: `JWT_SECRET_KEY`, AWS, 카카오 client secret — 운영 직전 1회 회전 완료. 백업 전용 IAM 키는 별도 발급·최소권한(PutObject only)
- **RPO/RTO 목표**: RPO 24h · RTO 4h (PITR 미도입 기준). PITR 도입 결정은 P1.
- **리허설**: 분기 1회, 담당자 로테이션, 결과는 `.doc/backup-drill-YYYYQn.md` 로 기록

## Supabase RLS (Row-Level Security)

Supabase는 PostgREST를 통해 `public` 스키마를 anon/authenticated 역할로 자동 노출한다. 우리는 백엔드(Render FastAPI)가 슈퍼유저(`postgres`, BYPASSRLS)로 직접 접속하므로 RLS 자체에는 영향을 받지 않지만, **RLS가 꺼진 테이블은 anon key + 프로젝트 URL 만으로 외부에서 CRUD 가능**하다.

- **정책**: `public` 스키마의 모든 테이블에 `ENABLE + FORCE ROW LEVEL SECURITY`. 정책(POLICY)은 일부러 추가하지 않아 anon/authenticated는 전부 차단.
- **자동 적용**: alembic revision `c4d8b71f9a05` (1회) + `alembic/env.py` 의 post-upgrade 훅이 매 `alembic upgrade` 종료 시 누락 테이블을 idempotent 하게 ENABLE+FORCE. 훅은 별도 `connection.begin()` 트랜잭션을 시작해 commit 보장. 훅 실패 시 기본은 stderr 경고만 남기지만, 운영에서 `STRICT_RLS_HOOK=1` 환경변수 설정 시 예외를 raise 해 deploy 자체를 실패시킨다 (보안 드리프트 즉시 탐지).
- **백엔드 연결 계정 요건**: `BYPASSRLS` 권한 보유. Supabase 기본 `postgres` 역할은 보유함. 운영 점검:
  ```sql
  SELECT current_user, rolbypassrls
  FROM pg_roles
  WHERE rolname = current_user;
  ```
- **RLS 상태 점검 SQL** (일반 테이블 'r' + partitioned 부모 'p' 모두 검사. 결과 0행이 정상):
  ```sql
  SELECT c.relname,
         c.relkind,
         c.relrowsecurity  AS rls_enabled,
         c.relforcerowsecurity AS rls_forced
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public'
    AND c.relkind IN ('r', 'p')
    AND (c.relrowsecurity = false OR c.relforcerowsecurity = false);
  ```
- **anon/authenticated 권한 점검 SQL** (RLS와 별도로 PostgREST가 호출 가능한 표면 확인):
  ```sql
  -- 1) 테이블 권한
  SELECT grantee, table_name, privilege_type
  FROM information_schema.role_table_grants
  WHERE table_schema = 'public'
    AND grantee IN ('anon', 'authenticated')
  ORDER BY table_name, privilege_type;

  -- 2) 스키마 USAGE / CREATE 권한 (드리프트 점검)
  SELECT n.nspname, r.rolname, has_schema_privilege(r.rolname, n.nspname, 'USAGE')  AS usage_ok,
                                has_schema_privilege(r.rolname, n.nspname, 'CREATE') AS create_ok
  FROM pg_namespace n
  CROSS JOIN pg_roles r
  WHERE n.nspname = 'public' AND r.rolname IN ('anon', 'authenticated');

  -- 3) SECURITY DEFINER 함수 + 실 EXECUTE 권한 보유자 (RLS 우회 위험)
  SELECT n.nspname AS schema, p.proname, p.prosecdef AS security_definer,
         pg_get_userbyid(p.proowner) AS owner,
         (aclexplode(coalesce(p.proacl, acldefault('f', p.proowner)))).grantee::regrole AS grantee,
         (aclexplode(coalesce(p.proacl, acldefault('f', p.proowner)))).privilege_type
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname = 'public';
  ```
- **비상 우회**: 일시적으로 PostgREST 노출까지 차단하려면 `REVOKE ALL ON SCHEMA public FROM anon, authenticated;` (적용 시 Supabase Studio Table Editor도 익명 조회 못 함).
- **자동 downgrade 금지**: `c4d8b71f9a05` revision 의 `downgrade()` 는 `NotImplementedError` 를 던진다. 일괄 RLS 해제는 보안 사고와 직결되므로 운영자가 의도적으로 위 점검 SQL을 역방향(`DISABLE ROW LEVEL SECURITY`)으로 작성해 수동 실행해야 한다.
- **anon/service_role key 회전**: Supabase Dashboard → Settings → API. 회전 시 외부 노출 가능성 차단.

## 잔여 결정 사항

- [ ] 자동 리마인더 발송 정책 (현재 미구현)
- [ ] 비번 미설정자 자동 재발송 cron (현재 수동)
- [ ] Sentry 등 외부 오류 추적 (현재 Render 로그만)
- [ ] Refresh token 도입 (현재 access 24h만)
- [ ] HttpOnly cookie 전환 (현재 localStorage)
