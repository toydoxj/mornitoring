# 데이터베이스 구조

Supabase PostgreSQL 17 (Seoul) | 마지막 갱신: 2026-04-19

## 테이블 요약

| 테이블 | 건수 | 용도 |
|---|---|---|
| `users` | 9 | 사용자 (4개 역할) |
| `reviewers` | 7 | 검토위원 상세 (group_no, specialty) |
| `buildings` | 3,401 | 통합관리대장 건축물 |
| `review_stages` | 983 | 건물별 단계 (예비/보완1~5차) |
| `inquiries` | 11 | 검토 문의사항 |
| `inquiry_attachments` | 0 | 문의 질문·답변 첨부 (kind=question/reply) |
| `inappropriate_notes` | 2 | 부적합 판정 간사진 의견 (다중) |
| `notification_logs` | 29 | 카카오톡 알림 발송 이력 (reminder 포함) |
| `announcements` | 1 | 공지사항 |
| `announcement_comments` | 0 | 공지사항 댓글 |
| `announcement_attachments` | 1 | 공지사항 본문 첨부 |
| `announcement_comment_attachments` | 0 | 공지사항 댓글 첨부 |
| `discussions` | 3 | 토론방 게시글 |
| `discussion_comments` | 1 | 토론방 댓글 |
| `discussion_attachments` | 2 | 토론방 본문 첨부 |
| `discussion_comment_attachments` | 1 | 토론방 댓글 첨부 |
| `audit_logs` | 29 | 감사 로그 |
| `kakao_link_sessions` | 0 | 카카오 OAuth 1회성 link 세션 |
| `password_setup_tokens` | 2 | 비번 셋업 토큰 (sha256 해시) |

---

## 테이블 상세

### users — 사용자
| 컬럼 | 타입 | 필수 | 설명 |
|---|---|---|---|
| id | integer (PK) | O | 자동증가 |
| name | varchar(50) | O | 이름 |
| email | varchar(100) (UNIQUE) | O | 이메일 (로그인ID) |
| role | varchar(15) | O | `team_leader` / `chief_secretary` / `secretary` / `reviewer` |
| phone | varchar(20) | | 전화번호 |
| kakao_id | varchar(100) | | 카카오 사용자 ID (OAuth 완료 플래그) |
| kakao_uuid | varchar(100) | | 친구 매칭 UUID (메시지 발송 대상 식별) |
| kakao_access_token | varchar(500) | | 카카오 액세스 토큰 (평문 — 보안 개선 예정) |
| kakao_refresh_token | varchar(500) | | 카카오 리프레시 토큰 |
| kakao_token_expires_at | timestamp | | 액세스 토큰 만료일 (자동 갱신 기준) |
| kakao_scopes_checked_at | timestamp | | 동의 상태 캐시 시각 |
| kakao_scopes_ok | boolean | | friends/talk_message 동의 완료 여부 |
| password_hash | varchar(200) | | bcrypt 해시 |
| must_change_password | boolean | O | 최초 로그인 시 비밀번호 변경 필요 (기본: false) |
| is_active | boolean | O | 활성 상태 |
| created_at / updated_at | timestamp | O | |

### reviewers — 검토위원 상세
| 컬럼 | 타입 | 필수 | 설명 |
|---|---|---|---|
| id | integer (PK) | O | |
| user_id | integer (FK→users, UNIQUE) | O | |
| group_no | varchar(10) | | 조 번호 |
| specialty | varchar(100) | | 전문 분야 |

> 사용자 등록 시 `services/reviewer_link.ensure_reviewer_link()` 가 자동으로 Reviewer 행 생성 + `buildings.assigned_reviewer_name` 이 일치하는 건물의 `reviewer_id` 를 채움. 동명이인이면 자동 연결 스킵.

### buildings — 건축물 (통합관리대장)
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer (PK) | |
| mgmt_no | varchar(20) UNIQUE INDEX | 관리번호 (예: 2025-0001) |
| reviewer_id | integer (FK→reviewers) | 검토위원 연결 |
| assigned_reviewer_name | varchar(50) | 배정 엑셀 기입 검토위원 이름 |
| building_type | varchar(50) | 건축구분 |
| sido / sigungu / beopjeongdong | varchar | 시도/시군구/법정동 |
| land_type | varchar(20) | 대지구분 |
| main_lot_no / sub_lot_no / special_lot_no | varchar | 본번/부번/특수지번 |
| building_name | varchar(200) | 건물명 |
| main_structure / other_structure | varchar | 주구조/기타구조 |
| main_usage / other_usage | varchar | 주용도/기타용도 |
| gross_area | numeric(12,2) | 연면적(㎡) |
| height | numeric(8,2) | 높이(m) |
| floors_above / floors_below | integer | 지상층수/지하층수 |
| is_special_structure | boolean | 특수구조 |
| is_high_rise | boolean | 고층 |
| is_multi_use | boolean | 다중이용 |
| high_risk_type | varchar(100) | 고위험유형 (현재 미사용) |
| architect_firm / architect_name | varchar | 건축사 (소속/성명) |
| struct_eng_firm / struct_eng_name | varchar | 책임구조기술자 (소속/성명) |
| drawing_creator_qualification | varchar(30) | 도면작성자 자격 (건축사/건축구조기술사/기타) |
| drawing_creator_firm / drawing_creator_name | varchar | 미사용 (향후 제거 가능) |
| seismic_level | varchar(50) | 내진등급 (특/I/II) |
| detail_category1~9 | varchar(50) | 유형별상세검토 |
| related_tech_coop | boolean | 관계기술자 협력대상 여부 |
| drawing_creation | boolean | 관계기술자 도면작성 여부 |
| remarks | text | 비고 |
| current_phase | varchar(30) **[INDEX]** | 현재 단계 (아래 참조) |
| final_result | varchar(30) **[INDEX]** | 최종 판정결과 (5분류) |
| created_at / updated_at | timestamp | |

#### 단계 흐름 (`current_phase`)
```
(null 미배정) → assigned → doc_received → preliminary
  → supplement_1_received → supplement_1
  → ... → supplement_5_received → supplement_5
  → completed
```
| 값 | 한글 |
|---|---|
| `(null)` | 미배정 |
| `assigned` | 배정완료 |
| `doc_received` | 예비도서 접수 |
| `preliminary` | 예비검토서 제출 |
| `supplement_N_received` | N차 보완도서 접수 |
| `supplement_N` | N차 보완검토서 제출 |
| `completed` | 완료 |

#### 최종 판정 5분류 (`final_result`)
| 값 | 한글 |
|---|---|
| `pass` | 적합 |
| `pass_supplement` | 보완적합 |
| `fail` | 부적합 |
| `fail_no_response` | 부적합(미회신) |
| `excluded` | 대상제외 |

### review_stages — 검토 단계 (건물별 1:N)
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer (PK) | |
| building_id | integer (FK→buildings) | |
| phase | varchar(12) (enum) | `preliminary` / `supplement_1~5` |
| phase_order | integer | 0=예비, 1=1차, ... |
| doc_received_at | date | 도서접수일 |
| doc_distributed_at | date | 도서배포일 (미사용) |
| **report_due_date** | date | **검토서 요청 예정일 (리마인드 기준일, 기본 접수일+14일)** |
| report_submitted_at | date **[INDEX]** | 검토서 제출일 |
| reviewer_name | varchar(50) | 검토자 이름 |
| result | varchar(12) (enum) | `pass` / `simple_error` / `recalculate` |
| review_opinion | text | 검토의견 |
| defect_type_1~3 | varchar(100) | 부적합유형 |
| objection_filed | boolean | 이의신청 여부 (레거시) |
| objection_content / objection_reason | text | 이의신청 (레거시) |
| s3_file_key | varchar(500) | S3 검토서 파일 경로 |
| stage_remarks | text | 비고 |
| inappropriate_review_needed | boolean | 부적정 사례 검토 필요 체크 |
| inappropriate_decision | varchar(17) (enum) | `PENDING` / `CONFIRMED_SERIOUS` / `CONFIRMED_SIMPLE` / `EXCLUDED` |
| created_at / updated_at | timestamp | |

### inappropriate_notes — 부적합 판정 간사진 의견 (다중)
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer (PK) | |
| stage_id | integer (FK→review_stages ON DELETE CASCADE, INDEX) | |
| author_id | integer (FK→users) | |
| author_name | varchar(50) | 작성 시점 이름 스냅샷 |
| content | text | 의견 내용 |
| created_at | timestamp | |

### inquiries — 문의사항
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer (PK) | |
| building_id | integer (FK→buildings) | |
| mgmt_no | varchar(20) | 관리번호 스냅샷 |
| phase | varchar(30) | 문의 시점 단계 |
| submitter_id | integer (FK→users, INDEX) | 문의 작성자 (NULL 허용 — historical) |
| submitter_name | varchar(50) | 표시용 이름 |
| content | text | 문의 내용 |
| reply | text | 답변 |
| status | varchar(13) (enum) | `open` 접수 / `asking_agency` 관리원문의중 / `completed` 완료 |
| created_at / updated_at | timestamp | |

> 답변 완료 시 작성자에게 카카오톡 자동 알림 발송 (`services/inquiry_notify.py`). 단계 변경 시 inquiry.status 자동 COMPLETED 처리.

### inquiry_attachments — 문의 질문·답변 첨부
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer (PK) | |
| inquiry_id | integer (FK→inquiries ON DELETE CASCADE, INDEX) | |
| kind | varchar (enum) | `question` 문의 작성자 업로드 / `reply` 답변자 업로드 |
| filename | varchar(255) | |
| s3_key | varchar(500) | |
| file_size | integer | |
| content_type | varchar(100) | MIME (이미지 인라인 렌더 판별) |
| uploaded_by | integer (FK→users) | |
| created_at | timestamp | |

### notification_logs — 카카오톡 알림 발송 이력
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer (PK) | |
| recipient_id | integer (FK→users) | 수신자 (NULL 허용) |
| channel | varchar(20) | `kakao` 친구발송 / `kakao_memo` 나에게보내기 / `web` |
| template_type | varchar(50) | `doc_received` / `review_request` / `reminder` / `inquiry_reply` |
| title / message | varchar / text | |
| related_building_id | integer (FK→buildings) | 관련 건축물 (옵션) |
| is_sent | boolean | 발송 성공 여부 |
| sent_at | timestamp | 발송 시간 |
| retry_count | integer | |
| error_message | text | 실패 사유 |
| created_at | timestamp | |

### announcements / announcement_comments / announcement_attachments / announcement_comment_attachments — 공지사항 + 첨부

`announcements` — 본문 (title/content, 간사 이상 작성)
`announcement_comments` — 댓글 (모든 로그인 사용자)
`announcement_attachments` — 본문 첨부 (content_type 포함)
`announcement_comment_attachments` — 댓글 첨부 (content_type 포함)

모든 첨부 테이블은 `content_type`, `file_size`, `s3_key`, `uploaded_by` 공통 구조.

### discussions / discussion_comments / discussion_attachments / discussion_comment_attachments — 토론방 + 첨부

구조는 announcements 와 대칭. 작성/댓글/첨부 업로드 모든 로그인 사용자 허용(REVIEWER 포함).

### audit_logs — 감사 로그
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer (PK) | |
| user_id | integer (FK→users) | 실행자 |
| action | varchar(100) | `create` / `update` / `delete` / `upload` / `assign` / `inappropriate_decision` 등 |
| target_type | varchar(50) | `building` / `review_stage` / `review_file` / `user` / `ledger` / ... |
| target_id | integer | 대상 ID |
| before_data / after_data | jsonb | 변경 전/후 |
| ip_address | varchar(45) | |
| created_at | timestamp | |

### kakao_link_sessions — 카카오 OAuth 1회성 link 세션

카카오 토큰이 DB에 저장되기 전 단계. sha256 해시된 세션키 + 10분 TTL.

### password_setup_tokens — 비번 셋업 토큰

sha256 해시 저장. 1회성 소비. 만료 시 자동 purge.

---

## 테이블 관계

```
users ─┐
       ├─1:1─ reviewers ──1:N─ buildings ──1:N─ review_stages ─1:N─ inappropriate_notes
       │                         │                 │
       │                         ├─1:N─ inquiries ─1:N─ inquiry_attachments
       │                         └─1:N─ notification_logs
       │
       ├─1:N─ announcements ──1:N─ announcement_comments ─1:N─ announcement_comment_attachments
       │                       └──1:N─ announcement_attachments
       ├─1:N─ discussions ──1:N─ discussion_comments ─1:N─ discussion_comment_attachments
       │                     └──1:N─ discussion_attachments
       ├─1:N─ audit_logs
       ├─1:N─ kakao_link_sessions
       └─1:N─ password_setup_tokens
```

---

## Enum 정의

### 부적합 판정 (`review_stages.inappropriate_decision`)
| 값 | 한글 | 의미 |
|---|---|---|
| `PENDING` | 대기 | 판정 미진행 (기본값) |
| `CONFIRMED_SERIOUS` | 확정(심각) | 부적합 확정 — 심각한 사유 |
| `CONFIRMED_SIMPLE` | 확정(단순) | 부적합 확정 — 단순한 사유 |
| `EXCLUDED` | 제외 | 확정 후 추후 제외 |

### 검토결과 (`review_stages.result`)
| 값 | 한글 |
|---|---|
| `pass` | 적합 |
| `simple_error` | 단순오류 |
| `recalculate` | 재계산 |

### 문의사항 상태 (`inquiries.status`)
| 값 | 한글 |
|---|---|
| `open` | 접수 |
| `asking_agency` | 관리원문의중 |
| `completed` | 완료 (단계 변경 시 자동 포함) |

> `next_phase` 값은 2026-04-18 마이그레이션에서 `completed`로 병합되어 제거됨.

### 문의 첨부 종류 (`inquiry_attachments.kind`)
| 값 | 한글 | 업로드 주체 |
|---|---|---|
| `question` | 질문 첨부 | 문의 작성자 본인 |
| `reply` | 답변 첨부 | 간사 이상 |

---

## S3 저장 구조

```
reviews/                            # 검토서 파일 (단계·날짜별)
├── 예비검토/{YYYY-MM-DD}/...
├── 보완검토(1차)/{YYYY-MM-DD}/...
├── ...
└── 보완검토(5차)/

announcements/{announcement_id}/
├── {uuid}_{filename}               # 본문 첨부
└── comments/{comment_id}/{uuid}_{filename}  # 댓글 첨부

discussions/{discussion_id}/
├── {uuid}_{filename}               # 본문 첨부
└── comments/{comment_id}/{uuid}_{filename}  # 댓글 첨부

inquiries/{inquiry_id}/{question|reply}/
└── {uuid}_{filename}               # 문의 질문/답변 첨부
```

검토서 재업로드 시 경로가 달라지면 기존 S3 파일 자동 삭제. 검토서 관리 페이지에서 수동 삭제 시 `DELETE /api/reviews/files` 로 S3 객체 + `review_stages.s3_file_key=NULL` 연결 해제 (검토 이력은 보존).

---

## 주요 인덱스

| 테이블.컬럼 | 목적 |
|---|---|
| `buildings.mgmt_no` (UNIQUE) | 관리번호 조회 |
| `buildings.current_phase` | 대시보드 단계별 집계 |
| `buildings.final_result` | 최종 판정 집계 |
| `review_stages.report_submitted_at` | 미제출 필터·리마인드 |
| `inquiries.submitter_id` | 본인 문의 조회 |
| `*_attachments.*_id` (각 FK) | 첨부 로드 N+1 회피 |

---

## 마이그레이션 히스토리 (주요)

| 리비전 | 설명 |
|---|---|
| `463340852196` | 초기 테이블 생성 |
| `2734bfa9e31b` | must_change_password |
| `47f787cb8b11` | inquiries 테이블 |
| `26dd5416f6ab` | notification_logs.recipient_id nullable |
| `4c2b2569fa54` | buildings.assigned_reviewer_name |
| `e563f2c70102` | buildings 내진등급/유형별상세검토 |
| `82ddbeabc057` | users.kakao_uuid, kakao_token_expires_at |
| `65678b8e44dc` | ResultType 3종 정리 |
| `86929ae4d301` | review_stages.inappropriate_decision |
| `e21306ca9ca6` | buildings.drawing_creator_qualification |
| `388af05f7fc8` | 공지사항 + 댓글 |
| `72fd6de98ff3` | 공지사항 첨부 |
| `aabfa375c25e` | password_setup_tokens |
| `34755893cd3c` | 토론방 + 댓글 + 첨부 |
| `b1a7c3d49012` | InquiryStatus `next_phase` → `completed` 통합 |
| `c47b3f51ab90` | 대시보드 인덱스 3종 (current_phase / final_result / report_submitted_at) |
| `d7e914c80f52` | review_stages.report_due_date |
| `e5d2a318f790` | announcement/discussion 첨부에 content_type + 댓글 첨부 테이블 |
| `f14b87e0c3d2` | inquiry_attachments (질문·답변 공용) |
