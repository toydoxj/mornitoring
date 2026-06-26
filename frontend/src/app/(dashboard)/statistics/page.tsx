"use client"

import { useCallback, useEffect, useState, type ReactNode } from "react"
import { useRouter } from "next/navigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
import { RESULT_LABELS, type PhaseType, type ResultType } from "@/types"

type ActiveTab = "reviewer" | "regional" | "severity" | "keyword" | "quality" | "opinion"
type RegionalTab = "area" | "floors" | "risk" | "drawing_creator"
type SeverityLabel = "L0" | "L1" | "L2" | "L3" | "L4"
type OpinionSeverity = "NA" | SeverityLabel
type ReportMaxLabel = "pass" | SeverityLabel
type OpinionQualityDecision = "suitable" | "unsuitable"
type AreaStatKey =
  | "area_0_300"
  | "area_300_600"
  | "area_600_1000"
  | "area_1000_5000"
  | "area_5000_over"
type FloorStatKey =
  | "floors_under_6"
  | "floors_6_under_16"
  | "floors_16_over"
type RiskStatKey =
  | "special"
  | "multi_use"
  | "high_rise"
  | "quasi_multi_use"
  | "related_tech_coop_target"
  | "related_tech_coop"
  | "related_tech_coop_missing"
type DrawingCreatorStatKey =
  | "drawing_creator_architect"
  | "drawing_creator_structural_engineer"
  | "drawing_creator_unknown"

interface ReviewerStat {
  name: string
  group_no: number | null
  total: number
  total_area: number
  area_over_1000: number
  high_risk: number
  doc_received: number
  submitted: number
  not_submitted: number
  completed: number
  preliminary: ReviewerPhaseStat
  supplement: ReviewerPhaseStat
}

interface ReviewerPhaseStat {
  doc_received: number
  report_submitted: number
  results: Record<ResultType, number>
}

type RegionalStatRow<T extends string> = {
  region: string
  total?: number
} & Record<T, number>

interface RegionalStats {
  area: RegionalStatRow<AreaStatKey>[]
  floors: RegionalStatRow<FloorStatKey>[]
  risk: RegionalStatRow<RiskStatKey>[]
  drawing_creator: RegionalStatRow<DrawingCreatorStatKey>[]
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

interface SeverityReportMaxPhaseStat {
  phase: PhaseType
  counts: Record<ReportMaxLabel, number>
  total: number
}

interface SeverityReportMaxStats {
  total: number
  totals: Record<ReportMaxLabel, number>
  by_phase: SeverityReportMaxPhaseStat[]
}

interface SeverityStats {
  total: number
  totals: Record<SeverityLabel, number>
  by_category: SeverityCategoryStat[]
  by_phase: SeverityPhaseStat[]
  by_report_max: SeverityReportMaxStats
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

interface OpinionQualityCategoryStat {
  category: string
  count: number
}

interface OpinionQualityTermStat {
  term: string
  count: number
}

interface OpinionQualityTagStat {
  tag: string
  count: number
}

interface OpinionQualityLevelStat {
  level: string
  count: number
}

interface OpinionQualityItem {
  id: number
  mgmt_no: string
  group_no: number | null
  reviewer_name: string | null
  opinion: string
  matched_terms: string[]
  matched_categories: string[]
  matched_tags: string[]
  matched_levels: string[]
  recommended_replacements: string[]
  quality_decision: OpinionQualityDecision
}

interface OpinionQualityStats {
  total_details: number
  flagged_details: number
  clean_details: number
  by_category: OpinionQualityCategoryStat[]
  by_tag: OpinionQualityTagStat[]
  by_level: OpinionQualityLevelStat[]
  by_term: OpinionQualityTermStat[]
  items: OpinionQualityItem[]
}

interface OpinionDetailItem {
  id: number
  stage_id: number
  building_id: number
  mgmt_no: string
  building_name: string | null
  phase: PhaseType
  phase_group: "preliminary" | "supplement"
  row_number: number | null
  category: string
  severity: OpinionSeverity
  content: string
  result: string | null
}

interface OpinionDetailListResponse {
  items: OpinionDetailItem[]
  total: number
}

interface StatsResponse {
  reviewer_stats: ReviewerStat[]
  regional_stats: RegionalStats
  severity_stats: SeverityStats
  keyword_stats: KeywordStats
  opinion_quality_stats: OpinionQualityStats
}

interface RegionalColumn<T extends string> {
  key: T
  label: string
}

const SEVERITY_LABELS: SeverityLabel[] = ["L0", "L1", "L2", "L3", "L4"]
const OPINION_SEVERITIES: OpinionSeverity[] = ["NA", ...SEVERITY_LABELS]
const REPORT_MAX_LABELS: ReportMaxLabel[] = ["pass", ...SEVERITY_LABELS]

const OPINION_SEVERITY_LABEL_TEXT: Record<OpinionSeverity, string> = {
  NA: "미분류",
  L0: "L0",
  L1: "L1",
  L2: "L2",
  L3: "L3",
  L4: "L4",
}

const REPORT_MAX_LABEL_TEXT: Record<ReportMaxLabel, string> = {
  pass: "적합",
  L0: "L0",
  L1: "L1",
  L2: "L2",
  L3: "L3",
  L4: "L4",
}

const PHASE_LABEL_TEXT: Record<PhaseType, string> = {
  preliminary: "예비검토",
  supplement_1: "1차 보완",
  supplement_2: "2차 보완",
  supplement_3: "3차 보완",
  supplement_4: "4차 보완",
  supplement_5: "5차 보완",
}

const SEVERITY_STYLE: Record<SeverityLabel, string> = {
  L0: "border-slate-200 bg-slate-50 text-slate-700",
  L1: "border-blue-200 bg-blue-50 text-blue-700",
  L2: "border-amber-200 bg-amber-50 text-amber-700",
  L3: "border-orange-200 bg-orange-50 text-orange-700",
  L4: "border-red-200 bg-red-50 text-red-700",
}

const OPINION_SEVERITY_STYLE: Record<OpinionSeverity, string> = {
  NA: "border-muted bg-muted text-muted-foreground",
  L0: SEVERITY_STYLE.L0,
  L1: SEVERITY_STYLE.L1,
  L2: SEVERITY_STYLE.L2,
  L3: SEVERITY_STYLE.L3,
  L4: SEVERITY_STYLE.L4,
}

const RESULT_BADGE_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pass: "default",
  pass_supplement: "default",
  simple_error: "secondary",
  recalculate: "destructive",
}
const REVIEW_RESULT_KEYS: ResultType[] = ["pass", "simple_error", "recalculate"]

const REPORT_MAX_STYLE: Record<ReportMaxLabel, string> = {
  pass: "border-emerald-200 bg-emerald-50 text-emerald-700",
  L0: SEVERITY_STYLE.L0,
  L1: SEVERITY_STYLE.L1,
  L2: SEVERITY_STYLE.L2,
  L3: SEVERITY_STYLE.L3,
  L4: SEVERITY_STYLE.L4,
}

const AREA_COLUMNS: RegionalColumn<AreaStatKey>[] = [
  { key: "area_0_300", label: "0~300" },
  { key: "area_300_600", label: "300~600" },
  { key: "area_600_1000", label: "600~1000" },
  { key: "area_1000_5000", label: "1000~5000" },
  { key: "area_5000_over", label: "5000 이상" },
]

const FLOOR_COLUMNS: RegionalColumn<FloorStatKey>[] = [
  { key: "floors_under_6", label: "6층 미만" },
  { key: "floors_6_under_16", label: "6층~16층 미만" },
  { key: "floors_16_over", label: "16층 이상" },
]

const RISK_COLUMNS: RegionalColumn<RiskStatKey>[] = [
  { key: "special", label: "특수" },
  { key: "multi_use", label: "다중" },
  { key: "high_rise", label: "고층" },
  { key: "quasi_multi_use", label: "준다중" },
  { key: "related_tech_coop_target", label: "협력대상" },
  { key: "related_tech_coop", label: "협력여부" },
  { key: "related_tech_coop_missing", label: "미입력" },
]

const DRAWING_CREATOR_COLUMNS: RegionalColumn<DrawingCreatorStatKey>[] = [
  { key: "drawing_creator_architect", label: "건축사" },
  { key: "drawing_creator_structural_engineer", label: "건축구조기술사" },
  { key: "drawing_creator_unknown", label: "미확인" },
]

const TAB_TITLES: Record<ActiveTab, string> = {
  reviewer: "검토위원별 현황",
  regional: "지역별 통계",
  severity: "심각도 통계",
  keyword: "키워드 분석",
  quality: "검토의견 표현 품질",
  opinion: "의견 심각도 지정",
}

export default function StatisticsPage() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const isUserLoading = useAuthStore((s) => s.isLoading)
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [activeTab, setActiveTab] = useState<ActiveTab>("reviewer")
  const [isLoading, setIsLoading] = useState(true)

  const isAdmin =
    !!user && ["team_leader", "chief_secretary", "secretary", "manager"].includes(user.role)

  useEffect(() => {
    if (!isUserLoading && user && !isAdmin) {
      router.replace("/dashboard")
    }
  }, [isUserLoading, user, isAdmin, router])

  const fetchStats = useCallback(async () => {
    if (!isAdmin) return
    setIsLoading(true)
    try {
      const { data } = await apiClient.get<StatsResponse>("/api/buildings/stats")
      setStats(data)
    } catch (err) {
      console.error("통계 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }, [isAdmin])

  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  if (isUserLoading || !user) {
    return <div className="flex justify-center py-20 text-muted-foreground">로딩 중...</div>
  }
  if (!isAdmin) {
    return null
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">통계자료</h1>
        <p className="text-sm text-muted-foreground">
          검토위원별 현황, 지역별 통계, 심각도, 키워드, 표현 품질
        </p>
      </div>

      <div
        role="tablist"
        aria-label="통계 자료 구분"
        className="inline-flex flex-wrap gap-1 rounded-md border bg-muted/30 p-1"
      >
        <TabButton value="reviewer" activeValue={activeTab} onSelect={setActiveTab}>
          검토위원별 현황
        </TabButton>
        <TabButton value="regional" activeValue={activeTab} onSelect={setActiveTab}>
          지역별 통계
        </TabButton>
        <TabButton value="severity" activeValue={activeTab} onSelect={setActiveTab}>
          심각도 통계
        </TabButton>
        <TabButton value="keyword" activeValue={activeTab} onSelect={setActiveTab}>
          키워드 분석
        </TabButton>
        <TabButton value="quality" activeValue={activeTab} onSelect={setActiveTab}>
          표현 품질
        </TabButton>
        <TabButton value="opinion" activeValue={activeTab} onSelect={setActiveTab}>
          의견 심각도 지정
        </TabButton>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{TAB_TITLES[activeTab]}</CardTitle>
        </CardHeader>
        <CardContent>
          {activeTab === "reviewer" && (
            <ReviewerStatsTable
              isLoading={isLoading}
              rows={stats?.reviewer_stats || []}
            />
          )}
          {activeTab === "regional" && (
            <RegionalStatsView
              isLoading={isLoading}
              stats={stats?.regional_stats || null}
            />
          )}
          {activeTab === "severity" && (
            <SeverityStatsView
              isLoading={isLoading}
              stats={stats?.severity_stats || null}
            />
          )}
          {activeTab === "keyword" && (
            <KeywordStatsView
              isLoading={isLoading}
              stats={stats?.keyword_stats || null}
            />
          )}
          {activeTab === "quality" && (
            <OpinionQualityStatsView
              isLoading={isLoading}
              stats={stats?.opinion_quality_stats || null}
              onChanged={fetchStats}
            />
          )}
          {activeTab === "opinion" && (
            <OpinionSeverityManager onChanged={fetchStats} />
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function TabButton<T extends string>({
  value,
  activeValue,
  onSelect,
  children,
}: {
  value: T
  activeValue: T
  onSelect: (value: T) => void
  children: ReactNode
}) {
  const isActive = value === activeValue

  return (
    <button
      type="button"
      role="tab"
      aria-selected={isActive}
      className={`rounded px-4 py-2 text-sm font-medium transition-colors ${
        isActive
          ? "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground"
      }`}
      onClick={() => onSelect(value)}
    >
      {children}
    </button>
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
    return <LoadingMessage />
  }
  if (rows.length === 0) {
    return <EmptyMessage>배정된 검토위원이 없습니다.</EmptyMessage>
  }

  return (
    <div className="max-h-[70vh] overflow-auto rounded-md border">
      <Table className="min-w-[1180px]">
        <TableHeader>
          <TableRow>
            <TableHead rowSpan={2} className="w-[64px] text-center">조</TableHead>
            <TableHead rowSpan={2} className="min-w-[120px]">이름</TableHead>
            <TableHead colSpan={5} className="border-l text-center">예비</TableHead>
            <TableHead colSpan={5} className="border-l text-center">보완</TableHead>
            <TableHead colSpan={5} className="border-l text-center">요약</TableHead>
          </TableRow>
          <TableRow>
            <TableHead className="border-l text-center">예비도서</TableHead>
            <TableHead className="text-center">예비검토서</TableHead>
            {REVIEW_RESULT_KEYS.map((result) => (
              <TableHead key={`preliminary-${result}`} className="text-center">
                {RESULT_LABELS[result]}
              </TableHead>
            ))}
            <TableHead className="border-l text-center">보완도서</TableHead>
            <TableHead className="text-center">보완검토서</TableHead>
            {REVIEW_RESULT_KEYS.map((result) => (
              <TableHead key={`supplement-${result}`} className="text-center">
                {RESULT_LABELS[result]}
              </TableHead>
            ))}
            <TableHead className="border-l text-center">배정</TableHead>
            <TableHead className="text-right">연면적 합</TableHead>
            <TableHead className="text-center">1000㎡ 이상</TableHead>
            <TableHead className="text-center">고위험</TableHead>
            <TableHead className="text-center">완료</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={`${row.group_no ?? "none"}-${row.name}`}>
              <TableCell className="text-center">
                {row.group_no ? `${row.group_no}조` : "-"}
              </TableCell>
              <TableCell className="font-medium">{row.name}</TableCell>
              <TableCell className="border-l text-center">
                {row.preliminary.doc_received}
              </TableCell>
              <TableCell className="text-center">
                <ReviewerCountBadge value={row.preliminary.report_submitted} />
              </TableCell>
              {REVIEW_RESULT_KEYS.map((result) => (
                <TableCell key={`preliminary-${row.name}-${result}`} className="text-center">
                  <ReviewerResultBadge
                    result={result}
                    value={row.preliminary.results[result]}
                  />
                </TableCell>
              ))}
              <TableCell className="border-l text-center">
                {row.supplement.doc_received}
              </TableCell>
              <TableCell className="text-center">
                <ReviewerCountBadge value={row.supplement.report_submitted} />
              </TableCell>
              {REVIEW_RESULT_KEYS.map((result) => (
                <TableCell key={`supplement-${row.name}-${result}`} className="text-center">
                  <ReviewerResultBadge
                    result={result}
                    value={row.supplement.results[result]}
                  />
                </TableCell>
              ))}
              <TableCell className="border-l text-center">{row.total}</TableCell>
              <TableCell className="text-right font-mono text-sm">
                {row.total_area.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </TableCell>
              <TableCell className="text-center">
                {row.area_over_1000 > 0 ? (
                  <Badge variant="secondary">{row.area_over_1000}</Badge>
                ) : "0"}
              </TableCell>
              <TableCell className="text-center">
                {row.high_risk > 0 ? (
                  <Badge variant="destructive">{row.high_risk}</Badge>
                ) : "0"}
              </TableCell>
              <TableCell className="text-center">{row.completed}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function ReviewerCountBadge({ value }: { value: number }) {
  return value > 0 ? <Badge>{value}</Badge> : "0"
}

function ReviewerResultBadge({
  result,
  value,
}: {
  result: ResultType
  value: number
}) {
  return value > 0 ? (
    <Badge variant={RESULT_BADGE_VARIANT[result]}>{value}</Badge>
  ) : "0"
}

function RegionalStatsView({
  isLoading,
  stats,
}: {
  isLoading: boolean
  stats: RegionalStats | null
}) {
  const [activeRegionalTab, setActiveRegionalTab] = useState<RegionalTab>("area")

  if (isLoading) {
    return <LoadingMessage />
  }
  if (!stats) {
    return <EmptyMessage>지역별 통계가 없습니다.</EmptyMessage>
  }

  return (
    <div className="space-y-4">
      <div
        role="tablist"
        aria-label="지역별 통계 구분"
        className="inline-flex flex-wrap gap-1 rounded-md border bg-muted/30 p-1"
      >
        <TabButton value="area" activeValue={activeRegionalTab} onSelect={setActiveRegionalTab}>
          연면적
        </TabButton>
        <TabButton value="floors" activeValue={activeRegionalTab} onSelect={setActiveRegionalTab}>
          층수
        </TabButton>
        <TabButton value="risk" activeValue={activeRegionalTab} onSelect={setActiveRegionalTab}>
          고위험군 및 관계기술자
        </TabButton>
        <TabButton
          value="drawing_creator"
          activeValue={activeRegionalTab}
          onSelect={setActiveRegionalTab}
        >
          구조도면 작성자
        </TabButton>
      </div>

      {activeRegionalTab === "area" && (
        <RegionalStatsTable rows={stats.area} columns={AREA_COLUMNS} />
      )}
      {activeRegionalTab === "floors" && (
        <RegionalStatsTable rows={stats.floors} columns={FLOOR_COLUMNS} />
      )}
      {activeRegionalTab === "risk" && (
        <RegionalStatsTable rows={stats.risk} columns={RISK_COLUMNS} />
      )}
      {activeRegionalTab === "drawing_creator" && (
        <RegionalStatsTable rows={stats.drawing_creator} columns={DRAWING_CREATOR_COLUMNS} />
      )}
    </div>
  )
}

function RegionalStatsTable<T extends string>({
  rows,
  columns,
}: {
  rows: RegionalStatRow<T>[]
  columns: RegionalColumn<T>[]
}) {
  if (rows.length === 0) {
    return <EmptyMessage>집계된 지역이 없습니다.</EmptyMessage>
  }

  const totalRow = rows.find((row) => row.region === "전체") ?? rows[0]
  const getRowTotal = (row: RegionalStatRow<T>) =>
    row.total ?? columns.reduce((sum, column) => sum + (row[column.key] ?? 0), 0)
  const grandTotal = getRowTotal(totalRow)

  return (
    <div className="overflow-x-auto rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="min-w-[180px]">지역</TableHead>
            {columns.map((column) => (
              <TableHead key={column.key} className="min-w-[92px] text-center">
                {column.label}
              </TableHead>
            ))}
            <TableHead className="min-w-[80px] text-center">합계</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const isTotal = row.region === "전체"
            const rowTotal = getRowTotal(row)
            return (
              <TableRow key={row.region} className={isTotal ? "bg-muted/40" : undefined}>
                <TableCell className={isTotal ? "font-bold" : "font-medium"}>
                  {row.region}
                </TableCell>
                {columns.map((column) => {
                  const value = row[column.key] ?? 0
                  return (
                    <TableCell
                      key={column.key}
                      className={`text-center ${isTotal ? "font-bold" : ""}`}
                    >
                      <CountWithPercent value={value} denominator={rowTotal} />
                    </TableCell>
                  )
                })}
                <TableCell className={`text-center ${isTotal ? "font-bold" : "font-semibold"}`}>
                  <CountWithPercent value={rowTotal} denominator={grandTotal} />
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

function CountWithPercent({
  value,
  denominator,
}: {
  value: number
  denominator: number
}) {
  return (
    <span className="inline-flex items-baseline justify-center gap-1 whitespace-nowrap">
      <span>{value.toLocaleString()}</span>
      <span className="text-xs font-normal text-muted-foreground">
        ({formatPercent(value, denominator)})
      </span>
    </span>
  )
}

function formatPercent(value: number, denominator: number) {
  if (denominator <= 0) return "0%"
  const percent = (value / denominator) * 100
  const maximumFractionDigits = percent > 0 && percent < 10 ? 1 : 0
  return `${percent.toLocaleString(undefined, { maximumFractionDigits })}%`
}

function SeverityStatsView({
  isLoading,
  stats,
}: {
  isLoading: boolean
  stats: SeverityStats | null
}) {
  if (isLoading) {
    return <LoadingMessage />
  }
  if (!stats || stats.total === 0) {
    return <EmptyMessage>심각도 집계가 없습니다.</EmptyMessage>
  }

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <h2 className="text-sm font-semibold">상세의견 건수 기준</h2>
        <SeveritySummaryCards
          labels={SEVERITY_LABELS}
          counts={stats.totals}
          getLabel={(label) => label}
          getStyle={(label) => SEVERITY_STYLE[label]}
        />
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">검토서 최고 Lv 기준</h2>
        <SeveritySummaryCards
          labels={REPORT_MAX_LABELS}
          counts={stats.by_report_max.totals}
          getLabel={(label) => REPORT_MAX_LABEL_TEXT[label]}
          getStyle={(label) => REPORT_MAX_STYLE[label]}
        />
        <SeverityTable
          labels={REPORT_MAX_LABELS}
          labelHeader="단계"
          rows={stats.by_report_max.by_phase}
          getColumnLabel={(label) => REPORT_MAX_LABEL_TEXT[label]}
          getLabel={(row) => PHASE_LABEL_TEXT[row.phase] || row.phase}
          emptyText="검토서 최고 Lv 집계가 없습니다."
        />
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">분류별 심각도</h2>
          <SeverityTable
            labels={SEVERITY_LABELS}
            labelHeader="분류"
            rows={stats.by_category}
            getColumnLabel={(label) => label}
            getLabel={(row) => row.category}
            emptyText="분류별 심각도 집계가 없습니다."
          />
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">단계별 심각도</h2>
          <SeverityTable
            labels={SEVERITY_LABELS}
            labelHeader="단계"
            rows={stats.by_phase}
            getColumnLabel={(label) => label}
            getLabel={(row) => PHASE_LABEL_TEXT[row.phase] || row.phase}
            emptyText="단계별 심각도 집계가 없습니다."
          />
        </section>
      </div>
    </div>
  )
}

function SeveritySummaryCards<TLabel extends string>({
  labels,
  counts,
  getLabel,
  getStyle,
}: {
  labels: TLabel[]
  counts: Record<TLabel, number>
  getLabel: (label: TLabel) => string
  getStyle: (label: TLabel) => string
}) {
  const gridClass =
    labels.length >= 6
      ? "grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6"
      : "grid gap-3 sm:grid-cols-2 lg:grid-cols-5"

  return (
    <div className={gridClass}>
      {labels.map((label) => {
        const count = counts[label] ?? 0
        return (
          <div
            key={label}
            className={`rounded-md border px-4 py-3 ${getStyle(label)}`}
          >
            <p className="text-sm font-medium">{getLabel(label)}</p>
            <p className="mt-1 text-2xl font-bold">
              {count.toLocaleString()}
              <span className="ml-1 text-sm font-normal">건</span>
            </p>
          </div>
        )
      })}
    </div>
  )
}

function SeverityTable<
  TLabel extends string,
  TRow extends { counts: Record<TLabel, number>; total: number },
>({
  labels,
  labelHeader,
  rows,
  getColumnLabel,
  getLabel,
  emptyText,
}: {
  labels: TLabel[]
  labelHeader: string
  rows: TRow[]
  getColumnLabel: (label: TLabel) => string
  getLabel: (row: TRow) => string
  emptyText: string
}) {
  if (rows.length === 0) {
    return <EmptyMessage>{emptyText}</EmptyMessage>
  }

  return (
    <div className="overflow-x-auto rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{labelHeader}</TableHead>
            {labels.map((label) => (
              <TableHead key={label} className="w-[70px] text-center">
                {getColumnLabel(label)}
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
              {labels.map((label) => {
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
    return <LoadingMessage />
  }
  if (!stats || stats.total_details === 0) {
    return <EmptyMessage>상세검토 내용 분석 자료가 없습니다.</EmptyMessage>
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
        <h2 className="text-sm font-semibold">키워드별 발생 현황</h2>
        {stats.by_keyword.length === 0 ? (
          <EmptyMessage>매칭된 키워드가 없습니다.</EmptyMessage>
        ) : (
          <div className="overflow-x-auto rounded-md border">
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
  tone: "slate" | "blue" | "amber" | "emerald" | "red"
}) {
  const toneClass = {
    slate: "border-slate-200 bg-slate-50 text-slate-800",
    blue: "border-blue-200 bg-blue-50 text-blue-800",
    amber: "border-amber-200 bg-amber-50 text-amber-800",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-800",
    red: "border-red-200 bg-red-50 text-red-800",
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

function OpinionQualityStatsView({
  isLoading,
  stats,
  onChanged,
}: {
  isLoading: boolean
  stats: OpinionQualityStats | null
  onChanged: () => Promise<void>
}) {
  const [updatingId, setUpdatingId] = useState<number | null>(null)

  if (isLoading) {
    return <LoadingMessage />
  }
  if (!stats || stats.total_details === 0) {
    return <EmptyMessage>표현 품질 분석 자료가 없습니다.</EmptyMessage>
  }

  const flaggedRate = formatPercent(stats.flagged_details, stats.total_details)
  const updateQualityDecision = async (
    item: OpinionQualityItem,
    qualityDecision: OpinionQualityDecision,
  ) => {
    if (item.quality_decision === qualityDecision) return
    setUpdatingId(item.id)
    try {
      await apiClient.patch(
        `/api/reviews/opinion-details/${item.id}/quality-decision`,
        { quality_decision: qualityDecision },
      )
      await onChanged()
    } catch (err) {
      console.error("표현 품질 판정 저장 실패:", err)
    } finally {
      setUpdatingId(null)
    }
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-4">
        <KeywordSummaryCard
          label="전체 의견"
          value={stats.total_details}
          tone="slate"
        />
        <KeywordSummaryCard
          label="점검 대상"
          value={stats.flagged_details}
          tone={stats.flagged_details > 0 ? "red" : "emerald"}
        />
        <KeywordSummaryCard
          label="일반 표현"
          value={stats.clean_details}
          tone="emerald"
        />
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-amber-800">
          <p className="text-sm font-medium">점검 비율</p>
          <p className="mt-1 text-2xl font-bold">{flaggedRate}</p>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">유형별 현황</h2>
          {stats.by_category.length === 0 ? (
            <EmptyMessage>점검 대상 유형이 없습니다.</EmptyMessage>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>유형</TableHead>
                    <TableHead className="w-[90px] text-center">건수</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stats.by_category.map((row) => (
                    <TableRow key={row.category}>
                      <TableCell className="font-medium">{row.category}</TableCell>
                      <TableCell className="text-center font-semibold">
                        {row.count}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">태그별 현황</h2>
          {stats.by_tag.length === 0 ? (
            <EmptyMessage>점검 태그가 없습니다.</EmptyMessage>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>태그</TableHead>
                    <TableHead className="w-[90px] text-center">건수</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stats.by_tag.map((row) => (
                    <TableRow key={row.tag}>
                      <TableCell className="font-mono text-sm font-medium">
                        {row.tag}
                      </TableCell>
                      <TableCell className="text-center font-semibold">
                        {row.count}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">금지·주의 현황</h2>
          {stats.by_level.length === 0 ? (
            <EmptyMessage>점검 단계가 없습니다.</EmptyMessage>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>단계</TableHead>
                    <TableHead className="w-[90px] text-center">건수</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stats.by_level.map((row) => (
                    <TableRow key={row.level}>
                      <TableCell className="font-medium">{row.level}</TableCell>
                      <TableCell className="text-center font-semibold">
                        {row.count}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </section>
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">표현별 현황</h2>
        {stats.by_term.length === 0 ? (
          <EmptyMessage>점검 대상 표현이 없습니다.</EmptyMessage>
        ) : (
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>표현</TableHead>
                  <TableHead className="w-[90px] text-center">건수</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {stats.by_term.map((row) => (
                  <TableRow key={row.term}>
                    <TableCell className="font-medium">{row.term}</TableCell>
                    <TableCell className="text-center font-semibold">
                      {row.count}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      <section className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold">상세 목록</h2>
          <span className="text-sm text-muted-foreground">
            통계 포함 {stats.items.length.toLocaleString()}건
          </span>
        </div>
        {stats.items.length === 0 ? (
          <EmptyMessage>점검 대상 의견이 없습니다.</EmptyMessage>
        ) : (
          <div className="max-h-[70vh] overflow-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[140px]">관리번호</TableHead>
                  <TableHead className="w-[80px] text-center">조</TableHead>
                  <TableHead className="min-w-[120px]">검토자</TableHead>
                  <TableHead className="min-w-[420px]">의견</TableHead>
                  <TableHead className="w-[150px] text-center">판정</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {stats.items.map((item) => {
                  const isUpdating = updatingId === item.id
                  return (
                    <TableRow key={item.id}>
                      <TableCell className="font-mono text-sm font-medium">
                        {item.mgmt_no}
                      </TableCell>
                      <TableCell className="text-center">
                        {item.group_no ? `${item.group_no}조` : "-"}
                      </TableCell>
                      <TableCell className="font-medium">
                        {item.reviewer_name || "-"}
                      </TableCell>
                      <TableCell>
                        <div className="max-h-28 overflow-y-auto whitespace-pre-wrap break-words text-sm">
                          {item.opinion}
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1">
                          {item.matched_levels.map((level) => (
                            <Badge
                              key={level}
                              variant={level === "금지어" ? "destructive" : "secondary"}
                            >
                              {level}
                            </Badge>
                          ))}
                          {item.matched_tags.map((tag) => (
                            <Badge key={tag} variant="outline">
                              {tag}
                            </Badge>
                          ))}
                          {item.matched_terms.map((term) => (
                            <Badge key={term} variant="secondary">
                              {term}
                            </Badge>
                          ))}
                        </div>
                        {item.recommended_replacements.length > 0 && (
                          <div className="mt-2 text-xs text-muted-foreground">
                            권장: {item.recommended_replacements.join(", ")}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="text-center">
                        <div className="inline-flex rounded-md border bg-background p-0.5">
                          <Button
                            type="button"
                            size="xs"
                            variant="outline"
                            className="border-emerald-200 text-emerald-700 hover:bg-emerald-50"
                            disabled={isUpdating}
                            onClick={() => updateQualityDecision(item, "suitable")}
                          >
                            적합
                          </Button>
                          <Button
                            type="button"
                            size="xs"
                            variant={
                              item.quality_decision === "unsuitable"
                                ? "destructive"
                                : "outline"
                            }
                            className="ml-1"
                            disabled={isUpdating}
                            onClick={() => updateQualityDecision(item, "unsuitable")}
                          >
                            부적합
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </section>
    </div>
  )
}

function OpinionSeverityManager({ onChanged }: { onChanged: () => Promise<void> }) {
  const [items, setItems] = useState<OpinionDetailItem[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [savingId, setSavingId] = useState<number | null>(null)
  const [searchInput, setSearchInput] = useState("")
  const [search, setSearch] = useState("")
  const [severityFilter, setSeverityFilter] = useState<OpinionSeverity | "all">("NA")

  const loadOpinions = useCallback(async () => {
    setIsLoading(true)
    try {
      const { data } = await apiClient.get<OpinionDetailListResponse>(
        "/api/reviews/opinion-details",
        {
          params: {
            size: 200,
            search: search || undefined,
            severity: severityFilter === "all" ? undefined : severityFilter,
          },
        },
      )
      setItems(data.items)
      setTotal(data.total)
    } catch (err) {
      console.error("의견 상세 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }, [search, severityFilter])

  useEffect(() => {
    loadOpinions()
  }, [loadOpinions])

  const updateSeverity = async (item: OpinionDetailItem, severity: OpinionSeverity) => {
    setSavingId(item.id)
    try {
      const { data } = await apiClient.patch<OpinionDetailItem>(
        `/api/reviews/opinion-details/${item.id}/severity`,
        { severity },
      )
      setItems((prev) =>
        prev.map((current) => (current.id === item.id ? data : current)),
      )
      await onChanged()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "심각도 저장 실패"
      alert(msg)
    } finally {
      setSavingId(null)
    }
  }

  const submitSearch = () => {
    setSearch(searchInput.trim())
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-1 flex-col gap-2 sm:flex-row">
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submitSearch()
            }}
            placeholder="관리번호, 건물명, 분류, 의견 검색"
            className="sm:max-w-md"
          />
          <Button type="button" variant="outline" onClick={submitSearch}>
            검색
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="h-10 rounded-md border bg-background px-3 text-sm"
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value as OpinionSeverity | "all")}
          >
            <option value="all">전체</option>
            {OPINION_SEVERITIES.map((severity) => (
              <option key={severity} value={severity}>
                {OPINION_SEVERITY_LABEL_TEXT[severity]}
              </option>
            ))}
          </select>
          <Button type="button" variant="outline" onClick={loadOpinions} loading={isLoading}>
            새로고침
          </Button>
        </div>
      </div>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>표시 {items.length.toLocaleString()}건 / 전체 {total.toLocaleString()}건</span>
        <span>심각도를 선택하면 통계가 즉시 갱신됩니다.</span>
      </div>

      {isLoading ? (
        <LoadingMessage />
      ) : items.length === 0 ? (
        <EmptyMessage>조건에 맞는 의견 상세가 없습니다.</EmptyMessage>
      ) : (
        <div className="max-h-[70vh] overflow-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[140px]">관리번호</TableHead>
                <TableHead className="min-w-[110px]">단계</TableHead>
                <TableHead className="w-[110px] text-center">판정결과</TableHead>
                <TableHead className="min-w-[140px]">분류</TableHead>
                <TableHead className="min-w-[360px]">의견</TableHead>
                <TableHead className="w-[130px] text-center">심각도</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell>
                    <div className="font-mono text-sm font-medium">{item.mgmt_no}</div>
                    {item.building_name && (
                      <div className="mt-1 max-w-[220px] truncate text-xs text-muted-foreground">
                        {item.building_name}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {PHASE_LABEL_TEXT[item.phase] || item.phase}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-center">
                    {item.result ? (
                      <Badge variant={RESULT_BADGE_VARIANT[item.result] || "outline"}>
                        {RESULT_LABELS[item.result] || item.result}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </TableCell>
                  <TableCell className="font-medium">{item.category}</TableCell>
                  <TableCell>
                    <div className="max-h-24 overflow-y-auto whitespace-pre-wrap break-words text-sm">
                      {item.content}
                    </div>
                  </TableCell>
                  <TableCell className="text-center">
                    <select
                      className={`h-9 w-full rounded-md border px-2 text-sm ${OPINION_SEVERITY_STYLE[item.severity]}`}
                      value={item.severity}
                      disabled={savingId === item.id}
                      onChange={(e) =>
                        updateSeverity(item, e.target.value as OpinionSeverity)
                      }
                    >
                      {OPINION_SEVERITIES.map((severity) => (
                        <option key={severity} value={severity}>
                          {OPINION_SEVERITY_LABEL_TEXT[severity]}
                        </option>
                      ))}
                    </select>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

function LoadingMessage() {
  return (
    <div className="flex justify-center py-10 text-muted-foreground">
      불러오는 중...
    </div>
  )
}

function EmptyMessage({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md border py-10 text-center text-sm text-muted-foreground">
      {children}
    </div>
  )
}
