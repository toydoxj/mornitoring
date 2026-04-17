"use client"

import { useEffect, useMemo, useState } from "react"
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
import apiClient from "@/lib/api/client"

type UserRole = "team_leader" | "chief_secretary" | "secretary" | "reviewer"

interface UserStatus {
  user_id: number
  name: string
  email: string
  role: UserRole
  kakao_linked: boolean
  kakao_uuid: string | null
}

const ROLE_LABELS: Record<UserRole, string> = {
  team_leader: "팀장",
  chief_secretary: "총괄간사",
  secretary: "간사",
  reviewer: "검토위원",
}

interface SendResultItem {
  recipient_id: number
  recipient_name: string
  is_sent: boolean
  error: string | null
}

interface SendResponse {
  sent_count: number
  failed_count: number
  results: SendResultItem[]
}

const TEMPLATES = [
  {
    type: "review_request",
    label: "검토 요청",
    title: "[모니터링] 검토 요청",
    body: "안녕하세요. 새 검토 대상이 배정되었습니다. 시스템에서 확인 부탁드립니다.",
  },
  {
    type: "doc_received",
    label: "도서 접수",
    title: "[모니터링] 설계도서 접수 안내",
    body: "검토 대상 건축물의 설계도서가 접수되었습니다.",
  },
  {
    type: "reminder",
    label: "리마인더",
    title: "[모니터링] 검토 마감 임박",
    body: "검토 마감일이 임박했습니다. 진행 상황을 확인해주세요.",
  },
] as const

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSuccess?: () => void
}

export function SendNotificationDialog({ open, onOpenChange, onSuccess }: Props) {
  const [users, setUsers] = useState<UserStatus[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [templateType, setTemplateType] = useState<string>(TEMPLATES[0].type)
  const [title, setTitle] = useState<string>(TEMPLATES[0].title)
  const [message, setMessage] = useState<string>(TEMPLATES[0].body)
  const [linkUrl, setLinkUrl] = useState("")
  const [search, setSearch] = useState("")
  const [isSending, setIsSending] = useState(false)
  const [result, setResult] = useState<SendResponse | null>(null)

  useEffect(() => {
    if (!open) return
    apiClient
      .get<UserStatus[]>("/api/kakao/reviewers")
      .then(({ data }) => setUsers(data))
      .catch((err) => console.error("사용자 조회 실패:", err))
  }, [open])

  useEffect(() => {
    const tpl = TEMPLATES.find((t) => t.type === templateType)
    if (tpl) {
      setTitle(tpl.title)
      setMessage(tpl.body)
    }
  }, [templateType])

  const filteredUsers = useMemo(
    () =>
      users.filter((r) => {
        const q = search.toLowerCase()
        return (
          r.name.toLowerCase().includes(q) ||
          r.email.toLowerCase().includes(q)
        )
      }),
    [users, search]
  )

  const linkedFiltered = filteredUsers.filter((r) => r.kakao_linked)

  const toggleId = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    if (selectedIds.size === linkedFiltered.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(linkedFiltered.map((r) => r.user_id)))
    }
  }

  const handleSend = async () => {
    if (selectedIds.size === 0) {
      alert("수신자를 1명 이상 선택해주세요")
      return
    }
    if (!title.trim() || !message.trim()) {
      alert("제목과 내용을 입력해주세요")
      return
    }
    setIsSending(true)
    setResult(null)
    try {
      const { data } = await apiClient.post<SendResponse>("/api/notifications/send", {
        recipient_ids: Array.from(selectedIds),
        title,
        message,
        template_type: templateType,
        link_url: linkUrl || null,
      })
      setResult(data)
      if (data.sent_count > 0) onSuccess?.()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "발송 실패"
      alert(msg)
    } finally {
      setIsSending(false)
    }
  }

  const handleClose = () => {
    onOpenChange(false)
    setSelectedIds(new Set())
    setResult(null)
    setSearch("")
  }

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : handleClose())}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>카카오톡 알림 발송</DialogTitle>
        </DialogHeader>

        {result ? (
          <div className="space-y-3">
            <div className="rounded-md border p-3">
              <p className="text-sm">
                성공 <span className="font-bold text-green-600">{result.sent_count}건</span>{" "}
                / 실패 <span className="font-bold text-red-600">{result.failed_count}건</span>
              </p>
            </div>
            <div className="max-h-[400px] overflow-y-auto rounded-md border">
              <ul className="divide-y">
                {result.results.map((r) => (
                  <li key={r.recipient_id} className="flex items-center gap-2 p-2 text-sm">
                    {r.is_sent ? (
                      <Badge>성공</Badge>
                    ) : (
                      <Badge variant="destructive">실패</Badge>
                    )}
                    <span className="font-medium">{r.recipient_name}</span>
                    {r.error && (
                      <span className="text-xs text-muted-foreground">— {r.error}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
            <DialogFooter>
              <Button onClick={handleClose}>닫기</Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>템플릿</Label>
              <div className="flex gap-2">
                {TEMPLATES.map((t) => (
                  <Button
                    key={t.type}
                    size="sm"
                    variant={templateType === t.type ? "default" : "outline"}
                    onClick={() => setTemplateType(t.type)}
                  >
                    {t.label}
                  </Button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="title">제목</Label>
              <Input
                id="title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="message">내용</Label>
              <textarea
                id="message"
                className="min-h-[100px] w-full rounded-md border px-3 py-2 text-sm"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="link">링크 URL (선택)</Label>
              <Input
                id="link"
                placeholder="https://..."
                value={linkUrl}
                onChange={(e) => setLinkUrl(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>
                  수신자 선택 ({selectedIds.size}명 선택됨 / 매칭된 사용자 {linkedFiltered.length}명)
                </Label>
                <Button size="sm" variant="ghost" onClick={toggleAll}>
                  {selectedIds.size === linkedFiltered.length ? "전체 해제" : "전체 선택"}
                </Button>
              </div>
              <Input
                placeholder="이름 또는 이메일 검색..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <div className="max-h-[260px] overflow-y-auto rounded-md border">
                <ul className="divide-y">
                  {filteredUsers.map((r) => {
                    const disabled = !r.kakao_linked
                    const checked = selectedIds.has(r.user_id)
                    return (
                      <li
                        key={r.user_id}
                        className={`flex items-center gap-2 p-2 text-sm ${
                          disabled ? "opacity-50" : "cursor-pointer hover:bg-gray-50"
                        }`}
                        onClick={() => !disabled && toggleId(r.user_id)}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={disabled}
                          onChange={() => toggleId(r.user_id)}
                          onClick={(e) => e.stopPropagation()}
                        />
                        <span className="font-medium">{r.name}</span>
                        <Badge variant="outline" className="text-xs">
                          {ROLE_LABELS[r.role]}
                        </Badge>
                        <span className="text-xs text-muted-foreground">{r.email}</span>
                        {!r.kakao_linked && (
                          <Badge variant="outline" className="ml-auto text-xs">
                            미매칭
                          </Badge>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </div>
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={handleClose} disabled={isSending}>
                취소
              </Button>
              <Button onClick={handleSend} disabled={isSending || selectedIds.size === 0}>
                {isSending ? "발송 중..." : `${selectedIds.size}명에게 발송`}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
