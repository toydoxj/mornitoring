"use client"

import { useCallback, useEffect, useState, useMemo } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { ArrowDown, ArrowUp, ArrowUpDown, FileSpreadsheet, Upload, X } from "lucide-react"
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
} from "@tanstack/react-table"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import apiClient from "@/lib/api/client"
import type { Building, BuildingListResponse } from "@/types"
import { RESULT_LABELS, PHASE_LABELS, type ResultType, type PhaseType } from "@/types"
import { useAuthStore } from "@/stores/authStore"

const RESULT_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pass: "default",
  pass_supplement: "default",
  simple_error: "secondary",
  recalculate: "destructive",
}

const SUBMITTED_PHASES = new Set([
  "preliminary",
  "supplement_1",
  "supplement_2",
  "supplement_3",
  "supplement_4",
  "supplement_5",
])

type LedgerUploadResult = {
  imported: number
  updated?: number
  skipped: number
  errors?: string[]
  error?: string
}

type FieldChange = {
  field: string
  label: string
  old_value: string | null
  new_value: string | null
  scope?: "building" | "review_stage" | "reference"
}

type ReviewUploadResult = {
  success: boolean
  message: string
  errors: string[]
  warnings: string[]
  changes: FieldChange[]
}

type SortOrder = "asc" | "desc"

const SORTABLE_FIELDS = new Set([
  "mgmt_no",
  "assigned_reviewer_name",
  "address",
  "building_name",
  "main_structure",
  "high_risk_type",
  "current_phase",
  "latest_result",
  "final_result",
])

function parsePositivePage(value: string | null) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 1
}

function parseSortOrder(value: string | null): SortOrder {
  return value === "desc" ? "desc" : "asc"
}

function parseSortValue(value: string) {
  if (!value) return { field: "", order: "asc" as SortOrder }
  const separatorIndex = value.lastIndexOf("_")
  if (separatorIndex <= 0) return { field: "", order: "asc" as SortOrder }
  const field = value.slice(0, separatorIndex)
  const order = parseSortOrder(value.slice(separatorIndex + 1))
  return { field, order }
}

export default function BuildingsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const user = useAuthStore((s) => s.user)
  const [data, setData] = useState<Building[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(() => parsePositivePage(searchParams.get("page")))
  const [search, setSearch] = useState(() => searchParams.get("search") ?? "")
  const [searchInput, setSearchInput] = useState(() => searchParams.get("search") ?? "")
  const [filterPhase, setFilterPhase] = useState(() => searchParams.get("phase") ?? "")
  const [filterReviewer, setFilterReviewer] = useState(() => searchParams.get("reviewer") ?? "")
  const [sortBy, setSortBy] = useState(() => {
    const value = searchParams.get("sort_by") ?? ""
    return SORTABLE_FIELDS.has(value) ? value : ""
  })
  const [sortOrder, setSortOrder] = useState<SortOrder>(() =>
    parseSortOrder(searchParams.get("sort_order"))
  )
  const [reviewerNames, setReviewerNames] = useState<string[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<LedgerUploadResult | null>(null)
  // 검토위원 배정
  const [assignOpen, setAssignOpen] = useState(false)
  const [assignFile, setAssignFile] = useState<File | null>(null)
  const [assignPreview, setAssignPreview] = useState<{
    changes: { mgmt_no: string; reviewer_name: string; current_reviewer: string | null; status: string }[]
    summary: Record<string, number>
  } | null>(null)
  const [assigning, setAssigning] = useState(false)
  const [assignResult, setAssignResult] = useState<{ applied: number; skipped: number } | null>(null)
  // 총괄간사 검토서 대리 업로드
  const [reviewUploadTarget, setReviewUploadTarget] = useState<Building | null>(null)
  const [reviewUploadFile, setReviewUploadFile] = useState<File | null>(null)
  const [reviewUploading, setReviewUploading] = useState(false)
  const [reviewUploadResult, setReviewUploadResult] = useState<ReviewUploadResult | null>(null)
  const [reviewPreviewDone, setReviewPreviewDone] = useState(false)
  const [reviewReuploadConfirmOpen, setReviewReuploadConfirmOpen] = useState(false)
  const [reviewInappropriateNeeded, setReviewInappropriateNeeded] = useState(false)
  const pageSize = 50

  const canManage = user && ["team_leader", "chief_secretary", "secretary"].includes(user.role)
  // 통합관리대장 업로드는 총괄간사에게만 허용
  const canUploadLedger = user?.role === "chief_secretary"
  const canProxyReviewUpload = user?.role === "chief_secretary"

  const listQueryString = useMemo(() => {
    const params = new URLSearchParams()
    if (page > 1) params.set("page", String(page))
    if (search) params.set("search", search)
    if (filterPhase) params.set("phase", filterPhase)
    if (filterReviewer) params.set("reviewer", filterReviewer)
    if (sortBy) {
      params.set("sort_by", sortBy)
      params.set("sort_order", sortOrder)
    }
    return params.toString()
  }, [filterPhase, filterReviewer, page, search, sortBy, sortOrder])

  const currentListPath = listQueryString ? `/buildings?${listQueryString}` : "/buildings"

  useEffect(() => {
    router.replace(currentListPath, { scroll: false })
  }, [currentListPath, router])

  const handleExport = async () => {
    try {
      const response = await apiClient.get("/api/ledger/export", {
        responseType: "blob",
      })
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement("a")
      link.href = url
      link.download = `통합관리대장_${new Date().toISOString().slice(0, 10)}.xlsx`
      link.click()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      console.error("엑셀 다운로드 실패:", err)
    }
  }

  const fetchBuildings = useCallback(async () => {
    setIsLoading(true)
    try {
      const params: Record<string, string | number> = { page, size: pageSize }
      if (search) params.search = search
      if (filterPhase) params.phase = filterPhase
      if (filterReviewer) params.reviewer = filterReviewer
      if (sortBy) {
        params.sort_by = sortBy
        params.sort_order = sortOrder
      }
      const { data: res } = await apiClient.get<BuildingListResponse>("/api/buildings", { params })
      setData(res.items)
      setTotal(res.total)
    } catch (err) {
      console.error("건물 목록 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }, [filterPhase, filterReviewer, page, search, sortBy, sortOrder])

  useEffect(() => {
    fetchBuildings()
  }, [fetchBuildings])

  useEffect(() => {
    apiClient.get<string[]>("/api/buildings/reviewer-names")
      .then(({ data }) => setReviewerNames(data))
      .catch(() => {})
  }, [])

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploading(true)
    setUploadResult(null)
    try {
      const formData = new FormData()
      formData.append("file", file)
      const { data: result } = await apiClient.post("/api/ledger/import", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      setUploadResult(result)
      fetchBuildings()
    } catch (err) {
      const axiosErr = err as {
        response?: { data?: { detail?: unknown } }
        message?: string
      }
      const detail = axiosErr.response?.data?.detail
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((item) => String(item)).join(", ")
            : axiosErr.message || "업로드 실패"
      setUploadResult({ imported: 0, skipped: 0, error: message })
    } finally {
      setUploading(false)
      e.target.value = ""
    }
  }

  const handleAssignPreview = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setAssignFile(file)
    setAssignPreview(null)
    setAssignResult(null)
    setAssigning(true)
    try {
      const formData = new FormData()
      formData.append("file", file)
      const { data } = await apiClient.post("/api/assignments/upload/preview", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      setAssignPreview(data)
    } catch {
      setAssignPreview(null)
    } finally {
      setAssigning(false)
      e.target.value = ""
    }
  }

  const handleAssignApply = async () => {
    if (!assignFile) return
    setAssigning(true)
    try {
      const formData = new FormData()
      formData.append("file", assignFile)
      const { data } = await apiClient.post("/api/assignments/upload/apply", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      setAssignResult(data)
      setAssignPreview(null)
      setAssignFile(null)
      fetchBuildings()
    } catch {
      // 에러 처리
    } finally {
      setAssigning(false)
    }
  }

  const resetReviewUpload = () => {
    setReviewUploadFile(null)
    setReviewUploadResult(null)
    setReviewPreviewDone(false)
    setReviewReuploadConfirmOpen(false)
    setReviewInappropriateNeeded(false)
  }

  const openReviewUpload = useCallback((building: Building) => {
    setReviewUploadTarget(building)
    setReviewUploadFile(null)
    setReviewUploadResult(null)
    setReviewPreviewDone(false)
    setReviewReuploadConfirmOpen(false)
    setReviewInappropriateNeeded(Boolean(building.latest_inappropriate))
  }, [])

  const validateReviewFile = (file: File): boolean => {
    if (!file.name.toLowerCase().endsWith(".xlsm")) {
      alert(".xlsm 파일만 업로드할 수 있습니다.")
      return false
    }
    return true
  }

  const previewReviewUpload = async (file: File) => {
    if (!reviewUploadTarget) return
    setReviewUploadFile(file)
    setReviewUploading(true)
    setReviewUploadResult(null)
    setReviewPreviewDone(false)

    try {
      const formData = new FormData()
      formData.append("file", file)
      const phase = reviewUploadTarget.current_phase || "preliminary"
      const { data: result } = await apiClient.post<ReviewUploadResult>(
        "/api/reviews/upload/preview",
        formData,
        {
          params: { mgmt_no: reviewUploadTarget.mgmt_no, phase },
          headers: { "Content-Type": "multipart/form-data" },
        }
      )
      setReviewUploadResult(result)
      setReviewPreviewDone(result.success)
    } catch {
      setReviewUploadResult({
        success: false,
        message: "검증 중 오류가 발생했습니다",
        errors: ["서버 연결을 확인해주세요"],
        warnings: [],
        changes: [],
      })
    } finally {
      setReviewUploading(false)
    }
  }

  const handleReviewFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file && validateReviewFile(file)) {
      previewReviewUpload(file)
    }
    e.target.value = ""
  }

  const clearReviewUploadFile = () => {
    setReviewUploadFile(null)
    setReviewUploadResult(null)
    setReviewPreviewDone(false)
    setReviewInappropriateNeeded(Boolean(reviewUploadTarget?.latest_inappropriate))
  }

  const handleReviewUploadClick = () => {
    if (!reviewUploadTarget) return
    const isReupload =
      reviewUploadTarget.current_phase && SUBMITTED_PHASES.has(reviewUploadTarget.current_phase)
    if (isReupload) {
      setReviewReuploadConfirmOpen(true)
      return
    }
    confirmReviewUpload()
  }

  const confirmReviewUpload = async () => {
    if (!reviewUploadTarget || !reviewUploadFile) return
    const hasBuildingChanges = reviewUploadResult?.changes.some(
      (change) =>
        (!change.scope || change.scope === "building") &&
        !change.label.includes("신규")
    )
    if (hasBuildingChanges && !confirm("기존 건축물 정보가 변경됩니다. 계속하시겠습니까?")) {
      return
    }

    setReviewUploading(true)
    try {
      const formData = new FormData()
      formData.append("file", reviewUploadFile)
      const phase = reviewUploadTarget.current_phase || "preliminary"
      const effectiveInappropriateNeeded = Boolean(
        reviewUploadTarget.latest_inappropriate || reviewInappropriateNeeded
      )
      const { data: result } = await apiClient.post<ReviewUploadResult>(
        "/api/reviews/upload",
        formData,
        {
          params: {
            mgmt_no: reviewUploadTarget.mgmt_no,
            phase,
            inappropriate_review_needed: effectiveInappropriateNeeded,
          },
          headers: { "Content-Type": "multipart/form-data" },
        }
      )
      setReviewUploadResult(result)
      setReviewPreviewDone(false)
      setReviewUploadFile(null)
      setReviewInappropriateNeeded(effectiveInappropriateNeeded)
      if (result.success) {
        fetchBuildings()
        setTimeout(() => {
          setReviewUploadTarget(null)
          resetReviewUpload()
        }, 1000)
      }
    } catch {
      setReviewUploadResult({
        success: false,
        message: "업로드 중 오류가 발생했습니다",
        errors: ["서버 연결을 확인해주세요"],
        warnings: [],
        changes: [],
      })
    } finally {
      setReviewUploading(false)
    }
  }

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setPage(1)
    setSearch(searchInput.trim())
  }

  const handleSort = useCallback((field: string) => {
    setPage(1)
    setSortBy((current) => {
      if (current === field) {
        setSortOrder((order) => (order === "asc" ? "desc" : "asc"))
        return current
      }
      setSortOrder("asc")
      return field
    })
  }, [])

  const renderSortableHeader = useCallback((field: string, label: string) => {
    const active = sortBy === field
    const Icon = active ? (sortOrder === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown
    return (
      <button
        type="button"
        className="inline-flex h-8 items-center gap-1 text-left font-medium hover:text-foreground"
        onClick={() => handleSort(field)}
        aria-label={`${label} 정렬`}
      >
        <span>{label}</span>
        <Icon className={`h-3.5 w-3.5 ${active ? "text-foreground" : "text-muted-foreground"}`} />
      </button>
    )
  }, [handleSort, sortBy, sortOrder])

  const columns = useMemo<ColumnDef<Building>[]>(
    () => [
      {
        accessorKey: "mgmt_no",
        header: () => renderSortableHeader("mgmt_no", "관리번호"),
        size: 120,
        cell: ({ getValue }) => (
          <span className="font-mono font-medium">{getValue<string>()}</span>
        ),
      },
      {
        accessorKey: "reviewer_name",
        header: () => renderSortableHeader("assigned_reviewer_name", "검토자"),
        size: 80,
        cell: ({ row }) => {
          const name = row.original.reviewer_name
          if (!name) return "-"
          const registered = row.original.reviewer_registered
          return registered
            ? <span>{name}</span>
            : <span className="text-red-500">{name}</span>
        },
      },
      {
        id: "address",
        header: () => renderSortableHeader("address", "주소"),
        size: 350,
        cell: ({ row }) => {
          const b = row.original
          const base = [b.sido, b.sigungu, b.beopjeongdong].filter(Boolean).join(" ")
          const lotParts = []
          if (b.main_lot_no) {
            lotParts.push(b.sub_lot_no ? `${b.main_lot_no}-${b.sub_lot_no}` : b.main_lot_no)
          }
          if (b.special_lot_no) lotParts.push(b.special_lot_no)
          const lot = lotParts.join(" ")
          return [base, lot].filter(Boolean).join(" ") || "-"
        },
      },
      {
        accessorKey: "building_name",
        header: () => renderSortableHeader("building_name", "건물명"),
        size: 200,
        cell: ({ getValue }) => getValue<string>() || "-",
      },
      {
        accessorKey: "main_structure",
        header: () => renderSortableHeader("main_structure", "주구조"),
        size: 120,
        cell: ({ getValue }) => getValue<string>() || "-",
      },
      {
        accessorKey: "high_risk_type",
        header: () => renderSortableHeader("high_risk_type", "고위험유형"),
        size: 100,
        cell: ({ getValue }) => getValue<string>() || "-",
      },
      {
        accessorKey: "current_phase",
        header: () => renderSortableHeader("current_phase", "현재 단계"),
        size: 100,
        cell: ({ getValue }) => {
          const v = getValue<string>()
          if (!v) return "-"
          return PHASE_LABELS[v as PhaseType] || v
        },
      },
      {
        accessorKey: "latest_result",
        header: () => renderSortableHeader("latest_result", "최근판정"),
        size: 90,
        cell: ({ getValue }) => {
          const v = getValue<string>()
          if (!v) return "-"
          const variant = RESULT_VARIANT[v] || "outline"
          const label = RESULT_LABELS[v as ResultType] || v
          return <Badge variant={variant}>{label}</Badge>
        },
      },
      {
        accessorKey: "final_result",
        header: () => renderSortableHeader("final_result", "최종완료"),
        size: 90,
        cell: ({ getValue }) => {
          const v = getValue<string>()
          if (!v) return "-"
          const variant = RESULT_VARIANT[v] || "outline"
          const label = RESULT_LABELS[v as ResultType] || v
          return <Badge variant={variant}>{label}</Badge>
        },
      },
      ...(canProxyReviewUpload
        ? [
            {
              id: "review_upload",
              header: "검토서",
              size: 110,
              cell: ({ row }) => (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={(event) => {
                    event.stopPropagation()
                    openReviewUpload(row.original)
                  }}
                >
                  <Upload />
                  대리 업로드
                </Button>
              ),
            } satisfies ColumnDef<Building>,
          ]
        : []),
    ],
    [canProxyReviewUpload, openReviewUpload, renderSortableHeader]
  )

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="space-y-4">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">통합관리대장</h1>
          <p className="text-sm text-muted-foreground">
            총 {total.toLocaleString()}건
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleExport}>
            엑셀 다운로드
          </Button>
          <form onSubmit={handleSearch} className="flex gap-2">
            <Input
              placeholder="관리번호 또는 건물명 검색"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="w-64"
            />
            <Button type="submit" variant="secondary">
              검색
            </Button>
          </form>
          {canManage && (
            <Button variant="outline" onClick={() => setAssignOpen(true)}>
              검토위원 배정
            </Button>
          )}
          {canUploadLedger && (
            <Dialog open={uploadOpen} onOpenChange={setUploadOpen}>
              <Button onClick={() => setUploadOpen(true)}>엑셀 업로드</Button>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>통합관리대장 엑셀 업로드</DialogTitle>
                </DialogHeader>
                <div className="space-y-4">
                  <p className="text-sm text-muted-foreground">
                    통합관리대장 엑셀 파일(.xlsx)을 선택하여 데이터를 일괄 등록/갱신합니다.
                    이미 등록된 관리번호는 최신 엑셀 내용으로 갱신됩니다.
                  </p>
                  <Input
                    type="file"
                    accept=".xlsx,.xls"
                    onChange={handleFileUpload}
                    disabled={uploading}
                  />
                  {uploading && (
                    <p className="text-sm">업로드 및 처리 중...</p>
                  )}
                  {uploadResult && (
                    <div className="rounded-md bg-muted p-3 text-sm">
                      <p>신규 등록: <strong>{uploadResult.imported}건</strong></p>
                      <p>기존 갱신: <strong>{uploadResult.updated ?? 0}건</strong></p>
                      <p>중복 스킵: {uploadResult.skipped}건</p>
                      {uploadResult.error && (
                        <p className="mt-2 text-destructive">{uploadResult.error}</p>
                      )}
                      {uploadResult.errors && uploadResult.errors.length > 0 && (
                        <p className="mt-2 text-destructive">{uploadResult.errors.join(", ")}</p>
                      )}
                    </div>
                  )}
                </div>
              </DialogContent>
            </Dialog>
          )}
        </div>
      </div>

      {/* 필터 */}
      <div className="flex flex-wrap gap-2 items-center">
        <select
          className="rounded-md border px-3 py-2 text-sm"
          value={filterPhase}
          onChange={(e) => { setFilterPhase(e.target.value); setPage(1) }}
        >
          <option value="">전체 단계</option>
          <option value="none">미접수</option>
          <option value="doc_received">예비도서 접수</option>
          <option value="preliminary">예비검토서 제출</option>
          <option value="supplement_1_received">보완도서(1차) 접수</option>
          <option value="supplement_1">보완검토서(1차) 제출</option>
          <option value="supplement_2_received">보완도서(2차) 접수</option>
          <option value="supplement_2">보완검토서(2차) 제출</option>
          <option value="supplement_3_received">보완도서(3차) 접수</option>
          <option value="supplement_3">보완검토서(3차) 제출</option>
          <option value="completed">완료</option>
        </select>

        <select
          className="rounded-md border px-3 py-2 text-sm"
          value={filterReviewer}
          onChange={(e) => { setFilterReviewer(e.target.value); setPage(1) }}
        >
          <option value="">전체 검토위원</option>
          {reviewerNames.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>

        <select
          className="rounded-md border px-3 py-2 text-sm"
          value={sortBy ? `${sortBy}_${sortOrder}` : ""}
          onChange={(e) => {
            const { field, order } = parseSortValue(e.target.value)
            setSortBy(field)
            setSortOrder(order)
            setPage(1)
          }}
        >
          <option value="">기본 정렬</option>
          <option value="mgmt_no_asc">관리번호 ↑</option>
          <option value="mgmt_no_desc">관리번호 ↓</option>
          <option value="assigned_reviewer_name_asc">검토위원 ↑</option>
          <option value="assigned_reviewer_name_desc">검토위원 ↓</option>
          <option value="address_asc">주소 ↑</option>
          <option value="address_desc">주소 ↓</option>
          <option value="building_name_asc">건물명 ↑</option>
          <option value="building_name_desc">건물명 ↓</option>
          <option value="current_phase_asc">현재단계 ↑</option>
          <option value="current_phase_desc">현재단계 ↓</option>
          <option value="latest_result_asc">최근판정 ↑</option>
          <option value="latest_result_desc">최근판정 ↓</option>
          <option value="final_result_asc">최종완료 ↑</option>
          <option value="final_result_desc">최종완료 ↓</option>
        </select>

        {(filterPhase || filterReviewer || sortBy) && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => { setFilterPhase(""); setFilterReviewer(""); setSortBy(""); setSortOrder("asc"); setPage(1) }}
          >
            필터 초기화
          </Button>
        )}
      </div>

      {/* 테이블 */}
      <div className="rounded-md border bg-white">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id} style={{ width: header.getSize() }}>
                    {flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-32 text-center">
                  로딩 중...
                </TableCell>
              </TableRow>
            ) : data.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-32 text-center text-muted-foreground">
                  데이터가 없습니다
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className="cursor-pointer hover:bg-muted/50"
                  onClick={() =>
                    router.push(
                      `/buildings/${row.original.id}?returnTo=${encodeURIComponent(currentListPath)}`
                    )
                  }
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* 페이지네이션 */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            이전
          </Button>
          <span className="text-sm text-muted-foreground">
            {page} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            다음
          </Button>
        </div>
      )}

      {/* 총괄간사 검토서 대리 업로드 다이얼로그 */}
      <Dialog open={!!reviewUploadTarget} onOpenChange={(open) => {
        if (!open) {
          setReviewUploadTarget(null)
          resetReviewUpload()
        }
      }}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>검토서 대리 업로드</DialogTitle>
          </DialogHeader>
          {reviewUploadTarget && (
            <div className="space-y-4">
              <div className="rounded-md bg-muted p-3 text-sm space-y-1">
                <p>관리번호: <strong>{reviewUploadTarget.mgmt_no}</strong></p>
                <p>건물명: {reviewUploadTarget.building_name || "-"}</p>
                <p>검토위원: {reviewUploadTarget.reviewer_name || reviewUploadTarget.assigned_reviewer_name || "-"}</p>
                <p>현재 단계: {reviewUploadTarget.current_phase
                  ? PHASE_LABELS[reviewUploadTarget.current_phase as PhaseType] || reviewUploadTarget.current_phase
                  : "-"}</p>
              </div>

              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">
                  검토위원에게 받은 .xlsm 검토서를 선택하세요. 검토서 내부 검토위원은 배정 검토위원과 일치해야 합니다.
                </p>
                <Input
                  type="file"
                  accept=".xlsm"
                  onChange={handleReviewFileChange}
                  disabled={reviewUploading || reviewPreviewDone}
                />
                {reviewUploadFile && (
                  <div className="flex items-center gap-3 rounded-md border border-primary/30 bg-primary/5 p-3">
                    <FileSpreadsheet className="h-8 w-8 shrink-0 text-primary" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{reviewUploadFile.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {reviewUploading
                          ? "검증 중..."
                          : `${(reviewUploadFile.size / 1024).toLocaleString(undefined, { maximumFractionDigits: 1 })} KB`}
                      </p>
                    </div>
                    {!reviewUploading && (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        onClick={clearReviewUploadFile}
                        aria-label="파일 제거"
                      >
                        <X />
                      </Button>
                    )}
                  </div>
                )}
              </div>

              {reviewUploadResult && (
                <div className="space-y-2">
                  <div className={`rounded-md p-3 text-sm ${
                    reviewUploadResult.success ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"
                  }`}>
                    <p className="font-medium">{reviewUploadResult.message}</p>
                    {reviewUploadResult.errors.length > 0 && (
                      <ul className="mt-2 list-disc pl-4 space-y-1">
                        {reviewUploadResult.errors.map((err, index) => (
                          <li key={index}>{err}</li>
                        ))}
                      </ul>
                    )}
                  </div>

                  {reviewUploadResult.warnings.length > 0 && (
                    <div className="rounded-md bg-yellow-50 p-3 text-sm text-yellow-800">
                      <p className="font-medium">확인 사항</p>
                      <ul className="mt-1 list-disc pl-4 space-y-1">
                        {reviewUploadResult.warnings.map((warning, index) => (
                          <li key={index}>{warning}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {reviewUploadResult.changes.length > 0 && (() => {
                    const reviewChanges = reviewUploadResult.changes.filter((change) => change.scope === "review_stage")
                    const buildingChanges = reviewUploadResult.changes.filter((change) => !change.scope || change.scope === "building")
                    const referenceChanges = reviewUploadResult.changes.filter((change) => change.scope === "reference")
                    return (
                      <div className="space-y-2">
                        {reviewChanges.length > 0 && (
                          <div className="rounded-md bg-green-50 p-3 text-sm text-green-900">
                            <p className="font-medium">검토서 단계 변경</p>
                            <ul className="mt-1 list-disc pl-4 space-y-1">
                              {reviewChanges.map((change, index) => (
                                <li key={index}>{change.label}: {change.old_value} → {change.new_value}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {buildingChanges.length > 0 && (
                          <div className="rounded-md bg-blue-50 p-3 text-sm text-blue-800">
                            <p className="font-medium">건축물 정보 변경 내역</p>
                            <ul className="mt-1 list-disc pl-4 space-y-1">
                              {buildingChanges.map((change, index) => (
                                <li key={index}>{change.label}: {change.old_value} → {change.new_value}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {referenceChanges.length > 0 && (
                          <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                            <p className="font-medium">주요 구조 형식 검토</p>
                            <ul className="mt-1 list-disc pl-4 space-y-1">
                              {referenceChanges.map((change, index) => (
                                <li key={index}>{change.label}: {change.old_value} → {change.new_value}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )
                  })()}

                  {reviewPreviewDone && (
                    <label className="flex cursor-pointer items-start gap-2 rounded-md border border-orange-200 bg-orange-50 p-3 text-sm hover:bg-orange-100">
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4 cursor-pointer"
                        checked={reviewInappropriateNeeded}
                        onChange={(event) => setReviewInappropriateNeeded(event.target.checked)}
                      />
                      <span className="flex-1">
                        <span className="font-medium text-orange-900">부적정 사례 검토 필요</span>
                        <span className="mt-0.5 block text-xs text-orange-800">
                          본 검토 건이 부적정 사례로 별도 검토가 필요한 경우 체크해주세요.
                        </span>
                      </span>
                    </label>
                  )}

                  {reviewPreviewDone && (
                    <div className="flex gap-2">
                      <Button
                        onClick={handleReviewUploadClick}
                        loading={reviewUploading}
                        loadingText="업로드 중..."
                        className="flex-1"
                      >
                        업로드
                      </Button>
                      <Button
                        variant="outline"
                        onClick={clearReviewUploadFile}
                        disabled={reviewUploading}
                        className="flex-1"
                      >
                        취소
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={reviewReuploadConfirmOpen} onOpenChange={setReviewReuploadConfirmOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>재업로드 확인</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 text-sm">
            <p>현재 <strong>제출된 상태</strong>입니다. 다시 검토서를 업로드하시겠습니까?</p>
            <p className="text-red-600">기존 검토서는 삭제됩니다.</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReviewReuploadConfirmOpen(false)}>
              아니오
            </Button>
            <Button
              onClick={() => {
                setReviewReuploadConfirmOpen(false)
                confirmReviewUpload()
              }}
            >
              예
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 검토위원 배정 다이얼로그 */}
      <Dialog open={assignOpen} onOpenChange={(open) => {
        setAssignOpen(open)
        if (!open) { setAssignPreview(null); setAssignResult(null); setAssignFile(null) }
      }}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>검토위원 배정 엑셀 업로드</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              A열: 관리번호, B열: 검토위원 이름으로 구성된 엑셀 파일을 업로드하세요.
              배정 변경사항을 미리 확인한 후 적용할 수 있습니다.
            </p>
            <Input
              type="file"
              accept=".xlsx,.xls"
              onChange={handleAssignPreview}
              disabled={assigning}
            />
            {assigning && <p className="text-sm">처리 중...</p>}

            {assignPreview && (
              <div className="space-y-3">
                <div className="flex gap-3 text-sm">
                  <Badge variant="default">신규 {assignPreview.summary.new}건</Badge>
                  <Badge variant="secondary">변경 {assignPreview.summary.changed}건</Badge>
                  <Badge variant="outline">동일 {assignPreview.summary.same}건</Badge>
                  {assignPreview.summary.not_found > 0 && (
                    <Badge variant="destructive">관리번호 없음 {assignPreview.summary.not_found}건</Badge>
                  )}
                  {assignPreview.summary.reviewer_not_found > 0 && (
                    <Badge variant="destructive">검토위원 없음 {assignPreview.summary.reviewer_not_found}건</Badge>
                  )}
                </div>

                <div className="rounded-md border max-h-60 overflow-y-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>관리번호</TableHead>
                        <TableHead>배정 검토위원</TableHead>
                        <TableHead>현재 검토위원</TableHead>
                        <TableHead>상태</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {assignPreview.changes
                        .filter((c) => c.status !== "same")
                        .map((c, i) => (
                          <TableRow key={i}>
                            <TableCell className="font-mono">{c.mgmt_no}</TableCell>
                            <TableCell>{c.reviewer_name}</TableCell>
                            <TableCell>{c.current_reviewer || "-"}</TableCell>
                            <TableCell>
                              <Badge variant={
                                c.status === "new" ? "default" :
                                c.status === "changed" ? "secondary" :
                                "destructive"
                              }>
                                {c.status === "new" ? "신규" :
                                 c.status === "changed" ? "변경" :
                                 c.status === "not_found" ? "관리번호 없음" :
                                 "검토위원 없음"}
                              </Badge>
                            </TableCell>
                          </TableRow>
                        ))}
                    </TableBody>
                  </Table>
                </div>

                <Button onClick={handleAssignApply} loading={assigning} loadingText="적용 중..." className="w-full">
                  배정 적용
                </Button>
              </div>
            )}

            {assignResult && (
              <div className="rounded-md bg-green-50 p-3 text-sm text-green-800">
                <p>배정 완료: <strong>{assignResult.applied}건</strong> 적용</p>
                {assignResult.skipped > 0 && <p>스킵: {assignResult.skipped}건</p>}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
