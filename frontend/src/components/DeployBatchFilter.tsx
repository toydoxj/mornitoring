"use client"

import { useId } from "react"
import { DEPLOY_BATCH_NUMBERS, deployBatchLabel } from "@/types"

type DeployBatchFilterProps = {
  value: number | "all"
  onChange: (value: number | "all") => void
  /** 배포차수별 전체 건수 (키: "1"~"5"). 있으면 선택지에 건수를 함께 표시 */
  counts?: Record<string, number>
  label?: string
  className?: string
}

/** 배포차수(관리번호 일련번호 구간) 선택 필터. 통계·대시보드 공용. */
export function DeployBatchFilter({
  value,
  onChange,
  counts,
  label = "배포차수",
  className,
}: DeployBatchFilterProps) {
  const selectId = useId()
  const totalCount = counts
    ? DEPLOY_BATCH_NUMBERS.reduce((sum, batch) => sum + (counts[String(batch)] ?? 0), 0)
    : null

  const optionLabel = (batch: number) => {
    const count = counts?.[String(batch)]
    return count === undefined ? deployBatchLabel(batch) : `${deployBatchLabel(batch)} (${count})`
  }

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className ?? ""}`}>
      <label htmlFor={selectId} className="text-sm text-muted-foreground">
        {label}
      </label>
      <select
        id={selectId}
        className="rounded-md border px-3 py-2 text-sm"
        value={value}
        onChange={(event) => {
          const next = event.target.value
          onChange(next === "all" ? "all" : Number(next))
        }}
      >
        <option value="all">
          {totalCount === null ? "전체" : `전체 (${totalCount})`}
        </option>
        {DEPLOY_BATCH_NUMBERS.map((batch) => (
          <option key={batch} value={batch}>
            {optionLabel(batch)}
          </option>
        ))}
      </select>
    </div>
  )
}
