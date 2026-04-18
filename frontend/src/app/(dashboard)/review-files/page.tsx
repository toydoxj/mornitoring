"use client"

import { useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import apiClient from "@/lib/api/client"

interface ReviewFile {
  key: string
  phase: string
  date: string
  filename: string
  size: number
  last_modified: string
}

export default function ReviewFilesPage() {
  const [files, setFiles] = useState<ReviewFile[]>([])
  const [filterPhase, setFilterPhase] = useState("")
  const [isLoading, setIsLoading] = useState(true)

  const fetchFiles = async () => {
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
  }

  useEffect(() => {
    fetchFiles()
  }, [filterPhase])

  const handleDownload = async (key: string, filename: string) => {
    try {
      const { data } = await apiClient.get("/api/reviews/files/download", {
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

  const handleDownloadAll = async (phase: string, date: string) => {
    const targetFiles = files.filter((f) => f.phase === phase && f.date === date)
    for (const f of targetFiles) {
      await handleDownload(f.key, f.filename)
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
      `${phase} ${date} 검토서 ${targetFiles.length}건을 모두 다운로드한 뒤 삭제합니다.\n` +
      `다운로드 시작 후 짧은 대기 시간을 두고 삭제가 진행됩니다. 계속할까요?`,
    )
    if (!confirmed) return

    const groupKey = `${phase}|||${date}`
    setDeletingGroup(groupKey)
    try {
      // 1) 다운로드 순차 트리거 — 브라우저 동시 다운로드 제한 회피용 짧은 간격
      for (const f of targetFiles) {
        try {
          const { data } = await apiClient.get("/api/reviews/files/download", { params: { key: f.key } })
          if (data.download_url) {
            const link = document.createElement("a")
            link.href = data.download_url
            link.download = f.filename
            link.click()
          }
        } catch {
          // 개별 다운로드 실패는 무시 — 삭제는 계속 진행 (사용자 판단)
        }
        await new Promise((r) => setTimeout(r, 200))
      }
      // 2) 브라우저 다운로드가 큐잉될 시간을 주고 삭제 진행
      await new Promise((r) => setTimeout(r, 1500))
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
    } finally {
      setDeletingGroup(null)
    }
  }

  const handleDeleteAll = async (phase: string, date: string) => {
    const targetFiles = files.filter((f) => f.phase === phase && f.date === date)
    if (targetFiles.length === 0) return
    const confirmed = confirm(
      `${phase} ${date} 검토서 ${targetFiles.length}건을 모두 삭제할까요?\n` +
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

  // 날짜+단계별 그룹핑
  const groups: Record<string, ReviewFile[]> = {}
  for (const f of files) {
    const groupKey = `${f.phase}|||${f.date}`
    if (!groups[groupKey]) groups[groupKey] = []
    groups[groupKey].push(f)
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">검토서 파일 관리</h1>
          <p className="text-sm text-muted-foreground">
            업로드된 검토서 {files.length}건
          </p>
        </div>
        <select
          className="rounded-md border px-3 py-2 text-sm"
          value={filterPhase}
          onChange={(e) => setFilterPhase(e.target.value)}
        >
          <option value="">전체 단계</option>
          <option value="preliminary">예비검토</option>
          <option value="supplement_1">보완검토(1차)</option>
          <option value="supplement_2">보완검토(2차)</option>
          <option value="supplement_3">보완검토(3차)</option>
        </select>
      </div>

      {isLoading ? (
        <div className="text-center py-20 text-muted-foreground">로딩 중...</div>
      ) : files.length === 0 ? (
        <div className="text-center py-20 text-muted-foreground">업로드된 검토서가 없습니다</div>
      ) : (
        Object.entries(groups).map(([groupKey, groupFiles]) => {
          const [phase, date] = groupKey.split("|||")
          return (
            <div key={groupKey} className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{phase}</Badge>
                  <span className="text-sm font-medium">{date}</span>
                  <span className="text-sm text-muted-foreground">({groupFiles.length}건)</span>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleDownloadAll(phase, date)}
                  >
                    전체 다운로드
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => handleDownloadThenDelete(phase, date)}
                    loading={deletingGroup === `${phase}|||${date}`}
                    loadingText="처리 중..."
                  >
                    다운로드 후 삭제
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => handleDeleteAll(phase, date)}
                    loading={deletingGroup === `${phase}|||${date}`}
                    loadingText="삭제 중..."
                  >
                    전체 삭제
                  </Button>
                </div>
              </div>
              <div className="rounded-md border bg-white">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>파일명</TableHead>
                      <TableHead className="w-[80px]">크기</TableHead>
                      <TableHead className="w-[200px]">관리</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {groupFiles.map((f) => (
                      <TableRow key={f.key}>
                        <TableCell className="font-mono text-sm">{f.filename}</TableCell>
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
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => handleDelete(f.key, f.filename)}
                              loading={deletingKey === f.key}
                              loadingText="삭제 중..."
                            >
                              삭제
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )
        })
      )}
    </div>
  )
}
