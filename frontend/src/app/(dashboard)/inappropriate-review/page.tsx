"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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

// 지적단계(검토서 제출 단계) 전용 짧은 한글 라벨
const INDICATION_PHASE_LABELS: Record<string, string> = {
  preliminary: "예비검토",
  supplement_1: "보완검토 1차",
  supplement_2: "보완검토 2차",
  supplement_3: "보완검토 3차",
  supplement_4: "보완검토 4차",
  supplement_5: "보완검토 5차",
}

type Decision = "pending" | "confirmed_serious" | "confirmed_simple" | "excluded"

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
  phase: string
}

const RESULT_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pass: "default",
  simple_error: "secondary",
  recalculate: "destructive",
}

const DECISION_FILTERS: { value: "all" | Decision; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "pending", label: "대기" },
  { value: "confirmed_serious", label: "확정(심각)" },
  { value: "confirmed_simple", label: "확정(단순)" },
  { value: "excluded", label: "제외" },
]

const DECISION_LABELS: Record<Decision, string> = {
  pending: "대기",
  confirmed_serious: "확정(심각)",
  confirmed_simple: "확정(단순)",
  excluded: "제외",
}

export default function InappropriateReviewPage() {
  const router = useRouter()
  const [items, setItems] = useState<InappropriateItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [filter, setFilter] = useState<"all" | Decision>("all")
  const [updating, setUpdating] = useState<number | null>(null)

  const fetchData = async () => {
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
  }

  useEffect(() => {
    fetchData()
  }, [filter])

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

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">부적합 대상 검토</h1>
        <p className="text-sm text-muted-foreground">
          검토위원이 "부적정 사례 검토 필요" 체크한 검토 건 ({items.length}건)
        </p>
      </div>

      <div className="flex gap-1">
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
              <TableHead className="w-[120px] text-center">관리번호</TableHead>
              <TableHead className="w-[220px]">주소</TableHead>
              <TableHead className="w-[100px] text-center">연면적(㎡)</TableHead>
              <TableHead className="w-[80px] text-center">지상층</TableHead>
              <TableHead className="w-[120px] text-center">고위험군</TableHead>
              <TableHead className="w-[120px] text-center">지적단계</TableHead>
              <TableHead className="w-[90px] text-center">최근판정</TableHead>
              <TableHead className="w-[90px] text-center">확정(심각)</TableHead>
              <TableHead className="w-[90px] text-center">확정(단순)</TableHead>
              <TableHead className="w-[80px] text-center">대기</TableHead>
              <TableHead className="w-[80px] text-center">제외</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={11} className="h-32 text-center">
                  로딩 중...
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={11} className="h-32 text-center text-muted-foreground">
                  부적합 검토 대상이 없습니다
                </TableCell>
              </TableRow>
            ) : (
              items.map((b) => {
                const d = b.inappropriate_decision
                return (
                  <TableRow
                    key={b.stage_id}
                    className="cursor-pointer hover:bg-muted/30"
                    onClick={() => router.push(`/buildings/${b.building_id}?from=inappropriate-review`)}
                  >
                    <TableCell className="font-mono font-medium text-blue-600 text-center">
                      {b.mgmt_no}
                    </TableCell>
                    <TableCell className="text-sm max-w-[220px] truncate" title={b.building_name ?? undefined}>
                      {b.full_address || "-"}
                    </TableCell>
                    <TableCell className="text-center">
                      {b.gross_area?.toLocaleString() ?? "-"}
                    </TableCell>
                    <TableCell className="text-center">{b.floors_above ?? "-"}</TableCell>
                    <TableCell className="text-sm text-center">
                      {(() => {
                        const tags: string[] = []
                        if (b.is_special_structure) tags.push("특수")
                        if (b.is_high_rise) tags.push("고층")
                        if (b.is_multi_use) tags.push("다중이용")
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
                    {/* 확정(심각) */}
                    <TableCell className="text-center" onClick={(e) => e.stopPropagation()}>
                      <Button
                        size="sm"
                        variant={d === "confirmed_serious" ? "default" : "outline"}
                        onClick={() => handleDecision(b.stage_id, "confirmed_serious")}
                        loading={updating === b.stage_id && d !== "confirmed_serious"}
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
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      </div>
      {items.length > 0 && (
        <p className="text-xs text-muted-foreground">
          현재 선택된 판정은 진하게 표시됩니다. 언제든 다른 상태로 변경 가능합니다.
        </p>
      )}
      {/* DECISION_LABELS 참조 제거 경고 방지 */}
      <span className="hidden">{JSON.stringify(DECISION_LABELS)}</span>
    </div>
  )
}
