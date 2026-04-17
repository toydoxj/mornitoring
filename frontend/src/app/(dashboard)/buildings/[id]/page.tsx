"use client"

import { useEffect, useState } from "react"
import { useParams, useRouter, useSearchParams } from "next/navigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import apiClient from "@/lib/api/client"
import { useAuthStore } from "@/stores/authStore"
import type { Building, ReviewStage, PhaseType, ResultType } from "@/types"
import { PHASE_LABELS, RESULT_LABELS } from "@/types"

const RESULT_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pass: "default",
  supplement: "secondary",
  fail: "destructive",
  minor: "outline",
}

export default function BuildingDetailPage() {
  const params = useParams()
  const router = useRouter()
  const searchParams = useSearchParams()
  const from = searchParams.get("from")
  const user = useAuthStore((s) => s.user)
  const backPath = from === "my-reviews" ? "/my-reviews" : "/buildings"
  const backLabel = from === "my-reviews" ? "← 내 검토 대상" : "← 목록으로"
  const [building, setBuilding] = useState<Building | null>(null)
  const [stages, setStages] = useState<ReviewStage[]>([])
  const [inquiries, setInquiries] = useState<{
    id: number; phase: string; submitter_name: string; content: string;
    reply: string | null; status: string; created_at: string
  }[]>([])
  const [newInquiry, setNewInquiry] = useState("")
  const [submittingInquiry, setSubmittingInquiry] = useState(false)
  const [isLoading, setIsLoading] = useState(true)

  const canManage = user && ["team_leader", "chief_secretary", "secretary"].includes(user.role)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [buildingRes, stagesRes] = await Promise.all([
          apiClient.get<Building>(`/api/buildings/${params.id}`),
          apiClient.get<ReviewStage[]>(`/api/reviews/stages/${params.id}`),
        ])
        setBuilding(buildingRes.data)
        setStages(stagesRes.data)

        // 문의사항 조회
        try {
          const { data: inqData } = await apiClient.get(`/api/reviews/building-inquiries/${buildingRes.data.mgmt_no}`)
          setInquiries(inqData)
        } catch { /* 문의 없음 */ }
      } catch {
        router.push("/buildings")
      } finally {
        setIsLoading(false)
      }
    }
    fetchData()
  }, [params.id, router])

  const handleAdvance = async () => {
    try {
      await apiClient.post(`/api/reviews/advance/${params.id}`)
      // 새로고침
      const [buildingRes, stagesRes] = await Promise.all([
        apiClient.get<Building>(`/api/buildings/${params.id}`),
        apiClient.get<ReviewStage[]>(`/api/reviews/stages/${params.id}`),
      ])
      setBuilding(buildingRes.data)
      setStages(stagesRes.data)
    } catch (err) {
      console.error("단계 전환 실패:", err)
    }
  }

  const handleSubmitInquiry = async () => {
    if (!building || !newInquiry.trim()) return
    setSubmittingInquiry(true)
    try {
      await apiClient.post("/api/reviews/inquiry", {
        mgmt_no: building.mgmt_no,
        phase: building.current_phase || "preliminary",
        content: newInquiry.trim(),
      })
      setNewInquiry("")
      // 문의 새로고침
      const { data: inqData } = await apiClient.get(`/api/reviews/building-inquiries/${building.mgmt_no}`)
      setInquiries(inqData)
    } catch {
      alert("문의 등록 실패")
    } finally {
      setSubmittingInquiry(false)
    }
  }

  if (isLoading) {
    return <div className="flex justify-center py-20 text-muted-foreground">로딩 중...</div>
  }

  if (!building) return null

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <div>
          <Button variant="ghost" size="sm" onClick={() => router.push(backPath)}>
            {backLabel}
          </Button>
          <h1 className="mt-2 text-2xl font-bold">
            <span className="font-mono">{building.mgmt_no}</span>
            {building.building_name && (
              <span className="ml-3 text-muted-foreground">{building.building_name}</span>
            )}
          </h1>
        </div>
        <div className="flex gap-2">
          {building.current_phase && (
            <Badge variant="outline" className="text-base px-3 py-1">
              {PHASE_LABELS[building.current_phase as PhaseType] || building.current_phase}
            </Badge>
          )}
          {building.final_result && (
            <Badge variant={RESULT_VARIANT[building.final_result] || "outline"} className="text-base px-3 py-1">
              최종: {RESULT_LABELS[building.final_result as ResultType] || building.final_result}
            </Badge>
          )}
        </div>
      </div>

      {/* 기본 정보 */}
      <Card>
        <CardHeader>
          <CardTitle>건축물 기본정보</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
            <InfoItem label="시도" value={building.sido} />
            <InfoItem label="시군구" value={building.sigungu} />
            <InfoItem label="법정동" value={building.beopjeongdong} />
            <InfoItem label="주구조" value={building.main_structure} />
            <InfoItem label="주용도" value={building.main_usage} />
            <InfoItem label="연면적" value={building.gross_area ? `${building.gross_area.toLocaleString()} ㎡` : null} />
            <InfoItem label="지상층수" value={building.floors_above?.toString()} />
            <InfoItem label="지하층수" value={building.floors_below?.toString()} />
            <InfoItem label="고위험유형" value={building.high_risk_type} />
          </div>
        </CardContent>
      </Card>

      {/* 검토 진행 타임라인 */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>검토 진행 현황</CardTitle>
          {canManage && !building.final_result && (
            <Button size="sm" onClick={handleAdvance}>
              다음 단계로 전환
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {stages.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              아직 검토 이력이 없습니다
            </p>
          ) : (
            <div className="space-y-4">
              {stages.map((stage, idx) => (
                <div key={stage.id}>
                  {idx > 0 && <Separator className="my-4" />}
                  <div className="flex items-start gap-4">
                    {/* 단계 라벨 */}
                    <div className="w-24 shrink-0">
                      <Badge
                        variant={stage.result ? (RESULT_VARIANT[stage.result] || "outline") : "outline"}
                        className="w-full justify-center"
                      >
                        {PHASE_LABELS[stage.phase as PhaseType] || stage.phase}
                      </Badge>
                    </div>

                    {/* 상세 정보 */}
                    <div className="flex-1 space-y-2 text-sm">
                      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                        {stage.doc_received_at && (
                          <InfoItem label="도서접수일" value={stage.doc_received_at} />
                        )}
                        {stage.report_submitted_at && (
                          <InfoItem label="검토서 제출일" value={stage.report_submitted_at} />
                        )}
                        {stage.reviewer_name && (
                          <InfoItem label="검토자" value={stage.reviewer_name} />
                        )}
                        {stage.result && (
                          <InfoItem
                            label="판정결과"
                            value={RESULT_LABELS[stage.result as ResultType] || stage.result}
                          />
                        )}
                      </div>

                      {/* 부적합 유형 */}
                      {(stage.defect_type_1 || stage.defect_type_2 || stage.defect_type_3) && (
                        <div>
                          <dt className="text-muted-foreground mb-1">부적합 유형</dt>
                          <div className="flex flex-wrap gap-1">
                            {[stage.defect_type_1, stage.defect_type_2, stage.defect_type_3]
                              .filter(Boolean)
                              .map((dt, i) => (
                                <Badge key={i} variant="destructive" className="text-xs">
                                  {dt}
                                </Badge>
                              ))}
                          </div>
                        </div>
                      )}

                      {/* 검토의견 */}
                      {stage.review_opinion && (
                        <div>
                          <dt className="text-muted-foreground mb-1">검토의견</dt>
                          <div className="rounded-md bg-muted p-3 text-sm whitespace-pre-wrap break-words max-h-60 overflow-y-auto">
                            {stage.review_opinion}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 문의사항 */}
      <Card>
        <CardHeader>
          <CardTitle>문의사항</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* 문의 등록 */}
          <div className="flex gap-2">
            <Input
              placeholder="문의 내용을 입력하세요"
              value={newInquiry}
              onChange={(e) => setNewInquiry(e.target.value)}
              className="flex-1"
            />
            <Button
              onClick={handleSubmitInquiry}
              disabled={submittingInquiry || !newInquiry.trim()}
            >
              {submittingInquiry ? "등록 중..." : "문의 등록"}
            </Button>
          </div>

          {/* 문의 이력 */}
          {inquiries.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              문의 이력이 없습니다
            </p>
          ) : (
            <div className="space-y-3">
              {inquiries.map((inq) => (
                <div key={inq.id} className="rounded-md border p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{inq.submitter_name}</span>
                      <Badge variant="outline" className="text-xs">
                        {PHASE_LABELS[inq.phase] || inq.phase}
                      </Badge>
                      <Badge variant={
                        inq.status === "open" ? "destructive" :
                        inq.status === "asking_agency" ? "secondary" : "default"
                      } className="text-xs">
                        {inq.status === "open" ? "접수" :
                         inq.status === "asking_agency" ? "관리원문의중" :
                         inq.status === "completed" ? "완료" : "다음단계"}
                      </Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {new Date(inq.created_at).toLocaleString("ko-KR")}
                    </span>
                  </div>
                  <p className="text-sm">{inq.content}</p>
                  {inq.reply && (
                    <div className="rounded bg-muted p-2 text-sm">
                      <span className="text-muted-foreground">답변: </span>
                      {inq.reply}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function InfoItem({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value || "-"}</dd>
    </div>
  )
}
