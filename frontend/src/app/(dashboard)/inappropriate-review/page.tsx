"use client"

import { useCallback, useEffect, useState, type ReactNode } from "react"
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { BuildingDetailDialog } from "@/components/BuildingDetailDialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import apiClient from "@/lib/api/client"
import { RESULT_LABELS, type ResultType } from "@/types"
import { useAuthStore } from "@/stores/authStore"

// 지적단계(검토서 제출 단계) 전용 짧은 한글 라벨
const INDICATION_PHASE_LABELS: Record<string, string> = {
  preliminary: "예비검토",
  supplement_1: "보완검토 1차",
  supplement_2: "보완검토 2차",
  supplement_3: "보완검토 3차",
  supplement_4: "보완검토 4차",
  supplement_5: "보완검토 5차",
}

const PHASE_SORT_ORDER: Record<string, number> = {
  preliminary: 0,
  supplement_1: 1,
  supplement_2: 2,
  supplement_3: 3,
  supplement_4: 4,
  supplement_5: 5,
}

type Decision =
  | "pending"
  | "collapse_risk"
  | "confirmed_serious"
  | "confirmed_simple"
  | "excluded"

type SortKey =
  | "mgmt_no"
  | "group_no"
  | "reviewer_name"
  | "full_address"
  | "gross_area"
  | "floors_above"
  | "high_risk"
  | "phase"
  | "latest_result"
  | "decision"

type SortDirection = "asc" | "desc"

interface SortState {
  key: SortKey
  direction: SortDirection
}

interface InappropriateItem {
  stage_id: number
  building_id: number
  mgmt_no: string
  building_name: string | null
  full_address: string | null
  gross_area: number | null
  floors_above: number | null
  is_special_structure: boolean | null
  is_high_rise: boolean | null
  is_multi_use: boolean | null
  current_phase: string | null
  latest_result: string | null
  inappropriate_decision: Decision
  latest_note: string | null
  latest_note_author: string | null
  note_count: number
  phase: string
  group_no: number | null
  reviewer_name: string | null
}

const RESULT_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pass: "default",
  simple_error: "secondary",
  recalculate: "destructive",
}

const RESULT_SORT_ORDER: Record<string, number> = {
  recalculate: 0,
  simple_error: 1,
  pass: 2,
}

const DECISION_FILTERS: { value: "all" | Decision; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "pending", label: "대기" },
  { value: "collapse_risk", label: "붕괴우려" },
  { value: "confirmed_serious", label: "확정(심각)" },
  { value: "confirmed_simple", label: "확정(단순)" },
  { value: "excluded", label: "제외" },
]

const DECISION_LABELS: Record<Decision, string> = {
  pending: "대기",
  collapse_risk: "붕괴우려",
  confirmed_serious: "확정(심각)",
  confirmed_simple: "확정(단순)",
  excluded: "제외",
}

// 심각한 판정이 위로 오도록 정렬 순서를 정의한다.
const DECISION_SORT_ORDER: Record<Decision, number> = {
  collapse_risk: 0,
  confirmed_serious: 1,
  confirmed_simple: 2,
  pending: 3,
  excluded: 4,
}

const TEXT_COLLATOR = new Intl.Collator("ko-KR", {
  numeric: true,
  sensitivity: "base",
})

export default function InappropriateReviewPage() {
  const user = useAuthStore((s) => s.user)
  const [detailBuildingId, setDetailBuildingId] = useState<number | null>(null)
  const [items, setItems] = useState<InappropriateItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [filter, setFilter] = useState<"all" | Decision>("all")
  const [updating, setUpdating] = useState<number | null>(null)
  const [sortState, setSortState] = useState<SortState>({
    key: "decision",
    direction: "asc",
  })
  const canEditDecision =
    !!user && ["team_leader", "chief_secretary", "secretary"].includes(user.role)
  const tableColumnCount = canEditDecision ? 14 : 10

  const fetchData = useCallback(async () => {
    setIsLoading(true)
    try {
      const params: Record<string, string> = {}
      if (filter !== "all") params.decision = filter
      const { data } = await apiClient.get<{ items: InappropriateItem[]; total: number }>(
        "/api/reviews/inappropriate",
        { params }
      )
      setItems(data.items)
    } catch (err) {
      console.error("부적합 대상 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }, [filter])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const handleDecision = async (stageId: number, decision: Decision) => {
    setUpdating(stageId)
    try {
      await apiClient.patch(`/api/reviews/inappropriate/${stageId}`, { decision })
      fetchData()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "변경 실패"
      alert(msg)
    } finally {
      setUpdating(null)
    }
  }

  const handleSort = (key: SortKey) => {
    setSortState((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }))
  }

  const sortedItems = [...items].sort((a, b) => compareItems(a, b, sortState))

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">부적합 대상 검토</h1>
        <p className="text-sm text-muted-foreground">
          검토위원이 &ldquo;부적정 사례 검토 필요&rdquo; 체크한 검토 건 ({items.length}건) — 조 구분 없이 전체 표시
        </p>
      </div>

      <div className="flex flex-wrap gap-1">
        {DECISION_FILTERS.map((f) => (
          <Button
            key={f.value}
            size="sm"
            variant={filter === f.value ? "default" : "outline"}
            onClick={() => setFilter(f.value)}
          >
            {f.label}
          </Button>
        ))}
      </div>

      <div className="rounded-md border bg-white overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <SortableHead
                sortKey="mgmt_no"
                sortState={sortState}
                onSort={handleSort}
                className="w-[130px]"
              >
                관리번호
              </SortableHead>
              <SortableHead
                sortKey="group_no"
                sortState={sortState}
                onSort={handleSort}
                className="w-[70px]"
              >
                조
              </SortableHead>
              <SortableHead
                sortKey="reviewer_name"
                sortState={sortState}
                onSort={handleSort}
                className="w-[110px]"
              >
                검토위원
              </SortableHead>
              <SortableHead
                sortKey="full_address"
                sortState={sortState}
                onSort={handleSort}
                align="left"
                className="w-[220px]"
              >
                주소
              </SortableHead>
              <SortableHead
                sortKey="gross_area"
                sortState={sortState}
                onSort={handleSort}
                className="w-[110px]"
              >
                연면적(㎡)
              </SortableHead>
              <SortableHead
                sortKey="floors_above"
                sortState={sortState}
                onSort={handleSort}
                className="w-[80px]"
              >
                지상층
              </SortableHead>
              <SortableHead
                sortKey="high_risk"
                sortState={sortState}
                onSort={handleSort}
                className="w-[120px]"
              >
                고위험군
              </SortableHead>
              <SortableHead
                sortKey="phase"
                sortState={sortState}
                onSort={handleSort}
                className="w-[120px]"
              >
                지적단계
              </SortableHead>
              <SortableHead
                sortKey="latest_result"
                sortState={sortState}
                onSort={handleSort}
                className="w-[90px]"
              >
                최근판정
              </SortableHead>
              {canEditDecision ? (
                <>
                  <SortableHead
                    sortKey="decision"
                    sortState={sortState}
                    onSort={handleSort}
                    className="w-[90px]"
                  >
                    붕괴우려
                  </SortableHead>
                  <TableHead className="w-[90px] text-center">확정(심각)</TableHead>
                  <TableHead className="w-[90px] text-center">확정(단순)</TableHead>
                  <TableHead className="w-[80px] text-center">대기</TableHead>
                  <TableHead className="w-[80px] text-center">제외</TableHead>
                </>
              ) : (
                <SortableHead
                  sortKey="decision"
                  sortState={sortState}
                  onSort={handleSort}
                  className="w-[120px]"
                >
                  판정
                </SortableHead>
              )}
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={tableColumnCount} className="h-32 text-center">
                  로딩 중...
                </TableCell>
              </TableRow>
            ) : sortedItems.length === 0 ? (
              <TableRow>
                <TableCell colSpan={tableColumnCount} className="h-32 text-center text-muted-foreground">
                  부적합 검토 대상이 없습니다
                </TableCell>
              </TableRow>
            ) : (
              sortedItems.map((b) => {
                const d = b.inappropriate_decision
                return (
                  <TableRow
                    key={b.stage_id}
                    className="cursor-pointer hover:bg-muted/30"
                    onClick={() => setDetailBuildingId(b.building_id)}
                  >
                    <TableCell className="font-mono font-medium text-blue-600 text-center">
                      {b.mgmt_no}
                    </TableCell>
                    <TableCell className="text-center">
                      {b.group_no ? `${b.group_no}조` : "-"}
                    </TableCell>
                    <TableCell className="text-center text-sm font-medium">
                      {b.reviewer_name || "-"}
                    </TableCell>
                    <TableCell className="text-sm max-w-[220px]">
                      <div className="truncate" title={b.building_name ?? undefined}>
                        {b.full_address || "-"}
                      </div>
                      {b.latest_note && (
                        <div
                          className="mt-1 truncate text-xs text-muted-foreground"
                          title={b.latest_note}
                        >
                          💬 [{b.latest_note_author}] {b.latest_note}
                          {b.note_count > 1 && (
                            <span className="ml-1 text-orange-600">+{b.note_count - 1}</span>
                          )}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="text-center">
                      {b.gross_area?.toLocaleString() ?? "-"}
                    </TableCell>
                    <TableCell className="text-center">{b.floors_above ?? "-"}</TableCell>
                    <TableCell className="text-sm text-center">
                      {(() => {
                        const tags = highRiskTags(b)
                        return tags.length > 0 ? (
                          <div className="flex flex-wrap justify-center gap-1">
                            {tags.map((t) => (
                              <Badge key={t} variant="outline" className="text-xs">
                                {t}
                              </Badge>
                            ))}
                          </div>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )
                      })()}
                    </TableCell>
                    <TableCell className="text-sm text-center">
                      {INDICATION_PHASE_LABELS[b.phase] || b.phase}
                    </TableCell>
                    <TableCell className="text-center">
                      {b.latest_result ? (
                        <Badge variant={RESULT_VARIANT[b.latest_result] || "outline"}>
                          {RESULT_LABELS[b.latest_result as ResultType] || b.latest_result}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </TableCell>
                    {canEditDecision ? (
                      <>
                        {/* 붕괴우려 (확정(심각) 상위) */}
                        <TableCell className="text-center" onClick={(e) => e.stopPropagation()}>
                          <Button
                            size="sm"
                            variant={d === "collapse_risk" ? "destructive" : "outline"}
                            onClick={() => handleDecision(b.stage_id, "collapse_risk")}
                            loading={updating === b.stage_id && d !== "collapse_risk"}
                          >
                            붕괴우려
                          </Button>
                        </TableCell>
                        {/* 확정(심각) */}
                        <TableCell className="text-center" onClick={(e) => e.stopPropagation()}>
                          <Button
                            size="sm"
                            variant={d === "confirmed_serious" ? "default" : "outline"}
                            onClick={() => handleDecision(b.stage_id, "confirmed_serious")}
                          >
                            확정(심각)
                          </Button>
                        </TableCell>
                        {/* 확정(단순) */}
                        <TableCell className="text-center" onClick={(e) => e.stopPropagation()}>
                          <Button
                            size="sm"
                            variant={d === "confirmed_simple" ? "default" : "outline"}
                            onClick={() => handleDecision(b.stage_id, "confirmed_simple")}
                          >
                            확정(단순)
                          </Button>
                        </TableCell>
                        {/* 대기 */}
                        <TableCell className="text-center" onClick={(e) => e.stopPropagation()}>
                          <Button
                            size="sm"
                            variant={d === "pending" ? "default" : "outline"}
                            onClick={() => handleDecision(b.stage_id, "pending")}
                          >
                            대기
                          </Button>
                        </TableCell>
                        {/* 제외 */}
                        <TableCell className="text-center" onClick={(e) => e.stopPropagation()}>
                          <Button
                            size="sm"
                            variant={d === "excluded" ? "destructive" : "outline"}
                            onClick={() => handleDecision(b.stage_id, "excluded")}
                          >
                            제외
                          </Button>
                        </TableCell>
                      </>
                    ) : (
                      <TableCell className="text-center">
                        <Badge
                          variant={
                            d === "collapse_risk" || d === "excluded"
                              ? "destructive"
                              : "outline"
                          }
                        >
                          {DECISION_LABELS[d]}
                        </Badge>
                      </TableCell>
                    )}
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      </div>
      {items.length > 0 && canEditDecision && (
        <p className="text-xs text-muted-foreground">
          행을 클릭하면 상세 화면이 팝업으로 열립니다. 현재 선택된 판정은 진하게 표시되며, 붕괴우려는 확정(심각)보다 상위 단계입니다.
        </p>
      )}

      <BuildingDetailDialog
        buildingId={detailBuildingId}
        onClose={() => {
          setDetailBuildingId(null)
          fetchData()
        }}
      />
    </div>
  )
}

function SortableHead({
  sortKey,
  sortState,
  onSort,
  children,
  align = "center",
  className = "",
}: {
  sortKey: SortKey
  sortState: SortState
  onSort: (key: SortKey) => void
  children: ReactNode
  align?: "left" | "center" | "right"
  className?: string
}) {
  const isActive = sortState.key === sortKey
  const Icon = isActive ? (sortState.direction === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown
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
    <TableHead aria-sort={ariaSort} className={className}>
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

function highRiskTags(item: InappropriateItem) {
  const tags: string[] = []
  if (item.is_special_structure) tags.push("특수")
  if (item.is_high_rise) tags.push("고층")
  if (item.is_multi_use) tags.push("다중이용")
  return tags
}

function compareItems(a: InappropriateItem, b: InappropriateItem, sortState: SortState) {
  const aValue = getSortValue(a, sortState.key)
  const bValue = getSortValue(b, sortState.key)
  const direction = sortState.direction === "asc" ? 1 : -1
  const primary =
    typeof aValue === "string" || typeof bValue === "string"
      ? TEXT_COLLATOR.compare(String(aValue), String(bValue))
      : aValue - bValue

  if (primary !== 0) return primary * direction
  return TEXT_COLLATOR.compare(a.mgmt_no, b.mgmt_no)
}

function getSortValue(item: InappropriateItem, key: SortKey): string | number {
  switch (key) {
    case "mgmt_no":
      return item.mgmt_no
    case "group_no":
      return item.group_no ?? Number.MAX_SAFE_INTEGER
    case "reviewer_name":
      return item.reviewer_name || "힣"
    case "full_address":
      return item.full_address || "힣"
    case "gross_area":
      return item.gross_area ?? -1
    case "floors_above":
      return item.floors_above ?? -1
    case "high_risk":
      return -highRiskTags(item).length
    case "phase":
      return PHASE_SORT_ORDER[item.phase] ?? Number.MAX_SAFE_INTEGER
    case "latest_result":
      return item.latest_result
        ? RESULT_SORT_ORDER[item.latest_result] ?? Number.MAX_SAFE_INTEGER
        : Number.MAX_SAFE_INTEGER
    case "decision":
      return DECISION_SORT_ORDER[item.inappropriate_decision] ?? Number.MAX_SAFE_INTEGER
  }
}
