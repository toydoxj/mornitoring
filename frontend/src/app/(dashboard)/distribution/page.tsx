"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
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

interface NotificationItem {
  reviewer_name: string
  count: number
  mgmt_nos: string[]
  message: string
  round?: string
  phase?: string
  report_due_date?: string
}

// 접수일 + N일을 YYYY-MM-DD 로 반환
const DEFAULT_DUE_DAYS = 14
function addDays(iso: string, days: number): string {
  const d = new Date(iso)
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

interface ReceiveResult {
  updated: number
  not_found: string[]
  notifications: NotificationItem[]
}

export default function DistributionPage() {
  const [mgmtNosInput, setMgmtNosInput] = useState("")
  const initialReceived = new Date().toISOString().slice(0, 10)
  const [receivedDate, setReceivedDate] = useState(initialReceived)
  // 검토서 요청 예정일 — 접수일 + DEFAULT_DUE_DAYS 기본값, 사용자가 직접 수정 가능
  const [reportDueDate, setReportDueDate] = useState(
    addDays(initialReceived, DEFAULT_DUE_DAYS)
  )
  // 예정일을 사용자가 한 번이라도 손댔으면 접수일 변경 시 더 이상 자동 계산하지 않는다
  const [dueDateTouched, setDueDateTouched] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [result, setResult] = useState<ReceiveResult | null>(null)
  const [notifSent, setNotifSent] = useState(false)

  const handleReceivedDateChange = (v: string) => {
    setReceivedDate(v)
    if (!dueDateTouched && v) {
      setReportDueDate(addDays(v, DEFAULT_DUE_DAYS))
    }
  }

  const handleDueDateChange = (v: string) => {
    setReportDueDate(v)
    setDueDateTouched(true)
  }

  // 파일에서 관리번호 추출
  const handleFileExtract = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const text = await file.text()
    // 폴더명/파일명에서 관리번호 패턴 추출
    const pattern = /\d{4}-\d{4}/g
    const matches = text.match(pattern)
    if (matches) {
      const unique = [...new Set(matches)]
      setMgmtNosInput(unique.join("\n"))
    }
    e.target.value = ""
  }

  const handleReceive = async () => {
    const mgmtNos = mgmtNosInput
      .split(/[\n,\s]+/)
      .map((s) => s.trim())
      .filter((s) => /^\d{4}-\d{4}$/.test(s))

    if (mgmtNos.length === 0) {
      alert("관리번호를 입력해주세요")
      return
    }

    setIsProcessing(true)
    setResult(null)
    setNotifSent(false)

    try {
      const { data } = await apiClient.post<ReceiveResult>(
        "/api/distribution/receive",
        {
          mgmt_nos: mgmtNos,
          received_date: receivedDate,
          report_due_date: reportDueDate || null,
        }
      )
      setResult(data)
    } catch (err) {
      console.error("접수 처리 실패:", err)
    } finally {
      setIsProcessing(false)
    }
  }

  const [notifSending, setNotifSending] = useState(false)
  const [notifResult, setNotifResult] = useState<{ sent: number; failed: number; error?: string } | null>(null)

  const handleSendNotifications = async () => {
    if (!result) return
    setNotifSending(true)
    setNotifResult(null)

    try {
      const { data } = await apiClient.post("/api/distribution/notify", result.notifications)
      setNotifSent(true)
      setNotifResult(data)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { error?: string } } }
      setNotifResult({
        sent: 0,
        failed: result.notifications.length,
        error: axiosErr.response?.data?.error || "발송 요청 실패",
      })
    } finally {
      setNotifSending(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">도서 접수/배포</h1>
        <p className="text-sm text-muted-foreground">
          관리번호를 입력하면 각 건물의 진행 상태에 따라 예비도서 또는 보완도서(1~5차) 접수가 자동으로 구분됩니다
        </p>
      </div>

      {/* 접수 입력 */}
      <Card>
        <CardHeader>
          <CardTitle>1단계: 접수 관리번호 입력</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-4">
            <div className="space-y-2">
              <Label>접수 날짜</Label>
              <Input
                type="date"
                value={receivedDate}
                onChange={(e) => handleReceivedDateChange(e.target.value)}
                className="w-48"
              />
            </div>
            <div className="space-y-2">
              <Label>검토서 요청 예정일</Label>
              <Input
                type="date"
                value={reportDueDate}
                onChange={(e) => handleDueDateChange(e.target.value)}
                className="w-48"
              />
              <p className="text-xs text-muted-foreground">
                기본값: 접수일 + {DEFAULT_DUE_DAYS}일 (직접 수정 가능)
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <Label>관리번호 (줄바꿈 또는 쉼표로 구분)</Label>
            <textarea
              className="w-full min-h-[150px] rounded-md border px-3 py-2 text-sm font-mono"
              placeholder={"2025-0001\n2025-0002\n2025-0003"}
              value={mgmtNosInput}
              onChange={(e) => setMgmtNosInput(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              입력된 관리번호 수:{" "}
              {
                mgmtNosInput
                  .split(/[\n,\s]+/)
                  .filter((s) => /^\d{4}-\d{4}$/.test(s.trim())).length
              }
              건
            </p>
          </div>

          <Button onClick={handleReceive} loading={isProcessing} loadingText="처리 중...">
            접수 처리
          </Button>
        </CardContent>
      </Card>

      {/* 처리 결과 */}
      {result && (
        <Card>
          <CardHeader>
            <CardTitle>2단계: 접수 결과 확인</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-3">
              <Badge variant="default">접수 완료 {result.updated}건</Badge>
              {result.not_found.length > 0 && (
                <Badge variant="destructive">
                  관리번호 없음 {result.not_found.length}건
                </Badge>
              )}
            </div>

            {result.not_found.length > 0 && (
              <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">
                <p className="font-medium">찾을 수 없는 관리번호:</p>
                <p className="font-mono">{result.not_found.join(", ")}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* 알림 발송 */}
      {result && result.notifications.length > 0 && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>3단계: 검토위원 알림 발송</CardTitle>
            <Button
              onClick={handleSendNotifications}
              disabled={notifSent}
              loading={notifSending}
              loadingText="발송 중..."
            >
              {notifSent ? "발송 완료" : "카카오톡 알림 발송"}
            </Button>
          </CardHeader>
          <CardContent>
            {notifResult && (
              <div className={`rounded-md p-3 text-sm mb-4 ${
                notifResult.sent > 0 ? "bg-green-50 text-green-800" : "bg-yellow-50 text-yellow-800"
              }`}>
                <p>발송 성공: <strong>{notifResult.sent}건</strong> / 실패: {notifResult.failed}건</p>
                {notifResult.error && <p className="text-red-600 mt-1">{notifResult.error}</p>}
                {notifResult.failed > 0 && !notifResult.error && (
                  <p className="mt-1 text-muted-foreground">실패 상세는 알림 현황 페이지에서 확인하세요</p>
                )}
              </div>
            )}
            <div className="rounded-md border max-h-96 overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>검토위원</TableHead>
                    <TableHead className="w-[100px]">차수</TableHead>
                    <TableHead className="w-[60px]">건수</TableHead>
                    <TableHead>알림 내용</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.notifications.map((n, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-medium">{n.reviewer_name}</TableCell>
                      <TableCell>
                        {n.round ? (
                          <Badge variant="outline">{n.round}</Badge>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                      <TableCell>{n.count}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {n.message}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
