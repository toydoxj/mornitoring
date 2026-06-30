"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
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
import { useAuthStore } from "@/stores/authStore"
import { PHASE_LABELS, RESULT_LABELS } from "@/types"

interface ReviewFile {
  key: string
  phase: string
  date: string
  filename: string
  size: number
  last_modified: string
  mgmt_no?: string | null
  building_id?: number | null
  reviewer_name?: string | null
  stage_id?: number | null
}

interface DownloadUrlResponse {
  download_url?: string
}

interface StructEngineerFirmBuilding {
  id: number
  mgmt_no: string
  building_name?: string | null
  struct_eng_name?: string | null
  reviewer_name?: string | null
  latest_reviewer_name?: string | null
  current_phase?: string | null
  final_result?: string | null
  latest_phase?: string | null
  latest_report_submitted_at?: string | null
}

interface StructEngineerFirmGroup {
  firm: string
  building_count: number
  reviewer_count: number
  submitted_count: number
  items: StructEngineerFirmBuilding[]
}

type ActiveTab = "files" | "structEngineerFirms"

const extractMgmtNo = (file: ReviewFile) => {
  if (file.mgmt_no) return file.mgmt_no
  const extensionIndex = file.filename.lastIndexOf(".")
  return extensionIndex > 0 ? file.filename.slice(0, extensionIndex) : file.filename
}

const makeArchiveName = (phase: string, date: string) => {
  const safePhase = phase.replace(/[\\/:*?"<>|]+/g, "_").trim() || "review-files"
  return `${safePhase}_${date}_검토서.zip`
}

const downloadBlob = (blob: Blob, filename: string) => {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000)
}

const getErrorMessage = (err: unknown, fallback: string) => {
  const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
  return typeof detail === "string" ? detail : fallback
}

const formatText = (value?: string | null) => {
  const text = value?.trim()
  return text || "-"
}

const formatPhase = (phase?: string | null) => {
  if (!phase) return "-"
  return PHASE_LABELS[phase] ?? phase
}

const formatResult = (result?: string | null) => {
  if (!result) return "-"
  return RESULT_LABELS[result] ?? result
}

const formatLatestSubmission = (item: StructEngineerFirmBuilding) => {
  if (!item.latest_phase && !item.latest_report_submitted_at) return "-"
  const phaseLabel = formatPhase(item.latest_phase)
  if (!item.latest_report_submitted_at) return phaseLabel
  return `${phaseLabel} · ${item.latest_report_submitted_at}`
}

export default function ReviewFilesPage() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const [activeTab, setActiveTab] = useState<ActiveTab>("files")
  const [files, setFiles] = useState<ReviewFile[]>([])
  const [filterPhase, setFilterPhase] = useState("")
  const [isLoading, setIsLoading] = useState(true)
  const [firmGroups, setFirmGroups] = useState<StructEngineerFirmGroup[]>([])
  const [selectedFirm, setSelectedFirm] = useState("")
  const [firmSearch, setFirmSearch] = useState("")
  const [isFirmLoading, setIsFirmLoading] = useState(true)
  const canDeleteFiles =
    !!user && ["team_leader", "chief_secretary"].includes(user.role)

  const fetchFiles = useCallback(async () => {
    setIsLoading(true)
    try {
      const params: Record<string, string> = {}
      if (filterPhase) params.phase = filterPhase
      const { data } = await apiClient.get<ReviewFile[]>("/api/reviews/files", { params })
      setFiles(data)
    } catch (err) {
      console.error("파일 목록 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }, [filterPhase])

  const fetchStructEngineerFirms = useCallback(async () => {
    setIsFirmLoading(true)
    try {
      const { data } = await apiClient.get<StructEngineerFirmGroup[]>(
        "/api/reviews/struct-engineer-firms",
      )
      setFirmGroups(data)
      setSelectedFirm((current) => {
        if (current && data.some((group) => group.firm === current)) return current
        return data[0]?.firm ?? ""
      })
    } catch (err) {
      console.error("책임구조기술자 사무소 목록 조회 실패:", err)
    } finally {
      setIsFirmLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchFiles()
  }, [fetchFiles])

  useEffect(() => {
    fetchStructEngineerFirms()
  }, [fetchStructEngineerFirms])

  const handleDownload = async (key: string, filename: string) => {
    try {
      const { data } = await apiClient.get<DownloadUrlResponse>("/api/reviews/files/download", {
        params: { key },
      })
      if (data.download_url) {
        const link = document.createElement("a")
        link.href = data.download_url
        link.download = filename
        link.click()
      }
    } catch (err) {
      console.error("다운로드 실패:", err)
    }
  }

  const handleOpenBuildingDetail = (file: ReviewFile) => {
    const mgmtNo = extractMgmtNo(file)
    if (!file.building_id) {
      alert(`관리번호 ${mgmtNo}에 해당하는 건축물 상세 정보를 찾을 수 없습니다.`)
      return
    }
    router.push(`/buildings/${file.building_id}?from=review-files`)
  }

  const downloadFilesAsZip = async (targetFiles: ReviewFile[], phase: string, date: string) => {
    const archiveName = makeArchiveName(phase, date)
    const { data } = await apiClient.post<Blob>(
      "/api/reviews/files/download-zip",
      {
        keys: targetFiles.map((f) => f.key),
        archive_name: archiveName,
      },
      { responseType: "blob" },
    )
    downloadBlob(data, archiveName)
  }

  const [downloadingGroup, setDownloadingGroup] = useState<string | null>(null)

  const handleDownloadAll = async (phase: string, date: string) => {
    const targetFiles = files.filter((f) => f.phase === phase && f.date === date)
    if (targetFiles.length === 0) return

    const groupKey = `${phase}|||${date}`
    setDownloadingGroup(groupKey)
    try {
      await downloadFilesAsZip(targetFiles, phase, date)
    } catch (err) {
      alert(getErrorMessage(err, "전체 다운로드에 실패했습니다."))
    } finally {
      setDownloadingGroup(null)
    }
  }

  const [deletingKey, setDeletingKey] = useState<string | null>(null)
  const handleDelete = async (key: string, filename: string) => {
    if (!confirm(`"${filename}" 파일을 삭제할까요?\n관련 검토 결과 이력은 유지되지만 업로드된 파일은 S3 에서 완전히 제거됩니다.`)) return
    setDeletingKey(key)
    try {
      await apiClient.delete("/api/reviews/files", { params: { key } })
      fetchFiles()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "삭제 실패"
      alert(msg)
    } finally {
      setDeletingKey(null)
    }
  }

  const [deletingGroup, setDeletingGroup] = useState<string | null>(null)

  const handleDownloadThenDelete = async (phase: string, date: string) => {
    const targetFiles = files.filter((f) => f.phase === phase && f.date === date)
    if (targetFiles.length === 0) return
    const confirmed = confirm(
      `${formatPhase(phase)} ${date} 검토서 ${targetFiles.length}건을 ZIP 파일로 다운로드한 뒤 삭제합니다.\n` +
      `ZIP 다운로드가 실패하면 삭제하지 않습니다. 계속할까요?`,
    )
    if (!confirmed) return

    const groupKey = `${phase}|||${date}`
    setDeletingGroup(groupKey)
    try {
      await downloadFilesAsZip(targetFiles, phase, date)
      const failed: string[] = []
      for (const f of targetFiles) {
        try {
          await apiClient.delete("/api/reviews/files", { params: { key: f.key } })
        } catch {
          failed.push(f.filename)
        }
      }
      if (failed.length > 0) {
        alert(`일부 파일 삭제 실패 (${failed.length}건):\n${failed.slice(0, 10).join("\n")}${failed.length > 10 ? "\n..." : ""}`)
      }
      fetchFiles()
    } catch (err) {
      alert(getErrorMessage(err, "다운로드 후 삭제에 실패했습니다. 파일은 삭제하지 않았습니다."))
    } finally {
      setDeletingGroup(null)
    }
  }

  const handleDeleteAll = async (phase: string, date: string) => {
    const targetFiles = files.filter((f) => f.phase === phase && f.date === date)
    if (targetFiles.length === 0) return
    const confirmed = confirm(
      `${formatPhase(phase)} ${date} 검토서 ${targetFiles.length}건을 모두 삭제할까요?\n` +
      `관련 검토 결과 이력은 유지되지만 S3 파일은 완전히 제거됩니다.`,
    )
    if (!confirmed) return

    const groupKey = `${phase}|||${date}`
    setDeletingGroup(groupKey)
    const failed: string[] = []
    try {
      for (const f of targetFiles) {
        try {
          await apiClient.delete("/api/reviews/files", { params: { key: f.key } })
        } catch {
          failed.push(f.filename)
        }
      }
      if (failed.length > 0) {
        alert(`일부 파일 삭제 실패 (${failed.length}건):\n${failed.slice(0, 10).join("\n")}${failed.length > 10 ? "\n..." : ""}`)
      }
      fetchFiles()
    } finally {
      setDeletingGroup(null)
    }
  }

  const groups: Record<string, ReviewFile[]> = {}
  for (const f of files) {
    const groupKey = `${f.phase}|||${f.date}`
    if (!groups[groupKey]) groups[groupKey] = []
    groups[groupKey].push(f)
  }

  const firmBuildingCount = firmGroups.reduce(
    (total, group) => total + group.building_count,
    0,
  )

  const filteredFirmGroups = useMemo(() => {
    const keyword = firmSearch.trim().toLowerCase()
    if (!keyword) return firmGroups
    return firmGroups.filter((group) => {
      if (group.firm.toLowerCase().includes(keyword)) return true
      return group.items.some((item) =>
        [
          item.mgmt_no,
          item.building_name,
          item.struct_eng_name,
          item.reviewer_name,
          item.latest_reviewer_name,
        ].some((value) => value?.toLowerCase().includes(keyword)),
      )
    })
  }, [firmGroups, firmSearch])

  const selectedFirmGroup = useMemo(() => {
    return (
      filteredFirmGroups.find((group) => group.firm === selectedFirm)
      ?? filteredFirmGroups[0]
      ?? null
    )
  }, [filteredFirmGroups, selectedFirm])

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold">검토서 확인</h1>
          <p className="text-sm text-muted-foreground">
            {activeTab === "files"
              ? `업로드된 검토서 ${files.length}건`
              : `책임구조기술자 사무소 ${firmGroups.length}곳 · 관련 관리번호 ${firmBuildingCount}건`}
          </p>
        </div>
        {activeTab === "files" ? (
          <select
            className="h-8 rounded-lg border px-3 text-sm"
            value={filterPhase}
            onChange={(e) => setFilterPhase(e.target.value)}
          >
            <option value="">전체 단계</option>
            <option value="preliminary">예비검토</option>
            <option value="supplement_1">보완검토(1차)</option>
            <option value="supplement_2">보완검토(2차)</option>
            <option value="supplement_3">보완검토(3차)</option>
            <option value="supplement_4">보완검토(4차)</option>
            <option value="supplement_5">보완검토(5차)</option>
          </select>
        ) : (
          <Input
            className="w-full lg:w-80"
            placeholder="사무소, 관리번호, 검토자 검색"
            value={firmSearch}
            onChange={(e) => setFirmSearch(e.target.value)}
          />
        )}
      </div>

      <div
        role="tablist"
        aria-label="검토서 확인 탭"
        className="inline-flex rounded-lg border bg-muted/30 p-1"
      >
        <Button
          type="button"
          role="tab"
          aria-selected={activeTab === "files"}
          variant={activeTab === "files" ? "default" : "ghost"}
          size="sm"
          onClick={() => setActiveTab("files")}
        >
          업로드 검토서
        </Button>
        <Button
          type="button"
          role="tab"
          aria-selected={activeTab === "structEngineerFirms"}
          variant={activeTab === "structEngineerFirms" ? "default" : "ghost"}
          size="sm"
          onClick={() => setActiveTab("structEngineerFirms")}
        >
          책임구조기술자 사무소
        </Button>
      </div>

      {activeTab === "files" ? (
        isLoading ? (
          <div className="py-20 text-center text-muted-foreground">로딩 중...</div>
        ) : files.length === 0 ? (
          <div className="py-20 text-center text-muted-foreground">업로드된 검토서가 없습니다</div>
        ) : (
          Object.entries(groups).map(([groupKey, groupFiles]) => {
            const [phase, date] = groupKey.split("|||")
            const isGroupDownloading = downloadingGroup === `${phase}|||${date}`
            const isGroupDeleting = deletingGroup === `${phase}|||${date}`
            return (
              <div key={groupKey} className="space-y-2">
                <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{formatPhase(phase)}</Badge>
                    <span className="text-sm font-medium">{date}</span>
                    <span className="text-sm text-muted-foreground">({groupFiles.length}건)</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleDownloadAll(phase, date)}
                      loading={isGroupDownloading}
                      loadingText="압축 중..."
                      disabled={isGroupDeleting}
                    >
                      전체 다운로드
                    </Button>
                    {canDeleteFiles && (
                      <>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => handleDownloadThenDelete(phase, date)}
                          loading={isGroupDeleting}
                          loadingText="처리 중..."
                          disabled={isGroupDownloading}
                        >
                          다운로드 후 삭제
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => handleDeleteAll(phase, date)}
                          loading={isGroupDeleting}
                          loadingText="삭제 중..."
                        >
                          전체 삭제
                        </Button>
                      </>
                    )}
                  </div>
                </div>
                <div className="overflow-x-auto rounded-md border bg-white">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-[140px]">관리번호</TableHead>
                        <TableHead>파일명</TableHead>
                        <TableHead className="w-[120px]">검토위원</TableHead>
                        <TableHead className="w-[80px]">크기</TableHead>
                        <TableHead className="w-[200px]">관리</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {groupFiles.map((f) => {
                        const mgmtNo = extractMgmtNo(f)
                        return (
                          <TableRow key={f.key}>
                            <TableCell>
                              <button
                                type="button"
                                className="font-mono text-sm font-medium text-blue-600 hover:underline disabled:cursor-not-allowed disabled:text-muted-foreground disabled:no-underline"
                                onClick={() => handleOpenBuildingDetail(f)}
                              >
                                {mgmtNo}
                              </button>
                            </TableCell>
                            <TableCell className="font-mono text-sm">{f.filename}</TableCell>
                            <TableCell className="text-sm">
                              {f.reviewer_name || <span className="text-muted-foreground">-</span>}
                            </TableCell>
                            <TableCell className="text-sm text-muted-foreground">{formatSize(f.size)}</TableCell>
                            <TableCell>
                              <div className="flex gap-1">
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => handleDownload(f.key, f.filename)}
                                >
                                  다운로드
                                </Button>
                                {canDeleteFiles && (
                                  <Button
                                    size="sm"
                                    variant="destructive"
                                    onClick={() => handleDelete(f.key, f.filename)}
                                    loading={deletingKey === f.key}
                                    loadingText="삭제 중..."
                                  >
                                    삭제
                                  </Button>
                                )}
                              </div>
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )
          })
        )
      ) : isFirmLoading ? (
        <div className="py-20 text-center text-muted-foreground">로딩 중...</div>
      ) : firmGroups.length === 0 ? (
        <div className="py-20 text-center text-muted-foreground">책임구조기술자 사무소 정보가 없습니다</div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(260px,340px)_1fr]">
          <div className="overflow-hidden rounded-md border bg-white">
            <div className="flex items-center justify-between border-b px-3 py-2">
              <span className="text-sm font-medium">사무소 명단</span>
              <Badge variant="outline">{filteredFirmGroups.length}곳</Badge>
            </div>
            <div className="max-h-[640px] overflow-y-auto">
              {filteredFirmGroups.length === 0 ? (
                <div className="px-3 py-10 text-center text-sm text-muted-foreground">
                  검색 결과가 없습니다
                </div>
              ) : (
                filteredFirmGroups.map((group) => {
                  const isSelected = selectedFirmGroup?.firm === group.firm
                  return (
                    <button
                      key={group.firm}
                      type="button"
                      className={cn(
                        "flex w-full items-start justify-between gap-3 border-b px-3 py-3 text-left text-sm transition-colors last:border-b-0 hover:bg-muted/70",
                        isSelected && "bg-muted",
                      )}
                      onClick={() => setSelectedFirm(group.firm)}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{group.firm}</span>
                        <span className="mt-1 block text-xs text-muted-foreground">
                          검토자 {group.reviewer_count}명 · 제출 {group.submitted_count}건
                        </span>
                      </span>
                      <Badge variant={isSelected ? "default" : "outline"}>
                        {group.building_count}건
                      </Badge>
                    </button>
                  )
                })
              )}
            </div>
          </div>

          <div className="space-y-3">
            {selectedFirmGroup ? (
              <>
                <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                  <div>
                    <h2 className="text-lg font-semibold">{selectedFirmGroup.firm}</h2>
                    <p className="text-sm text-muted-foreground">
                      관련 관리번호 {selectedFirmGroup.building_count}건 · 검토자 {selectedFirmGroup.reviewer_count}명
                    </p>
                  </div>
                  <Badge variant="outline">검토서 제출 {selectedFirmGroup.submitted_count}건</Badge>
                </div>

                <div className="overflow-x-auto rounded-md border bg-white">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-[140px]">관리번호</TableHead>
                        <TableHead>건축물명</TableHead>
                        <TableHead className="w-[140px]">책임구조기술자</TableHead>
                        <TableHead className="w-[120px]">검토자</TableHead>
                        <TableHead className="w-[190px]">최근 검토서</TableHead>
                        <TableHead className="w-[110px]">최종결과</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {selectedFirmGroup.items.map((item) => (
                        <TableRow key={item.id}>
                          <TableCell>
                            <button
                              type="button"
                              className="font-mono text-sm font-medium text-blue-600 hover:underline"
                              onClick={() => router.push(`/buildings/${item.id}?from=review-files`)}
                            >
                              {item.mgmt_no}
                            </button>
                          </TableCell>
                          <TableCell className="text-sm">{formatText(item.building_name)}</TableCell>
                          <TableCell className="text-sm">{formatText(item.struct_eng_name)}</TableCell>
                          <TableCell className="text-sm">
                            {formatText(item.latest_reviewer_name ?? item.reviewer_name)}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {formatLatestSubmission(item)}
                          </TableCell>
                          <TableCell className="text-sm">{formatResult(item.final_result)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </>
            ) : (
              <div className="py-20 text-center text-muted-foreground">선택된 사무소가 없습니다</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
