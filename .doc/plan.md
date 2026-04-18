# 건축구조안전 모니터링 시스템 — 구현 계획서

> 최종 갱신: 2026-04-18
> 진행 상황: Stage 1~4 완료. 보안 P0/P0.5 + P1 D + N5 + 외부 리뷰 4종 quick win까지 완료. **94 테스트 PASS**.
> **운영 투입 직전 — 다음 단계는 운영 dry-run 또는 운영 전환.**

## 운영 문서 (50명 온보딩 직전 참조)

- [first-onboarding-checklist.md](./first-onboarding-checklist.md) — 검토위원 50명 일괄 온보딩 단계별 체크리스트
- [operator-onboarding-manual.md](./operator-onboarding-manual.md) — 운영자(팀장/간사) 사용자 등록·발송 매뉴얼
- [troubleshooting.md](./troubleshooting.md) — 자주 발생할 만한 이슈 대응
- [operational-dry-run.md](./operational-dry-run.md) — 50명 온보딩 전 테스트 계정 2~3개로 end-to-end 점검
- [operations-policy.md](./operations-policy.md) — 권한/토큰/카카오/데이터 정합성 정책 요약

---

## 위협 모델링 (2026-04-18 기준, codex 검토)

### 가장 가능성 높은 공격 벡터 5개 (우선순위순)

| # | 벡터 | 공격 시나리오 | 잔여 위험 |
|---|---|---|---|
| 1 | **XSS → localStorage JWT 탈취** | 공지/토론/첨부파일명 등 사용자 입력 지점에 스크립트 삽입 → 브라우저 JS로 JWT 읽어 외부 전송 | 🔴 높음 |
| 2 | **DB 자격증명 유출/직접 접근** | `.env` 유출, 운영자 PC 침해, Supabase 자격증명 노출 → `users.kakao_*_token`(평문)·운영 데이터 직접 열람 | 🔴 높음 |
| 3 | **운영자 계정 탈취** | 피싱·약한 비번·비번 재사용 → 간사/총괄간사 계정 → `/admin`·발송·리셋 악용 | 🟡 중~높음 |
| 4 | **업로드/엑셀 파싱 경로** | 악성 파일·edge-case payload → 서버 예외/리소스 소진·parser 취약점 | 🟡 중간 |
| 5 | **OAuth/setup 토큰 재사용** | 피싱·shoulder surfing·운영자 화면 노출 후 setup_url 재사용 시도 | 🟡 중간 |

### 🚨 가장 위험한 단일 공격
> **XSS → localStorage JWT 탈취** — 한 번 통하면 세션 즉시 탈취. 운영자 세션 탈취 시 피해 매우 큼.

### 현재 적용된 방어 (요약)
- JWT 32자 secret 검증, OAuth state JWT (10분 TTL)
- 카카오 토큰 1회성 link_session (DB), 비번 셋업 토큰 sha256 해시 저장 + 1회성
- REVIEWER 권한: `reviewer_id` 매칭만 (이름 X), 라우터 sweep 8종
- 파일 업로드 10/20MB 크기 제한 + stream tempfile, MIME 화이트리스트 미적용
- 카카오 토큰 detail 응답 마스킹, 외부 응답 본문 비노출
- request middleware + key=value 로깅 + X-Request-ID
- CORS env화, must_change_password, 401 race 방지

### 🔴 즉시 보강 권장 (운영 시작 전 또는 1주 내)

1. **프론트 XSS 점검 + CSP 헤더 추가** ⭐ 1순위
   - `dangerouslySetInnerHTML` 사용처 grep + 모두 점검
   - Next.js `next.config` 또는 middleware로 CSP 헤더 (script-src 'self' 등)
   - 사용자 입력이 HTML로 렌더링되는 모든 지점 escaping 재확인 (공지/토론/문의 본문 등)
2. **관리자 계정 운영 강화**
   - 운영자 7명 비번 재점검 + 재사용 금지 안내
   - "ksea" 잔존 계정 3명 비번 초기화 (이미 plan에 있음)
   - 관리자 로그인 실패 로그 모니터링 (`event=auth_login_failed reason=...`)
3. **DB 접근 최소화**
   - Supabase DB 비번 재로테이션 주기화 (분기별)
   - 최소권한 DB 계정 (앱용 vs admin용 분리)
   - 가능하면 Supabase 네트워크/IP 제한
4. **카카오 토큰 컬럼 암호화 설계 착수**
   - 즉시 KMS는 과한 부담이지만 설계·컬럼 래퍼 준비 시작
   - DB 유출 시 토큰 재사용 방지
5. **OAuth state 1회성 저장소 검토**
   - 현재 JWT 서명만 (replay window 10분)
   - DB 또는 Redis 기반 nonce 1회성 소비 구조 설계

### 🟢 장기 방어 (안정화)

1. **HttpOnly cookie 전환** — XSS로 JWT 탈취 자체 차단 (가장 효과적인 #1 벡터 방어)
2. **카카오 토큰 KMS 또는 앱 계층 암호화** — DB 유출 시 토큰 비활성화
3. **관리자 MFA** — 운영자 계정 탈취 차단
4. **파일 처리 worker 분리** — parser 취약점 격리
5. **보안 헤더 전수 정리** — CSP, HSTS, X-Frame-Options, Permissions-Policy

### 운영자 위협 인식 가이드 (행동)
- 카카오 메시지/이메일 링크 의심 시 직접 입력 (URL 복붙 X)
- 운영 사이트 외 카카오 OAuth 동의 화면이 떠도 일단 닫기
- 운영자 PC에 .env 같은 시크릿 파일 보관 시 디스크 암호화
- 화면 미사용 시 잠금 (shoulder surfing 방지)
- 비번을 다른 서비스와 공유 X

## Context

건축구조안전 모니터링 업무(관리번호 부여 → 설계도서 배포 → 검토서 수집 → 보완 반복)를 현재 엑셀 기반 수작업에서 **웹 기반 통합 시스템**으로 전환.

- 사용자: 팀장 1 + 총괄간사 1 + 간사 5 + 검토위원 50 ≈ **약 60명**
- 핵심 데이터: 통합관리대장 (102열, 3,401건 적재 완료)

---

## 기술 스택

| 계층 | 스택 |
|---|---|
| Frontend | Next.js 16 (App Router) + TypeScript + Tailwind + shadcn/ui |
| Backend | FastAPI + SQLAlchemy + Alembic + Pydantic v2 |
| DB | PostgreSQL 17 (Supabase Seoul) |
| Storage | AWS S3 (검토서 파일) |
| 인증 | JWT + 카카오 OAuth2 |
| 알림 | 카카오톡 친구 메시지 API + 나에게 보내기 |
| 배포 | Frontend → Vercel / Backend → Render |

---

## 구현 진행 현황

### ✅ Stage 1: 기반 구축 — 완료

- [x] **1-1** PostgreSQL 스키마 + Alembic 마이그레이션
  - 10개 테이블: users, reviewers, buildings, review_stages, inquiries, inappropriate_notes, notification_logs, announcements, announcement_comments, audit_logs
- [x] **1-2** JWT 인증 + RBAC (4개 역할)
- [x] **1-3** 통합관리대장 엑셀 → DB import 엔진 (`engines/ledger_import_unified.py`)
- [x] **1-4** DB → 엑셀 export (`engines/ledger_export.py`)
- [x] **1-5** 사용자 관리 CRUD + 엑셀 일괄 등록 (`/admin`)
- [ ] **1-6** 간사용 엑셀 입력 유틸리티 (Python CLI) — **미구현** (실무상 불필요 판단)

### ✅ Stage 2: 핵심 루프 — 완료

- [x] **2-1** 관리번호 조회 + 대장 그리드 (`/buildings`)
- [x] **2-2** 검토위원 배정 UI (엑셀 일괄 + 수동)
- [x] **2-3** 간사용 엑셀 업로드
- [x] **2-4** 카카오톡 알림 연동 (OAuth + 친구 메시지 + 나에게 보내기)
- [x] **2-5** 검토위원 "내 검토 대상" 페이지 (`/my-reviews`)

### ✅ Stage 3: 검토서 업로드 — 완료

- [x] **3-1** 검토서 업로드 API + UI (미리보기 → 확인 → 업로드 2단계)
- [x] **3-2** 유효성 검증 (파일명/관리번호/검토자명/단계별 차수 라벨)
- [x] **3-3** S3 업로드 (날짜/단계별 prefix, 재업로드 시 이전 파일 자동 삭제)
- [x] **3-4** 검토서 내용 자동 추출 (H4 결과 / F11 주구조 / F12 내진등급 / F13 도면작성자 자격 / G81~ 부적합유형 등)
- [x] **3-5** 대장 그리드에 단계별 상태 반영

### ⏸ Stage 4: 반복 패턴 + 운영 — 일부 완료

- [x] **4-1** 단계 상태머신 (`phase_machine.py`, PHASE_SEQUENCE에 `assigned` 추가됨)
- [x] **4-2** 단계별 동적 컬럼 (건물 상세 페이지 타임라인)
- [x] **4-3** 감사 로그 (audit_logs)
- [x] **4-4** 엑셀 export (DB → 통합관리대장 형식)
- [x] **4-5** 검토서 미제출 사유 입력 → 문의사항으로 확장 (`/inquiries`)

### ✅ 추가 구현 완료

**카카오 알림**
- [x] 카카오 디벨로퍼스 권한 검수 통과 (2026-04-17)
- [x] Scope 자동 체크 + 재동의 리다이렉트
- [x] 친구 매칭 페이지 (`/admin`에 통합)
- [x] 본인 발송 시 "나에게 보내기" API 자동 분기
- [x] pair 20건/일 제한 자체 모니터링

**부적합 대상 검토**
- [x] 검토서 업로드 시 "부적정 사례 검토 필요" 체크박스
- [x] `/inappropriate-review` 페이지 (간사 이상)
- [x] 판정 4단계 (확정-심각 / 확정-단순 / 대기 / 제외)
- [x] 간사진 의견 다중 작성 (작성자/시각 기록)
- [x] 지적단계 표시 (예비검토/보완검토 N차)

**공지사항**
- [x] 게시판 (목록/상세/작성/수정/삭제)
- [x] 댓글 기능
- [x] 대시보드 상단 위젯 (공지사항 + 카톡 알림 최신 5건)

**대시보드**
- [x] 개인 현황 (배정/제출검토서/연면적/1000㎡↑/고위험/검토대상/경과일수)
- [x] 전체 현황 (미배정/배정완료/검토서대기/검토진행중/완료)
- [x] 위원별 현황 테이블 (간사 이상)

**기타**
- [x] Button 컴포넌트 인터랙션 강화 (loading prop + 스피너)
- [x] 화면폭 반응형 (뷰포트 90%)
- [x] 간사 이상이 단계 수동 수정 가능 (건물 상세)
- [x] 문의사항 작성 권한 — "담당 건물" 기준 (역할 무관)

---

## 아직 남은 작업 (TODO)

### 🔴 운영 시작 전 필수 (사람-손, 2026-04-18 시점)

- [ ] **운영 dry-run** — 테스트 계정 2~3개로 end-to-end 흐름 검증
  - 절차: [.doc/operational-dry-run.md](./operational-dry-run.md)
  - 검증: 등록 → 자동 발송 → 카카오 수신 → 비번 셋팅 → 카카오 연동 → 동의 진단 → 검토위원 화면 확인
- [ ] **AWS IAM 기존 키 `AKIAZZPZKADQH5MH5YMY` Deactivate** (검증 후 Delete)
- [ ] **"ksea" 잔존 계정 3명 비번 초기화** — `/admin`에서 "초대 발송" 또는 "PW초기화"
- [ ] **카카오 콘솔 friends 동의항목 '선택 동의' 변경**
- [ ] **`.env.example` 갱신** — `CORS_ORIGINS`, `FRONTEND_BASE_URL`, `KAKAO_CLIENT_SECRET` 누락 항목 추가
- [ ] **검토위원 50명 실제 온보딩**
  - `/admin`에서 엑셀 일괄 등록 (자동 발송 ON 권장)
  - 카카오 매칭 사용자: 자동 발송 → 사용자가 비번 셋팅 + 카카오 연동
  - 미매칭 사용자: 수동 전달용 setup_url을 SMS/이메일로 전달
  - 50명 등록 후 `python -m scripts.backfill_reviewer_id --include-all-roles --apply --create-missing-reviewer`
  - `/admin`에서 카카오 친구 매칭 (선택)
  - "비번 미설정자만 보기" 토글로 미설정자 식별 → 재발송

### 🟡 운영 시작 후 1주 내

- [ ] **`/reset-password` 통합** — D 토큰 흐름으로 단계적 통합, `initial_password` 응답 단계적 제거
- [ ] **자동 리마인더 정책 결정** — 접수 후 N일 경과 미설정자/검토 미제출자 자동 알림
- [ ] **purge cron 외부 scheduler 이동** — 멀티워커 중복 실행 방지 (Render cron job 등)
- [ ] **검토위원 미설정자 일괄 재발송 단축 액션 (UI)** — 현재는 체크박스+일괄, "필터 결과 모두 선택" 단축 버튼

### 🟢 안정화 단계 (1주~1개월)

#### 보안 강화
- [ ] **OAuth state 1회성 nonce 저장소** (현재 JWT 서명만, replay window 10분)
- [ ] **Refresh token 도입** (access 15분 + refresh 14일, `/api/auth/refresh`)
- [ ] **HttpOnly cookie 전환** (현재 localStorage, cross-site cookie SameSite=None;Secure 고려)
- [ ] **카카오 토큰 컬럼 암호화 또는 KMS** (현재 평문, XSS/DB 유출 시 피해 큼)
- [ ] **must_change_password 전면 가드** — `/api/auth/change-password` 외 차단

#### 운영 가시성
- [ ] **Sentry 또는 외부 오류 추적 풀도입** (현재 Render 로그 + key=value 평문)
- [ ] **카카오 발송 일일 카운트 모니터링 대시보드**

#### 코드 구조 (외부 리뷰 종합)
- [ ] **`reviews.py` (1,043줄) → `services/` 레이어 분리**
- [ ] **`buildings.py` (700+줄) → 동일 분리**
- [ ] **프론트 `admin/page.tsx` (1,385줄, useState 31개) → 섹션별 분리**
- [ ] **React Query 도입** — 수동 fetch 너무 많음, 점진 도입
- [ ] **phase/result 정의 중앙화** — 백엔드 phase_machine + reviews.py 맵 + 프론트 PHASE_LABELS + PRD 분산. 단일 소스
- [ ] **alert/confirm → shadcn Dialog/Toast 통합** — 운영툴은 사용자 실수 방지·액션 추적성 중요

#### 안정성 (외부 리뷰)
- [ ] **async/sync 혼용 정리** — async 라우트에서 동기 SQLAlchemy/openpyxl/파일 I/O. event loop block 가능. (a) DB/엑셀 라우트는 def로, 또는 (b) AsyncSession + 백그라운드 워커
- [ ] **purge cron 외부 scheduler** — DB advisory lock 또는 외부 cron (현재 lifespan task는 멀티워커 중복)

#### 기능
- [ ] **최종 completed 판정용 별도 엑셀 업로드 기능** — 현재 `phase_machine`에서 자동 completed 비활성화됨
- [ ] **검토서 양식 셀 위치 재확인** (내진등급 F12, 도면작성자 자격 F13)
- [ ] **도서배포(`doc_distributed_at`) 워크플로** (현재 `doc_received_at`만 기록)
- [ ] **검토서 버전 히스토리** (현재 재업로드 시 덮어쓰기)
- [ ] **검토위원별 성과 리포트 export**
- [ ] **알림 템플릿 관리 UI** (현재 하드코딩, DB 기반 관리)
- [ ] **모바일 반응형 최적화** (현재 태블릿 이상)

#### 확장성 (외부 리뷰 4)
- [ ] **엑셀 검증/추출 worker 분리** — 대용량 처리 안정성
- [ ] **presigned upload 도입** — 대용량 업로드 증가 시 서버 경유 회피

#### 데이터 정합성
- [ ] **미사용 필드 정리** — `buildings.drawing_creator_firm/name`, `high_risk_type`
- [ ] **인덱스 최적화** — `current_phase`, `assigned_reviewer_name` 등 (3,401건이라 당장 부담 없음)

### 문서화
- [ ] `kakao-message-setup.md` 최신화 (검수 통과 반영)
- [ ] `kakao-permission-review-purpose.md` 보관/삭제 결정
- [ ] API 엔드포인트 전체 목록 문서 (현재 `/openapi.json`)

---

## 완료된 마일스톤

| 시점 | 마일스톤 |
|---|---|
| 2026-04 초 | Stage 1 완료 (DB/인증/대장 import·export) |
| 2026-04 중 | Stage 2~3 완료 (검토서 업로드/검증/추출 + 카카오 알림) |
| 2026-04-17 | **카카오 디벨로퍼스 친구/메시지 권한 검수 통과** |
| 2026-04-17 | 부적합 검토·공지사항·대시보드 재구성 |
| 2026-04-18 | **보안 하드닝 P0/P0.5 + P1 D + N5 + 외부 리뷰 4종 잔여까지 완료. 94 테스트 PASS** |
| 2026-04-18 | 운영 문서 5종 + 카카오 초대 링크 비번 셋업 + 비번 미설정자 UI + 사용자 본인 동의 안내 배너 |
| 2026-04-18 | 외부 리뷰 quick win — get_current_user 401 보강 + 업로드 stream 메모리 절약 |

---

## 2026-04-18 세션 누적 변경 (보안·UX 묶음 31 커밋, 94 테스트 PASS)

| 묶음 | 핵심 |
|---|---|
| P0 (B/C/G/H) | 카카오 토큰 봉인, REVIEWER 권한 강화, reviews.py hotfix, pytest 인프라 |
| P0.5 N1+N2 | reviewer_id 백필 스크립트, my-* OR 조건 정리 |
| P0.5 N3 | reviews.py 잔여 권한, Inquiry.submitter_id |
| P0.5 N4 | audit/kakao/announcements/discussions 등 8개 라우터 권한 sweep |
| P0.5 N6+N8 | GitHub Actions CI, X-Request-ID 미들웨어, 키-값 로깅 |
| P1 D 3단계 | 카카오 초대 링크 비번 셋업 + admin UI + 일괄 발송 |
| P1 N5 | respx 카카오 mock 통합 테스트 |
| 운영 이슈 fix | reviewer_id 백필 확장 + inquiry submitter_id 백필 + 본인 데이터 노출 복구 |
| 비번 셋업 상태 UI | /admin "비번 미설정 N명" 컬럼 + 미설정자 필터 |
| 카카오 동의 컬럼 | /admin 동의 OK/부족/미확인 캐시 + "동의 안내" 발송 버튼 |
| 사용자 본인 배너 | dashboard layout 전역 배너 (미연동/동의부족) + "카카오 연동하기" 버튼 |
| 외부 리뷰 잔여 1~3 | 파일 업로드 크기 제한 (8개 엔드포인트), S3 lru_cache, seed.py 환경 가드, 토큰 detail 마스킹, 401 race condition, docker-compose 가드, _registered_names_cache 데드 변수 제거 |
| 외부 리뷰 4 quick win | get_current_user int(sub) 예외 401 보강 + 회귀 테스트 2개, 업로드 stream 개선 (stream_upload_to_tempfile으로 메모리 2중 사용 회피) |

---

## 발생 가능 시나리오 및 대응 (기존)

### 시나리오 1: 엑셀과 DB 데이터 불일치
엑셀 업로드 시 diff 비교 화면 제공 (미리보기 → 확인 → 업로드). ✅ 구현됨.

### 시나리오 2: 검토서 유효성 검증 실패
구체적 오류 메시지 반환. ✅ 구현됨.

### 시나리오 3: 카카오톡 알림 발송 실패
`notification_logs`에 기록, 토큰 만료 자동 갱신, pair 20건/일 자체 체크. ✅ 구현됨.

### 시나리오 4: 검토위원 50명 동시 접속
S3 pre-signed URL 직접 업로드 — **현재는 서버 경유 업로드** (3,401건 기준 충분, 추후 최적화 여지).

### 시나리오 5: 엑셀 양식 변경
열 매핑은 `engines/column_mapping.py`에서 관리. 변경 시 이 파일만 수정. ✅

### 시나리오 6: 보완 검토 5차 이상
`review_stages` 1:N 구조. 현재 코드는 supplement_1~5 enum 제한 — 6차 이상 필요 시 enum 확장 필요.

### 시나리오 7: 예비도서 재접수 (2번 오는 경우)
간사가 건물 상세 페이지에서 **단계 수동 수정** 기능으로 처리 가능. ✅ 구현됨.

---

## 참고 문서

- `.doc/PRD.md` — 제품 요구사항
- `.doc/database.md` — DB 스키마 상세 (최신)
- `.doc/kakao-message-setup.md` — 카카오 API 도입 가이드
- `.doc/kakao-permission-review-purpose.md` — 검수 신청 시 제출 문서 (통과됨)
- `.doc/excel_valid.md` — 엑셀 유효성 규칙
- `.doc/관리대장 샘플.xlsx` — 통합관리대장 양식
- `.doc/2025-0005.xlsm` — 검토서 양식 샘플
