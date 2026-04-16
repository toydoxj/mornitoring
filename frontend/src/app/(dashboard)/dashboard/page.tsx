"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
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

interface ReviewerStat {
  name: string
  total: number
  doc_received: number
  submitted: number
  not_submitted: number
  completed: number
}

interface DashboardStats {
  total: number
  doc_received: number
  not_submitted: number
  preliminary: number
  supplement: number
  completed: number
  reviewer_stats: ReviewerStat[]
}

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user)
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const { data } = await apiClient.get<DashboardStats>("/api/buildings/stats")
        setStats(data)
      } catch (err) {
        console.error("통계 조회 실패:", err)
      } finally {
        setIsLoading(false)
      }
    }
    fetchStats()
  }, [])

  if (isLoading || !stats) {
    return <div className="flex justify-center py-20 text-muted-foreground">로딩 중...</div>
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">대시보드</h1>
        <p className="text-sm text-muted-foreground">
          {user?.name}님, 환영합니다
        </p>
      </div>

      {/* 통계 카드 */}
      <div className="grid gap-4 md:grid-cols-5">
        <StatCard title="총 등록건" value={stats.total} />
        <StatCard title="예비도서 배포" value={stats.doc_received} color="blue" />
        <StatCard title="검토서 미접수" value={stats.not_submitted} color="red" />
        <StatCard title="보완 진행" value={stats.supplement} />
        <StatCard title="최종 완료" value={stats.completed} color="green" />
      </div>

      {/* 위원별 현황 */}
      {stats.reviewer_stats.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>검토위원별 현황</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="rounded-md border max-h-[500px] overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>검토위원</TableHead>
                    <TableHead className="w-[80px] text-center">배정</TableHead>
                    <TableHead className="w-[80px] text-center">배포</TableHead>
                    <TableHead className="w-[80px] text-center">제출</TableHead>
                    <TableHead className="w-[80px] text-center">미제출</TableHead>
                    <TableHead className="w-[80px] text-center">완료</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stats.reviewer_stats.map((r) => (
                    <TableRow key={r.name}>
                      <TableCell className="font-medium">{r.name}</TableCell>
                      <TableCell className="text-center">{r.total}</TableCell>
                      <TableCell className="text-center">{r.doc_received}</TableCell>
                      <TableCell className="text-center">
                        {r.submitted > 0 ? (
                          <Badge variant="default">{r.submitted}</Badge>
                        ) : (
                          "0"
                        )}
                      </TableCell>
                      <TableCell className="text-center">
                        {r.not_submitted > 0 ? (
                          <Badge variant="destructive">{r.not_submitted}</Badge>
                        ) : (
                          "0"
                        )}
                      </TableCell>
                      <TableCell className="text-center">{r.completed}</TableCell>
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

function StatCard({
  title,
  value,
  color,
}: {
  title: string
  value: number
  color?: "blue" | "red" | "green"
}) {
  const colorClass = color === "blue"
    ? "text-blue-600"
    : color === "red"
    ? "text-red-600"
    : color === "green"
    ? "text-green-600"
    : ""

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className={`text-3xl font-bold ${colorClass}`}>{value.toLocaleString()}</p>
      </CardContent>
    </Card>
  )
}
