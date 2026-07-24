"use client"

import { useState, type ReactNode } from "react"
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"
import { TableHead } from "@/components/ui/table"

export type SortDirection = "asc" | "desc"

export interface SortState<K extends string> {
  key: K
  direction: SortDirection
}

/** 한글/숫자 혼용 정렬용 공통 collator */
export const TABLE_SORT_COLLATOR = new Intl.Collator("ko-KR", {
  numeric: true,
  sensitivity: "base",
})

/**
 * 표 헤더 정렬 상태 훅.
 *
 * - `initial` 미지정 시 정렬하지 않은 원본 순서를 유지한다.
 * - `numericKeys` 에 넣은 열은 첫 클릭에서 내림차순(큰 값 우선)으로 시작한다.
 */
export function useTableSort<K extends string>(options?: {
  initial?: SortState<K>
  numericKeys?: readonly K[]
}) {
  const [sortState, setSortState] = useState<SortState<K> | null>(
    options?.initial ?? null
  )
  const numericKeys = options?.numericKeys ?? []

  const handleSort = (key: K) => {
    setSortState((current) => {
      if (current && current.key === key) {
        return { key, direction: current.direction === "asc" ? "desc" : "asc" }
      }
      return { key, direction: numericKeys.includes(key) ? "desc" : "asc" }
    })
  }

  return { sortState, handleSort }
}

/**
 * 정렬 상태에 따라 행을 정렬한다. 정렬 상태가 없으면 원본 배열을 그대로 돌려준다.
 *
 * @param getValue 열별 정렬 값. 문자열이면 collator, 숫자면 대소 비교를 쓴다.
 * @param tiebreak 값이 같을 때의 보조 비교 (정렬 방향의 영향을 받지 않는다).
 */
export function sortRowsBy<T, K extends string>(
  rows: T[],
  sortState: SortState<K> | null,
  getValue: (row: T, key: K) => string | number,
  tiebreak?: (a: T, b: T) => number,
): T[] {
  if (!sortState) return rows
  const direction = sortState.direction === "asc" ? 1 : -1

  return [...rows].sort((a, b) => {
    const aValue = getValue(a, sortState.key)
    const bValue = getValue(b, sortState.key)
    const primary =
      typeof aValue === "string" || typeof bValue === "string"
        ? TABLE_SORT_COLLATOR.compare(String(aValue), String(bValue))
        : aValue - bValue

    if (primary !== 0) return primary * direction
    return tiebreak ? tiebreak(a, b) : 0
  })
}

/** 클릭으로 정렬되는 표 헤더 셀. */
export function SortableTableHead<K extends string>({
  sortKey,
  sortState,
  onSort,
  children,
  align = "center",
  className = "",
  rowSpan,
}: {
  sortKey: K
  sortState: SortState<K> | null
  onSort: (key: K) => void
  children: ReactNode
  align?: "left" | "center" | "right"
  className?: string
  rowSpan?: number
}) {
  const isActive = sortState?.key === sortKey
  const Icon = isActive
    ? sortState.direction === "asc"
      ? ArrowUp
      : ArrowDown
    : ArrowUpDown
  const ariaSort = isActive
    ? sortState.direction === "asc"
      ? "ascending"
      : "descending"
    : "none"
  const justifyClass = {
    left: "justify-start",
    center: "justify-center",
    right: "justify-end",
  }[align]

  return (
    <TableHead rowSpan={rowSpan} aria-sort={ariaSort} className={className}>
      <button
        type="button"
        className={`inline-flex w-full items-center gap-1 ${justifyClass} rounded px-1 py-1 text-sm font-medium hover:bg-muted`}
        onClick={() => onSort(sortKey)}
      >
        <span>{children}</span>
        <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
      </button>
    </TableHead>
  )
}
