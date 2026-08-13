"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import apiClient from "@/lib/api/client"
import { useAuthStore } from "@/stores/authStore"
import type { ResubmissionListResponse, ResubmissionRequest } from "@/types"
import { PHASE_LABELS, RESUBMISSION_STATUS_LABELS } from "@/types"
import { getResubmitPreviousPhase } from "@/lib/phases"

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "destructive",
  completed: "default",
}

function formatDateTime(value: string | null) {
  if (!value) return "-"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString("ko-KR")
}

function phaseLabel(phase: string | null) {
  if (!phase) return "-"
  return PHASE_LABELS[phase] || phase
}

export default function ResubmissionsPage() {
  const user = useAuthStore((s) => s.user)
  // 관리원은 확인 전용 — 처리 상태와 회신은 간사 이상만 남긴다.
  const canManage =
    !!user && ["team_leader", "chief_secretary", "secretary"].includes(user.role)

  const [pendingItems, setPendingItems] = useState<ResubmissionRequest[]>([])
  const [pendingTotal, setPendingTotal] = useState(0)
  const [completedItems, setCompletedItems] = useState<ResubmissionRequest[]>([])
  const [completedTotal, setCompletedTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [replyMap, setReplyMap] = useState<Record<number, string>>({})
  const [savingId, setSavingId] = useState<number | null>(null)

  const fetchData = useCallback(async () => {
    setIsLoading(true)
    try {
      const [pendingRes, completedRes] = await Promise.all([
        apiClient.get<ResubmissionListResponse>("/api/resubmissions", {
          params: { status_filter: "pending", size: 200 },
        }),
        apiClient.get<ResubmissionListResponse>("/api/resubmissions", {
          params: { status_filter: "completed", size: 200 },
        }),
      ])
      setPendingItems(pendingRes.data.items)
      setPendingTotal(pendingRes.data.total)
      setCompletedItems(completedRes.data.items)
      setCompletedTotal(completedRes.data.total)

      const map: Record<number, string> = {}
      for (const item of pendingRes.data.items) {
        if (item.reply) map[item.id] = item.reply
      }
      setReplyMap(map)
    } catch (err) {
      console.error("재제출 요청 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const handleUpdate = async (
    item: ResubmissionRequest,
    options: {
      status?: string
      clearDueDate?: boolean
      rollbackPhase?: boolean
    } = {}
  ) => {
    setSavingId(item.id)
    try {
      const { data } = await apiClient.patch<{ message: string }>(
        `/api/resubmissions/${item.id}`,
        {
          reply: replyMap[item.id] ?? null,
          status: options.status ?? null,
          rollback_phase: options.rollbackPhase ?? false,
          clear_due_date: options.clearDueDate ?? false,
        }
      )
      await fetchData()
      if (options.clearDueDate || options.rollbackPhase) alert(data.message)
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "저장 실패"
      alert(msg)
    } finally {
      setSavingId(null)
    }
  }

  const handleClearDueDate = (item: ResubmissionRequest) => {
    if (
      !confirm(
        `${item.mgmt_no}의 검토서 요청 예정일(${item.current_due_date})을 삭제하시겠습니까?\n` +
        "도서가 다시 접수되면 예정일이 새로 부여됩니다."
      )
    ) {
      return
    }
    handleUpdate(item, { clearDueDate: true })
  }

  const handleRollbackPhase = (item: ResubmissionRequest) => {
    const target = getResubmitPreviousPhase(item.current_phase)
    if (!target) {
      alert("도서 접수 상태가 아니어서 되돌릴 수 없습니다.")
      return
    }
    if (
      !confirm(
        `${item.mgmt_no}의 단계를 ${phaseLabel(item.current_phase)} → ` +
        `${phaseLabel(target)}(으)로 되돌리시겠습니까?`
      )
    ) {
      return
    }
    handleUpdate(item, { rollbackPhase: true })
  }

  const renderRequestCell = (item: ResubmissionRequest) => (
    <div className="space-y-1">
      <p className="whitespace-pre-wrap break-words text-sm">{item.reason}</p>
      <p className="text-xs text-muted-foreground">
        {item.to_phase
          ? `단계 되돌림: ${phaseLabel(item.from_phase)} → ${phaseLabel(item.to_phase)}`
          : `요청 시점 단계: ${phaseLabel(item.from_phase)}`}
        {item.cleared_due_date && ` / 삭제한 제출 예정일: ${item.cleared_due_date}`}
      </p>
      {item.re_received_at && (
        <p className="text-xs text-blue-700">
          도서 재접수됨 ({formatDateTime(item.re_received_at)})
        </p>
      )}
    </div>
  )

  // 현재 단계 + 되돌리기 버튼 — 되돌리기는 간사가 판단해 실행한다
  const renderPhaseCell = (item: ResubmissionRequest) => {
    const target = getResubmitPreviousPhase(item.current_phase)
    return (
      <div className="space-y-1">
        <p className="text-sm">{phaseLabel(item.current_phase)}</p>
        {item.to_phase ? (
          <p className="text-xs text-muted-foreground">되돌림 완료</p>
        ) : (
          canManage && (
            <Button
              size="sm"
              variant="outline"
              disabled={!target}
              title={target ? undefined : "도서 접수 상태에서만 되돌릴 수 있습니다"}
              loading={savingId === item.id}
              loadingText="처리 중..."
              onClick={() => handleRollbackPhase(item)}
            >
              이전 단계로
            </Button>
          )
        )}
      </div>
    )
  }

  // 예정일 상태 — 간사가 삭제 여부를 판단하는 칸
  const renderDueCell = (item: ResubmissionRequest) => {
    if (item.current_due_date) {
      return (
        <div className="space-y-1">
          <p className="text-sm">{item.current_due_date}</p>
          {canManage && (
            <Button
              size="sm"
              variant="destructive"
              loading={savingId === item.id}
              loadingText="삭제 중..."
              onClick={() => handleClearDueDate(item)}
            >
              예정일 삭제
            </Button>
          )}
        </div>
      )
    }
    return (
      <p className="text-sm text-muted-foreground">
        {item.cleared_due_date ? `삭제됨 (${item.cleared_due_date})` : "없음"}
      </p>
    )
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-20 text-muted-foreground">로딩 중...</div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">재제출 요청</h1>
        <p className="text-sm text-muted-foreground">
          대기 {pendingTotal}건 / 처리완료 {completedTotal}건
        </p>
      </div>

      {/* 대기중 요청 */}
      <div>
        <h2 className="mb-2 text-lg font-semibold">대기</h2>
        <div className="rounded-md border bg-white overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[110px]">관리번호</TableHead>
                <TableHead className="w-[80px]">검토위원</TableHead>
                <TableHead className="w-[110px]">검토 단계</TableHead>
                <TableHead>재제출 사유</TableHead>
                <TableHead className="w-[110px]">현재 단계</TableHead>
                <TableHead className="w-[120px]">제출 예정일</TableHead>
                <TableHead className="w-[80px]">상태</TableHead>
                <TableHead className="w-[130px]">요청일시</TableHead>
                {canManage && <TableHead className="w-[260px]">처리</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {pendingItems.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={canManage ? 9 : 8}
                    className="h-20 text-center text-muted-foreground"
                  >
                    대기중인 재제출 요청이 없습니다
                  </TableCell>
                </TableRow>
              ) : (
                pendingItems.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="font-mono text-sm align-top">
                      {item.building_id ? (
                        <Link
                          href={`/buildings/${item.building_id}?from=resubmissions`}
                          className="text-primary hover:underline"
                        >
                          {item.mgmt_no}
                        </Link>
                      ) : (
                        item.mgmt_no
                      )}
                      {item.building_name && (
                        <p className="mt-0.5 text-xs font-sans text-muted-foreground">
                          {item.building_name}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="text-sm align-top">
                      {item.requester_name}
                      {item.reviewer_group_no !== null && (
                        <span className="block text-xs text-muted-foreground">
                          {item.reviewer_group_no}조
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="align-top">
                      <Badge variant="outline" className="text-xs">
                        {phaseLabel(item.phase)}
                      </Badge>
                    </TableCell>
                    <TableCell className="align-top">{renderRequestCell(item)}</TableCell>
                    <TableCell className="align-top">{renderPhaseCell(item)}</TableCell>
                    <TableCell className="align-top">{renderDueCell(item)}</TableCell>
                    <TableCell className="align-top">
                      <Badge variant={STATUS_VARIANT[item.status]}>
                        {RESUBMISSION_STATUS_LABELS[item.status]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm align-top">
                      {formatDateTime(item.created_at)}
                    </TableCell>
                    {canManage && (
                      <TableCell className="align-top">
                        <div className="space-y-2">
                          <Input
                            value={replyMap[item.id] ?? ""}
                            onChange={(e) =>
                              setReplyMap({ ...replyMap, [item.id]: e.target.value })
                            }
                            placeholder="처리 메모 입력"
                            className="text-sm"
                          />
                          <div className="flex flex-wrap gap-1">
                            <Button
                              size="sm"
                              variant="outline"
                              loading={savingId === item.id}
                              loadingText="저장 중..."
                              onClick={() => handleUpdate(item)}
                            >
                              메모저장
                            </Button>
                            <Button
                              size="sm"
                              variant="default"
                              loading={savingId === item.id}
                              loadingText="저장 중..."
                              onClick={() => handleUpdate(item, { status: "completed" })}
                            >
                              처리완료
                            </Button>
                          </div>
                        </div>
                      </TableCell>
                    )}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* 처리완료 요청 */}
      {completedItems.length > 0 && (
        <div>
          <h2 className="mb-2 text-lg font-semibold">처리완료</h2>
          <div className="rounded-md border bg-white overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[110px]">관리번호</TableHead>
                  <TableHead className="w-[80px]">검토위원</TableHead>
                  <TableHead className="w-[110px]">검토 단계</TableHead>
                  <TableHead>재제출 사유</TableHead>
                  <TableHead>처리 메모</TableHead>
                  <TableHead className="w-[90px]">처리자</TableHead>
                  <TableHead className="w-[130px]">처리일시</TableHead>
                  {canManage && <TableHead className="w-[110px]">관리</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {completedItems.map((item) => (
                  <TableRow key={item.id} className="text-muted-foreground">
                    <TableCell className="font-mono text-sm align-top">
                      {item.building_id ? (
                        <Link
                          href={`/buildings/${item.building_id}?from=resubmissions`}
                          className="text-primary hover:underline"
                        >
                          {item.mgmt_no}
                        </Link>
                      ) : (
                        item.mgmt_no
                      )}
                      {item.building_name && (
                        <p className="mt-0.5 text-xs font-sans">{item.building_name}</p>
                      )}
                    </TableCell>
                    <TableCell className="text-sm align-top">
                      {item.requester_name}
                    </TableCell>
                    <TableCell className="align-top">
                      <Badge variant="outline" className="text-xs">
                        {phaseLabel(item.phase)}
                      </Badge>
                    </TableCell>
                    <TableCell className="align-top">{renderRequestCell(item)}</TableCell>
                    <TableCell className="text-sm align-top">
                      <p className="whitespace-pre-wrap break-words">
                        {item.reply || "-"}
                      </p>
                    </TableCell>
                    <TableCell className="text-sm align-top">
                      {item.handled_by_name || "-"}
                    </TableCell>
                    <TableCell className="text-sm align-top">
                      {formatDateTime(item.handled_at ?? item.updated_at)}
                    </TableCell>
                    {canManage && (
                      <TableCell className="align-top">
                        <Button
                          size="sm"
                          variant="outline"
                          loading={savingId === item.id}
                          loadingText="처리 중..."
                          onClick={() => handleUpdate(item, { status: "pending" })}
                        >
                          대기로
                        </Button>
                      </TableCell>
                    )}
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
