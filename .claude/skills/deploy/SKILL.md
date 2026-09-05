---
name: deploy
description: 이 프로젝트를 운영에 배포한다. "배포해줘", "운영 반영", "릴리스", "deploy", "푸시해서 배포" 같은 요청이나, 배포 상태·현재 운영 커밋 확인, 배포 롤백 요청에 사용한다.
---

# 배포 절차

운영 사용자 약 60명(팀장·간사·검토위원)이 쓰는 시스템이다. 배포는 되돌리기
어려운 외부 영향 작업이므로 아래 순서를 건너뛰지 않는다.

## 배포 구조

배포 전용 파이프라인은 없다. **GitHub `main` 브랜치에 푸시하면
Vercel·Render가 각각 자동으로 감지해 배포한다.**

| 구성요소 | 호스팅 | 주소 | 트리거 |
|---|---|---|---|
| 프론트엔드 | Vercel (프로젝트 `frontend`, root=`frontend/`) | https://ksea-m.vercel.app | `main` 푸시 |
| 백엔드 | Render | https://monitoring-backend-sg.onrender.com | `main` 푸시 |
| DB | Supabase (운영) | — | 백엔드 기동 시 `alembic upgrade head` |

- GitHub Actions(`backend-ci`, `frontend-ci`)는 **테스트만 돌린다. 배포하지 않는다.**
  따라서 CI 실패와 무관하게 배포는 진행되므로, CI를 기다린다고 안전해지지 않는다.
  검증은 푸시 **전에** 로컬에서 끝내야 한다.
- 백엔드 Docker CMD가 `alembic upgrade head && uvicorn ...` 이라
  **마이그레이션은 배포 시 자동 적용된다.**
- `backend/` 만 바뀐 커밋은 Vercel이, `frontend/` 만 바뀐 커밋은 Render가
  재배포하지 않을 수 있다. 배포 확인 시 바뀐 쪽만 보면 된다.

## 1. 배포 전 검증 (필수)

푸시하면 곧바로 운영이므로 여기서 다 잡는다.

```bash
# 백엔드 — 전체 통과해야 한다 (Windows 기준 경로)
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q

# 프론트엔드
cd frontend && npm run lint && npm run typecheck
```

- lint 경고 중 `notifications/page.tsx` 등 **기존부터 있던 warning은 배포를 막지
  않는다.** 이번 변경으로 새로 생긴 것인지만 구분한다. error는 반드시 해결한다.
- 프로젝트 지침에 따라 **커밋 전 Codex 코드 리뷰**를 거친다.

  ```bash
  codex exec --profile consult --sandbox read-only -o .codex-last.md "<변경 요약과 검토 요청 사항>"
  ```

  지적된 문제는 배포 전에 고치고, 재발 방지 테스트를 함께 남긴다.

## 2. 마이그레이션 유무 판정

```bash
git diff --stat HEAD~1 -- backend/alembic/versions
```

새 리비전이 있으면 **배포 직전에 수동 백업을 먼저 받는다.**

```bash
gh workflow run db-backup.yml -f label=pre-migration
gh run list --workflow=db-backup.yml --limit 1   # success 확인 후 진행
```

## 3. 커밋

`main`에서 직접 작업 중이면 그대로 커밋한다(배포가 `main` 푸시로 트리거되므로
브랜치를 따면 병합 단계가 추가된다). 커밋 메시지는 한국어, 본문에 *무엇을 왜*
바꿨는지 적는다.

Bash 도구를 쓸 때는 heredoc(`git commit -F - <<'EOF'`)을 쓴다.
PowerShell here-string(`@'...'@`)을 Bash에 쓰면 제목에 `@`가 섞여 들어간다.

## 4. 푸시 (= 배포 시작)

```bash
git push origin main
```

## 5. 배포 확인

```bash
# 백엔드 — 배포 완료되면 commit 값이 방금 푸시한 SHA 앞 7자리로 바뀐다.
# Render 콜드스타트가 있어 최초 응답까지 최대 1분 걸릴 수 있다.
curl -s https://monitoring-backend-sg.onrender.com/api/health --max-time 90

# 프론트
curl -s -o /dev/null -w "%{http_code}\n" https://ksea-m.vercel.app/

# CI 결과 (배포와 별개지만 회귀 신호로 본다)
gh run list --limit 3
```

배포 반영에는 보통 수 분이 걸린다. `/api/health`의 `commit`이 이전 SHA 그대로면
아직 진행 중이거나, 해당 커밋에 `backend/` 변경이 없어 재배포가 일어나지
않은 것이다.

변경한 화면을 실제로 열어 동작을 확인한다. 확인하지 않았다면 "배포는 됐고
화면 확인은 하지 않았음"이라고 사실대로 보고한다.

## 6. 문제 발생 시 롤백

```bash
git revert <배포한 커밋 SHA>
git push origin main
```

`git reset --hard` + force push는 쓰지 않는다. **마이그레이션이 포함된 배포는
코드 revert만으로 되돌아가지 않는다.** 스키마 되돌리기와 데이터 복구는
`.doc/backup-recovery.md`의 절차를 따른다.

## 사용자에게 확인할 것

- 운영 배포는 사용자 승인 없이 시작하지 않는다. 한 번의 승인은 그 배포 한 번에만 유효하다.
- 마이그레이션이 포함되면 그 사실과 백업 여부를 명시적으로 알린다.

## 참조

- `.doc/operations-policy.md` — 백업 주기, Supabase RLS, 로그 확인
- `.doc/backup-recovery.md` — 백업·재해 복구(DR) 절차
- `.doc/troubleshooting.md` — 장애 대응
