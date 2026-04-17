"use client"

import { useEffect, useRef, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { FileIcon, Paperclip, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import apiClient from "@/lib/api/client"
import { useAuthStore } from "@/stores/authStore"

interface Comment {
  id: number
  announcement_id: number
  author_id: number
  author_name: string
  content: string
  created_at: string
}

interface Attachment {
  id: number
  announcement_id: number
  filename: string
  file_size: number
  uploaded_by: number
  created_at: string
}

interface AnnouncementDetail {
  id: number
  author_id: number
  author_name: string
  title: string
  content: string
  created_at: string
  updated_at: string
  comment_count: number
  comments: Comment[]
  attachments: Attachment[]
}

export default function AnnouncementDetailPage() {
  const params = useParams()
  const router = useRouter()
  const user = useAuthStore((s) => s.user)

  const [ann, setAnn] = useState<AnnouncementDetail | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [newComment, setNewComment] = useState("")
  const [submittingComment, setSubmittingComment] = useState(false)

  const [editOpen, setEditOpen] = useState(false)
  const [editTitle, setEditTitle] = useState("")
  const [editContent, setEditContent] = useState("")
  const [submittingEdit, setSubmittingEdit] = useState(false)

  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [uploadingFile, setUploadingFile] = useState(false)

  const isOwner = !!user && !!ann && user.id === ann.author_id
  const isAdmin = user && ["team_leader", "chief_secretary"].includes(user.role)
  const canEdit = isOwner || (!!user && ["team_leader", "chief_secretary", "secretary"].includes(user.role))

  const fetchData = async () => {
    try {
      const { data } = await apiClient.get<AnnouncementDetail>(
        `/api/announcements/${params.id}`
      )
      setAnn(data)
    } catch (err) {
      console.error("공지사항 조회 실패:", err)
      router.push("/announcements")
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [params.id])

  const handleAddComment = async () => {
    if (!newComment.trim()) return
    setSubmittingComment(true)
    try {
      await apiClient.post(`/api/announcements/${params.id}/comments`, {
        content: newComment,
      })
      setNewComment("")
      fetchData()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "등록 실패"
      alert(msg)
    } finally {
      setSubmittingComment(false)
    }
  }

  const handleDeleteComment = async (commentId: number) => {
    if (!confirm("댓글을 삭제하시겠습니까?")) return
    try {
      await apiClient.delete(`/api/announcements/comments/${commentId}`)
      fetchData()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "삭제 실패"
      alert(msg)
    }
  }

  const openEdit = () => {
    if (!ann) return
    setEditTitle(ann.title)
    setEditContent(ann.content)
    setEditOpen(true)
  }

  const handleSaveEdit = async () => {
    if (!editTitle.trim() || !editContent.trim()) return
    setSubmittingEdit(true)
    try {
      await apiClient.patch(`/api/announcements/${params.id}`, {
        title: editTitle,
        content: editContent,
      })
      setEditOpen(false)
      fetchData()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "수정 실패"
      alert(msg)
    } finally {
      setSubmittingEdit(false)
    }
  }

  const handleUploadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadingFile(true)
    try {
      const formData = new FormData()
      formData.append("file", file)
      await apiClient.post(`/api/announcements/${params.id}/attachments`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      fetchData()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "업로드 실패"
      alert(msg)
    } finally {
      setUploadingFile(false)
      if (fileInputRef.current) fileInputRef.current.value = ""
    }
  }

  const handleDeleteAttachment = async (attId: number) => {
    if (!confirm("첨부파일을 삭제하시겠습니까?")) return
    try {
      await apiClient.delete(`/api/announcements/attachments/${attId}`)
      fetchData()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "삭제 실패"
      alert(msg)
    }
  }

  const handleDownloadAttachment = async (attId: number) => {
    try {
      const { data } = await apiClient.get<{ download_url: string; filename: string }>(
        `/api/announcements/attachments/${attId}/download`
      )
      if (data.download_url) {
        window.open(data.download_url, "_blank")
      } else {
        alert("다운로드 URL을 생성할 수 없습니다")
      }
    } catch {
      alert("다운로드 실패")
    }
  }

  const handleDelete = async () => {
    if (!confirm("공지사항을 삭제하시겠습니까?")) return
    try {
      await apiClient.delete(`/api/announcements/${params.id}`)
      router.push("/announcements")
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "삭제 실패"
      alert(msg)
    }
  }

  if (isLoading) {
    return <div className="flex justify-center py-20 text-muted-foreground">로딩 중...</div>
  }
  if (!ann) return null

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={() => router.push("/announcements")}>
        ← 목록으로
      </Button>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1">
              <h1 className="text-2xl font-bold">{ann.title}</h1>
              <div className="mt-2 flex items-center gap-3 text-sm text-muted-foreground">
                <span>{ann.author_name}</span>
                <span>·</span>
                <span>{new Date(ann.created_at).toLocaleString("ko-KR")}</span>
                {ann.updated_at !== ann.created_at && (
                  <>
                    <span>·</span>
                    <span className="italic">
                      수정: {new Date(ann.updated_at).toLocaleString("ko-KR")}
                    </span>
                  </>
                )}
              </div>
            </div>
            {canEdit && (
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={openEdit}>
                  수정
                </Button>
                {(isOwner || isAdmin) && (
                  <Button size="sm" variant="destructive" onClick={handleDelete}>
                    삭제
                  </Button>
                )}
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div className="whitespace-pre-wrap break-words text-sm">{ann.content}</div>

          {/* 첨부파일 목록 */}
          {(ann.attachments?.length ?? 0) > 0 && (
            <div className="mt-6 space-y-2">
              <p className="text-sm font-medium">첨부파일 ({ann.attachments.length})</p>
              {ann.attachments.map((a) => {
                const canDeleteFile =
                  user?.id === a.uploaded_by ||
                  (user && ["team_leader", "chief_secretary"].includes(user.role))
                return (
                  <div
                    key={a.id}
                    className="flex items-center gap-2 rounded-md border p-2 text-sm"
                  >
                    <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <button
                      className="flex-1 truncate text-left text-blue-600 hover:underline"
                      onClick={() => handleDownloadAttachment(a.id)}
                    >
                      {a.filename}
                    </button>
                    <span className="text-xs text-muted-foreground shrink-0">
                      {(a.file_size / 1024).toLocaleString(undefined, { maximumFractionDigits: 1 })} KB
                    </span>
                    {canDeleteFile && (
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        onClick={() => handleDeleteAttachment(a.id)}
                        aria-label="삭제"
                      >
                        <X />
                      </Button>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {/* 첨부파일 업로드 버튼 (수정 권한자) */}
          {canEdit && (
            <div className="mt-4">
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                onChange={handleUploadFile}
                disabled={uploadingFile}
              />
              <Button
                variant="outline"
                size="sm"
                onClick={() => fileInputRef.current?.click()}
                loading={uploadingFile}
                loadingText="업로드 중..."
              >
                <Paperclip className="mr-1" />
                첨부파일 추가
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 댓글 */}
      <Card>
        <CardHeader>
          <h2 className="text-lg font-bold">댓글 ({ann.comments.length})</h2>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            {ann.comments.length === 0 ? (
              <p className="text-sm text-muted-foreground">아직 댓글이 없습니다.</p>
            ) : (
              ann.comments.map((c) => {
                const isCommentOwner = user?.id === c.author_id
                return (
                  <div key={c.id} className="rounded-md border p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm">{c.author_name}</span>
                        <span className="text-xs text-muted-foreground">
                          {new Date(c.created_at).toLocaleString("ko-KR")}
                        </span>
                      </div>
                      {(isCommentOwner || isAdmin) && (
                        <Button
                          size="icon-xs"
                          variant="ghost"
                          onClick={() => handleDeleteComment(c.id)}
                          aria-label="삭제"
                        >
                          ×
                        </Button>
                      )}
                    </div>
                    <p className="mt-1 whitespace-pre-wrap break-words text-sm">{c.content}</p>
                  </div>
                )
              })
            )}
          </div>

          <div className="space-y-2">
            <Label>댓글 작성</Label>
            <textarea
              className="w-full min-h-[80px] rounded-md border px-3 py-2 text-sm"
              value={newComment}
              onChange={(e) => setNewComment(e.target.value)}
              placeholder="댓글을 입력하세요"
            />
            <div className="flex justify-end">
              <Button
                onClick={handleAddComment}
                disabled={!newComment.trim()}
                loading={submittingComment}
                loadingText="등록 중..."
              >
                댓글 등록
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 수정 다이얼로그 */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>공지사항 수정</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-2">
              <Label>제목</Label>
              <Input
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>내용</Label>
              <textarea
                className="w-full min-h-[240px] rounded-md border px-3 py-2 text-sm"
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)} disabled={submittingEdit}>
              취소
            </Button>
            <Button
              onClick={handleSaveEdit}
              disabled={!editTitle.trim() || !editContent.trim()}
              loading={submittingEdit}
              loadingText="저장 중..."
            >
              저장
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
