"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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

type Trigger = "within_3_days" | "d_minus_1" | "overdue"

const TRIGGER_OPTIONS: { value: Trigger; label: string; hint: string }[] = [
  { value: "within_3_days", label: "D-3 이내 + 초과", hint: "예정일 3일 이내이거나 이미 지난 미제출 건" },
  { value: "d_minus_1", label: "D-1만", hint: "예정일이 내일인 미제출 건" },
  { value: "overdue", label: "초과만", hint: "예정일이 지난 미제출 건" },
]

interface ReviewerPreview {
  reviewer_user_id: number
  reviewer_name: string
  kakao_matched: boolean
  count: number
  mgmt_nos: string[]
}

interface PreviewResponse {
  trigger: string
  target_count: number
  sent: number
  failed: number
  dry_run: boolean
  by_reviewer: ReviewerPreview[]
}

export default function RemindersPage() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const isUserLoading = useAuthStore((s) => s.isLoading)
  const isAdmin =
    !!user && ["team_leader", "chief_secretary", "secretary"].includes(user.role)

  useEffect(() => {
    if (!isUserLoading && user && !isAdmin) router.replace("/dashboard")
  }, [isUserLoading, user, isAdmin, router])

  const [trigger, setTrigger] = useState<Trigger>("within_3_days")
  const [preview, setPreview] = useState<PreviewResponse | null>(null)
  const [selected, setSelected] = useState<Record<number, boolean>>({})
  const [isPreviewLoading, setIsPreviewLoading] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [sendResult, setSendResult] = useState<{ sent: number; failed: number } | null>(null)

  const fetchPreview = useCallback(async (t: Trigger) => {
    setIsPreviewLoading(true)
    try {
      const { data } = await apiClient.post<PreviewResponse>(
        "/api/notifications/review-reminder",
        { trigger: t, dry_run: true },
      )
      setPreview(data)
      // 카카오 매칭된 검토위원만 기본 체크
      const initial: Record<number, boolean> = {}
      for (const r of data.by_reviewer) {
        initial[r.reviewer_user_id] = !!r.kakao_matched
      }
      setSelected(initial)
    } catch (err) {
      console.error("리마인드 대상 조회 실패:", err)
    } finally {
      setIsPreviewLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isAdmin) fetchPreview("within_3_days")
  }, [isAdmin, fetchPreview])

  const handleTriggerChange = (t: Trigger) => {
    setTrigger(t)
    setSendResult(null)
    fetchPreview(t)
  }

  const toggle = (id: number) => {
    setSelected((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const selectAll = () => {
    if (!preview) return
    // 미매칭 검토위원은 발송 불가이므로 "전체 선택" 대상에서도 제외
    const all: Record<number, boolean> = {}
    for (const r of preview.by_reviewer) all[r.reviewer_user_id] = r.kakao_matched
    setSelected(all)
  }
  const clearAll = () => {
    if (!preview) return
    const none: Record<number, boolean> = {}
    for (const r of preview.by_reviewer) none[r.reviewer_user_id] = false
    setSelected(none)
  }

  const selectedIds = useMemo(() => {
    if (!preview) return []
    // 미매칭 검토위원은 state 에 true 가 남아 있어도 실제 발송 페이로드에서 제외
    return preview.by_reviewer
      .filter((r) => r.kakao_matched && selected[r.reviewer_user_id])
      .map((r) => r.reviewer_user_id)
  }, [preview, selected])

  const handleSend = async () => {
    if (selectedIds.length === 0) return
    if (!confirm(`선택한 ${selectedIds.length}명의 검토위원에게 카카오톡 리마인드를 발송합니다. 진행할까요?`)) return

    setIsSending(true)
    setSendResult(null)
    try {
      const { data } = await apiClient.post<PreviewResponse>(
        "/api/notifications/review-reminder",
        {
          trigger,
          dry_run: false,
          recipient_user_ids: selectedIds,
        },
      )
      setSendResult({ sent: data.sent, failed: data.failed })
      // 자동 재조회
      await fetchPreview(trigger)
    } catch (err) {
      console.error("리마인드 발송 실패:", err)
      setSendResult({ sent: 0, failed: selectedIds.length })
    } finally {
      setIsSending(false)
    }
  }

  if (isUserLoading || !user) {
    return <div className="flex justify-center py-20 text-muted-foreground">로딩 중...</div>
  }
  if (!isAdmin) return null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">리마인드 알림</h1>
        <p className="text-sm text-muted-foreground">
          검토서 미제출 건을 담당 검토위원에게 카카오톡으로 리마인드합니다. 기본 조회는 D-3 이내 + 초과 건입니다.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>조회 조건</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-4">
            {TRIGGER_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className={`flex cursor-pointer items-start gap-2 rounded-md border px-3 py-2 text-sm ${
                  trigger === opt.value ? "border-primary bg-primary/5" : "border-slate-200"
                }`}
              >
                <input
                  type="radio"
                  name="trigger"
                  value={opt.value}
                  checked={trigger === opt.value}
                  onChange={() => handleTriggerChange(opt.value)}
                  className="mt-0.5"
                />
                <span>
                  <span className="font-medium">{opt.label}</span>
                  <span className="block text-xs text-muted-foreground">{opt.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>대상자</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              전체 대상 {preview?.target_count ?? 0}건 ·{" "}
              선택된 검토위원 {selectedIds.length}명
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={selectAll} disabled={!preview || isPreviewLoading}>
              전체 선택
            </Button>
            <Button variant="outline" size="sm" onClick={clearAll} disabled={!preview || isPreviewLoading}>
              전체 해제
            </Button>
            <Button
              onClick={handleSend}
              disabled={selectedIds.length === 0 || isSending || isPreviewLoading}
              loading={isSending}
              loadingText="발송 중..."
            >
              선택 발송
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {sendResult && (
            <div className="mb-3 rounded-md bg-slate-50 p-3 text-sm">
              발송 성공 <strong>{sendResult.sent}건</strong> / 실패 {sendResult.failed}건
              <p className="mt-1 text-xs text-muted-foreground">
                상세 결과는 알림 현황 페이지에서 확인하세요.
              </p>
            </div>
          )}

          {isPreviewLoading ? (
            <div className="py-10 text-center text-muted-foreground">불러오는 중...</div>
          ) : !preview || preview.by_reviewer.length === 0 ? (
            <div className="py-10 text-center text-muted-foreground">
              발송할 대상이 없습니다.
            </div>
          ) : (
            <div className="rounded-md border max-h-[60vh] overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[60px] text-center">선택</TableHead>
                    <TableHead className="w-[120px]">검토위원</TableHead>
                    <TableHead className="w-[70px] text-center">대상수</TableHead>
                    <TableHead>관리번호</TableHead>
                    <TableHead className="w-[80px] text-center">카카오</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.by_reviewer.map((r) => {
                    const checked = !!selected[r.reviewer_user_id]
                    return (
                      <TableRow
                        key={r.reviewer_user_id}
                        className={!r.kakao_matched ? "text-muted-foreground" : ""}
                      >
                        <TableCell className="text-center">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggle(r.reviewer_user_id)}
                            disabled={!r.kakao_matched}
                          />
                        </TableCell>
                        <TableCell className="font-medium">{r.reviewer_name}</TableCell>
                        <TableCell className="text-center">{r.count}</TableCell>
                        <TableCell className="text-xs font-mono">
                          {r.mgmt_nos.slice(0, 6).join(", ")}
                          {r.mgmt_nos.length > 6 && ` 외 ${r.mgmt_nos.length - 6}건`}
                        </TableCell>
                        <TableCell className="text-center">
                          {r.kakao_matched ? (
                            <Badge variant="default">✓</Badge>
                          ) : (
                            <Badge variant="outline" className="text-xs">미매칭</Badge>
                          )}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          )}

          {preview && preview.by_reviewer.some((r) => !r.kakao_matched) && (
            <p className="mt-3 text-xs text-muted-foreground">
              ※ 카카오 매칭이 안 된 검토위원은 기본 체크 해제되며 발송 대상에서 제외됩니다.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

