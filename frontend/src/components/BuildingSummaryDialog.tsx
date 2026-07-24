"use client"

import { useCallback, useEffect, useState, type ReactNode } from "react"
import { useRouter } from "next/navigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import apiClient from "@/lib/api/client"
import {
  PHASE_LABELS,
  RESULT_LABELS,
  type Building,
  type InappropriateDecisionType,
  type PhaseType,
  type ResultType,
} from "@/types"

interface GroupReviewerSummary {
  reviewer_id: number
  user_id: number
  name: string
  specialty: string | null
  phone: string | null
  is_assigned: boolean
  assigned_count: number
}

interface BuildingStageSummary {
  id: number
  phase: PhaseType
  phase_order: number
  doc_received_at: string | null
  doc_distributed_at: string | null
  report_submitted_at: string | null
  reviewer_name: string | null
  result: ResultType | null
  severity_l0_count: number
  severity_l1_count: number
  severity_l2_count: number
  severity_l3_count: number
  severity_l4_count: number
  inappropriate_review_needed: boolean
  inappropriate_decision: InappropriateDecisionType | null
}

interface BuildingSummary {
  building: Building
  group_no: number | null
  reviewer_name: string | null
  group_reviewers: GroupReviewerSummary[]
  stages: BuildingStageSummary[]
}

const STAGE_PHASE_LABELS: Record<PhaseType, string> = {
  preliminary: "예비검토",
  supplement_1: "1차 보완",
  supplement_2: "2차 보완",
  supplement_3: "3차 보완",
  supplement_4: "4차 보완",
  supplement_5: "5차 보완",
}

const RESULT_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pass: "default",
  simple_error: "secondary",
  recalculate: "destructive",
}

const DECISION_LABELS: Record<InappropriateDecisionType, string> = {
  pending: "대기",
  collapse_risk: "붕괴우려",
  confirmed_serious: "확정(심각)",
  confirmed_simple: "확정(단순)",
  excluded: "제외",
}

const FINAL_RESULT_LABELS: Record<string, string> = {
  pass: "적합",
  pass_supplement: "보완적합",
  fail_simple_error: "부적합(단순오류)",
  fail_recalculate: "부적합(재계산)",
  fail_no_response: "부적합(미회신)",
  excluded: "대상제외",
  fail: "부적합",
}

export function BuildingSummaryDialog({
  buildingId,
  onClose,
}: {
  buildingId: number | null
  onClose: () => void
}) {
  const router = useRouter()
  const [summary, setSummary] = useState<BuildingSummary | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadSummary = useCallback(async (id: number) => {
    setIsLoading(true)
    setError(null)
    try {
      const { data } = await apiClient.get<BuildingSummary>(
        `/api/buildings/${id}/summary`
      )
      setSummary(data)
    } catch (err) {
      console.error("건축물 요약 조회 실패:", err)
      setError(
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "건축물 정보를 불러오지 못했습니다"
      )
      setSummary(null)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (buildingId === null) {
      setSummary(null)
      setError(null)
      return
    }
    loadSummary(buildingId)
  }, [buildingId, loadSummary])

  const building = summary?.building

  return (
    <Dialog
      open={buildingId !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="max-h-[85vh] w-[min(1100px,calc(100vw-2rem))] max-w-none overflow-y-auto sm:max-w-none">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            <span className="font-mono">{building?.mgmt_no ?? "건축물 상세"}</span>
            {building?.building_name && (
              <span className="text-sm font-normal text-muted-foreground">
                {building.building_name}
              </span>
            )}
            {summary?.group_no != null && (
              <Badge variant="secondary">{summary.group_no}조</Badge>
            )}
          </DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <div className="py-16 text-center text-muted-foreground">불러오는 중...</div>
        ) : error ? (
          <div className="py-16 text-center text-sm text-destructive">{error}</div>
        ) : !summary || !building ? (
          <div className="py-16 text-center text-muted-foreground">
            표시할 정보가 없습니다.
          </div>
        ) : (
          <div className="space-y-5">
            <section className="grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
              <InfoRow label="주소">{building.full_address || "-"}</InfoRow>
              <InfoRow label="연면적">
                {building.gross_area != null
                  ? `${building.gross_area.toLocaleString(undefined, { maximumFractionDigits: 2 })} ㎡`
                  : "-"}
              </InfoRow>
              <InfoRow label="층수">
                지상 {building.floors_above ?? "-"} / 지하 {building.floors_below ?? "-"}
              </InfoRow>
              <InfoRow label="주구조">{building.main_structure || "-"}</InfoRow>
              <InfoRow label="주용도">{building.main_usage || "-"}</InfoRow>
              <InfoRow label="내진등급">{building.seismic_level || "-"}</InfoRow>
              <InfoRow label="책임구조기술자">
                {building.struct_eng_name || "-"}
                {building.struct_eng_firm && (
                  <span className="ml-1 text-xs text-muted-foreground">
                    ({building.struct_eng_firm})
                  </span>
                )}
              </InfoRow>
              <InfoRow label="현재 단계">
                {building.current_phase
                  ? PHASE_LABELS[building.current_phase] || building.current_phase
                  : "-"}
              </InfoRow>
              <InfoRow label="최종판정">
                {building.final_result ? (
                  <Badge variant={building.final_result === "pass" ? "default" : "outline"}>
                    {FINAL_RESULT_LABELS[building.final_result] || building.final_result}
                  </Badge>
                ) : (
                  "-"
                )}
              </InfoRow>
              <InfoRow label="고위험군">
                <HighRiskTags building={building} />
              </InfoRow>
            </section>

            <section className="space-y-2">
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="text-sm font-semibold">
                  {summary.group_no != null ? `${summary.group_no}조 검토위원 명단` : "검토위원"}
                </h3>
                <span className="text-xs text-muted-foreground">
                  담당 검토위원: {summary.reviewer_name || "미배정"}
                </span>
              </div>
              {summary.group_reviewers.length === 0 ? (
                <div className="rounded-md border py-6 text-center text-sm text-muted-foreground">
                  {summary.group_no == null
                    ? "조가 배정되지 않아 명단을 표시할 수 없습니다."
                    : "해당 조에 등록된 검토위원이 없습니다."}
                </div>
              ) : (
                <div className="overflow-x-auto rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="min-w-[120px]">이름</TableHead>
                        <TableHead className="min-w-[140px]">전문분야</TableHead>
                        <TableHead className="min-w-[120px]">연락처</TableHead>
                        <TableHead className="w-[110px] text-center">담당 건수</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {summary.group_reviewers.map((reviewer) => (
                        <TableRow
                          key={reviewer.reviewer_id}
                          className={reviewer.is_assigned ? "bg-blue-50/60" : undefined}
                        >
                          <TableCell className="font-medium">
                            {reviewer.name}
                            {reviewer.is_assigned && (
                              <Badge className="ml-2" variant="default">
                                담당
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {reviewer.specialty || "-"}
                          </TableCell>
                          <TableCell className="font-mono text-sm">
                            {reviewer.phone || "-"}
                          </TableCell>
                          <TableCell className="text-center">
                            {reviewer.assigned_count.toLocaleString()}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </section>

            <section className="space-y-2">
              <h3 className="text-sm font-semibold">검토 단계 이력</h3>
              {summary.stages.length === 0 ? (
                <div className="rounded-md border py-6 text-center text-sm text-muted-foreground">
                  등록된 검토 단계가 없습니다.
                </div>
              ) : (
                <div className="overflow-x-auto rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="min-w-[100px]">단계</TableHead>
                        <TableHead className="min-w-[110px]">검토자</TableHead>
                        <TableHead className="w-[110px] text-center">도서접수</TableHead>
                        <TableHead className="w-[110px] text-center">검토서제출</TableHead>
                        <TableHead className="w-[100px] text-center">판정</TableHead>
                        <TableHead className="min-w-[160px] text-center">심각도(L0~L4)</TableHead>
                        <TableHead className="w-[120px] text-center">부적합 검토</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {summary.stages.map((stage) => (
                        <TableRow key={stage.id}>
                          <TableCell>
                            <Badge variant="outline">
                              {STAGE_PHASE_LABELS[stage.phase] || stage.phase}
                            </Badge>
                          </TableCell>
                          <TableCell className="font-medium">
                            {stage.reviewer_name || "-"}
                          </TableCell>
                          <TableCell className="text-center text-sm">
                            {stage.doc_received_at || "-"}
                          </TableCell>
                          <TableCell className="text-center text-sm">
                            {stage.report_submitted_at || "-"}
                          </TableCell>
                          <TableCell className="text-center">
                            {stage.result ? (
                              <Badge variant={RESULT_VARIANT[stage.result] || "outline"}>
                                {RESULT_LABELS[stage.result] || stage.result}
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </TableCell>
                          <TableCell className="text-center font-mono text-sm">
                            {[
                              stage.severity_l0_count,
                              stage.severity_l1_count,
                              stage.severity_l2_count,
                              stage.severity_l3_count,
                              stage.severity_l4_count,
                            ].join(" / ")}
                          </TableCell>
                          <TableCell className="text-center">
                            {stage.inappropriate_review_needed ? (
                              <Badge
                                variant={
                                  stage.inappropriate_decision === "collapse_risk"
                                    ? "destructive"
                                    : stage.inappropriate_decision === "excluded"
                                      ? "outline"
                                      : "secondary"
                                }
                              >
                                {DECISION_LABELS[stage.inappropriate_decision ?? "pending"]}
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </section>

            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => router.push(`/buildings/${building.id}?from=statistics`)}
              >
                상세 페이지 열기
              </Button>
              <Button variant="ghost" onClick={onClose}>
                닫기
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-2 border-b py-1.5 text-sm last:border-b-0">
      <span className="w-[110px] shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 flex-1 break-words font-medium">{children}</span>
    </div>
  )
}

function HighRiskTags({ building }: { building: Building }) {
  const tags: string[] = []
  if (building.is_special_structure) tags.push("특수")
  if (building.is_high_rise) tags.push("고층")
  if (building.is_multi_use) tags.push("다중이용")
  if (building.is_quasi_multi_use) tags.push("준다중이용")

  if (tags.length === 0) {
    return <span className="text-muted-foreground">-</span>
  }
  return (
    <span className="flex flex-wrap gap-1">
      {tags.map((tag) => (
        <Badge key={tag} variant="outline">
          {tag}
        </Badge>
      ))}
    </span>
  )
}
