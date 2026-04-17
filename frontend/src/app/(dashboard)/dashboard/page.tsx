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
import { PHASE_LABELS } from "@/types"

interface ReviewerStat {
  name: string
  total: number
  total_area: number
  area_over_1000: number
  high_risk: number
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
  phase_counts: Record<string, number>
  reviewer_stats: ReviewerStat[]
}

interface MyStats {
  total: number
  total_area: number
  area_over_1000: number
  high_risk: number
  need_review: number
  submitted: number
  submitted_preliminary: number
  submitted_supplement: number
  elapsed_buckets: Record<string, number>
}

const ELAPSED_ORDER = ["1일", "2일", "3일", "4일", "5일", "6일", "7일", "1주", "2주이상"] as const

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user)
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [myStats, setMyStats] = useState<MyStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const isAdmin = user && ["team_leader", "chief_secretary", "secretary"].includes(user.role)

  useEffect(() => {
    const fetchAll = async () => {
      try {
        // 개인 통계는 모든 로그인 사용자
        const { data: mine } = await apiClient.get<MyStats>("/api/buildings/my-stats")
        setMyStats(mine)
      } catch (err) {
        console.error("개인 통계 조회 실패:", err)
      }

      // 간사 이상만 전체 통계
      if (isAdmin) {
        try {
          const { data } = await apiClient.get<DashboardStats>("/api/buildings/stats")
          setStats(data)
        } catch (err) {
          console.error("전체 통계 조회 실패:", err)
        }
      }
      setIsLoading(false)
    }
    fetchAll()
  }, [isAdmin])

  if (isLoading) {
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

      {/* 내 담당 현황 (모든 로그인 사용자) */}
      {myStats && myStats.total > 0 && (
        <>
          <div>
            <h2 className="text-lg font-bold mb-2">내 담당 현황</h2>
            {/* 배정 | 제출된 검토서 | 연면적 | 1000↑ | 고위험 */}
            <div className="grid gap-4 md:grid-cols-5">
              <StatCard title="배정" value={myStats.total} />

              {/* 현재까지 제출된 검토서 — 예비 / 보완 분리 */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    현재까지 제출된 검토서
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-0">
                  <div className="flex items-baseline gap-4">
                    <div>
                      <p className="text-xs text-muted-foreground">예비</p>
                      <p className="text-xl font-bold">{myStats.submitted_preliminary}건</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">보완</p>
                      <p className="text-xl font-bold">{myStats.submitted_supplement}건</p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <StatCard
                title="연면적 합"
                value={Math.round(myStats.total_area)}
                suffix="㎡"
              />
              <StatCard title="1,000㎡ 이상" value={myStats.area_over_1000} color="blue" />
              <StatCard title="고위험군" value={myStats.high_risk} color="red" />
            </div>
          </div>

          {/* 검토대상 | 경과일수 (검토대상 우측에 9칸) */}
          <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
            <StatCard title="검토 대상 (미제출)" value={myStats.need_review} color="red" />
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  접수 후 경과일수 (검토서 미제출 건)
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid gap-2 grid-cols-3 md:grid-cols-5 lg:grid-cols-9">
                  {ELAPSED_ORDER.map((key) => {
                    const count = myStats.elapsed_buckets[key] ?? 0
                    const isLong = key === "1주" || key === "2주이상"
                    return (
                      <div
                        key={key}
                        className={`rounded-md border p-2 text-center ${
                          isLong && count > 0
                            ? "border-red-300 bg-red-50"
                            : count > 0
                              ? "border-orange-200 bg-orange-50"
                              : ""
                        }`}
                      >
                        <p className="text-[11px] text-muted-foreground">{key}</p>
                        <p className="text-base font-bold">{count}</p>
                      </div>
                    )
                  })}
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      )}

      {/* 전체 통계 (간사 이상) */}
      {isAdmin && stats && (
        <>
          <div>
            <h2 className="text-lg font-bold mb-2">전체 현황</h2>
            <div className="grid gap-4 md:grid-cols-5">
              <StatCard title="총 등록건" value={stats.total} />
              <StatCard title="예비도서 배포" value={stats.doc_received} color="blue" />
              <StatCard title="검토서 미접수" value={stats.not_submitted} color="red" />
              <StatCard title="보완 진행" value={stats.supplement} />
              <StatCard title="최종 완료" value={stats.completed} color="green" />
            </div>
          </div>

          {/* 단계별 현황 */}
          <Card>
            <CardHeader>
              <CardTitle>단계별 현황</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 md:grid-cols-4">
                {Object.entries(PHASE_LABELS).map(([key, label]) => {
                  const count = stats.phase_counts[key] || 0
                  if (count === 0 && !["doc_received", "preliminary", "none"].includes(key)) return null
                  return (
                    <div key={key} className="flex items-center justify-between rounded-md border p-3">
                      <span className="text-sm">{label}</span>
                      <span className="text-lg font-bold">{count}</span>
                    </div>
                  )
                })}
                <div className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm">미접수</span>
                  <span className="text-lg font-bold">{stats.phase_counts["none"] || 0}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {/* 위원별 현황 */}
      {isAdmin && stats && stats.reviewer_stats.length > 0 && (
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
                    <TableHead className="w-[70px] text-center">배정</TableHead>
                    <TableHead className="w-[100px] text-right">연면적합</TableHead>
                    <TableHead className="w-[70px] text-center">1000↑</TableHead>
                    <TableHead className="w-[70px] text-center">고위험</TableHead>
                    <TableHead className="w-[70px] text-center">배포</TableHead>
                    <TableHead className="w-[70px] text-center">제출</TableHead>
                    <TableHead className="w-[70px] text-center">미제출</TableHead>
                    <TableHead className="w-[70px] text-center">완료</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stats.reviewer_stats.map((r) => (
                    <TableRow key={r.name}>
                      <TableCell className="font-medium">{r.name}</TableCell>
                      <TableCell className="text-center">{r.total}</TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {r.total_area.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                      </TableCell>
                      <TableCell className="text-center">
                        {r.area_over_1000 > 0 ? (
                          <Badge variant="secondary">{r.area_over_1000}</Badge>
                        ) : "0"}
                      </TableCell>
                      <TableCell className="text-center">
                        {r.high_risk > 0 ? (
                          <Badge variant="destructive">{r.high_risk}</Badge>
                        ) : "0"}
                      </TableCell>
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
  suffix,
}: {
  title: string
  value: number
  color?: "blue" | "red" | "green"
  suffix?: string
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
        <p className={`text-3xl font-bold ${colorClass}`}>
          {value.toLocaleString()}
          {suffix && <span className="ml-1 text-base font-normal text-muted-foreground">{suffix}</span>}
        </p>
      </CardContent>
    </Card>
  )
}
