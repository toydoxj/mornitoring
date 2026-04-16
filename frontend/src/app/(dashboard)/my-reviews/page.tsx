"use client"

import { useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import apiClient from "@/lib/api/client"
import type { Building, BuildingListResponse, PhaseType, ResultType } from "@/types"
import { PHASE_LABELS, RESULT_LABELS } from "@/types"

const RESULT_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pass: "default",
  supplement: "secondary",
  fail: "destructive",
  minor: "outline",
}

interface UploadResult {
  success: boolean
  message: string
  errors: string[]
}

export default function MyReviewsPage() {
  const [data, setData] = useState<Building[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)

  // 업로드 다이얼로그 상태
  const [uploadTarget, setUploadTarget] = useState<Building | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null)

  const fetchData = async () => {
    try {
      const { data: res } = await apiClient.get<BuildingListResponse>(
        "/api/buildings/my-reviews"
      )
      setData(res.items)
      setTotal(res.total)
    } catch (err) {
      console.error("검토 대상 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !uploadTarget) return

    setUploading(true)
    setUploadResult(null)

    try {
      const formData = new FormData()
      formData.append("file", file)

      const phase = uploadTarget.current_phase || "preliminary"
      const { data: result } = await apiClient.post<UploadResult>(
        `/api/reviews/upload?mgmt_no=${uploadTarget.mgmt_no}&phase=${phase}`,
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      )
      setUploadResult(result)
      if (result.success) {
        fetchData()
      }
    } catch {
      setUploadResult({
        success: false,
        message: "업로드 중 오류가 발생했습니다",
        errors: ["서버 연결을 확인해주세요"],
      })
    } finally {
      setUploading(false)
      e.target.value = ""
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">내 검토 대상</h1>
        <p className="text-sm text-muted-foreground">
          배정된 검토 대상 {total}건
        </p>
      </div>

      <div className="rounded-md border bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[120px]">관리번호</TableHead>
              <TableHead>건물명</TableHead>
              <TableHead>주소</TableHead>
              <TableHead className="w-[100px]">연면적(㎡)</TableHead>
              <TableHead className="w-[80px]">지상층</TableHead>
              <TableHead className="w-[100px]">현재 단계</TableHead>
              <TableHead className="w-[90px]">최종 판정</TableHead>
              <TableHead className="w-[120px]">검토서</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={8} className="h-32 text-center">
                  로딩 중...
                </TableCell>
              </TableRow>
            ) : data.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="h-32 text-center text-muted-foreground">
                  배정된 검토 대상이 없습니다
                </TableCell>
              </TableRow>
            ) : (
              data.map((b) => (
                <TableRow key={b.id}>
                  <TableCell className="font-mono font-medium">{b.mgmt_no}</TableCell>
                  <TableCell>{b.building_name || "-"}</TableCell>
                  <TableCell>
                    {[b.sido, b.sigungu, b.beopjeongdong].filter(Boolean).join(" ") || "-"}
                  </TableCell>
                  <TableCell>{b.gross_area?.toLocaleString() ?? "-"}</TableCell>
                  <TableCell>{b.floors_above ?? "-"}</TableCell>
                  <TableCell>
                    {b.current_phase
                      ? PHASE_LABELS[b.current_phase as PhaseType] || b.current_phase
                      : "-"}
                  </TableCell>
                  <TableCell>
                    {b.final_result ? (
                      <Badge variant={RESULT_VARIANT[b.final_result] || "outline"}>
                        {RESULT_LABELS[b.final_result as ResultType] || b.final_result}
                      </Badge>
                    ) : (
                      "-"
                    )}
                  </TableCell>
                  <TableCell>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setUploadTarget(b)
                        setUploadResult(null)
                      }}
                    >
                      업로드
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* 검토서 업로드 다이얼로그 */}
      <Dialog open={!!uploadTarget} onOpenChange={(open) => !open && setUploadTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>검토서 업로드</DialogTitle>
          </DialogHeader>
          {uploadTarget && (
            <div className="space-y-4">
              <div className="rounded-md bg-muted p-3 text-sm space-y-1">
                <p>관리번호: <strong>{uploadTarget.mgmt_no}</strong></p>
                <p>건물명: {uploadTarget.building_name || "-"}</p>
                <p>현재 단계: {uploadTarget.current_phase
                  ? PHASE_LABELS[uploadTarget.current_phase as PhaseType] || uploadTarget.current_phase
                  : "예비검토"}</p>
              </div>

              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">
                  검토서 파일(.xlsm/.xlsx)을 선택해주세요.
                  파일명은 관리번호로 시작해야 합니다.
                </p>
                <Input
                  type="file"
                  accept=".xlsm,.xlsx,.xls"
                  onChange={handleUpload}
                  disabled={uploading}
                />
              </div>

              {uploading && (
                <p className="text-sm">업로드 및 검증 중...</p>
              )}

              {uploadResult && (
                <div className={`rounded-md p-3 text-sm ${
                  uploadResult.success ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"
                }`}>
                  <p className="font-medium">{uploadResult.message}</p>
                  {uploadResult.errors.length > 0 && (
                    <ul className="mt-2 list-disc pl-4 space-y-1">
                      {uploadResult.errors.map((err, i) => (
                        <li key={i}>{err}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
