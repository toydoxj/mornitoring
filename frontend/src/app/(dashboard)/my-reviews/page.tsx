"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { FileSpreadsheet, Upload, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Dialog,
  DialogContent,
  DialogFooter,
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
  simple_error: "secondary",
  recalculate: "destructive",
}

// 이미 검토서가 제출된 단계 (재업로드 경고 대상)
const SUBMITTED_PHASES = new Set([
  "preliminary",
  "supplement_1",
  "supplement_2",
  "supplement_3",
  "supplement_4",
  "supplement_5",
])

interface FieldChange {
  field: string
  label: string
  old_value: string | null
  new_value: string | null
  scope?: "building" | "review_stage" | "reference"
}

interface UploadResult {
  success: boolean
  message: string
  errors: string[]
  warnings: string[]
  changes: FieldChange[]
}

export default function MyReviewsPage() {
  const router = useRouter()
  const [data, setData] = useState<Building[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)

  // 업로드 다이얼로그 상태
  const [uploadTarget, setUploadTarget] = useState<Building | null>(null)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null)
  const [previewDone, setPreviewDone] = useState(false)
  const [inappropriateReviewNeeded, setInappropriateReviewNeeded] = useState(false)
  const [reuploadConfirmOpen, setReuploadConfirmOpen] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // 문의 사유 다이얼로그
  const [reasonTarget, setReasonTarget] = useState<Building | null>(null)
  const [reasonText, setReasonText] = useState("")
  const [reasonSubmitting, setReasonSubmitting] = useState(false)

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

  const handleReasonSubmit = async () => {
    if (!reasonTarget || !reasonText.trim()) return
    setReasonSubmitting(true)
    try {
      await apiClient.post("/api/reviews/inquiry", {
        mgmt_no: reasonTarget.mgmt_no,
        phase: reasonTarget.current_phase || "preliminary",
        content: reasonText.trim(),
      })
      setReasonTarget(null)
      setReasonText("")
      alert("문의 사유가 저장되었습니다")
    } catch {
      alert("저장 실패")
    } finally {
      setReasonSubmitting(false)
    }
  }

  // 1단계: 파일 선택 → 미리보기 (검증만)
  const processFile = async (file: File) => {
    if (!uploadTarget) return
    setUploadFile(file)
    setUploading(true)
    setUploadResult(null)
    setPreviewDone(false)

    try {
      const formData = new FormData()
      formData.append("file", file)

      const phase = uploadTarget.current_phase || "preliminary"
      const { data: result } = await apiClient.post<UploadResult>(
        `/api/reviews/upload/preview?mgmt_no=${uploadTarget.mgmt_no}&phase=${phase}`,
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      )
      setUploadResult(result)
      setPreviewDone(result.success)
    } catch {
      setUploadResult({
        success: false,
        message: "검증 중 오류가 발생했습니다",
        errors: ["서버 연결을 확인해주세요"],
        warnings: [],
        changes: [],
      })
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ""
    }
  }

  const validateExtension = (file: File): boolean => {
    if (!file.name.toLowerCase().endsWith(".xlsm")) {
      alert(".xlsm 파일만 업로드할 수 있습니다.")
      return false
    }
    return true
  }

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file && validateExtension(file)) processFile(file)
  }

  const handleDrop = (e: React.DragEvent<HTMLElement>) => {
    e.preventDefault()
    setIsDragging(false)
    if (uploading || previewDone) return
    const file = e.dataTransfer.files?.[0]
    if (file && validateExtension(file)) processFile(file)
  }

  const handleClearFile = () => {
    setUploadFile(null)
    setUploadResult(null)
    setPreviewDone(false)
    setInappropriateReviewNeeded(false)
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  // 업로드 버튼 클릭 핸들러 — 재업로드 확인 다이얼로그 체크
  const handleUploadClick = () => {
    if (!uploadTarget) return
    const isReupload =
      uploadTarget.current_phase && SUBMITTED_PHASES.has(uploadTarget.current_phase)
    if (isReupload) {
      setReuploadConfirmOpen(true)
      return
    }
    handleConfirmUpload()
  }

  // 2단계: 확인 후 업로드
  const handleConfirmUpload = async () => {
    if (!uploadFile || !uploadTarget) return

    const hasChanges = uploadResult?.changes && uploadResult.changes.some(
      c => (!c.scope || c.scope === "building") && !c.label.includes("신규")
    )
    if (hasChanges) {
      if (!confirm("기존 건축물 정보가 변경됩니다. 계속하시겠습니까?")) return
    }

    setUploading(true)

    try {
      const formData = new FormData()
      formData.append("file", uploadFile)

      const phase = uploadTarget.current_phase || "preliminary"
      const { data: result } = await apiClient.post<UploadResult>(
        `/api/reviews/upload?mgmt_no=${uploadTarget.mgmt_no}&phase=${phase}&inappropriate_review_needed=${inappropriateReviewNeeded}`,
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      )
      setUploadResult(result)
      setPreviewDone(false)
      setUploadFile(null)
      setInappropriateReviewNeeded(false)
      if (result.success) {
        fetchData()
        // 성공 알림을 1초간 보여준 뒤 다이얼로그 닫기
        setTimeout(() => {
          setUploadTarget(null)
          setUploadResult(null)
        }, 1000)
      }
    } catch {
      setUploadResult({
        success: false,
        message: "업로드 중 오류가 발생했습니다",
        errors: ["서버 연결을 확인해주세요"],
        warnings: [],
        changes: [],
      })
    } finally {
      setUploading(false)
    }
  }

  const handleCancelUpload = () => {
    setUploadFile(null)
    setUploadResult(null)
    setPreviewDone(false)
    setInappropriateReviewNeeded(false)
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">내 검토 대상</h1>
        <p className="text-sm text-muted-foreground">
          배정된 검토 대상 {total}건
        </p>
      </div>

      <div className="rounded-md border bg-white overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[120px] text-center">관리번호</TableHead>
              <TableHead className="w-[220px]">주소</TableHead>
              <TableHead className="w-[100px] text-center">연면적(㎡)</TableHead>
              <TableHead className="w-[80px] text-center">지상층</TableHead>
              <TableHead className="w-[120px] text-center">고위험군</TableHead>
              <TableHead className="w-[80px] text-center">부적합</TableHead>
              <TableHead className="w-[120px] text-center">현재단계</TableHead>
              <TableHead className="w-[90px] text-center">최근판정</TableHead>
              <TableHead className="w-[100px] text-center">검토서</TableHead>
              <TableHead className="w-[80px] text-center">문의</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={10} className="h-32 text-center">
                  로딩 중...
                </TableCell>
              </TableRow>
            ) : data.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} className="h-32 text-center text-muted-foreground">
                  배정된 검토 대상이 없습니다
                </TableCell>
              </TableRow>
            ) : (
              data.map((b) => (
                <TableRow key={b.id}>
                  <TableCell
                    className="font-mono font-medium text-blue-600 cursor-pointer hover:underline text-center"
                    onClick={() => router.push(`/buildings/${b.id}?from=my-reviews`)}
                  >
                    {b.mgmt_no}
                  </TableCell>
                  <TableCell
                    className="text-sm max-w-[220px] truncate"
                    title={b.building_name ?? undefined}
                  >
                    {b.full_address || "-"}
                  </TableCell>
                  <TableCell className="text-center">{b.gross_area?.toLocaleString() ?? "-"}</TableCell>
                  <TableCell className="text-center">{b.floors_above ?? "-"}</TableCell>
                  <TableCell className="text-sm text-center">
                    {(() => {
                      const tags: string[] = []
                      if (b.is_special_structure) tags.push("특수")
                      if (b.is_high_rise) tags.push("고층")
                      if (b.is_multi_use) tags.push("다중이용")
                      return tags.length > 0 ? (
                        <div className="flex flex-wrap justify-center gap-1">
                          {tags.map((t) => (
                            <Badge key={t} variant="outline" className="text-xs">
                              {t}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )
                    })()}
                  </TableCell>
                  <TableCell className="text-center">
                    {b.latest_inappropriate ? (
                      <Badge variant="destructive">해당</Badge>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-center">
                    {b.current_phase
                      ? PHASE_LABELS[b.current_phase as PhaseType] || b.current_phase
                      : "-"}
                  </TableCell>
                  <TableCell className="text-center">
                    {b.latest_result ? (
                      <Badge variant={RESULT_VARIANT[b.latest_result] || "outline"}>
                        {RESULT_LABELS[b.latest_result as ResultType] || b.latest_result}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </TableCell>
                  <TableCell className="text-center">
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
                  <TableCell className="text-center">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setReasonTarget(b)
                        setReasonText("")
                      }}
                    >
                      문의
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* 검토서 업로드 다이얼로그 */}
      <Dialog open={!!uploadTarget} onOpenChange={(open) => {
        if (!open) {
          setUploadTarget(null)
          setUploadFile(null)
          setUploadResult(null)
          setPreviewDone(false)
          setInappropriateReviewNeeded(false)
        }
      }}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
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
                  검토서 파일(.xlsm)을 선택하거나 드래그해주세요.
                  파일명은 관리번호로 시작해야 합니다.
                </p>

                {/* 숨은 파일 input */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsm"
                  onChange={handleFileInputChange}
                  disabled={uploading || previewDone}
                  className="hidden"
                />

                {/* 드롭존 카드 */}
                {!uploadFile ? (
                  <button
                    type="button"
                    disabled={uploading || previewDone}
                    onClick={() => fileInputRef.current?.click()}
                    onDragOver={(e) => {
                      e.preventDefault()
                      if (!uploading && !previewDone) setIsDragging(true)
                    }}
                    onDragLeave={() => setIsDragging(false)}
                    onDrop={handleDrop}
                    className={`group flex w-full flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 transition-all
                      ${isDragging
                        ? "border-primary bg-primary/5 scale-[1.01]"
                        : "border-muted-foreground/30 hover:border-primary/60 hover:bg-muted/50"}
                      ${uploading || previewDone ? "cursor-not-allowed opacity-50" : "cursor-pointer"}
                    `}
                  >
                    <Upload className={`h-8 w-8 transition-transform ${isDragging ? "-translate-y-1 text-primary" : "text-muted-foreground group-hover:-translate-y-0.5 group-hover:text-primary"}`} />
                    <span className="text-sm font-medium">
                      {isDragging ? "놓으면 업로드 시작" : "클릭 또는 파일을 드래그하세요"}
                    </span>
                    <span className="text-xs text-muted-foreground">.xlsm 파일만 가능</span>
                  </button>
                ) : (
                  <div className="flex items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 p-3">
                    <FileSpreadsheet className="h-8 w-8 text-primary shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{uploadFile.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {uploading
                          ? "검증 중..."
                          : `${(uploadFile.size / 1024).toLocaleString(undefined, { maximumFractionDigits: 1 })} KB`}
                      </p>
                    </div>
                    {!uploading && (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        onClick={handleClearFile}
                        aria-label="파일 제거"
                      >
                        <X />
                      </Button>
                    )}
                  </div>
                )}
              </div>

              {uploadResult && (
                <div className="space-y-2">
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
                  {uploadResult.warnings && uploadResult.warnings.length > 0 && (
                    <div className="rounded-md p-3 text-sm bg-yellow-50 text-yellow-800">
                      <p className="font-medium">확인 사항</p>
                      <ul className="mt-1 list-disc pl-4 space-y-1">
                        {uploadResult.warnings.map((w, i) => (
                          <li key={i}>{w}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {uploadResult.changes && uploadResult.changes.length > 0 && (() => {
                    const reviewChanges = uploadResult.changes.filter((c) => c.scope === "review_stage")
                    const buildingChanges = uploadResult.changes.filter((c) => !c.scope || c.scope === "building")
                    const referenceChanges = uploadResult.changes.filter((c) => c.scope === "reference")
                    return (
                      <div className="space-y-2">
                        {reviewChanges.length > 0 && (
                          <div className="rounded-md p-3 text-sm bg-green-50 text-green-900">
                            <p className="font-medium">검토서 단계 변경</p>
                            <ul className="mt-1 list-disc pl-4 space-y-1">
                              {reviewChanges.map((c, i) => (
                                <li key={i}>{c.label}: {c.old_value} → {c.new_value}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {buildingChanges.length > 0 && (
                          <div className="rounded-md p-3 text-sm bg-blue-50 text-blue-800">
                            <p className="font-medium">건축물 정보 변경 내역</p>
                            <ul className="mt-1 list-disc pl-4 space-y-1">
                              {buildingChanges.map((c, i) => (
                                <li key={i}>{c.label}: {c.old_value} → {c.new_value}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {referenceChanges.length > 0 && (
                          <div className="rounded-md p-3 text-sm bg-amber-50 text-amber-900 border border-amber-200">
                            <p className="font-medium">주요 구조 형식 검토</p>
                            <ul className="mt-1 list-disc pl-4 space-y-1">
                              {referenceChanges.map((c, i) => (
                                <li key={i}>{c.label}: {c.old_value} → {c.new_value}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )
                  })()}

                  {/* 부적정 사례 검토 필요 체크박스 (미리보기 성공 시) */}
                  {previewDone && (
                    <label className="flex items-start gap-2 rounded-md border border-orange-200 bg-orange-50 p-3 text-sm cursor-pointer hover:bg-orange-100 transition-colors">
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4 cursor-pointer"
                        checked={inappropriateReviewNeeded}
                        onChange={(e) => setInappropriateReviewNeeded(e.target.checked)}
                      />
                      <span className="flex-1">
                        <span className="font-medium text-orange-900">부적정 사례 검토 필요</span>
                        <span className="block text-xs text-orange-800 mt-0.5">
                          본 검토 건이 부적정 사례로 별도 검토가 필요한 경우 체크해주세요.
                        </span>
                      </span>
                    </label>
                  )}

                  {/* 업로드/취소 버튼 (미리보기 성공 시) */}
                  {previewDone && (
                    <div className="flex gap-2">
                      <Button onClick={handleUploadClick} loading={uploading} loadingText="업로드 중..." className="flex-1">
                        업로드
                      </Button>
                      <Button variant="outline" onClick={handleCancelUpload} disabled={uploading} className="flex-1">
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

      {/* 문의 사유 다이얼로그 */}
      <Dialog open={!!reasonTarget} onOpenChange={(open) => !open && setReasonTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>검토서 문의 사유</DialogTitle>
          </DialogHeader>
          {reasonTarget && (
            <div className="space-y-4">
              <div className="rounded-md bg-muted p-3 text-sm">
                <p>관리번호: <strong>{reasonTarget.mgmt_no}</strong></p>
                <p>건물명: {reasonTarget.building_name || "-"}</p>
              </div>
              <div className="space-y-2">
                <Label>문의 사유</Label>
                <textarea
                  className="w-full min-h-[100px] rounded-md border px-3 py-2 text-sm"
                  placeholder="문의 내용을 입력해주세요"
                  value={reasonText}
                  onChange={(e) => setReasonText(e.target.value)}
                />
              </div>
              <Button
                onClick={handleReasonSubmit}
                disabled={!reasonText.trim()}
                loading={reasonSubmitting}
                loadingText="저장 중..."
                className="w-full"
              >
                저장
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* 재업로드 확인 다이얼로그 */}
      <Dialog open={reuploadConfirmOpen} onOpenChange={setReuploadConfirmOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>재업로드 확인</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 text-sm">
            <p>현재 <strong>제출된 상태</strong>입니다. 다시 검토서를 업로드하시겠습니까?</p>
            <p className="text-red-600">기존 검토서는 삭제됩니다.</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReuploadConfirmOpen(false)}>
              아니오
            </Button>
            <Button
              onClick={() => {
                setReuploadConfirmOpen(false)
                handleConfirmUpload()
              }}
            >
              예
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
