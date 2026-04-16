"use client"

import { useEffect, useState } from "react"
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

interface NotificationItem {
  id: number
  channel: string
  template_type: string
  title: string
  message: string | null
  is_sent: boolean
  sent_at: string | null
  retry_count: number
  error_message: string | null
  created_at: string
}

interface NotificationListResponse {
  items: NotificationItem[]
  total: number
}

const TEMPLATE_LABELS: Record<string, string> = {
  doc_received: "도서 접수",
  review_request: "검토 요청",
  reminder: "리마인더",
}

export default function NotificationsPage() {
  const [data, setData] = useState<NotificationItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [filter, setFilter] = useState<"all" | "sent" | "failed">("all")
  const [isLoading, setIsLoading] = useState(true)
  const pageSize = 50

  const fetchData = async () => {
    setIsLoading(true)
    try {
      const params: Record<string, string | number> = { page, size: pageSize }
      if (filter === "sent") params.is_sent = 1
      if (filter === "failed") params.is_sent = 0

      const { data: res } = await apiClient.get<NotificationListResponse>(
        "/api/notifications",
        { params }
      )
      setData(res.items)
      setTotal(res.total)
    } catch (err) {
      console.error("알림 로그 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [page, filter])

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">알림 발송 현황</h1>
          <p className="text-sm text-muted-foreground">총 {total}건</p>
        </div>
        <div className="flex gap-1">
          {(["all", "sent", "failed"] as const).map((f) => (
            <Button
              key={f}
              variant={filter === f ? "default" : "outline"}
              size="sm"
              onClick={() => { setFilter(f); setPage(1) }}
            >
              {f === "all" ? "전체" : f === "sent" ? "발송 성공" : "발송 실패"}
            </Button>
          ))}
        </div>
      </div>

      <div className="rounded-md border bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[60px]">ID</TableHead>
              <TableHead className="w-[80px]">채널</TableHead>
              <TableHead className="w-[100px]">유형</TableHead>
              <TableHead>내용</TableHead>
              <TableHead className="w-[80px]">상태</TableHead>
              <TableHead className="w-[160px]">발송 시간</TableHead>
              <TableHead>오류</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7} className="h-32 text-center">
                  로딩 중...
                </TableCell>
              </TableRow>
            ) : data.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="h-32 text-center text-muted-foreground">
                  알림 로그가 없습니다
                </TableCell>
              </TableRow>
            ) : (
              data.map((n) => (
                <TableRow key={n.id}>
                  <TableCell>{n.id}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{n.channel}</Badge>
                  </TableCell>
                  <TableCell className="text-sm">
                    {TEMPLATE_LABELS[n.template_type] || n.template_type}
                  </TableCell>
                  <TableCell className="text-sm max-w-xs truncate">
                    {n.message || n.title}
                  </TableCell>
                  <TableCell>
                    <Badge variant={n.is_sent ? "default" : "destructive"}>
                      {n.is_sent ? "성공" : "실패"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {n.sent_at
                      ? new Date(n.sent_at).toLocaleString("ko-KR")
                      : new Date(n.created_at).toLocaleString("ko-KR")}
                  </TableCell>
                  <TableCell className="text-sm text-red-500 max-w-xs truncate">
                    {n.error_message || "-"}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
            이전
          </Button>
          <span className="text-sm text-muted-foreground">{page} / {totalPages}</span>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
            다음
          </Button>
        </div>
      )}
    </div>
  )
}
