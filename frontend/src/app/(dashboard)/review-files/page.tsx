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
