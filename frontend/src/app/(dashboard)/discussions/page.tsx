"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { Paperclip, X } from "lucide-react"
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

interface Discussion {
  id: number
  author_id: number
  author_name: string
  title: string
  content: string
  created_at: string
  updated_at: string
  comment_count: number
}

interface ListResponse {
  items: Discussion[]
  total: number
}

export default function DiscussionsPage() {
  const router = useRouter()

  const [items, setItems] = useState<Discussion[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [writeOpen, setWriteOpen] = useState(false)
  const [title, setTitle] = useState("")
  const [content, setContent] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [pendingFiles, setPendingFiles] = useState<File[]>([])
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const fetchData = async () => {
    setIsLoading(true)
    try {
      const { data } = await apiClient.get<ListResponse>("/api/discussions", {
        params: { size: 50 },
      })
      setItems(data.items)
      setTotal(data.total)
    } catch (err) {
      console.error("토론방 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const handleCreate = async () => {
    if (!title.trim() || !content.trim()) return
    setSubmitting(true)
    try {
      const { data } = await apiClient.post<{ id: number }>(
        "/api/discussions",
        { title, content }
      )
      for (const file of pendingFiles) {
        const formData = new FormData()
        formData.append("file", file)
        try {
          await apiClient.post(
            `/api/discussions/${data.id}/attachments`,
            formData,
            { headers: { "Content-Type": "multipart/form-data" } }
          )
        } catch (err) {
          console.error("첨부파일 업로드 실패:", file.name, err)
        }
      }
      setWriteOpen(false)
      setTitle("")
      setContent("")
      setPendingFiles([])
      fetchData()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "등록 실패"
      alert(msg)
    } finally {
      setSubmitting(false)
    }
  }

  const handleAddFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    setPendingFiles((prev) => [...prev, ...files])
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const handleRemoveFile = (idx: number) => {
    setPendingFiles((prev) => prev.filter((_, i) => i !== idx))
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">토론방</h1>
          <p className="text-sm text-muted-foreground">총 {total}건 · 누구나 글을 쓸 수 있습니다</p>
        </div>
        <Button onClick={() => setWriteOpen(true)}>새 글 작성</Button>
      </div>

      <div className="rounded-md border bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[60px] text-center">번호</TableHead>
              <TableHead>제목</TableHead>
              <TableHead className="w-[120px] text-center">작성자</TableHead>
              <TableHead className="w-[140px] text-center">작성일</TableHead>
              <TableHead className="w-[80px] text-center">댓글</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={5} className="h-32 text-center">
                  로딩 중...
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="h-32 text-center text-muted-foreground">
                  등록된 글이 없습니다
                </TableCell>
              </TableRow>
            ) : (
              items.map((d) => (
                <TableRow
                  key={d.id}
                  className="cursor-pointer hover:bg-muted/30"
                  onClick={() => router.push(`/discussions/${d.id}`)}
                >
                  <TableCell className="text-center">{d.id}</TableCell>
                  <TableCell className="font-medium">{d.title}</TableCell>
                  <TableCell className="text-center text-sm">{d.author_name}</TableCell>
                  <TableCell className="text-center text-sm text-muted-foreground">
                    {new Date(d.created_at).toLocaleDateString("ko-KR")}
                  </TableCell>
                  <TableCell className="text-center">
                    {d.comment_count > 0 ? (
                      <Badge variant="secondary">{d.comment_count}</Badge>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* 글 작성 다이얼로그 */}
      <Dialog open={writeOpen} onOpenChange={setWriteOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>새 글 작성</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-2">
              <Label>제목</Label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="제목을 입력하세요"
              />
            </div>
            <div className="space-y-2">
              <Label>내용</Label>
              <textarea
                className="w-full min-h-[200px] rounded-md border px-3 py-2 text-sm"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="내용을 입력하세요"
              />
            </div>
            <div className="space-y-2">
              <Label>첨부파일 (선택)</Label>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={handleAddFiles}
              />
              <Button
                variant="outline"
                size="sm"
                onClick={() => fileInputRef.current?.click()}
                type="button"
              >
                <Paperclip className="mr-1" />
                파일 선택
              </Button>
              {pendingFiles.length > 0 && (
                <div className="space-y-1">
                  {pendingFiles.map((f, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-2 rounded-md border p-2 text-sm"
                    >
                      <span className="flex-1 truncate">{f.name}</span>
                      <span className="text-xs text-muted-foreground shrink-0">
                        {(f.size / 1024).toLocaleString(undefined, { maximumFractionDigits: 1 })} KB
                      </span>
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        onClick={() => handleRemoveFile(i)}
                      >
                        <X />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setWriteOpen(false)} disabled={submitting}>
              취소
            </Button>
            <Button
              onClick={handleCreate}
              disabled={!title.trim() || !content.trim()}
              loading={submitting}
              loadingText="등록 중..."
            >
              등록
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
