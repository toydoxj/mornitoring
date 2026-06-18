"""폴더명 기반 설계도서 검토위원별 분배 엔진."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import shutil

MGMT_PATTERN = re.compile(r"^(\d{4}-\d{4})")
INVALID_DIR_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')


def extract_mgmt_no(name: str) -> str | None:
    """폴더/파일명 시작 부분에서 관리번호를 추출한다."""
    match = MGMT_PATTERN.match(name)
    return match.group(1) if match else None


def _safe_dir_name(name: str) -> str:
    """검토위원명을 단일 폴더명으로 사용할 수 있게 정리한다."""
    safe = INVALID_DIR_CHARS.sub("_", name).strip().strip(".")
    return safe or "미지정"


def _remove_existing(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _transfer_item(source: Path, destination: Path, operation: str) -> None:
    if operation == "move":
        shutil.move(str(source), str(destination))
        return
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def distribute_by_folder_name(
    source_dir: str | Path,
    target_dir: str | Path,
    assignment: dict[str, str],
    *,
    dry_run: bool = False,
    operation: str = "move",
    overwrite: bool = False,
) -> dict:
    """소스 폴더의 항목을 검토위원별 폴더로 분배한다.

    소스 항목명은 `2025-0001_...`처럼 관리번호로 시작해야 한다.
    dry_run=True이면 실제 파일 이동/복사 없이 결과만 계산한다.
    """
    if operation not in {"move", "copy"}:
        raise ValueError("operation은 move 또는 copy만 가능합니다")

    source = Path(source_dir).expanduser()
    target = Path(target_dir).expanduser()

    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"접수 폴더가 존재하지 않습니다: {source}")
    if target.exists() and not target.is_dir():
        raise NotADirectoryError(f"배포 경로가 폴더가 아닙니다: {target}")
    source_resolved = source.resolve()
    target_resolved = target.resolve()
    if source_resolved == target_resolved:
        raise ValueError("접수 폴더와 배포 폴더는 같을 수 없습니다")
    if source_resolved in target_resolved.parents:
        raise ValueError("배포 폴더는 접수 폴더 밖에 있어야 합니다")

    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)

    details: list[dict] = []
    classified_mgmt_nos: list[str] = []
    reviewer_counts: Counter[str] = Counter()
    classified = 0
    skipped = 0

    for item in sorted(source.iterdir(), key=lambda p: p.name):
        item_resolved = item.resolve()
        if item_resolved == target_resolved:
            skipped += 1
            details.append({
                "status": "skipped",
                "item_name": item.name,
                "mgmt_no": None,
                "reviewer_name": None,
                "reviewer_dir_name": None,
                "destination": None,
                "reason": "배포 폴더는 분배 대상에서 제외됩니다",
            })
            continue

        mgmt_no = extract_mgmt_no(item.name)
        if not mgmt_no:
            skipped += 1
            details.append({
                "status": "skipped",
                "item_name": item.name,
                "mgmt_no": None,
                "reviewer_name": None,
                "reviewer_dir_name": None,
                "destination": None,
                "reason": "관리번호 인식 불가",
            })
            continue

        reviewer_name = assignment.get(mgmt_no)
        if not reviewer_name:
            skipped += 1
            details.append({
                "status": "skipped",
                "item_name": item.name,
                "mgmt_no": mgmt_no,
                "reviewer_name": None,
                "reviewer_dir_name": None,
                "destination": None,
                "reason": "검토위원 미배정",
            })
            continue

        reviewer_dir_name = _safe_dir_name(reviewer_name)
        reviewer_dir = target / reviewer_dir_name
        destination = reviewer_dir / item.name
        destination_resolved = destination.resolve()
        if target_resolved not in destination_resolved.parents:
            skipped += 1
            details.append({
                "status": "skipped",
                "item_name": item.name,
                "mgmt_no": mgmt_no,
                "reviewer_name": reviewer_name,
                "reviewer_dir_name": reviewer_dir_name,
                "destination": str(destination),
                "reason": "배포 폴더 밖으로 이동할 수 없습니다",
            })
            continue

        exists = destination.exists()
        if exists and not overwrite:
            skipped += 1
            details.append({
                "status": "skipped",
                "item_name": item.name,
                "mgmt_no": mgmt_no,
                "reviewer_name": reviewer_name,
                "reviewer_dir_name": reviewer_dir_name,
                "destination": str(destination),
                "reason": "대상에 같은 이름이 이미 있습니다",
            })
            continue

        if not dry_run:
            reviewer_dir.mkdir(parents=True, exist_ok=True)
            if exists:
                _remove_existing(destination)
            _transfer_item(item, destination, operation)

        status = "overwritten" if exists else operation
        classified += 1
        reviewer_counts[reviewer_name] += 1
        classified_mgmt_nos.append(mgmt_no)
        details.append({
            "status": status,
            "item_name": item.name,
            "mgmt_no": mgmt_no,
            "reviewer_name": reviewer_name,
            "reviewer_dir_name": reviewer_dir_name,
            "destination": str(destination),
            "reason": None,
        })

    return {
        "classified": classified,
        "skipped": skipped,
        "dry_run": dry_run,
        "operation": operation,
        "overwrite": overwrite,
        "assignment_count": len(assignment),
        "classified_mgmt_nos": list(dict.fromkeys(classified_mgmt_nos)),
        "reviewer_counts": dict(sorted(reviewer_counts.items())),
        "details": details,
    }
