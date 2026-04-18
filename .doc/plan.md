# 건축구조안전 모니터링 시스템 — 구현 계획서

> 최종 갱신: 2026-04-19
> 진행 상황: Stage 1~4 완료 + 운영 UX/기능 확장 묶음 완료. **113 테스트 PASS**.
> **운영 투입 중 — 기능 확장과 안정화 병행 단계.**

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
- REVIEWER 권한: `reviewer_id` 매칭만 (이름 X), 라우터 sweep 전 라우터 적용
- 파일 업로드 20MB 크기 제한 + stream tempfile, SVG 인라인 차단(XSS)
- 카카오 토큰 detail 응답 마스킹, 외부 응답 본문 비노출
- request middleware + key=value 로깅 + X-Request-ID
- CORS env화, must_change_password, 401 race 방지
- 리마인드 발송 CLI 스크립트에도 HTTP와 동일한 role 검증

### 🔴 즉시 보강 권장 (운영 시작 전 또는 1주 내)

1. **프론트 XSS 점검 + CSP 헤더 추가** ⭐ 1순위
   - `dangerouslySetInnerHTML` 사용처 grep + 모두 점검
   - Next.js middleware로 CSP 헤더 (script-src 'self' 등)
2. **관리자 계정 운영 강화**
   - 운영자 7명 비번 재점검 + 재사용 금지 안내
   - 관리자 로그인 실패 로그 모니터링
3. **DB 접근 최소화**
   - Supabase DB 비번 재로테이션 주기화 (분기별)
   - 최소권한 DB 계정 (앱용 vs admin용 분리)
4. **카카오 토큰 컬럼 암호화 설계 착수**
5. **OAuth state 1회성 nonce 저장소 검토**

### 🟢 장기 방어 (안정화)

1. HttpOnly cookie 전환
2. 카카오 토큰 KMS 또는 앱 계층 암호화
3. 관리자 MFA
4. 파일 처리 worker 분리
5. 보안 헤더 전수 정리 (CSP / HSTS / X-Frame-Options / Permissions-Policy)

---

## Context

건축구조안전 모니터링 업무(관리번호 부여 → 설계도서 배포 → 검토서 수집 → 보완 반복)를 웹 기반 통합 시스템으로 전환.

- 사용자: 팀장 1 + 총괄간사 1 + 간사 5 + 검토위원 50 ≈ **약 60명**
- 핵심 데이터: 통합관리대장 3,401건 적재 완료

---

## 기술 스택

| 계층 | 스택 |
|---|---|
| Frontend | Next.js 16 (App Router) + TypeScript + Tailwind + shadcn/ui |
| Backend | FastAPI + SQLAlchemy + Alembic + Pydantic v2 |
| DB | PostgreSQL 17 (Supabase Seoul) |
| Storage | AWS S3 |
| 인증 | JWT + 카카오 OAuth2 |
| 알림 | 카카오톡 친구 메시지 API + 나에게 보내기 |
| 배포 | Frontend → Vercel / Backend → Render (Pre-Deploy `alembic upgrade head`) |

---

## 구현 진행 현황

### ✅ Stage 1~4 — 완료
DB 스키마, JWT/RBAC, 통합관리대장 import/export, 관리번호 조회 + 대장 그리드, 검토위원 배정 UI, 카카오 알림 연동, 검토서 업로드 + 유효성 검증 + 자동 추출, 단계 상태머신, 감사 로그, 문의사항.

### ✅ 운영 UX/기능 확장 (2026-04-18~19)

**문의사항**
- 단계 변경 인라인 다이얼로그 + 자동 COMPLETED 처리
- InquiryStatus.NEXT_PHASE 제거(`completed`로 병합)
- 답변 완료 시 작성자에게 카톡 자동 알림 (`inquiry_notify`)
- 처리 컬럼 간소화(관리원문의 / 답변저장) + 3-way 확인 다이얼로그(완료 / 단계변경 / 취소)
- 질문·답변 첨부파일 + 이미지 인라인 렌더

**검토서 관리**
- `report_due_date` 필드 추가 (기본 접수일+14일, 카톡 알림에 포함)
- 검토서 파일 개별/그룹 일괄 삭제, 다운로드 후 삭제 (감사 로그 기록)
- 업로드 시점의 `file_size=len(content)` 미정의 변수 버그 수정

**리마인드 알림**
- `services/review_reminder.py` + `POST /api/notifications/review-reminder`
- Trigger: `within_n_days`(기본 N=3, D-N 이내 + 초과), `overdue`, `d_minus_1`(cron용)
- 리마인드 페이지 `/reminders` (팀장/총괄간사) — 체크박스 기반 선택 발송, 오늘 발송 횟수 표시, 미매칭 검토위원 자동 제외
- `scripts/send_review_reminders.py` cron 뼈대 (역할 검증 포함)

**대시보드 (관리자)**
- 6개 API `Promise.all` 병렬 + 진행률 바
- 상단 2박스 레이아웃(단계별 집계 / 현황) — 외곽 + 내부 총 7카드 높이 균일
- 단계별 집계 플로우: 총 등록건 | 예비검토 → 보완검토 → 최종 완료 (D-N 라벨)
- 검토위원별 일정관리 테이블: 활성 사용자 전원, 미제출·D-3~D-day·초과 버킷 + 일정 준수율 막대그래프(%)
- 검토위원별 통계(연면적/1000㎡↑/고위험 등)는 `/statistics` 분리 (간사 접근 가능, REVIEWER 차단)
- 업로드된 검토서 카드 → 검토서 관리 바로가기(팀장/총괄간사만 클릭)
- 문의사항 카드 → 문의사항 페이지 바로가기
- 내 담당 현황 6버킷(미제출/D-3/D-2/D-1/D-day/초과)

**공지사항 / 토론방**
- 본문 + 댓글 첨부 통합 지원
- content_type 저장 + presigned `download_url` 응답 포함
- 공통 `AttachmentItem` 컴포넌트(이미지 인라인, SVG 제외, 다운로드/삭제)

**통합관리대장**
- 업로드 권한 총괄간사로 축소 (감사 로그 기록)
- 신규 사용자 등록 시 Reviewer 자동 생성 + 배정 건물 자동 연결 (`services/reviewer_link`)
- 동명이인이면 자동 연결 스킵
- 통합관리대장 파싱 성능 / DB 인덱스 3종(current_phase / final_result / report_submitted_at) 추가

**브랜딩 / 보안**
- KSEA 로고 홈버튼 + favicon, 브라우저 타이틀 "건축구조안전 모니터링"
- `.doc/*.xlsx|xls|xlsm|xlsb` gitignore 처리 (추적 해제, 로컬 유지)

### DB 테이블 (18종)
`users`, `reviewers`, `buildings`, `review_stages`, `inquiries`, `inquiry_attachments`, `inappropriate_notes`, `notification_logs`, `announcements`, `announcement_comments`, `announcement_attachments`, `announcement_comment_attachments`, `discussions`, `discussion_comments`, `discussion_attachments`, `discussion_comment_attachments`, `audit_logs`, `kakao_link_sessions`, `password_setup_tokens`

---

## 남은 작업 (TODO)

### 🔴 운영 시작 전 필수

- [ ] **운영 dry-run** — 테스트 계정 2~3개로 end-to-end 흐름 검증
- [ ] **AWS IAM 기존 키 `AKIAZZPZKADQH5MH5YMY` Deactivate**
- [ ] **"ksea" 잔존 계정 3명 비번 초기화**
- [ ] **카카오 콘솔 friends 동의항목 '선택 동의' 변경**
- [ ] **`.env.example` 갱신** (`CORS_ORIGINS`, `FRONTEND_BASE_URL`, `KAKAO_CLIENT_SECRET` 누락)
- [ ] **검토위원 50명 온보딩** (등록 자동 Reviewer 연결 적용됨 — 엑셀 import 후 bulk invite + 카카오 매칭)
- [ ] **S3 리전 시드니 → 서울 이전 검토** (대용량 파일 레이턴시 개선)
- [ ] **과거 저장소 히스토리의 `.doc/*.xlsx` 제거 여부 결정** (git filter-repo + force push)

### 🟡 운영 시작 후 1주 내

- [ ] **자동 리마인더 Render cron 등록** — `scripts/send_review_reminders.py` 활용 (D-1 / overdue)
- [ ] **`/reset-password` 통합** (D 토큰 흐름 통합 + initial_password 응답 단계적 제거)
- [ ] **검토위원 미설정자 일괄 재발송 단축 액션 (UI)**
- [ ] **카카오 토큰 암호화 설계 착수**

### 🟢 안정화 단계 (1주~1개월)

**보안**
- [ ] OAuth state 1회성 nonce 저장소
- [ ] Refresh token 도입
- [ ] HttpOnly cookie 전환
- [ ] 관리자 MFA
- [ ] CSP / HSTS / 보안 헤더 전수 정리

**운영 가시성**
- [ ] Sentry 또는 외부 오류 추적 도입
- [ ] 카카오 발송 일일 카운트 모니터링

**코드 구조**
- [ ] `reviews.py` / `buildings.py` 서비스 레이어 분리
- [ ] 프론트 `admin/page.tsx` 섹션 분리
- [ ] React Query 도입
- [ ] phase/result 정의 중앙화
- [ ] alert/confirm → shadcn Dialog/Toast 통합

**기능**
- [ ] 최종 completed 판정용 별도 엑셀 업로드 (5분류 포함)
- [ ] 도서배포(`doc_distributed_at`) 워크플로
- [ ] 검토서 버전 히스토리
- [ ] 검토위원별 성과 리포트 export
- [ ] 알림 템플릿 관리 UI
- [ ] 모바일 반응형 최적화

**데이터 정합성**
- [ ] 미사용 필드 정리 (`buildings.drawing_creator_firm/name`, `high_risk_type`)
- [ ] 문의 알림 sender_id 추적(현재 전역 reminder count만)

### 문서화
- [ ] `kakao-message-setup.md` 최신화 (검수 통과 반영)
- [ ] API 엔드포인트 전체 목록 문서

---

## 완료된 마일스톤

| 시점 | 마일스톤 |
|---|---|
| 2026-04 초 | Stage 1 완료 (DB/인증/대장 import·export) |
| 2026-04 중 | Stage 2~3 완료 (검토서 업로드/검증/추출 + 카카오 알림) |
| 2026-04-17 | **카카오 디벨로퍼스 친구/메시지 권한 검수 통과** |
| 2026-04-17 | 부적합 검토·공지사항·대시보드 재구성 |
| 2026-04-18 | 보안 하드닝 P0/P0.5 + P1 D + N5 + 외부 리뷰 4종 완료 (94 테스트) |
| 2026-04-18 | 운영 문서 5종 + 카카오 초대 링크 비번 셋업 + 비번 미설정자 UI |
| 2026-04-19 | **운영 UX 확장** — 리마인드, 문의 첨부, 검토서 삭제, 대시보드 재구성, 자동 Reviewer 연결, 공지·토론 첨부 인라인 (113 테스트) |

---

## 발생 가능 시나리오 및 대응

### 시나리오 1: 엑셀과 DB 데이터 불일치
엑셀 업로드 시 diff 비교 화면 제공 (미리보기 → 확인 → 업로드). ✅

### 시나리오 2: 검토서 유효성 검증 실패
구체적 오류 메시지 반환. ✅

### 시나리오 3: 카카오톡 알림 발송 실패
`notification_logs`에 사유별 기록, 토큰 만료 자동 갱신, pair 20건/일 자체 체크. ✅

### 시나리오 4: 검토위원 50명 동시 접속
S3 pre-signed URL 직접 업로드 — **현재는 서버 경유** (3,401건 기준 충분).

### 시나리오 5: 엑셀 양식 변경
열 매핑 `engines/column_mapping.py` 에서 관리. ✅

### 시나리오 6: 보완 검토 5차 이상
`review_stages` 1:N 구조. 현재 enum `supplement_1~5` 제한 — 6차 이상 필요 시 enum 확장.

### 시나리오 7: 예비도서 재접수
간사가 건물 상세 페이지에서 단계 수동 수정. ✅

### 시나리오 8: 뒤늦게 가입하는 검토위원
사용자 등록 시 `services/reviewer_link.ensure_reviewer_link()` 자동 호출로 `Reviewer` 생성 + 담당 건물 자동 연결. 동명이인은 스킵 후 운영자 수동 확인. ✅

### 시나리오 9: 잘못 업로드된 검토서
검토서 관리 페이지에서 개별/그룹 일괄 삭제 가능. S3 객체 제거 + `review_stages.s3_file_key=NULL` (검토 결과 이력 보존). ✅

---

## 참고 문서

- `.doc/PRD.md` — 제품 요구사항
- `.doc/database.md` — DB 스키마 상세 (최신)
- `.doc/kakao-message-setup.md` — 카카오 API 도입 가이드
- `.doc/excel_valid.md` — 엑셀 유효성 규칙
