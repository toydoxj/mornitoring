# 백업 / 복구 절차서

건축구조안전 모니터링 시스템의 DB · 첨부파일 백업 정책과 재해 복구(DR) 절차.
Supabase 자동 스냅샷만으로는 벤더 내부 사고(계정 탈취, 프로젝트 삭제 등)에
취약하므로 **GitHub Actions 로 S3 오프사이트 덤프를 병행**한다.

최종 수정: 2026-06-11 (접속 형식을 Session pooler 기준으로 정정, 덤프 검증 단계 추가 반영)

---

## 1. 백업 체계 한눈에

| 대상 | 1차(관리형) | 2차(오프사이트) | 보존 |
|---|---|---|---|
| PostgreSQL (Supabase) | Supabase 자동 일일 스냅샷 | GitHub Actions → AWS S3 `pg_dump -Fc` | S3 90일 + Glacier 1년 |
| S3 첨부 버킷 (검토서 · 공지 · 토론 · 문의) | Versioning ON | (선택) CRR 타 리전 복제 | noncurrent 90일 후 Glacier |
| 시크릿 (JWT, AWS, 카카오) | Render / Vercel / GitHub Secrets | 비밀 저장소(1Password 등) 별도 보관 | 교체 시 이력 남김 |

RPO 목표: **24시간 이내**, RTO 목표: **4시간 이내** (PITR 미도입 기준).

---

## 2. 사전 준비 (최초 1회)

### 2.1 AWS 백업 버킷 만들기
> 운영 첨부 버킷과 **반드시 분리**한다. 가능하면 별도 AWS 계정 또는 최소 별도 리전.

1. S3 콘솔 → Create bucket
   - 이름 예: `ksea-m-db-backup-apne2`
   - 리전: `ap-northeast-2` (Seoul)
   - **Block all public access ON**
2. Properties → **Bucket Versioning: Enable**
3. Properties → Default encryption: **SSE-S3 (AES256)** 또는 KMS 키 생성 후 **SSE-KMS**
4. Management → Lifecycle rule 추가
   - 이름: `db-retention`
   - Current versions: 90일 후 `GLACIER_IR` 전환, 365일 후 Expire
   - Noncurrent versions: 30일 후 Expire
   - 불완전 멀티파트 업로드: 7일 후 정리

### 2.2 백업 전용 IAM 사용자
최소 권한 정책 예시:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:AbortMultipartUpload"],
      "Resource": "arn:aws:s3:::ksea-m-db-backup-apne2/*"
    }
  ]
}
```
> 복구/검증용 Read 권한은 별도 IAM 사용자로 분리해 운영자에게만 부여한다.

### 2.3 DATABASE_URL 형식 주의
- **Session pooler(포트 5432) 사용** — 호스트는 `aws-0-<region>.pooler.supabase.com`, 사용자명은 `postgres.<ref>` 형식
  - 직접 DB 호스트(`db.<ref>.supabase.co`)는 **IPv6 전용**이라 GitHub Actions 러너(IPv4만 지원)에서 연결 불가 (IPv4 add-on 구매 시에만 사용 가능)
  - Transaction pooler(포트 6543)는 `pg_dump` 와 비호환 — 사용 금지
  - Session pooler 는 5432 포트로 `pg_dump` 호환 + IPv4 제공
- URL 끝에 `?sslmode=require` 필수. 없으면 스크립트가 자동으로 require 로 강제함.
- DB명(`/postgres`) 누락 금지 — 스크립트가 즉시 실패 처리함.
- 예: `postgres://postgres.<ref>:<pw>@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres?sslmode=require`
- 접속 정보는 Supabase 대시보드 → Connect → **Session pooler** 탭에서 확인.

### 2.4 GitHub Secrets / Variables 등록
리포 → Settings → Secrets and variables → Actions

**Secrets** (암호화 저장)
- `PROD_DATABASE_URL` — Supabase connection string (postgres://…)
- `BACKUP_S3_BUCKET` — 위에서 만든 버킷 이름
- `BACKUP_AWS_ACCESS_KEY_ID`
- `BACKUP_AWS_SECRET_ACCESS_KEY`
- `BACKUP_KMS_KEY_ID` — (SSE-KMS 사용 시에만)

**Variables** (평문 노출 OK)
- `BACKUP_AWS_REGION` — 예: `ap-northeast-2`
- `BACKUP_S3_PREFIX` — 기본 `db/`

> **P1 전환 예정**: 장기 IAM 키 대신 GitHub OIDC → AWS `sts:AssumeRoleWithWebIdentity` 방식으로 교체. 키 유출 영향 최소화 및 자동 만료 확보.

### 2.5 운영 첨부 S3 버킷 Versioning 켜기
1. 운영 S3 버킷 → Properties → **Bucket Versioning: Enable**
2. Lifecycle rule — Noncurrent versions 90일 후 Glacier, 365일 후 Expire
3. (권장) 같은 리전 다른 버킷 또는 타 리전 복제(CRR) 구성

---

## 3. 일상 운영

### 3.1 자동 백업
- GitHub Actions `.github/workflows/db-backup.yml`
- 매일 KST 03:10 자동 실행 + 수동 실행(workflow_dispatch) 가능
- 실패 시 GitHub 가 리포 관리자에게 자동 메일 발송

### 3.2 수동 백업 (배포/마이그레이션 직전)
GitHub → Actions → `DB Backup` → **Run workflow**
- `label` 에 `pre-migration` 또는 `pre-release` 입력
- 결과는 `s3://<bucket>/db/YYYY/MM/<timestamp>-<label>.dump`

### 3.3 무결성 검증 — `.complete` 마커 규칙
백업 1세트는 아래 4개 객체로 구성된다. 업로드 순서도 아래와 동일.

| 순서 | Key | 역할 |
|---|---|---|
| 1 | `*.dump` | 본체 |
| 2 | `*.dump.sha256` | 체크섬 |
| 3 | `*.dump.meta.json` | 메타 (시작·종료, 크기, 카탈로그 항목 수, pg_dump 버전, alembic head) |
| 4 | `*.dump.complete` | **완료 마커 — 이 파일이 있는 세트만 유효** |

업로드 전에 스크립트가 `pg_restore --list` 카탈로그 파싱과 최소 크기 가드
(`BACKUP_MIN_DUMP_BYTES`, 기본 100KB)를 통과해야 `.complete` 가 생성된다.
즉 `.complete` 는 "업로드 완료"뿐 아니라 "내용 검증 통과"의 의미도 가진다.

`*.dump` 만 존재하고 `*.complete` 가 없다면 업로드 중단된 “부분 백업”이므로 복구에 사용 금지.

```bash
# 1) 최신 유효 백업 찾기: complete 마커가 있는 타임스탬프만 필터링
aws s3 ls s3://<bucket>/db/ --recursive \
  | awk '/\.complete$/ {print $NF}' | sort | tail -n 5

# 2) 본체·체크섬 내려받아 검증
aws s3 cp s3://<bucket>/db/2026/04/20260419T181000Z.dump .
aws s3 cp s3://<bucket>/db/2026/04/20260419T181000Z.dump.sha256 .
shasum -a 256 -c 20260419T181000Z.dump.sha256
```

---

## 4. 복구 절차

### 4.1 시나리오 A: 실수로 테이블/행 삭제 (전체 복구)
1. Supabase → Settings → **Backups** → 사고 시점 직전 스냅샷 복구
   - 신규 프로젝트로 복원 후 확인 → 성공 시 운영 DATABASE_URL 스왑
2. Supabase 백업이 불가한 경우(계정 사고 등) → **§4.3** 로 진행

### 4.2 시나리오 B: 특정 테이블/소수 행만 복원
Supabase 복구는 DB 전체 스왑이라 과하다. 아래 흐름:
1. 최신 덤프를 로컬에 복원 (임시 DB)
   ```bash
   createdb ksea_restore
   pg_restore --dbname=ksea_restore --no-owner --no-privileges 20260419T181000Z.dump
   ```
2. 필요한 테이블/행만 `pg_dump -t <table>` 또는 `COPY` 로 추출
3. 운영 DB 에 수동 병합 (트랜잭션 + 감사 로그 필수)

### 4.3 시나리오 C: 벤더 사고(프로젝트 삭제 · 리전 장애) → 오프사이트 복구
1. 새 PostgreSQL 인스턴스 준비 (Supabase 신규 프로젝트 or RDS)
2. S3 에서 최신 덤프 다운로드
   ```bash
   aws s3 ls s3://<bucket>/db/ --recursive | sort | tail -n 5
   aws s3 cp s3://<bucket>/db/2026/04/<latest>.dump .
   ```
3. 체크섬 검증 → `pg_restore`
   ```bash
   pg_restore \
     --dbname="<NEW_DATABASE_URL>" \
     --no-owner --no-privileges --clean --if-exists \
     <latest>.dump
   ```
4. `.meta.json` 의 `alembic_head` 와 현 리포 `alembic heads` 비교
   - 일치: 그대로 사용
   - 리포가 더 앞서있음: `alembic upgrade head` 로 전진
5. Render 환경 변수 `DATABASE_URL` 갱신 → 배포 재시작
6. 스모크 테스트 (§5)

### 4.4 시나리오 D: 첨부파일 손상/삭제
1. S3 → 버킷 → **Show versions** → 이전 버전 복원 (Versioning 덕분)
2. 영구 삭제(Delete marker) 된 경우에도 noncurrent 90일 내면 복원 가능

---

## 5. 복구 직후 스모크 테스트
`docs/operational-dry-run.md` 의 골든 패스를 준용하며, 최소한 아래 5종은 직접 확인:
1. 팀장/간사/검토위원 각 1명으로 로그인
2. 관리대장 목록 로드(핵심 건수 일치 여부)
3. 검토서 업로드 1건 → S3 저장 → 다운로드 재확인
4. 공지 · 토론 · 문의 목록 조회
5. `/reminders` 페이지 정상 렌더

---

## 6. 리허설 (분기 1회)

복구 리허설은 “실제로 안 해보면 못 쓴다”가 원칙. 매 분기 1회, 담당자 로테이션.

| 단계 | 확인 내용 | 소요 (목표) |
|---|---|---|
| 1 | 최신 덤프 다운로드 + sha256 검증 | 5분 |
| 2 | 격리 DB 에 `pg_restore` | 20분 |
| 3 | `alembic heads` 일치 확인 | 2분 |
| 4 | 랜덤 20건 행 검증 + 스모크 5종 | 15분 |
| 5 | RTO/RPO 실측 + 개선사항 기록 | 5분 |

리허설 결과는 `.doc/` 내 `backup-drill-YYYYQn.md` 로 1페이지 분량 기록.

---

## 7. 향후 재사용 가이드

- **연도/차수 리셋**: 운영 DB 리셋 대신 **연도별 DB 분리**. 과거 연도는 read-only 역할로 고정, 신규는 새 Supabase 프로젝트 + 새 스키마.
- **개발/스테이징 데이터 복제**: 최신 덤프 → dev DB 복원 직후 **PII 마스킹 SQL** 필수 (이메일/전화/이름/카카오 ID 해시 또는 더미 치환).
- **타 조직 템플릿 이관**: Alembic 마이그레이션 + `backend/seed.py` + 코드값만 패키지화. **운영 데이터 · 첨부 · PII 는 절대 포함하지 않는다.**

---

## 8. 금지사항

- 운영 `DATABASE_URL` 을 개인 노트북/로컬에 저장 금지
- 백업 파일을 공용 Slack · 이메일 · Google Drive 로 전송 금지 (반드시 S3 Presigned URL 또는 접근 통제된 저장소 사용)
- 테스트용 DB 에 운영 덤프를 “그대로” 복원 금지 (PII 마스킹 후)
- 키 회전 없이 재직자/퇴직자 권한을 방치하지 말 것
