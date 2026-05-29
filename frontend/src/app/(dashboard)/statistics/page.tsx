"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
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
import { useAuthStore } from "@/stores/authStore"
import { PHASE_LABELS, type PhaseType } from "@/types"

type ActiveTab = "reviewer" | "severity" | "keyword"
type SeverityLabel = "L0" | "L1" | "L2" | "L3" | "L4"

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

interface SeverityPivotRow {
  counts: Record<SeverityLabel, number>
  total: number
}

interface SeverityCategoryStat extends SeverityPivotRow {
  category: string
}

interface SeverityPhaseStat extends SeverityPivotRow {
  phase: PhaseType
}

interface SeverityStats {
  total: number
  totals: Record<SeverityLabel, number>
  by_category: SeverityCategoryStat[]
  by_phase: SeverityPhaseStat[]
}

interface KeywordStat {
  keyword: string
  total: number
  preliminary: number
  supplement: number
  L0: number
  L1: number
  L2: number
  L3: number
  L4: number
}

interface KeywordStats {
  total_details: number
  detail_counts: {
    preliminary: number
    supplement: number
  }
  by_keyword: KeywordStat[]
}

interface StatsResponse {
  reviewer_stats: ReviewerStat[]
  severity_stats: SeverityStats
  keyword_stats: KeywordStats
}

const SEVERITY_LABELS: SeverityLabel[] = ["L0", "L1", "L2", "L3", "L4"]

const SEVERITY_STYLE: Record<SeverityLabel, string> = {
  L0: "border-slate-200 bg-slate-50 text-slate-700",
  L1: "border-blue-200 bg-blue-50 text-blue-700",
  L2: "border-amber-200 bg-amber-50 text-amber-700",
  L3: "border-orange-200 bg-orange-50 text-orange-700",
  L4: "border-red-200 bg-red-50 text-red-700",
}

export default function StatisticsPage() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const isUserLoading = useAuthStore((s) => s.isLoading)
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [activeTab, setActiveTab] = useState<ActiveTab>("reviewer")
  const [isLoading, setIsLoading] = useState(true)

  const isAdmin =
    !!user && ["team_leader", "chief_secretary", "secretary"].includes(user.role)

  // 검토위원은 접근 불가 — 사용자 정보 로드 후 비인가 접근 시 대시보드로 이동
  useEffect(() => {
    if (!isUserLoading && user && !isAdmin) {
      router.replace("/dashboard")
    }
  }, [isUserLoading, user, isAdmin, router])

  useEffect(() => {
    if (!isAdmin) return
    const fetchStats = async () => {
      setIsLoading(true)
      try {
        const { data } = await apiClient.get<StatsResponse>("/api/buildings/stats")
        setStats(data)
      } catch (err) {
        console.error("통계 조회 실패:", err)
      } finally {
        setIsLoading(false)
      }
    }
    fetchStats()
  }, [isAdmin])

  if (isUserLoading || !user) {
    return <div className="flex justify-center py-20 text-muted-foreground">로딩 중...</div>
  }
  if (!isAdmin) {
    // 리다이렉트 대기 중 빈 상태
    return null
  }

  const reviewerRows = stats?.reviewer_stats || []
  const severityStats = stats?.severity_stats || null
  const keywordStats = stats?.keyword_stats || null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">통계자료</h1>
        <p className="text-sm text-muted-foreground">검토위원별 현황, 심각도, 키워드 분석</p>
      </div>

      <div
        role="tablist"
        aria-label="통계 자료 구분"
        className="inline-flex rounded-md border bg-muted/30 p-1"
      >
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "reviewer"}
          className={`rounded px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === "reviewer"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => setActiveTab("reviewer")}
        >
          검토위원별 현황
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "severity"}
          className={`rounded px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === "severity"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => setActiveTab("severity")}
        >
          심각도 통계
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "keyword"}
          className={`rounded px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === "keyword"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => setActiveTab("keyword")}
        >
          키워드 분석
        </button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            {activeTab === "reviewer"
              ? "검토위원별 현황"
              : activeTab === "severity"
                ? "심각도 통계"
                : "키워드 분석"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {activeTab === "reviewer" && (
            <ReviewerStatsTable isLoading={isLoading} rows={reviewerRows} />
          )}
          {activeTab === "severity" && (
            <SeverityStatsView isLoading={isLoading} stats={severityStats} />
          )}
          {activeTab === "keyword" && (
            <KeywordStatsView isLoading={isLoading} stats={keywordStats} />
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function ReviewerStatsTable({
  isLoading,
  rows,
}: {
  isLoading: boolean
  rows: ReviewerStat[]
}) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-10 text-muted-foreground">
        불러오는 중...
      </div>
    )
  }
  if (rows.length === 0) {
    return (
      <div className="flex justify-center py-10 text-muted-foreground">
        배정된 검토위원이 없습니다.
      </div>
    )
  }
  return (
    <div className="rounded-md border max-h-[70vh] overflow-y-auto">
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
          {rows.map((r) => (
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
  )
}

function SeverityStatsView({
  isLoading,
  stats,
}: {
  isLoading: boolean
  stats: SeverityStats | null
}) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-10 text-muted-foreground">
        불러오는 중...
      </div>
    )
  }
  if (!stats || stats.total === 0) {
    return (
      <div className="flex justify-center py-10 text-muted-foreground">
        심각도 집계가 없습니다.
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {SEVERITY_LABELS.map((label) => {
          const count = stats.totals[label] ?? 0
          return (
            <div
              key={label}
              className={`rounded-md border px-4 py-3 ${SEVERITY_STYLE[label]}`}
            >
              <p className="text-sm font-medium">{label}</p>
              <p className="mt-1 text-2xl font-bold">
                {count.toLocaleString()}
                <span className="ml-1 text-sm font-normal">건</span>
              </p>
            </div>
          )
        })}
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <section className="space-y-2">
          <div>
            <h2 className="text-sm font-semibold">분류별 심각도</h2>
            <p className="text-xs text-muted-foreground">
              상세의견 분류 기준 집계
            </p>
          </div>
          <SeverityTable
            labelHeader="분류"
            rows={stats.by_category}
            getLabel={(row) => row.category}
            emptyText="분류별 심각도 집계가 없습니다."
          />
        </section>

        <section className="space-y-2">
          <div>
            <h2 className="text-sm font-semibold">단계별 심각도</h2>
            <p className="text-xs text-muted-foreground">
              검토서 제출 단계 기준 집계
            </p>
          </div>
          <SeverityTable
            labelHeader="단계"
            rows={stats.by_phase}
            getLabel={(row) => PHASE_LABELS[row.phase] || row.phase}
            emptyText="단계별 심각도 집계가 없습니다."
          />
        </section>
      </div>
    </div>
  )
}

function SeverityTable<T extends SeverityPivotRow>({
  labelHeader,
  rows,
  getLabel,
  emptyText,
}: {
  labelHeader: string
  rows: T[]
  getLabel: (row: T) => string
  emptyText: string
}) {
  if (rows.length === 0) {
    return (
      <div className="rounded-md border py-10 text-center text-sm text-muted-foreground">
        {emptyText}
      </div>
    )
  }

  return (
    <div className="rounded-md border overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{labelHeader}</TableHead>
            {SEVERITY_LABELS.map((label) => (
              <TableHead key={label} className="w-[70px] text-center">
                {label}
              </TableHead>
            ))}
            <TableHead className="w-[80px] text-center">합계</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${getLabel(row)}-${index}`}>
              <TableCell className="min-w-[220px] font-medium">
                {getLabel(row)}
              </TableCell>
              {SEVERITY_LABELS.map((label) => {
                const count = row.counts[label] ?? 0
                return (
                  <TableCell key={label} className="text-center">
                    {count > 0 ? (
                      <Badge
                        variant={
                          label === "L3" || label === "L4"
                            ? "destructive"
                            : "secondary"
                        }
                      >
                        {count}
                      </Badge>
                    ) : (
                      "0"
                    )}
                  </TableCell>
                )
              })}
              <TableCell className="text-center font-semibold">
                {row.total}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function KeywordStatsView({
  isLoading,
  stats,
}: {
  isLoading: boolean
  stats: KeywordStats | null
}) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-10 text-muted-foreground">
        불러오는 중...
      </div>
    )
  }
  if (!stats || stats.total_details === 0) {
    return (
      <div className="flex justify-center py-10 text-muted-foreground">
        상세검토 내용 저장 자료가 없습니다.
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-3">
        <KeywordSummaryCard
          label="상세내용 총합"
          value={stats.total_details}
          tone="slate"
        />
        <KeywordSummaryCard
          label="예비검토"
          value={stats.detail_counts.preliminary}
          tone="blue"
        />
        <KeywordSummaryCard
          label="보완검토"
          value={stats.detail_counts.supplement}
          tone="amber"
        />
      </div>

      <section className="space-y-2">
        <div>
          <h2 className="text-sm font-semibold">키워드별 발생 현황</h2>
          <p className="text-xs text-muted-foreground">
            저장된 상세검토 내용 원문에서 사전 기반 키워드를 집계합니다.
          </p>
        </div>
        {stats.by_keyword.length === 0 ? (
          <div className="rounded-md border py-10 text-center text-sm text-muted-foreground">
            매칭된 키워드가 없습니다.
          </div>
        ) : (
          <div className="rounded-md border overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>키워드</TableHead>
                  <TableHead className="w-[90px] text-center">합계</TableHead>
                  <TableHead className="w-[90px] text-center">예비</TableHead>
                  <TableHead className="w-[90px] text-center">보완</TableHead>
                  {SEVERITY_LABELS.map((label) => (
                    <TableHead key={label} className="w-[70px] text-center">
                      {label}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {stats.by_keyword.map((row) => (
                  <TableRow key={row.keyword}>
                    <TableCell className="font-medium">{row.keyword}</TableCell>
                    <TableCell className="text-center font-semibold">
                      {row.total}
                    </TableCell>
                    <TableCell className="text-center">{row.preliminary}</TableCell>
                    <TableCell className="text-center">{row.supplement}</TableCell>
                    {SEVERITY_LABELS.map((label) => {
                      const count = row[label] ?? 0
                      return (
                        <TableCell key={label} className="text-center">
                          {count > 0 ? (
                            <Badge
                              variant={
                                label === "L3" || label === "L4"
                                  ? "destructive"
                                  : "secondary"
                              }
                            >
                              {count}
                            </Badge>
                          ) : (
                            "0"
                          )}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>
    </div>
  )
}

function KeywordSummaryCard({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone: "slate" | "blue" | "amber"
}) {
  const toneClass = {
    slate: "border-slate-200 bg-slate-50 text-slate-800",
    blue: "border-blue-200 bg-blue-50 text-blue-800",
    amber: "border-amber-200 bg-amber-50 text-amber-800",
  }[tone]

  return (
    <div className={`rounded-md border px-4 py-3 ${toneClass}`}>
      <p className="text-sm font-medium">{label}</p>
      <p className="mt-1 text-2xl font-bold">
        {value.toLocaleString()}
        <span className="ml-1 text-sm font-normal">건</span>
      </p>
    </div>
  )
}
