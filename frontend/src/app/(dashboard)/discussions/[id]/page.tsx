"use client"

import { useEffect, useRef, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { Paperclip } from "lucide-react"
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
import { AttachmentItem } from "@/components/AttachmentItem"

interface CommentAttachment {
  id: number
  comment_id: number
  filename: string
  file_size: number
  content_type: string | null
  uploaded_by: number
  created_at: string
  download_url: string | null
}

interface Comment {
  id: number
  discussion_id: number
  author_id: number
  author_name: string
  content: string
  created_at: string
  attachments: CommentAttachment[]
}

interface Attachment {
  id: number
  discussion_id: number
  filename: string
  file_size: number
  content_type: string | null
  uploaded_by: number
  created_at: string
  download_url: string | null
}

interface DiscussionDetail {
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

export default function DiscussionDetailPage() {
  const params = useParams()
  const router = useRouter()
  const user = useAuthStore((s) => s.user)

  const [d, setD] = useState<DiscussionDetail | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [newComment, setNewComment] = useState("")
  const [submittingComment, setSubmittingComment] = useState(false)

  const [editOpen, setEditOpen] = useState(false)
  const [editTitle, setEditTitle] = useState("")
  const [editContent, setEditContent] = useState("")
  const [submittingEdit, setSubmittingEdit] = useState(false)

  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [uploadingFile, setUploadingFile] = useState(false)

  const isOwner = !!user && !!d && user.id === d.author_id
  const isAdmin = user && ["team_leader", "chief_secretary"].includes(user.role)
  const canEdit = isOwner || isAdmin

  const fetchData = async () => {
    try {
      const { data } = await apiClient.get<DiscussionDetail>(
        `/api/discussions/${params.id}`
      )
      setD(data)
    } catch (err) {
      console.error("토론글 조회 실패:", err)
      router.push("/discussions")
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
      await apiClient.post(`/api/discussions/${params.id}/comments`, {
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
      await apiClient.delete(`/api/discussions/comments/${commentId}`)
      fetchData()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "삭제 실패"
      alert(msg)
    }
  }

  const openEdit = () => {
    if (!d) return
    setEditTitle(d.title)
    setEditContent(d.content)
    setEditOpen(true)
  }

  const handleSaveEdit = async () => {
    if (!editTitle.trim() || !editContent.trim()) return
    setSubmittingEdit(true)
    try {
      await apiClient.patch(`/api/discussions/${params.id}`, {
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
      await apiClient.post(`/api/discussions/${params.id}/attachments`, formData, {
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
      await apiClient.delete(`/api/discussions/attachments/${attId}`)
      fetchData()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "삭제 실패"
      alert(msg)
    }
  }

  // 댓글 첨부
  const commentFileInputs = useRef<Record<number, HTMLInputElement | null>>({})
  const [uploadingCommentFile, setUploadingCommentFile] = useState<number | null>(null)

  const handleUploadCommentFile = async (
    e: React.ChangeEvent<HTMLInputElement>,
    commentId: number,
  ) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadingCommentFile(commentId)
    try {
      const formData = new FormData()
      formData.append("file", file)
      await apiClient.post(
        `/api/discussions/comments/${commentId}/attachments`,
        formData,
        { headers: { "Content-Type": "multipart/form-data" } },
      )
      fetchData()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "업로드 실패"
      alert(msg)
    } finally {
      setUploadingCommentFile(null)
      const input = commentFileInputs.current[commentId]
      if (input) input.value = ""
    }
  }

  const handleDeleteCommentAttachment = async (attId: number) => {
    if (!confirm("첨부파일을 삭제하시겠습니까?")) return
    try {
      await apiClient.delete(`/api/discussions/comment-attachments/${attId}`)
      fetchData()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "삭제 실패"
      alert(msg)
    }
  }

  const handleDelete = async () => {
    if (!confirm("토론글을 삭제하시겠습니까?")) return
    try {
      await apiClient.delete(`/api/discussions/${params.id}`)
      router.push("/discussions")
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
  if (!d) return null

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={() => router.push("/discussions")}>
        ← 목록으로
      </Button>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1">
              <h1 className="text-2xl font-bold">{d.title}</h1>
              <div className="mt-2 flex items-center gap-3 text-sm text-muted-foreground">
                <span>{d.author_name}</span>
                <span>·</span>
                <span>{new Date(d.created_at).toLocaleString("ko-KR")}</span>
                {d.updated_at !== d.created_at && (
                  <>
                    <span>·</span>
                    <span className="italic">
                      수정: {new Date(d.updated_at).toLocaleString("ko-KR")}
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
                <Button size="sm" variant="destructive" onClick={handleDelete}>
                  삭제
                </Button>
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div className="whitespace-pre-wrap break-words text-sm">{d.content}</div>

          {(d.attachments?.length ?? 0) > 0 && (
            <div className="mt-6 space-y-2">
              <p className="text-sm font-medium">첨부파일 ({d.attachments.length})</p>
              {d.attachments.map((a) => (
                <AttachmentItem
                  key={a.id}
                  attachment={a}
                  canDelete={user?.id === a.uploaded_by || !!isAdmin}
                  onDelete={() => handleDeleteAttachment(a.id)}
                />
              ))}
            </div>
          )}

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

      <Card>
        <CardHeader>
          <h2 className="text-lg font-bold">댓글 ({d.comments.length})</h2>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            {d.comments.length === 0 ? (
              <p className="text-sm text-muted-foreground">아직 댓글이 없습니다.</p>
            ) : (
              d.comments.map((c) => {
                const isCommentOwner = user?.id === c.author_id
                const canUploadToComment = !!user  // 로그인 사용자 전원
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
                        >
                          ×
                        </Button>
                      )}
                    </div>
                    <p className="mt-1 whitespace-pre-wrap break-words text-sm">{c.content}</p>

                    {(c.attachments?.length ?? 0) > 0 && (
                      <div className="mt-2 space-y-2">
                        {c.attachments.map((a) => (
                          <AttachmentItem
                            key={a.id}
                            attachment={a}
                            canDelete={user?.id === a.uploaded_by || !!isAdmin}
                            onDelete={() => handleDeleteCommentAttachment(a.id)}
                          />
                        ))}
                      </div>
                    )}

                    {canUploadToComment && (
                      <div className="mt-2">
                        <input
                          ref={(el) => {
                            commentFileInputs.current[c.id] = el
                          }}
                          type="file"
                          className="hidden"
                          onChange={(e) => handleUploadCommentFile(e, c.id)}
                        />
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => commentFileInputs.current[c.id]?.click()}
                          loading={uploadingCommentFile === c.id}
                          loadingText="업로드 중..."
                        >
                          <Paperclip className="mr-1 h-3.5 w-3.5" />
                          첨부
                        </Button>
                      </div>
                    )}
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

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>토론글 수정</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-2">
              <Label>제목</Label>
              <Input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>내용</Label>
              <textarea
                className="w-full min-h-[200px] rounded-md border px-3 py-2 text-sm"
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
