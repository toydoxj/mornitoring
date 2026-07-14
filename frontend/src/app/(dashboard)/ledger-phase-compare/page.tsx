"use client"

import Link from "next/link"
import { useMemo, useRef, useState } from "react"
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileSpreadsheet,
  RefreshCw,
  Search,
  Upload,
  XCircle,
} from "lucide-react"
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
import { cn } from "@/lib/utils"
import { PHASE_LABELS, RESULT_LABELS } from "@/types"
import { useAuthStore } from "@/stores/authStore"

type CompareStatus =
  | "matched"
  | "mismatch"
  | "missing_db"
  | "excel_phase_missing"
  | "not_checked"
type FinalResultStatus =
  | "matched"
  | "mismatch"
  | "missing_db"
  | "excel_final_result_missing"
  | "not_checked"
type PhaseDirection = "same" | "db_ahead" | "excel_ahead" | "unknown"
type ViewMode = "issues" | "all" | "matched"

interface SupplementRoundStatus {
  round: number
  doc_column: string
  report_column: string
  doc_submitted: boolean
  report_submitted: boolean
  doc_value: string | null
  report_value: string | null
}

interface LedgerPhaseCompareItem {
  row_number: number
  management_row_number: number | null
  mgmt_no: string
  building_id: number | null
  building_name: string | null
  reviewer_name: string | null
  excel_phase: string | null
  db_phase: string | null
  excel_final_result: string | null
  excel_final_result_raw: string | null
  db_final_result: string | null
  final_result_status: FinalResultStatus
  final_result_matched: boolean | null
  final_result_column: string | null
  status: CompareStatus
  matched: boolean
  cw_completed: boolean
  phase_gap: number | null
  phase_direction: PhaseDirection
  evidence_round: number | null
  evidence_column: string | null
  evidence_value: string | null
  evidence_label: string | null
  rounds: SupplementRoundStatus[]
}

interface StageCompareSummary {
  matched: number
  mismatched: number
  missing_db: number
  excel_phase_missing: number
  compared: number
}

interface FinalResultCompareSummary {
  matched: number
  mismatched: number
  missing_db: number
  excel_final_result_missing: number
  compared: number
}

interface LedgerPhaseCompareResponse {
  sheet: string
  management_sheet: string | null
  total_rows: number
  // 단계 비교(엑셀 단계 vs DB current_phase)
  phase_compare: StageCompareSummary
  // 판정 비교(엑셀 CW 파싱 vs DB final_result)
  final_result_compare: FinalResultCompareSummary
  items: LedgerPhaseCompareItem[]
}

interface LedgerFinalResultApplyResponse {
  updated: number
  matched: number
  missing_db: number
  excel_final_result_missing: number
  warnings: string[]
}

type ErrorWithResponse = {
  response?: { data?: { detail?: unknown } }
  message?: string
}

const STATUS_LABELS: Record<CompareStatus, string> = {
  matched: "일치",
  mismatch: "불일치",
  missing_db: "DB 없음",
  excel_phase_missing: "판단 불가",
  not_checked: "-",
}

const FINAL_RESULT_STATUS_LABELS: Record<FinalResultStatus, string> = {
  matched: "일치",
  mismatch: "불일치",
  missing_db: "DB 없음",
  excel_final_result_missing: "제외/공란",
  not_checked: "-",
}

const VIEW_MODE_LABELS: Record<ViewMode, string> = {
  issues: "점검 필요",
  all: "전체",
  matched: "일치",
}

function getErrorMessage(error: unknown) {
  const err = error as ErrorWithResponse
  const detail = err.response?.data?.detail
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) return detail.map((item) => String(item)).join(", ")
  return err.message ?? "비교검토 중 오류가 발생했습니다."
}

function getPhaseLabel(phase: string | null) {
  if (!phase) return "-"
  return PHASE_LABELS[phase] ?? phase
}

function getFinalResultLabel(result: string | null) {
  if (!result) return "-"
  return RESULT_LABELS[result] ?? result
}

function getStatusVariant(status: CompareStatus): "default" | "secondary" | "destructive" | "outline" {
  if (status === "matched") return "default"
  if (status === "mismatch") return "destructive"
  if (status === "missing_db") return "secondary"
  return "outline"
}

function getFinalResultVariant(
  status: FinalResultStatus
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "matched") return "default"
  if (status === "mismatch") return "destructive"
  if (status === "missing_db") return "secondary"
  return "outline"
}

function isIssueItem(item: LedgerPhaseCompareItem) {
  return (
    item.status === "mismatch" ||
    item.status === "missing_db" ||
    item.status === "excel_phase_missing" ||
    item.final_result_status === "mismatch" ||
    item.final_result_status === "missing_db" ||
    item.final_result_status === "excel_final_result_missing"
  )
}

function getRowClass(item: LedgerPhaseCompareItem) {
  if (item.status === "mismatch" || item.final_result_status === "mismatch") {
    return "bg-red-50/80 hover:bg-red-50"
  }
  if (item.final_result_status === "excel_final_result_missing") {
    return "bg-slate-50 hover:bg-slate-100"
  }
  const status = item.status
  if (status === "missing_db") return "bg-amber-50/80 hover:bg-amber-50"
  if (status === "excel_phase_missing") return "bg-slate-50 hover:bg-slate-100"
  return ""
}

function getDirectionLabel(item: LedgerPhaseCompareItem) {
  if (item.phase_direction === "same") return "동일"
  if (item.phase_gap === null) return "-"
  const step = Math.abs(item.phase_gap)
  if (item.phase_direction === "db_ahead") return `DB가 ${step}순서 앞섬`
  if (item.phase_direction === "excel_ahead") return `엑셀이 ${step}순서 앞섬`
  return "-"
}

function SummaryStat({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone: "neutral" | "green" | "red" | "amber" | "slate"
}) {
  const toneClass = {
    neutral: "border-blue-200 bg-blue-50 text-blue-900",
    green: "border-emerald-200 bg-emerald-50 text-emerald-900",
    red: "border-red-200 bg-red-50 text-red-900",
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    slate: "border-slate-200 bg-slate-50 text-slate-900",
  }[tone]

  return (
    <div className={cn("rounded-lg border px-4 py-3", toneClass)}>
      <div className="text-xs font-medium">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value.toLocaleString()}</div>
    </div>
  )
}

function RoundMarkers({ rounds }: { rounds: SupplementRoundStatus[] }) {
  return (
    <div className="flex min-w-[260px] gap-1">
      {rounds.map((round) => (
        <div
          key={round.round}
          className="flex items-center gap-0.5 rounded-md border bg-white px-1.5 py-1 text-[11px]"
          title={`${round.round}차 도서: ${round.doc_column}, 검토서: ${round.report_column}`}
        >
          <span className="w-4 text-center font-medium">{round.round}</span>
          <span
            className={cn(
              "rounded px-1",
              round.doc_submitted ? "bg-blue-600 text-white" : "bg-muted text-muted-foreground"
            )}
          >
            도
          </span>
          <span
            className={cn(
              "rounded px-1",
              round.report_submitted ? "bg-emerald-600 text-white" : "bg-muted text-muted-foreground"
            )}
          >
            검
          </span>
        </div>
      ))}
    </div>
  )
}

export default function LedgerPhaseComparePage() {
  const user = useAuthStore((state) => state.user)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<LedgerPhaseCompareResponse | null>(null)
  const [isComparing, setIsComparing] = useState(false)
  const [isApplyingFinalResults, setIsApplyingFinalResults] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [applyMessage, setApplyMessage] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>("issues")
  const [search, setSearch] = useState("")
  const canApplyFinalResults = user?.role === "chief_secretary"

  const issueCount = result
    ? result.items.filter(isIssueItem).length
    : 0

  const filteredItems = useMemo(() => {
    if (!result) return []
    const query = search.trim().toLowerCase()
    return result.items.filter((item) => {
      if (viewMode === "issues" && !isIssueItem(item)) return false
      if (viewMode === "matched" && isIssueItem(item)) return false
      if (!query) return true

      const values = [
        item.mgmt_no,
        item.building_name,
        item.reviewer_name,
        getPhaseLabel(item.excel_phase),
        getPhaseLabel(item.db_phase),
        getFinalResultLabel(item.excel_final_result),
        getFinalResultLabel(item.db_final_result),
        item.evidence_label,
        item.evidence_column,
      ]
      return values.some((value) => value?.toLowerCase().includes(query))
    })
  }, [result, search, viewMode])

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] ?? null
    setFile(selected)
    setResult(null)
    setError(null)
    setApplyMessage(null)
    event.target.value = ""
  }

  const runCompare = async (targetFile: File) => {
    setIsComparing(true)
    setError(null)
    setApplyMessage(null)
    try {
      const formData = new FormData()
      formData.append("file", targetFile)
      const { data } = await apiClient.post<LedgerPhaseCompareResponse>(
        "/api/ledger/phase-compare",
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      )
      setResult(data)
      const hasIssues =
        data.phase_compare.mismatched +
        data.phase_compare.missing_db +
        data.phase_compare.excel_phase_missing +
        data.final_result_compare.mismatched +
        data.final_result_compare.missing_db +
        data.final_result_compare.excel_final_result_missing >
        0
      setViewMode(hasIssues ? "issues" : "all")
    } catch (err) {
      setResult(null)
      setError(getErrorMessage(err))
    } finally {
      setIsComparing(false)
    }
  }

  const handleCompare = async () => {
    if (!file) {
      setError("비교할 엑셀 파일을 선택해주세요.")
      return
    }
    await runCompare(file)
  }

  const handleApplyFinalResults = async () => {
    if (!file || !result) return
    const confirmed = window.confirm(
      `최종판정 불일치 ${result.final_result_compare.mismatched.toLocaleString()}건을 엑셀 CW열 기준으로 업데이트할까요?`
    )
    if (!confirmed) return

    setIsApplyingFinalResults(true)
    setError(null)
    setApplyMessage(null)
    try {
      const formData = new FormData()
      formData.append("file", file)
      const { data } = await apiClient.post<LedgerFinalResultApplyResponse>(
        "/api/ledger/final-results/apply",
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      )
      await runCompare(file)
      setApplyMessage(
        `최종판정 ${data.updated.toLocaleString()}건을 업데이트했습니다.`
      )
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsApplyingFinalResults(false)
    }
  }

  return (
    <div className="mx-auto flex w-[92%] flex-col gap-5 py-6 lg:w-[90%]">
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
        <div>
          <h1 className="text-2xl font-bold">통합관리대장 비교검토</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            통합 보완대장 단계와 통합 관리대장 CW 최종판정 비교
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls"
            className="sr-only"
            onChange={handleFileChange}
          />
          <Button
            type="button"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload className="h-4 w-4" />
            파일 선택
          </Button>
          <Button
            type="button"
            onClick={handleCompare}
            loading={isComparing}
            loadingText="비교 중"
            disabled={!file}
          >
            <FileSpreadsheet className="h-4 w-4" />
            비교 실행
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={handleApplyFinalResults}
            loading={isApplyingFinalResults}
            loadingText="업데이트 중"
            disabled={
              !file ||
              !result ||
              result.final_result_compare.mismatched === 0 ||
              !canApplyFinalResults
            }
            title={!canApplyFinalResults ? "총괄간사만 업데이트할 수 있습니다." : undefined}
          >
            <RefreshCw className="h-4 w-4" />
            최종판정 업데이트
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-2 rounded-lg border bg-white px-4 py-3 text-sm md:flex-row md:items-center md:justify-between">
        <div className="flex min-w-0 items-center gap-2">
          <FileSpreadsheet className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{file?.name ?? "선택된 파일 없음"}</span>
        </div>
        {result && (
          <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
            <Database className="h-4 w-4" />
            <span>{result.sheet}</span>
            {result.management_sheet && <span>/ {result.management_sheet}</span>}
          </div>
        )}
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {applyMessage && (
        <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{applyMessage}</span>
        </div>
      )}

      {result && (
        <>
          <div className="flex flex-col gap-3">
            <div>
              <div className="mb-1.5 flex items-center gap-2 text-xs font-semibold text-muted-foreground">
                판정 비교 (CW 최종판정 vs DB)
                <span className="font-normal">전체 {result.total_rows.toLocaleString()}건</span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <SummaryStat label="비교 대상" value={result.final_result_compare.compared} tone="neutral" />
                <SummaryStat label="일치" value={result.final_result_compare.matched} tone="green" />
                <SummaryStat label="불일치" value={result.final_result_compare.mismatched} tone="red" />
                <SummaryStat label="DB 없음" value={result.final_result_compare.missing_db} tone="amber" />
                <SummaryStat
                  label="제외/공란"
                  value={result.final_result_compare.excel_final_result_missing}
                  tone="slate"
                />
              </div>
            </div>
            <div>
              <div className="mb-1.5 text-xs font-semibold text-muted-foreground">
                단계 비교 (엑셀 단계 vs DB 현재 단계)
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <SummaryStat label="비교 대상" value={result.phase_compare.compared} tone="neutral" />
                <SummaryStat label="일치" value={result.phase_compare.matched} tone="green" />
                <SummaryStat label="불일치" value={result.phase_compare.mismatched} tone="red" />
                <SummaryStat label="DB 없음" value={result.phase_compare.missing_db} tone="amber" />
                <SummaryStat label="판단 불가" value={result.phase_compare.excel_phase_missing} tone="slate" />
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-3 rounded-lg border bg-white p-3 md:flex-row md:items-center md:justify-between">
            <div className="flex flex-wrap gap-1">
              {(["issues", "all", "matched"] as const).map((mode) => (
                <Button
                  key={mode}
                  type="button"
                  size="sm"
                  variant={viewMode === mode ? "secondary" : "ghost"}
                  onClick={() => setViewMode(mode)}
                >
                  {VIEW_MODE_LABELS[mode]}
                </Button>
              ))}
            </div>
            <div className="relative w-full md:w-80">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="관리번호, 단계, 검토위원 검색"
                className="pl-8"
              />
            </div>
          </div>

          <div className="rounded-lg border bg-white">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <div className="flex items-center gap-2 text-sm font-medium">
                {issueCount > 0 ? (
                  <XCircle className="h-4 w-4 text-red-600" />
                ) : (
                  <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                )}
                결과 {filteredItems.length.toLocaleString()}건
              </div>
              <Badge variant={issueCount > 0 ? "destructive" : "default"}>
                점검 필요 {issueCount.toLocaleString()}건
              </Badge>
            </div>

            <div className="overflow-x-auto">
              <Table>
                <TableHeader className="bg-muted/40">
                  <TableRow>
                    <TableHead className="w-[92px]">단계 비교</TableHead>
                    <TableHead className="w-[112px]">판정 비교</TableHead>
                    <TableHead className="w-[64px] text-right">행</TableHead>
                    <TableHead className="w-[120px]">관리번호</TableHead>
                    <TableHead className="min-w-[180px]">건물명</TableHead>
                    <TableHead className="w-[110px]">검토위원</TableHead>
                    <TableHead className="w-[150px]">엑셀 단계</TableHead>
                    <TableHead className="w-[150px]">DB 단계</TableHead>
                    <TableHead className="w-[140px]">엑셀 판정</TableHead>
                    <TableHead className="w-[140px]">DB 판정</TableHead>
                    <TableHead className="min-w-[210px]">근거</TableHead>
                    <TableHead className="min-w-[270px]">제출 흐름</TableHead>
                    <TableHead className="w-[120px]">차이</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredItems.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={13} className="h-24 text-center text-muted-foreground">
                        표시할 결과가 없습니다.
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredItems.map((item) => (
                      <TableRow
                        key={`${item.row_number}-${item.mgmt_no}`}
                        className={getRowClass(item)}
                      >
                        <TableCell>
                          <Badge variant={getStatusVariant(item.status)}>
                            {STATUS_LABELS[item.status]}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {item.final_result_status === "not_checked" ? (
                            "-"
                          ) : (
                            <Badge variant={getFinalResultVariant(item.final_result_status)}>
                              {FINAL_RESULT_STATUS_LABELS[item.final_result_status]}
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{item.row_number}</TableCell>
                        <TableCell className="font-mono text-xs">
                          {item.building_id ? (
                            <Link
                              href={`/buildings/${item.building_id}?from=ledger-phase-compare`}
                              className="font-semibold text-primary underline-offset-4 hover:underline"
                            >
                              {item.mgmt_no}
                            </Link>
                          ) : (
                            item.mgmt_no
                          )}
                        </TableCell>
                        <TableCell className="max-w-[240px] whitespace-normal">
                          {item.building_name ?? "-"}
                        </TableCell>
                        <TableCell>{item.reviewer_name ?? "-"}</TableCell>
                        <TableCell>{getPhaseLabel(item.excel_phase)}</TableCell>
                        <TableCell>{getPhaseLabel(item.db_phase)}</TableCell>
                        <TableCell>{getFinalResultLabel(item.excel_final_result)}</TableCell>
                        <TableCell>{getFinalResultLabel(item.db_final_result)}</TableCell>
                        <TableCell className="whitespace-normal">
                          {item.evidence_label && item.evidence_column ? (
                            <div>
                              <div className="font-medium">
                                {item.evidence_label} ({item.evidence_column})
                              </div>
                              {item.evidence_value && (
                                <div className="text-xs text-muted-foreground">
                                  {item.evidence_value}
                                </div>
                              )}
                            </div>
                          ) : (
                            "-"
                          )}
                        </TableCell>
                        <TableCell>
                          <RoundMarkers rounds={item.rounds} />
                        </TableCell>
                        <TableCell>{getDirectionLabel(item)}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
