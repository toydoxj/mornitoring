"use client"

import { useEffect, useState } from "react"
import { useParams, useRouter, useSearchParams } from "next/navigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import apiClient from "@/lib/api/client"
import { useAuthStore } from "@/stores/authStore"
import type { Building, ReviewStage, PhaseType, ResultType, InappropriateDecisionType } from "@/types"
import { PHASE_LABELS, RESULT_LABELS } from "@/types"

const RESULT_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pass: "default",
  simple_error: "secondary",
  recalculate: "destructive",
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
  const [phaseEditOpen, setPhaseEditOpen] = useState(false)
  const [phaseDraft, setPhaseDraft] = useState<string>("")
  const [savingPhase, setSavingPhase] = useState(false)

  const canManage = user && ["team_leader", "chief_secretary", "secretary"].includes(user.role)
  const isAssigned =
    !!user &&
    !!building &&
    (building.reviewer_name === user.name ||
      building.assigned_reviewer_name === user.name)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [buildingRes, stagesRes] = await Promise.all([
          apiClient.get<Building>(`/api/buildings/${params.id}`),
          apiClient.get<ReviewStage[]>(`/api/reviews/stages/${params.id}`),
        ])
        setBuilding(buildingRes.data)
        setStages(stagesRes.data)

        // 부적합 체크된 단계의 의견 선로딩
        const inappropriateStages = stagesRes.data.filter((s) => s.inappropriate_review_needed)
        for (const s of inappropriateStages) {
          try {
            const { data: notes } = await apiClient.get(`/api/reviews/inappropriate/${s.id}/notes`)
            setNotesByStage((prev) => ({ ...prev, [s.id]: notes }))
          } catch { /* 의견 없음 */ }
        }

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

  interface NoteItem {
    id: number
    stage_id: number
    author_id: number
    author_name: string
    content: string
    created_at: string
  }
  const [notesByStage, setNotesByStage] = useState<Record<number, NoteItem[]>>({})
  const [newNoteDraft, setNewNoteDraft] = useState<Record<number, string>>({})
  const [savingNote, setSavingNote] = useState<number | null>(null)

  const fetchNotes = async (stageId: number) => {
    try {
      const { data } = await apiClient.get<NoteItem[]>(
        `/api/reviews/inappropriate/${stageId}/notes`
      )
      setNotesByStage((prev) => ({ ...prev, [stageId]: data }))
    } catch {
      // 무시
    }
  }

  const handleAddNote = async (stageId: number) => {
    const content = (newNoteDraft[stageId] ?? "").trim()
    if (!content) return
    setSavingNote(stageId)
    try {
      await apiClient.post(`/api/reviews/inappropriate/${stageId}/notes`, { content })
      setNewNoteDraft((prev) => ({ ...prev, [stageId]: "" }))
      await fetchNotes(stageId)
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "등록 실패"
      alert(msg)
    } finally {
      setSavingNote(null)
    }
  }

  const handleDeleteNote = async (stageId: number, noteId: number) => {
    if (!confirm("이 의견을 삭제하시겠습니까?")) return
    try {
      await apiClient.delete(`/api/reviews/inappropriate/notes/${noteId}`)
      await fetchNotes(stageId)
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "삭제 실패"
      alert(msg)
    }
  }

  const handleSavePhase = async () => {
    if (!building || !phaseDraft) return
    if (phaseDraft === building.current_phase) {
      setPhaseEditOpen(false)
      return
    }
    setSavingPhase(true)
    try {
      const { data } = await apiClient.patch<Building>(
        `/api/buildings/${building.id}`,
        { current_phase: phaseDraft }
      )
      setBuilding(data)
      setPhaseEditOpen(false)
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "단계 변경 실패"
      alert(msg)
    } finally {
      setSavingPhase(false)
    }
  }

  const handleInappropriateDecision = async (
    stageId: number,
    decision: InappropriateDecisionType
  ) => {
    try {
      await apiClient.patch(`/api/reviews/inappropriate/${stageId}`, { decision })
      // 단계 목록 재조회
      const { data: stagesRes } = await apiClient.get<ReviewStage[]>(`/api/reviews/stages/${params.id}`)
      setStages(stagesRes)
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "변경 실패"
      alert(msg)
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
        <div className="flex items-center gap-2">
          {building.current_phase && (
            <Badge variant="outline" className="text-base px-3 py-1">
              {PHASE_LABELS[building.current_phase as PhaseType] || building.current_phase}
            </Badge>
          )}
          {canManage && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setPhaseDraft(building.current_phase ?? "")
                setPhaseEditOpen(true)
              }}
            >
              단계 수정
            </Button>
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
        <CardContent className="space-y-5">
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
            <InfoItem label="내진등급" value={building.seismic_level} />
          </div>

          <Separator />

          <div className="grid grid-cols-1 gap-4 text-sm md:grid-cols-3">
            <div>
              <p className="mb-1 text-muted-foreground font-medium">건축사사무소</p>
              <div className="space-y-1">
                <InfoItem label="소속" value={building.architect_firm} />
                <InfoItem label="성명" value={building.architect_name} />
              </div>
            </div>
            <div>
              <p className="mb-1 text-muted-foreground font-medium">책임구조기술자 사무소</p>
              <div className="space-y-1">
                <InfoItem label="소속" value={building.struct_eng_firm} />
                <InfoItem label="성명" value={building.struct_eng_name} />
              </div>
            </div>
            <div>
              <p className="mb-1 text-muted-foreground font-medium">도면작성자</p>
              <div className="space-y-1">
                <InfoItem label="자격" value={building.drawing_creator_qualification} />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 검토 진행 타임라인 */}
      <Card>
        <CardHeader>
          <CardTitle>검토 진행 현황</CardTitle>
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

                      {/* 부적합 검토 판정 (간사 이상 + 부적합 체크된 단계만) */}
                      {stage.inappropriate_review_needed && canManage && (
                        <div className="rounded-md border border-orange-200 bg-orange-50 p-3 space-y-3">
                          <div>
                            <dt className="text-sm font-medium text-orange-900 mb-2">
                              부적합 대상 검토 판정
                            </dt>
                            <div className="flex flex-wrap gap-2">
                              {([
                                { key: "confirmed_serious", label: "확정(심각)" },
                                { key: "confirmed_simple", label: "확정(단순)" },
                                { key: "pending", label: "대기" },
                                { key: "excluded", label: "제외" },
                              ] as const).map((opt) => {
                                const active = (stage.inappropriate_decision ?? "pending") === opt.key
                                return (
                                  <Button
                                    key={opt.key}
                                    size="sm"
                                    variant={active ? (opt.key === "excluded" ? "destructive" : "default") : "outline"}
                                    onClick={() => handleInappropriateDecision(stage.id, opt.key)}
                                  >
                                    {opt.label}
                                  </Button>
                                )
                              })}
                            </div>
                          </div>

                          {/* 간사진 의견 (다중, 작성자 기록) */}
                          <div>
                            <dt className="text-sm font-medium text-orange-900 mb-2">
                              간사진 의견
                              {notesByStage[stage.id]?.length > 0 && (
                                <span className="ml-2 text-xs text-orange-700">
                                  ({notesByStage[stage.id].length})
                                </span>
                              )}
                            </dt>

                            {/* 의견 리스트 */}
                            <div className="space-y-2 mb-3">
                              {(notesByStage[stage.id] ?? []).map((n) => {
                                const isOwner = user?.id === n.author_id
                                const isAdmin = user && ["team_leader", "chief_secretary"].includes(user.role)
                                return (
                                  <div
                                    key={n.id}
                                    className="rounded-md border border-orange-200 bg-white p-3 text-sm"
                                  >
                                    <div className="flex items-start justify-between gap-2">
                                      <div className="flex items-center gap-2">
                                        <span className="font-medium">{n.author_name}</span>
                                        <span className="text-xs text-muted-foreground">
                                          {new Date(n.created_at).toLocaleString("ko-KR")}
                                        </span>
                                      </div>
                                      {(isOwner || isAdmin) && (
                                        <Button
                                          size="icon-xs"
                                          variant="ghost"
                                          onClick={() => handleDeleteNote(stage.id, n.id)}
                                          aria-label="삭제"
                                        >
                                          ×
                                        </Button>
                                      )}
                                    </div>
                                    <p className="mt-1 whitespace-pre-wrap break-words">
                                      {n.content}
                                    </p>
                                  </div>
                                )
                              })}
                              {(!notesByStage[stage.id] || notesByStage[stage.id].length === 0) && (
                                <p className="text-xs text-muted-foreground">
                                  아직 등록된 의견이 없습니다.
                                </p>
                              )}
                            </div>

                            {/* 새 의견 입력 */}
                            <textarea
                              className="w-full min-h-[60px] rounded-md border border-orange-200 bg-white px-3 py-2 text-sm"
                              placeholder="새 의견을 작성하세요"
                              value={newNoteDraft[stage.id] ?? ""}
                              onChange={(e) =>
                                setNewNoteDraft({ ...newNoteDraft, [stage.id]: e.target.value })
                              }
                            />
                            <div className="flex justify-end mt-2">
                              <Button
                                size="sm"
                                onClick={() => handleAddNote(stage.id)}
                                disabled={!(newNoteDraft[stage.id] ?? "").trim()}
                                loading={savingNote === stage.id}
                                loadingText="등록 중..."
                              >
                                의견 등록
                              </Button>
                            </div>
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
          {/* 문의 등록 — 해당 건물의 담당 검토자만 가능 (역할 무관) */}
          {isAssigned && (
            <div className="flex gap-2">
              <Input
                placeholder="문의 내용을 입력하세요"
                value={newInquiry}
                onChange={(e) => setNewInquiry(e.target.value)}
                className="flex-1"
              />
              <Button
                onClick={handleSubmitInquiry}
                disabled={!newInquiry.trim()}
                loading={submittingInquiry}
                loadingText="등록 중..."
              >
                문의 등록
              </Button>
            </div>
          )}

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

      {/* 현재 단계 수정 다이얼로그 (간사 이상) */}
      <Dialog open={phaseEditOpen} onOpenChange={setPhaseEditOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>현재 단계 수정</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              자동 전환과 무관하게 이 건축물의 현재 진행 단계를 수동으로 지정할 수 있습니다.
            </p>
            <div className="space-y-2">
              <Label>단계 선택</Label>
              <select
                className="w-full rounded-md border px-3 py-2 text-sm"
                value={phaseDraft}
                onChange={(e) => setPhaseDraft(e.target.value)}
              >
                <option value="">선택 안 함</option>
                {Object.entries(PHASE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPhaseEditOpen(false)} disabled={savingPhase}>
              취소
            </Button>
            <Button onClick={handleSavePhase} loading={savingPhase} loadingText="저장 중...">
              저장
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
