# 데이터베이스 구조

Supabase PostgreSQL 17 (Seoul) | 마지막 갱신: 2026-04-17

## 테이블 요약

| 테이블 | 건수 | 용도 |
|---|---|---|
| `users` | 9 | 사용자 (4개 역할) |
| `reviewers` | 0 | 검토위원 상세 (group_no, specialty) |
| `buildings` | 3,401 | 통합관리대장 건축물 |
| `review_stages` | 982 | 건물별 단계 (예비/보완1~5차) |
| `inquiries` | 9 | 검토 문의사항 |
| `inappropriate_notes` | 1 | 부적합 판정 간사진 의견 (다중) |
| `notification_logs` | 27 | 카카오톡 알림 발송 이력 |
| `announcements` | 0 | 공지사항 |
| `announcement_comments` | 0 | 공지사항 댓글 |
| `audit_logs` | 14 | 감사 로그 |

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
| kakao_access_token | varchar(500) | | 카카오 액세스 토큰 |
| kakao_refresh_token | varchar(500) | | 카카오 리프레시 토큰 |
| kakao_token_expires_at | timestamp | | 액세스 토큰 만료일 (자동 갱신 기준) |
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

> 현재 미사용 (0건). 기본 배정은 `buildings.assigned_reviewer_name` 및 `buildings.reviewer_id`로 처리.

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
| high_risk_type | varchar(100) | 고위험유형 (텍스트, 현재 미사용) |
| architect_firm / architect_name | varchar | 건축사 (소속/성명) |
| struct_eng_firm / struct_eng_name | varchar | 책임구조기술자 (소속/성명) |
| **drawing_creator_qualification** | varchar(30) | **도면작성자 자격** (건축사/건축구조기술사/기타) |
| drawing_creator_firm / drawing_creator_name | varchar | (미사용 - 향후 제거 가능) |
| seismic_level | varchar(50) | 내진등급 (특/I/II) |
| detail_category1~9 | varchar(50) | 유형별상세검토 (공법/전이/면진제진/특수전단벽/무량판/캔틸래버/장스팬/고층/필로티) |
| related_tech_coop | boolean | 관계기술자 협력대상 여부 |
| drawing_creation | boolean | 관계기술자 도면작성 여부 |
| remarks | text | 비고 |
| current_phase | varchar(30) | 현재 단계 (아래 참조) |
| final_result | varchar(30) | 최종 판정결과 (별도 엑셀 업로드로 지정 예정) |
| created_at / updated_at | timestamp | |

#### 단계 흐름 (`current_phase`)
```
(null 미배정) → assigned → doc_received → preliminary
  → supplement_1_received → supplement_1
  → supplement_2_received → supplement_2
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

### review_stages — 검토 단계 (건물별 1:N)
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer (PK) | |
| building_id | integer (FK→buildings) | |
| phase | varchar(12) (enum) | `preliminary` / `supplement_1~5` |
| phase_order | integer | 0=예비, 1=1차, ... |
| doc_received_at | date | 도서접수일 |
| doc_distributed_at | date | 도서배포일 |
| report_submitted_at | date | 검토서 제출일 |
| reviewer_name | varchar(50) | 검토자 이름 |
| result | varchar(12) (enum) | `pass` 적합 / `simple_error` 단순오류 / `recalculate` 재계산 |
| review_opinion | text | 검토의견 (적정성 검토 결과) |
| defect_type_1~3 | varchar(100) | 부적합유형 |
| objection_filed | boolean | 이의신청 여부 (레거시) |
| objection_content / objection_reason | text | 이의신청 내용/사유 (레거시) |
| s3_file_key | varchar(500) | S3 검토서 파일 경로 |
| stage_remarks | text | 비고 |
| **inappropriate_review_needed** | boolean | **부적정 사례 검토 필요 체크** (검토자 업로드 시) |
| **inappropriate_decision** | varchar(17) (enum) | **부적합 판정**: `PENDING` / `CONFIRMED_SERIOUS` / `CONFIRMED_SIMPLE` / `EXCLUDED` |
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
| submitter_name | varchar(50) | 문의자 이름 |
| content | text | 문의 내용 |
| reply | text | 답변 |
| status | varchar(13) (enum) | `open` 접수 / `asking_agency` 관리원문의중 / `completed` 완료 |
| created_at / updated_at | timestamp | |

### notification_logs — 카카오톡 알림 발송 이력
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer (PK) | |
| recipient_id | integer (FK→users) | 수신자 (NULL 허용: 이름만 아는 경우) |
| channel | varchar(20) | `kakao` 친구발송 / `kakao_memo` 나에게보내기 / `web` |
| template_type | varchar(50) | `doc_received` / `review_request` / `reminder` 등 |
| title / message | varchar / text | |
| related_building_id | integer (FK→buildings) | 관련 건축물 (옵션) |
| is_sent | boolean | 발송 성공 여부 |
| sent_at | timestamp | 발송 시간 |
| retry_count | integer | |
| error_message | text | 실패 사유 |
| created_at | timestamp | |

### announcements — 공지사항
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer (PK) | |
| author_id | integer (FK→users) | |
| author_name | varchar(50) | 스냅샷 |
| title | varchar(200) | |
| content | text | |
| created_at / updated_at | timestamp | |

### announcement_comments — 공지사항 댓글
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer (PK) | |
| announcement_id | integer (FK→announcements ON DELETE CASCADE, INDEX) | |
| author_id | integer (FK→users) | |
| author_name | varchar(50) | 스냅샷 |
| content | text | |
| created_at | timestamp | |

### audit_logs — 감사 로그
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer (PK) | |
| user_id | integer (FK→users) | 실행자 |
| action | varchar(100) | `create` / `update` / `delete` / `upload` / `assign` / `inappropriate_decision` 등 |
| target_type | varchar(50) | `building` / `review_stage` / `user` / ... |
| target_id | integer | 대상 ID |
| before_data / after_data | jsonb | 변경 전/후 |
| ip_address | varchar(45) | |
| created_at | timestamp | |

---

## 테이블 관계

```
users ─┐
       ├─1:1─ reviewers ──1:N─ buildings ──1:N─ review_stages ─1:N─ inappropriate_notes
       │                         │                 │
       │                         ├─1:N─ inquiries  │
       │                         └─1:N─ notification_logs
       │
       ├─1:N─ announcements ──1:N─ announcement_comments
       └─1:N─ audit_logs
```

---

## 부적합 판정 enum (`inappropriate_decision`)

| 값 | 한글 | 의미 |
|---|---|---|
| `PENDING` | 대기 | 판정 미진행 (기본값) |
| `CONFIRMED_SERIOUS` | 확정(심각) | 부적합 확정 — 심각한 사유 |
| `CONFIRMED_SIMPLE` | 확정(단순) | 부적합 확정 — 단순한 사유 |
| `EXCLUDED` | 제외 | 확정 후 추후 제외 |

## 검토결과 enum (`review_stages.result`)

| 값 | 한글 |
|---|---|
| `pass` | 적합 |
| `simple_error` | 단순오류 |
| `recalculate` | 재계산 |

---

## S3 저장 구조

검토서 파일은 AWS S3에 저장. 경로:

```
reviews/
├── 예비검토/
│   ├── 2026-04-17/
│   │   ├── 2025-0001.xlsm
│   │   └── 2025-0005.xlsm
│   └── 2026-04-18/
├── 보완검토(1차)/
│   └── 2026-04-20/
├── 보완검토(2차)/
├── 보완검토(3차)/
├── 보완검토(4차)/
└── 보완검토(5차)/
```

재업로드 시 경로가 달라지면 기존 S3 파일 자동 삭제.

---

## 마이그레이션 히스토리 (주요)

| 리비전 | 설명 |
|---|---|
| `463340852196` | 초기 테이블 생성 |
| `2734bfa9e31b` | must_change_password 필드 |
| `47f787cb8b11` | inquiries 테이블 |
| `26dd5416f6ab` | notification_logs.recipient_id nullable |
| `4c2b2569fa54` | buildings에 assigned_reviewer_name |
| `1995f7d916c4` | special_lot_no 컬럼 크기 확장 |
| `e563f2c70102` | buildings에 내진등급/유형별상세검토 |
| `82ddbeabc057` | users에 kakao_uuid, kakao_token_expires_at |
| `1d79e90f3ebe` | review_stages에 inappropriate_review_needed |
| `e5822b439e6b` / `934a1f38b94a` | ResultType에 simple_error, recalculate 추가 |
| `65678b8e44dc` | ResultType을 3종으로 정리 |
| `86929ae4d301` | review_stages에 inappropriate_decision |
| `2179b4bec65d` → `352699499ffa` | inappropriate_notes 테이블 + buildings 도면작성자 필드 |
| `e21306ca9ca6` | buildings에 drawing_creator_qualification |
| `388af05f7fc8` | 공지사항 및 댓글 테이블 |
