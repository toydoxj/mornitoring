"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
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
import { useAuthStore } from "@/stores/authStore"

interface Announcement {
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
  items: Announcement[]
  total: number
}

export default function AnnouncementsPage() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const canWrite =
    user && ["team_leader", "chief_secretary", "secretary"].includes(user.role)

  const [items, setItems] = useState<Announcement[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [writeOpen, setWriteOpen] = useState(false)
  const [title, setTitle] = useState("")
  const [content, setContent] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const fetchData = async () => {
    setIsLoading(true)
    try {
      const { data } = await apiClient.get<ListResponse>("/api/announcements", {
        params: { size: 50 },
      })
      setItems(data.items)
      setTotal(data.total)
    } catch (err) {
      console.error("공지사항 조회 실패:", err)
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
      await apiClient.post("/api/announcements", { title, content })
      setWriteOpen(false)
      setTitle("")
      setContent("")
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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">공지사항</h1>
          <p className="text-sm text-muted-foreground">총 {total}건</p>
        </div>
        {canWrite && (
          <Button onClick={() => setWriteOpen(true)}>새 공지 작성</Button>
        )}
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
                  등록된 공지사항이 없습니다
                </TableCell>
              </TableRow>
            ) : (
              items.map((a) => (
                <TableRow
                  key={a.id}
                  className="cursor-pointer hover:bg-muted/30"
                  onClick={() => router.push(`/announcements/${a.id}`)}
                >
                  <TableCell className="text-center">{a.id}</TableCell>
                  <TableCell className="font-medium">{a.title}</TableCell>
                  <TableCell className="text-center text-sm">{a.author_name}</TableCell>
                  <TableCell className="text-center text-sm text-muted-foreground">
                    {new Date(a.created_at).toLocaleDateString("ko-KR")}
                  </TableCell>
                  <TableCell className="text-center">
                    {a.comment_count > 0 ? (
                      <Badge variant="secondary">{a.comment_count}</Badge>
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

      {/* 공지 작성 다이얼로그 */}
      <Dialog open={writeOpen} onOpenChange={setWriteOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>새 공지사항 작성</DialogTitle>
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
                className="w-full min-h-[240px] rounded-md border px-3 py-2 text-sm"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="공지 내용을 입력하세요"
              />
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
