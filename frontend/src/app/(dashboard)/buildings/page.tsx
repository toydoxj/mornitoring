"use client"

import { useEffect, useState, useMemo } from "react"
import { useRouter } from "next/navigation"
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
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import apiClient from "@/lib/api/client"
import type { Building, BuildingListResponse } from "@/types"
import { RESULT_LABELS, PHASE_LABELS, type ResultType, type PhaseType } from "@/types"
import { useAuthStore } from "@/stores/authStore"

const RESULT_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pass: "default",
  supplement: "secondary",
  fail: "destructive",
  minor: "outline",
}

export default function BuildingsPage() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const [data, setData] = useState<Building[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState("")
  const [searchInput, setSearchInput] = useState("")
  const [isLoading, setIsLoading] = useState(true)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<{ imported: number; skipped: number } | null>(null)
  const pageSize = 50

  const canManage = user && ["team_leader", "chief_secretary", "secretary"].includes(user.role)

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

  const fetchBuildings = async () => {
    setIsLoading(true)
    try {
      const params: Record<string, string | number> = { page, size: pageSize }
      if (search) params.search = search
      const { data: res } = await apiClient.get<BuildingListResponse>("/api/buildings", { params })
      setData(res.items)
      setTotal(res.total)
    } catch (err) {
      console.error("건물 목록 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchBuildings()
  }, [page, search])

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
    } catch {
      setUploadResult({ imported: 0, skipped: 0 })
    } finally {
      setUploading(false)
      e.target.value = ""
    }
  }

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setPage(1)
    setSearch(searchInput)
  }

  const columns = useMemo<ColumnDef<Building>[]>(
    () => [
      {
        accessorKey: "mgmt_no",
        header: "관리번호",
        size: 120,
        cell: ({ getValue }) => (
          <span className="font-mono font-medium">{getValue<string>()}</span>
        ),
      },
      {
        accessorKey: "building_name",
        header: "건물명",
        size: 200,
        cell: ({ getValue }) => getValue<string>() || "-",
      },
      {
        id: "address",
        header: "주소",
        size: 250,
        cell: ({ row }) => {
          const b = row.original
          return [b.sido, b.sigungu, b.beopjeongdong].filter(Boolean).join(" ") || "-"
        },
      },
      {
        accessorKey: "main_structure",
        header: "주구조",
        size: 100,
        cell: ({ getValue }) => getValue<string>() || "-",
      },
      {
        accessorKey: "gross_area",
        header: "연면적(㎡)",
        size: 100,
        cell: ({ getValue }) => {
          const v = getValue<number>()
          return v != null ? v.toLocaleString() : "-"
        },
      },
      {
        accessorKey: "floors_above",
        header: "지상층",
        size: 70,
        cell: ({ getValue }) => getValue<number>() ?? "-",
      },
      {
        accessorKey: "high_risk_type",
        header: "고위험유형",
        size: 100,
        cell: ({ getValue }) => getValue<string>() || "-",
      },
      {
        accessorKey: "current_phase",
        header: "현재 단계",
        size: 100,
        cell: ({ getValue }) => {
          const v = getValue<string>()
          if (!v) return "-"
          return PHASE_LABELS[v as PhaseType] || v
        },
      },
      {
        accessorKey: "final_result",
        header: "최종 판정",
        size: 90,
        cell: ({ getValue }) => {
          const v = getValue<string>()
          if (!v) return "-"
          const variant = RESULT_VARIANT[v] || "outline"
          const label = RESULT_LABELS[v as ResultType] || v
          return <Badge variant={variant}>{label}</Badge>
        },
      },
    ],
    []
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
            <Dialog open={uploadOpen} onOpenChange={setUploadOpen}>
              <DialogTrigger>
                <Button>엑셀 업로드</Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>통합관리대장 엑셀 업로드</DialogTitle>
                </DialogHeader>
                <div className="space-y-4">
                  <p className="text-sm text-muted-foreground">
                    통합관리대장 엑셀 파일(.xlsx)을 선택하여 데이터를 일괄 등록합니다.
                    이미 등록된 관리번호는 건너뜁니다.
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
                      <p>중복 스킵: {uploadResult.skipped}건</p>
                    </div>
                  )}
                </div>
              </DialogContent>
            </Dialog>
          )}
        </div>
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
                  onClick={() => router.push(`/buildings/${row.original.id}`)}
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
    </div>
  )
}
