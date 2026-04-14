# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

건축구조안전 모니터링 업무 통합 시스템. 통합관리대장(엑셀 102열) 기반으로 관리번호 부여 → 설계도서 배포 → 검토서 수집 → 보완 반복 워크플로를 자동화한다.

사용자: 팀장 1 + 총괄간사 1 + 간사 5 + 검토위원 50 ≈ 약 60명

## 기술 스택

- **프론트엔드**: Next.js (App Router) + React 19 + TypeScript + Tailwind CSS + shadcn/ui
- **백엔드**: FastAPI (Python) + SQLAlchemy + Alembic + PostgreSQL
- **인증**: JWT + 카카오 OAuth2 (친구에게 보내기 API)
- **파일**: AWS S3 (검토서 저장), openpyxl (엑셀 처리)

## 개발 명령어

### 프론트엔드 (`frontend/`)
```bash
npm run dev       # 개발 서버 (localhost:3000)
npm run build     # 프로덕션 빌드
npm run lint      # ESLint 실행
```

### 백엔드 (`backend/`)
```bash
source .venv/bin/activate                    # 가상환경 활성화
uvicorn main:app --reload                    # 개발 서버 (localhost:8000)
alembic revision --autogenerate -m "설명"     # 마이그레이션 생성
alembic upgrade head                         # 마이그레이션 적용
```

## 아키텍처

```
frontend/ (Next.js)  ──HTTP/JSON──→  backend/ (FastAPI)
                                        │
                                   PostgreSQL + S3
```

### 백엔드 구조
- `routers/` — API 엔드포인트 (auth, users, buildings). 역할 기반 접근 제어는 `routers/auth.py`의 `require_roles()` 의존성으로 처리
- `models/` — SQLAlchemy ORM 모델. `Building`은 통합관리대장 A~AD열, `ReviewStage`는 예비검토~N차 보완 단계를 1:N으로 관리
- `engines/` — 비즈니스 로직 엔진. `column_mapping.py`에 엑셀 열↔DB 필드 매핑 정의, `ledger_import.py`/`ledger_export.py`로 엑셀 import/export
- `config.py` — Pydantic BaseSettings 기반 설정 (`.env` 파일 로드)

### 핵심 도메인 모델
- `User` — 4개 역할: `team_leader`, `chief_secretary`, `secretary`, `reviewer`
- `Building` — 관리번호(`mgmt_no`) 기준 건축물. 30개 컬럼이 엑셀 열과 1:1 매핑
- `ReviewStage` — 건물당 N개. `PhaseType` enum으로 예비/1차~5차 보완 구분. `ResultType`으로 적합/보완/부적합/경미 판정

### 엑셀 열 매핑
`engines/column_mapping.py`에 정의. 엑셀 양식 변경 시 이 파일만 수정하면 import/export 모두 반영됨.

## 코딩 규칙

- 응답/주석/커밋 메시지/문서: 한국어
- 변수명/함수명: 영어
- 들여쓰기: 2칸 (프론트엔드), 4칸 (백엔드 Python)
- `any` 타입 사용 금지 (TypeScript)
- Python은 반드시 가상환경(`.venv`) 사용
- 컴포넌트: shadcn/ui 기반, 반응형 필수

## 참조 문서

- `.doc/PRD.md` — 제품 요구사항 (업무 프로세스 Phase 0~2)
- `.doc/plan.md` — 구현 계획서 (4단계 Stage, 시나리오, 기술 결정)
- `.doc/관리대장 샘플.xlsx` — 통합관리대장 실제 양식 (102열, 7개 시트)
