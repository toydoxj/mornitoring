# 건축구조안전 모니터링 시스템 — 구현 계획서

> 최종 갱신: 2026-04-18
> 진행 상황: Stage 1~4 거의 완료. 보안 P0/P0.5 + P1 D 완료. 운영 투입 직전.

## 운영 문서 (50명 온보딩 직전 참조)

- [first-onboarding-checklist.md](./first-onboarding-checklist.md) — 검토위원 50명 일괄 온보딩 단계별 체크리스트
- [operator-onboarding-manual.md](./operator-onboarding-manual.md) — 운영자(팀장/간사) 사용자 등록·발송 매뉴얼
- [troubleshooting.md](./troubleshooting.md) — 자주 발생할 만한 이슈 대응
- [operational-dry-run.md](./operational-dry-run.md) — 50명 온보딩 전 테스트 계정 2~3개로 end-to-end 점검
- [operations-policy.md](./operations-policy.md) — 권한/토큰/카카오/데이터 정합성 정책 요약

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

### 우선순위 높음
- [ ] **검토서 양식 셀 위치 재확인**
  - F9/H9 도면작성자 소속/성명 — **현재 미사용으로 삭제됨, 자격(F13)만 유지**
  - 실제 양식의 내진등급 셀이 F12가 맞는지 최종 확인
- [ ] **최종 완료(completed) 판정용 별도 엑셀 업로드 기능**
  - 현재 `phase_machine`에서 자동 completed 처리 비활성화됨
  - 별도 엑셀로 최종 판정 지정 예정 (사용자 요구)
- [ ] **검토위원 50명 실제 온보딩**
  - 사용자 계정 생성 (엑셀 일괄등록)
  - 카카오 로그인 + 동의 + 카카오톡 친구 관계 확보
  - 간사가 `/admin`에서 친구 매칭
- [ ] **프로덕션 배포 환경 최종 점검**
  - 마이그레이션 자동 적용 확인 (Render)
  - 환경변수/시크릿 점검
  - AWS S3 운영 버킷 / IAM 정책

### 우선순위 중간
- [ ] **도서배포(`doc_distributed_at`) 워크플로**
  - 현재 `doc_received_at`만 기록되고 있음
  - 간사가 검토위원에게 도서 배포한 날짜를 별도 기록하는 UI/API 필요할지 검토
- [ ] **검토 마감일 알림 (자동 리마인더)**
  - 접수 후 N일 경과 시 자동 알림 (카카오 메시지 API 자동 발송은 검수 정책상 별도 검토 필요)
  - 현재는 수동 발송만 구현
- [ ] **검토서 버전 히스토리**
  - 현재 같은 단계 재업로드 시 기존 파일/데이터 덮어쓰기
  - 이전 버전 스냅샷 보존 필요한지 검토 (audit_logs에 업로드 행위만 기록 중)
- [ ] **인덱스 최적화**
  - `buildings.current_phase`, `buildings.assigned_reviewer_name` 등 빈번한 필터 대상 인덱스 검토
  - 3,401건 규모에서는 문제 없으나 확장 대비

### 우선순위 낮음
- [ ] **미사용 필드 정리**
  - `buildings.drawing_creator_firm`, `drawing_creator_name` (사용자가 제거 요청, DB 컬럼은 아직 존재)
  - `buildings.high_risk_type` (전부 NULL, is_special/high_rise/multi_use 3개 불리언으로 대체됨)
- [ ] **검토위원별 성과 리포트 export**
- [ ] **알림 템플릿 관리 UI**
  - 현재 프론트에 하드코딩된 템플릿 3종 (검토 요청/도서 접수/리마인더)
  - 팀장이 템플릿 편집하게 하려면 DB 기반 관리 필요
- [ ] **백엔드 단위 테스트 / E2E 테스트 작성**
- [ ] **모바일 반응형 최적화** (현재 태블릿 이상 전제)

### 문서화
- [ ] `kakao-message-setup.md` 최신화 (검수 통과 반영)
- [ ] `kakao-permission-review-purpose.md`는 보관/삭제 결정
- [ ] API 엔드포인트 전체 목록 문서 (현재 `/openapi.json`으로 확인 가능)
- [ ] 운영 매뉴얼 (간사/팀장용 사용 가이드)

---

## 완료된 마일스톤

| 시점 | 마일스톤 |
|---|---|
| 2026-04 초 | Stage 1 완료 (DB/인증/대장 import·export) |
| 2026-04 중 | Stage 2~3 완료 (검토서 업로드/검증/추출 + 카카오 알림) |
| 2026-04-17 | **카카오 디벨로퍼스 친구/메시지 권한 검수 통과** |
| 2026-04-17 | 부적합 검토·공지사항·대시보드 재구성 |

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
