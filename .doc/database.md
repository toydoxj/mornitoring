# 데이터베이스 구조

Supabase PostgreSQL 17 (Seoul)

## 테이블 구조

### users (12건) - 사용자
| 컬럼명 | 타입 | 필수 | 설명 |
|--------|------|------|------|
| id | integer (PK) | O | 자동증가 |
| name | varchar | O | 이름 |
| email | varchar (UNIQUE) | O | 이메일 (로그인ID) |
| role | enum | O | team_leader / chief_secretary / secretary / reviewer |
| phone | varchar | | 전화번호 |
| kakao_id | varchar | | 카카오 사용자 ID |
| kakao_access_token | varchar | | 카카오 액세스 토큰 |
| kakao_refresh_token | varchar | | 카카오 리프레시 토큰 |
| password_hash | varchar | | bcrypt 해시 비밀번호 |
| must_change_password | boolean | O | 최초 로그인 시 비밀번호 변경 필요 (기본: true) |
| is_active | boolean | O | 활성 상태 (기본: true) |
| created_at | timestamptz | O | 생성일시 |
| updated_at | timestamptz | O | 수정일시 |

### buildings (3,401건) - 건축물 (통합관리대장)
| 컬럼명 | 타입 | 필수 | 설명 |
|--------|------|------|------|
| id | integer (PK) | O | 자동증가 |
| mgmt_no | varchar (UNIQUE, INDEX) | O | 관리번호 (예: 2025-0001) |
| reviewer_id | integer (FK→reviewers) | | 검토위원 연결 |
| assigned_reviewer_name | varchar | | 배정 엑셀 기입 검토위원 이름 |
| building_type | varchar | | 건축구분 |
| sido | varchar | | 시도명 |
| sigungu | varchar | | 시군구명 |
| beopjeongdong | varchar | | 법정동명 |
| land_type | varchar | | 대지구분 |
| main_lot_no | varchar | | 본번 |
| sub_lot_no | varchar | | 부번 |
| special_lot_no | varchar | | 특수지번 |
| building_name | varchar | | 건물명 |
| main_structure | varchar | | 주구조 |
| other_structure | varchar | | 기타구조 |
| main_usage | varchar | | 주용도 |
| other_usage | varchar | | 기타용도 |
| gross_area | numeric(12,2) | | 연면적(㎡) |
| height | numeric(8,2) | | 높이(m) |
| floors_above | integer | | 지상층수 |
| floors_below | integer | | 지하층수 |
| is_special_structure | boolean | | 특수구조물 여부 |
| is_high_rise | boolean | | 고층 여부 |
| is_multi_use | boolean | | 다중이용건축물 여부 |
| remarks | text | | 비고 |
| architect_firm | varchar | | 건축사(소속) |
| architect_name | varchar | | 건축사(성명) |
| struct_eng_firm | varchar | | 책임구조기술자(소속) |
| struct_eng_name | varchar | | 책임구조기술자(성명) |
| high_risk_type | varchar | | 고위험유형 |
| related_tech_coop | boolean | | 관계기술자 협력대상 여부 |
| drawing_creation | boolean | | 관계기술자 도면작성 여부 |
| current_phase | varchar | | 현재 단계 (아래 단계 흐름 참조) |
| final_result | varchar | | 최종 판정결과 |
| created_at | timestamptz | O | 생성일시 |
| updated_at | timestamptz | O | 수정일시 |

#### 단계 흐름 (current_phase)
```
(없음) → doc_received → preliminary → supplement_1_received → supplement_1 
→ supplement_2_received → supplement_2 → ... → completed
```
| 값 | 한글 |
|----|------|
| (null) | 미접수 |
| doc_received | 예비도서 접수 |
| preliminary | 예비검토서 제출 |
| supplement_1_received | 보완도서(1차) 접수 |
| supplement_1 | 보완검토서(1차) 제출 |
| supplement_2_received | 보완도서(2차) 접수 |
| supplement_2 | 보완검토서(2차) 제출 |
| completed | 완료 |

### reviewers (0건) - 검토위원 상세
| 컬럼명 | 타입 | 필수 | 설명 |
|--------|------|------|------|
| id | integer (PK) | O | 자동증가 |
| user_id | integer (FK→users, UNIQUE) | O | 사용자 연결 |
| group_no | varchar | | 조 번호 |
| specialty | varchar | | 전문 분야 |

### review_stages (970건) - 검토 단계
| 컬럼명 | 타입 | 필수 | 설명 |
|--------|------|------|------|
| id | integer (PK) | O | 자동증가 |
| building_id | integer (FK→buildings) | O | 건축물 연결 |
| phase | enum | O | preliminary / supplement_1~5 |
| phase_order | integer | O | 0=예비, 1=1차보완, ... |
| doc_received_at | date | | 도서접수일 |
| doc_distributed_at | date | | 도서배포일 |
| report_submitted_at | date | | 검토서 제출일 |
| reviewer_name | varchar | | 검토자 이름 |
| result | enum | | pass / supplement / fail / minor |
| review_opinion | text | | 검토의견 (적정성 검토 결과) |
| defect_type_1 | varchar | | 부적합유형-1 |
| defect_type_2 | varchar | | 부적합유형-2 |
| defect_type_3 | varchar | | 부적합유형-3 |
| objection_filed | boolean | | 이의신청 여부 |
| objection_content | text | | 이의신청 검토내용 |
| objection_reason | text | | 이의신청 사유 |
| s3_file_key | varchar | | S3 검토서 파일 경로 |
| stage_remarks | text | | 비고 |
| created_at | timestamptz | O | 생성일시 |
| updated_at | timestamptz | O | 수정일시 |

### inquiries (6건) - 문의사항
| 컬럼명 | 타입 | 필수 | 설명 |
|--------|------|------|------|
| id | integer (PK) | O | 자동증가 |
| building_id | integer (FK→buildings) | O | 건축물 연결 |
| mgmt_no | varchar | O | 관리번호 |
| phase | varchar | O | 문의 시점 단계 |
| submitter_name | varchar | O | 문의자 이름 |
| content | text | O | 문의 내용 |
| reply | text | | 답변 |
| status | enum | O | open / asking_agency / completed / next_phase |
| created_at | timestamptz | O | 생성일시 |
| updated_at | timestamptz | O | 수정일시 |

#### 문의 상태 (status)
| 값 | 한글 | 진행/완료 |
|----|------|----------|
| open | 접수 | 진행중 |
| asking_agency | 관리원문의중 | 진행중 |
| completed | 완료 | 완료 |
| next_phase | 다음단계 | 완료 |

### notification_logs (13건) - 알림 발송 이력
| 컬럼명 | 타입 | 필수 | 설명 |
|--------|------|------|------|
| id | integer (PK) | O | 자동증가 |
| recipient_id | integer (FK→users) | | 수신자 |
| channel | varchar | O | kakao / web |
| template_type | varchar | O | doc_received / review_request / reminder |
| title | varchar | O | 알림 제목 |
| message | text | | 알림 내용 |
| related_building_id | integer (FK→buildings) | | 관련 건축물 |
| is_sent | boolean | O | 발송 성공 여부 |
| sent_at | timestamptz | | 발송 시간 |
| retry_count | integer | O | 재시도 횟수 |
| error_message | text | | 실패 사유 |
| created_at | timestamptz | O | 생성일시 |

### audit_logs (5건) - 감사 로그
| 컬럼명 | 타입 | 필수 | 설명 |
|--------|------|------|------|
| id | integer (PK) | O | 자동증가 |
| user_id | integer (FK→users) | | 실행자 |
| action | varchar | O | create / update / delete / upload / assign |
| target_type | varchar | O | building / review_stage / user |
| target_id | integer | | 대상 ID |
| before_data | jsonb | | 변경 전 데이터 |
| after_data | jsonb | | 변경 후 데이터 |
| ip_address | varchar | | IP 주소 |
| created_at | timestamptz | O | 생성일시 |

## 테이블 관계

```
users 1──1 reviewers 1──N buildings 1──N review_stages
                              │
                              ├──N inquiries
                              ├──N notification_logs
                              └──N audit_logs
```

## S3 저장 구조

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
└── ...
```
