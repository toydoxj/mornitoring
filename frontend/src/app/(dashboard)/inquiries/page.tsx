"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Dialog,
  DialogContent,
  DialogFooter,
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
import { PHASE_LABELS } from "@/types"

interface InquiryItem {
  id: number
  building_id: number
  mgmt_no: string
  phase: string
  current_phase: string | null
  submitter_name: string
  content: string
  reply: string | null
  status: string
  created_at: string
  updated_at: string
}

interface InquiryListResponse {
  items: InquiryItem[]
  total: number
}

const STATUS_LABELS: Record<string, string> = {
  open: "접수",
  asking_agency: "관리원문의중",
  completed: "완료",
}

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  open: "destructive",
  asking_agency: "secondary",
  completed: "default",
}

export default function InquiriesPage() {
  const [activeData, setActiveData] = useState<InquiryItem[]>([])
  const [activeTotal, setActiveTotal] = useState(0)
  const [closedData, setClosedData] = useState<InquiryItem[]>([])
  const [closedTotal, setClosedTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [replyMap, setReplyMap] = useState<Record<number, string>>({})
  // 단계 변경 다이얼로그 상태
  const [phaseEditTarget, setPhaseEditTarget] = useState<InquiryItem | null>(null)
  const [phaseDraft, setPhaseDraft] = useState<string>("")
  const [savingPhase, setSavingPhase] = useState(false)
  // 답변저장 후 진행 방식을 선택받는 확인 다이얼로그 상태
  const [replyActionTarget, setReplyActionTarget] = useState<InquiryItem | null>(null)
  const [savingReplyAction, setSavingReplyAction] = useState(false)

  const openPhaseDialog = (item: InquiryItem) => {
    setPhaseEditTarget(item)
    setPhaseDraft(item.current_phase ?? "")
  }

  const closePhaseDialog = () => {
    setPhaseEditTarget(null)
    setPhaseDraft("")
  }

  const handleSavePhase = async () => {
    if (!phaseEditTarget) return
    const next = phaseDraft.trim()
    if (!next) {
      alert("변경할 단계를 선택해주세요")
      return
    }
    setSavingPhase(true)
    try {
      await apiClient.patch(`/api/reviews/inquiry/${phaseEditTarget.id}`, {
        reply: replyMap[phaseEditTarget.id] || null,
        new_phase: next,
      })
      closePhaseDialog()
      fetchData()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "단계 변경 실패"
      alert(msg)
    } finally {
      setSavingPhase(false)
    }
  }

  const fetchData = async () => {
    setIsLoading(true)
    try {
      const [activeRes, closedRes] = await Promise.all([
        apiClient.get<InquiryListResponse>("/api/reviews/inquiries", { params: { status_filter: "active", size: 200 } }),
        apiClient.get<InquiryListResponse>("/api/reviews/inquiries", { params: { status_filter: "closed", size: 200 } }),
      ])
      setActiveData(activeRes.data.items)
      setActiveTotal(activeRes.data.total)
      setClosedData(closedRes.data.items)
      setClosedTotal(closedRes.data.total)

      // 기존 답변 로드
      const map: Record<number, string> = {}
      for (const item of activeRes.data.items) {
        if (item.reply) map[item.id] = item.reply
      }
      setReplyMap(map)
    } catch (err) {
      console.error("문의사항 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const handleUpdate = async (id: number, status: string) => {
    try {
      await apiClient.patch(`/api/reviews/inquiry/${id}`, {
        reply: replyMap[id] || null,
        status,
      })
      fetchData()
    } catch (err) {
      console.error("업데이트 실패:", err)
    }
  }

  const handleReplyAndComplete = async () => {
    if (!replyActionTarget) return
    setSavingReplyAction(true)
    try {
      await apiClient.patch(`/api/reviews/inquiry/${replyActionTarget.id}`, {
        reply: replyMap[replyActionTarget.id] || null,
        status: "completed",
      })
      setReplyActionTarget(null)
      fetchData()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "저장 실패"
      alert(msg)
    } finally {
      setSavingReplyAction(false)
    }
  }

  const handleReplyAndGoToPhaseChange = () => {
    // 단계 변경 다이얼로그로 이관. 답변은 그쪽 저장 시 함께 PATCH된다.
    if (!replyActionTarget) return
    const target = replyActionTarget
    setReplyActionTarget(null)
    openPhaseDialog(target)
  }

  if (isLoading) {
    return <div className="flex justify-center py-20 text-muted-foreground">로딩 중...</div>
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">문의사항</h1>
        <p className="text-sm text-muted-foreground">
          진행중 {activeTotal}건 / 완료 {closedTotal}건
        </p>
      </div>

      {/* 진행중 문의 */}
      <div>
        <h2 className="text-lg font-semibold mb-2">진행중</h2>
        <div className="rounded-md border bg-white">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[100px]">관리번호</TableHead>
                <TableHead className="w-[70px]">검토위원</TableHead>
                <TableHead className="w-[80px]">단계</TableHead>
                <TableHead>문의 내용</TableHead>
                <TableHead className="w-[250px]">답변</TableHead>
                <TableHead className="w-[80px]">상태</TableHead>
                <TableHead className="w-[180px]">처리</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {activeData.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="h-20 text-center text-muted-foreground">
                    진행중인 문의가 없습니다
                  </TableCell>
                </TableRow>
              ) : (
                activeData.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="font-mono text-sm">
                      <Link
                        href={`/buildings/${item.building_id}?from=inquiries`}
                        className="text-primary hover:underline"
                      >
                        {item.mgmt_no}
                      </Link>
                    </TableCell>
                    <TableCell className="text-sm">{item.submitter_name}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {PHASE_LABELS[item.phase] || item.phase}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">{item.content}</TableCell>
                    <TableCell>
                      <Input
                        value={replyMap[item.id] ?? item.reply ?? ""}
                        onChange={(e) => setReplyMap({ ...replyMap, [item.id]: e.target.value })}
                        placeholder="답변 입력"
                        className="text-sm"
                      />
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[item.status]}>
                        {STATUS_LABELS[item.status]}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1 flex-wrap">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => handleUpdate(item.id, "asking_agency")}
                        >
                          관리원문의
                        </Button>
                        <Button
                          size="sm"
                          variant="default"
                          onClick={() => setReplyActionTarget(item)}
                        >
                          답변저장
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* 답변저장 후 후속 조치 선택 다이얼로그 */}
      <Dialog
        open={!!replyActionTarget}
        onOpenChange={(open) => { if (!open) setReplyActionTarget(null) }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>답변을 저장합니다</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 text-sm">
            <p>저장 후 진행 방식을 선택해주세요.</p>
            {replyActionTarget && (
              <p className="text-xs text-muted-foreground">
                관리번호{" "}
                <span className="font-mono font-medium">{replyActionTarget.mgmt_no}</span>
              </p>
            )}
          </div>
          <DialogFooter className="flex-col gap-2 sm:flex-row sm:justify-end">
            <Button
              variant="ghost"
              onClick={() => setReplyActionTarget(null)}
              disabled={savingReplyAction}
            >
              취소
            </Button>
            <Button
              variant="secondary"
              onClick={handleReplyAndGoToPhaseChange}
              disabled={savingReplyAction}
            >
              단계변경하기
            </Button>
            <Button
              variant="default"
              onClick={handleReplyAndComplete}
              loading={savingReplyAction}
              loadingText="저장 중..."
            >
              완료하기
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 단계 변경 다이얼로그 — 저장 시 건물 current_phase 갱신 + 문의 상태 completed */}
      <Dialog
        open={!!phaseEditTarget}
        onOpenChange={(open) => { if (!open) closePhaseDialog() }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>단계 변경</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {phaseEditTarget && (
              <p className="text-xs text-muted-foreground">
                관리번호 <span className="font-mono font-medium">{phaseEditTarget.mgmt_no}</span>
                의 현재 단계를 변경합니다. 저장하면 본 문의는 자동으로 완료 처리됩니다.
              </p>
            )}
            <div className="space-y-2">
              <Label>단계 선택</Label>
              <select
                className="w-full rounded-md border px-3 py-2 text-sm"
                value={phaseDraft}
                onChange={(e) => setPhaseDraft(e.target.value)}
              >
                <option value="">선택 안 함</option>
                {Object.entries(PHASE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closePhaseDialog} disabled={savingPhase}>
              취소
            </Button>
            <Button onClick={handleSavePhase} loading={savingPhase} loadingText="저장 중...">
              저장
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 완료된 문의 */}
      {closedData.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-2">완료</h2>
          <div className="rounded-md border bg-white">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[100px]">관리번호</TableHead>
                  <TableHead className="w-[70px]">검토위원</TableHead>
                  <TableHead className="w-[80px]">단계</TableHead>
                  <TableHead>문의 내용</TableHead>
                  <TableHead>답변</TableHead>
                  <TableHead className="w-[80px]">상태</TableHead>
                  <TableHead className="w-[130px]">처리일시</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {closedData.map((item) => (
                  <TableRow key={item.id} className="text-muted-foreground">
                    <TableCell className="font-mono text-sm">
                      <Link
                        href={`/buildings/${item.building_id}?from=inquiries`}
                        className="text-primary hover:underline"
                      >
                        {item.mgmt_no}
                      </Link>
                    </TableCell>
                    <TableCell className="text-sm">{item.submitter_name}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {PHASE_LABELS[item.phase] || item.phase}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">{item.content}</TableCell>
                    <TableCell className="text-sm">{item.reply || "-"}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[item.status]}>
                        {STATUS_LABELS[item.status]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">
                      {new Date(item.updated_at).toLocaleString("ko-KR")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </div>
  )
}
