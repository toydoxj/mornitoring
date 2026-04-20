"use client"

import { useEffect, useState } from "react"
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

interface LoginLogItem {
  id: number
  user_id: number | null
  user_name: string | null
  user_email: string | null
  action: "login" | "login_failed"
  provider: string | null
  failure_reason: string | null
  attempted_email: string | null
  ip_address: string | null
  created_at: string
}

interface LoginLogListResponse {
  items: LoginLogItem[]
  total: number
}

const PROVIDER_LABELS: Record<string, string> = {
  password: "이메일/비번",
  kakao: "카카오",
  kakao_link: "카카오 연결",
}

const FAILURE_REASON_LABELS: Record<string, string> = {
  user_not_found: "존재하지 않는 계정",
  bad_password: "비밀번호 불일치",
}

type StatusFilter = "all" | "success" | "failed"

export default function LoginLogsPage() {
  const [data, setData] = useState<LoginLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<StatusFilter>("all")
  const [q, setQ] = useState("")
  const [qInput, setQInput] = useState("")
  const [isLoading, setIsLoading] = useState(true)
  const pageSize = 50

  const fetchData = async () => {
    setIsLoading(true)
    try {
      const params: Record<string, string | number> = { page, size: pageSize, status }
      if (q.trim()) params.q = q.trim()

      const { data: res } = await apiClient.get<LoginLogListResponse>(
        "/api/audit-logs/logins",
        { params }
      )
      setData(res.items)
      setTotal(res.total)
    } catch (err) {
      console.error("로그인 이력 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, status, q])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setPage(1)
    setQ(qInput)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">로그인 이력</h1>
          <p className="text-sm text-muted-foreground">총 {total}건</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1">
            {(["all", "success", "failed"] as const).map((f) => (
              <Button
                key={f}
                variant={status === f ? "default" : "outline"}
                size="sm"
                onClick={() => { setStatus(f); setPage(1) }}
              >
                {f === "all" ? "전체" : f === "success" ? "성공" : "실패"}
              </Button>
            ))}
          </div>
          <form onSubmit={handleSearch} className="flex gap-1">
            <Input
              type="search"
              placeholder="이름/이메일 검색"
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              className="h-9 w-48"
            />
            <Button type="submit" size="sm" variant="outline">검색</Button>
            {q && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => { setQ(""); setQInput(""); setPage(1) }}
              >
                초기화
              </Button>
            )}
          </form>
        </div>
      </div>

      <div className="rounded-md border bg-white overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[80px] text-center">상태</TableHead>
              <TableHead className="w-[140px]">사용자</TableHead>
              <TableHead className="w-[200px]">이메일</TableHead>
              <TableHead className="w-[110px]">경로</TableHead>
              <TableHead>실패 사유</TableHead>
              <TableHead className="w-[140px]">IP</TableHead>
              <TableHead className="w-[170px]">시각</TableHead>
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
                  표시할 이력이 없습니다
                </TableCell>
              </TableRow>
            ) : (
              data.map((row) => {
                const isSuccess = row.action === "login"
                const email = row.user_email || row.attempted_email || "-"
                return (
                  <TableRow key={row.id}>
                    <TableCell className="text-center">
                      <Badge variant={isSuccess ? "default" : "destructive"}>
                        {isSuccess ? "성공" : "실패"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">{row.user_name || "-"}</TableCell>
                    <TableCell className="text-sm font-mono">{email}</TableCell>
                    <TableCell className="text-sm">
                      {row.provider
                        ? PROVIDER_LABELS[row.provider] || row.provider
                        : "-"}
                    </TableCell>
                    <TableCell className="text-sm text-red-600">
                      {row.failure_reason
                        ? FAILURE_REASON_LABELS[row.failure_reason] || row.failure_reason
                        : "-"}
                    </TableCell>
                    <TableCell className="text-sm font-mono">
                      {row.ip_address || "-"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {new Date(row.created_at).toLocaleString("ko-KR")}
                    </TableCell>
                  </TableRow>
                )
              })
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
