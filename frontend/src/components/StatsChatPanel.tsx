"use client"

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  ArrowLeftIcon,
  BotIcon,
  DatabaseIcon,
  HistoryIcon,
  PlusIcon,
  SendIcon,
  Trash2Icon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import apiClient from "@/lib/api/client"
import { useAuthStore } from "@/stores/authStore"

/** 백엔드가 SSE `sql` 이벤트로 내려주는 조회 기록 1건. */
interface SqlLogEntry {
  sql: string | null
  purpose?: string
  row_count?: number
  duration_ms?: number
  truncated?: boolean
  error?: string | null
}

interface ChatMessage {
  role: "user" | "assistant"
  content: string
  sqlLog: SqlLogEntry[]
}

interface StatusResponse {
  enabled: boolean
  model: string
}

/** 이력 목록 1건 (총괄간사 전용). */
interface ConversationSummary {
  id: number
  title: string
  updated_at: string
  user_id: number
  user_name: string
}

interface ConversationMessage {
  id: number
  role: "user" | "assistant"
  content: string
  sql_log: SqlLogEntry[]
  created_at: string
}

interface ConversationDetail {
  id: number
  title: string
  user_id: number
  user_name: string
  messages: ConversationMessage[]
}

type PanelView = "chat" | "history"

/** 처음 열었을 때 보여줄 예시 질문. 실제 DB 컬럼으로 답할 수 있는 것만 넣는다. */
const SAMPLE_QUESTIONS = [
  "시도별 대상 건축물 수를 많은 순으로 알려줘",
  "예비검토 결과 비율을 적합·단순오류·재계산으로 나눠줘",
  "조별 검토서 제출률을 비교해줘",
  "심각도 L3 이상 지적이 가장 많은 분류 10개는?",
]

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export function StatsChatPanel({ screenContext }: { screenContext?: string }) {
  const [isOpen, setIsOpen] = useState(false)
  const [isEnabled, setIsEnabled] = useState<boolean | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [isStreaming, setIsStreaming] = useState(false)
  const [statusText, setStatusText] = useState("")
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [view, setView] = useState<PanelView>("chat")
  const [historyRows, setHistoryRows] = useState<ConversationSummary[]>([])
  const [isHistoryLoading, setIsHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState("")
  // 남의 대화를 열어본 경우의 작성자 이름. 본인 대화면 빈 문자열이며,
  // 값이 있으면 이어서 질문할 수 없는 열람 전용 상태다.
  const [viewingAuthor, setViewingAuthor] = useState("")
  const scrollRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const currentUser = useAuthStore((state) => state.user)
  const canViewHistory = currentUser?.role === "chief_secretary"
  const isReadOnly = viewingAuthor !== ""

  useEffect(() => {
    let cancelled = false
    apiClient
      .get<StatusResponse>("/api/stats-chat/status")
      .then(({ data }) => {
        if (!cancelled) setIsEnabled(data.enabled)
      })
      .catch(() => {
        if (!cancelled) setIsEnabled(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // 새 내용이 붙을 때마다 맨 아래로
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages, statusText])

  // 패널을 닫거나 화면을 벗어나면 진행 중인 스트림을 끊는다
  useEffect(() => {
    return () => abortRef.current?.abort()
  }, [])

  const appendToLastAssistant = useCallback(
    (updater: (message: ChatMessage) => ChatMessage) => {
      setMessages((prev) => {
        const next = [...prev]
        const last = next[next.length - 1]
        if (!last || last.role !== "assistant") return prev
        next[next.length - 1] = updater(last)
        return next
      })
    },
    [],
  )

  const send = useCallback(
    async (question: string) => {
      const trimmed = question.trim()
      if (!trimmed || isStreaming) return

      setInput("")
      setStatusText("분석을 준비하는 중...")
      setIsStreaming(true)
      setMessages((prev) => [
        ...prev,
        { role: "user", content: trimmed, sqlLog: [] },
        { role: "assistant", content: "", sqlLog: [] },
      ])

      const controller = new AbortController()
      abortRef.current = controller
      // done 또는 error 를 받았는지 — 못 받고 끝나면 끊긴 응답으로 처리한다.
      let terminated = false
      const token =
        typeof window !== "undefined" ? localStorage.getItem("access_token") : null

      try {
        const response = await fetch(`${API_BASE}/api/stats-chat/ask`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            question: trimmed,
            conversation_id: conversationId,
            screen_context: screenContext,
          }),
          signal: controller.signal,
        })

        if (!response.ok || !response.body) {
          const detail = await response.text().catch(() => "")
          throw new Error(detail || `요청이 실패했습니다 (${response.status})`)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ""

        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          // SSE 프레임은 빈 줄로 구분된다. 마지막 조각은 다음 청크와 이어 붙인다.
          const frames = buffer.split("\n\n")
          buffer = frames.pop() ?? ""
          for (const frame of frames) {
            handleFrame(frame)
          }
        }
        // 마지막 프레임이 빈 줄 없이 끝났을 수 있다.
        if (buffer.trim()) handleFrame(buffer)

        // done/error 없이 연결이 끊기면 부분 답변을 정상 완료처럼 보여주게 된다.
        if (!terminated) {
          appendToLastAssistant((last) => ({
            ...last,
            content:
              `${last.content}\n\n**오류:** 응답이 중간에 끊겼다. 다시 시도할 것.`.trim(),
          }))
        }
      } catch (error) {
        if ((error as Error).name === "AbortError") return
        const message =
          error instanceof Error ? error.message : "알 수 없는 오류가 발생했습니다"
        appendToLastAssistant((last) => ({
          ...last,
          content: last.content || `오류: ${message}`,
        }))
      } finally {
        setIsStreaming(false)
        setStatusText("")
        abortRef.current = null
      }

      function handleFrame(frame: string) {
        const lines = frame.split("\n")
        const eventLine = lines.find((line) => line.startsWith("event: "))
        const dataLine = lines.find((line) => line.startsWith("data: "))
        if (!eventLine || !dataLine) return

        const eventName = eventLine.slice(7).trim()
        let data: Record<string, unknown>
        try {
          data = JSON.parse(dataLine.slice(6)) as Record<string, unknown>
        } catch {
          return
        }

        if (eventName === "delta") {
          const text = typeof data.text === "string" ? data.text : ""
          setStatusText("")
          appendToLastAssistant((last) => ({
            ...last,
            content: last.content + text,
          }))
        } else if (eventName === "status") {
          setStatusText(typeof data.message === "string" ? data.message : "")
        } else if (eventName === "sql") {
          const entry = data as unknown as SqlLogEntry
          appendToLastAssistant((last) => ({
            ...last,
            sqlLog: [...last.sqlLog, entry],
          }))
        } else if (eventName === "done") {
          terminated = true
          if (typeof data.conversation_id === "number") {
            setConversationId(data.conversation_id)
          }
        } else if (eventName === "error") {
          terminated = true
          const message =
            typeof data.message === "string" ? data.message : "오류가 발생했습니다"
          appendToLastAssistant((last) => ({
            ...last,
            content: `${last.content}\n\n**오류:** ${message}`.trim(),
          }))
        }
      }
    },
    [appendToLastAssistant, conversationId, isStreaming, screenContext],
  )

  const resetConversation = useCallback(() => {
    abortRef.current?.abort()
    setMessages([])
    setConversationId(null)
    setStatusText("")
    setViewingAuthor("")
    setView("chat")
  }, [])

  const openHistory = useCallback(async () => {
    setView("history")
    setIsHistoryLoading(true)
    setHistoryError("")
    try {
      const { data } = await apiClient.get<ConversationSummary[]>(
        "/api/stats-chat/conversations",
      )
      setHistoryRows(data)
    } catch {
      setHistoryError("대화 목록을 불러오지 못했다.")
    } finally {
      setIsHistoryLoading(false)
    }
  }, [])

  const openConversation = useCallback(
    async (row: ConversationSummary) => {
      abortRef.current?.abort()
      try {
        const { data } = await apiClient.get<ConversationDetail>(
          `/api/stats-chat/conversations/${row.id}`,
        )
        setMessages(
          data.messages.map((message) => ({
            role: message.role,
            content: message.content,
            sqlLog: message.sql_log ?? [],
          })),
        )
        setConversationId(data.id)
        // 남의 대화에 내 질문을 덧붙이면 이력 주인이 뒤섞인다. 열람 전용으로 둔다.
        setViewingAuthor(data.user_id === currentUser?.id ? "" : data.user_name)
        setView("chat")
      } catch {
        setHistoryError("대화를 불러오지 못했다.")
      }
    },
    [currentUser?.id],
  )

  const deleteConversation = useCallback(
    async (id: number) => {
      try {
        await apiClient.delete(`/api/stats-chat/conversations/${id}`)
        setHistoryRows((prev) => prev.filter((row) => row.id !== id))
        if (conversationId === id) resetConversation()
      } catch {
        setHistoryError("대화를 삭제하지 못했다.")
      }
    },
    [conversationId, resetConversation],
  )

  if (isEnabled === false) return null

  return (
    <>
      <Button
        type="button"
        onClick={() => setIsOpen(true)}
        className="fixed bottom-6 right-6 z-40 h-12 gap-2 rounded-full px-5 shadow-lg"
      >
        <BotIcon className="size-4" />
        AI 분석
      </Button>

      <Sheet open={isOpen} onOpenChange={setIsOpen}>
        {/* 기본 폭(3/4·max-w-sm)은 data-[side] 변형이라 우선순위가 높다.
            표를 읽을 수 있게 넓히려면 ! 로 덮어써야 한다. */}
        <SheetContent
          side="right"
          className="flex w-full! flex-col gap-0 p-0 sm:max-w-xl!"
        >
          {/* pr-12: SheetContent가 우상단(top-3 right-3)에 닫기 버튼을 겹쳐 그리므로
              헤더 오른쪽에 그만큼 자리를 비워 둔다. */}
          <SheetHeader className="border-b p-4 pr-12">
            <div className="flex items-start justify-between gap-2">
              <div>
                <SheetTitle>
                  {view === "history" ? "대화 이력" : "통계 AI 분석"}
                </SheetTitle>
                <SheetDescription>
                  {view === "history"
                    ? "전체 사용자가 주고받은 대화다. 항목을 누르면 내용을 볼 수 있다."
                    : "현재 DB를 직접 조회해서 답한다. 답변에 사용한 SQL을 함께 확인할 수 있다."}
                </SheetDescription>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {view === "history" ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setView("chat")}
                  >
                    <ArrowLeftIcon className="size-4" />
                    돌아가기
                  </Button>
                ) : (
                  <>
                    {canViewHistory && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={openHistory}
                        disabled={isStreaming}
                      >
                        <HistoryIcon className="size-4" />
                        이력
                      </Button>
                    )}
                    {messages.length > 0 && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={resetConversation}
                        disabled={isStreaming}
                      >
                        <PlusIcon className="size-4" />새 대화
                      </Button>
                    )}
                  </>
                )}
              </div>
            </div>
          </SheetHeader>

          {view === "history" ? (
            <HistoryList
              rows={historyRows}
              isLoading={isHistoryLoading}
              error={historyError}
              onOpen={openConversation}
              onDelete={deleteConversation}
            />
          ) : (
            <>
              <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
                {isReadOnly && (
                  <div className="rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                    {viewingAuthor} 님의 대화를 열람 중이다. 이어서 질문하려면 새 대화를
                    시작한다.
                  </div>
                )}
                {messages.length === 0 && (
                  <div className="space-y-3">
                    <p className="text-sm text-muted-foreground">
                      통계자료에 대해 자연어로 질문하면 데이터베이스를 조회해 답한다.
                    </p>
                    <div className="flex flex-col gap-2">
                      {SAMPLE_QUESTIONS.map((question) => (
                        <button
                          key={question}
                          type="button"
                          onClick={() => send(question)}
                          className="rounded-md border px-3 py-2 text-left text-sm hover:bg-muted"
                        >
                          {question}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {messages.map((message, index) => (
                  <MessageBubble key={index} message={message} />
                ))}

                {statusText && (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <DatabaseIcon className="size-4 animate-pulse" />
                    {statusText}
                  </div>
                )}
              </div>

              <form
                className="flex gap-2 border-t p-4"
                onSubmit={(event) => {
                  event.preventDefault()
                  send(input)
                }}
              >
                <Input
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  placeholder={
                    isReadOnly
                      ? "열람 전용 — 질문하려면 새 대화를 시작한다"
                      : "예: 조별 검토서 제출률을 비교해줘"
                  }
                  disabled={isStreaming || isReadOnly}
                  maxLength={2000}
                />
                <Button
                  type="submit"
                  size="icon"
                  disabled={isStreaming || isReadOnly || !input.trim()}
                >
                  <SendIcon className="size-4" />
                  <span className="sr-only">전송</span>
                </Button>
              </form>
            </>
          )}
        </SheetContent>
      </Sheet>
    </>
  )
}

/** 총괄간사 감독용 대화 이력 목록. */
function HistoryList({
  rows,
  isLoading,
  error,
  onOpen,
  onDelete,
}: {
  rows: ConversationSummary[]
  isLoading: boolean
  error: string
  onOpen: (row: ConversationSummary) => void
  onDelete: (id: number) => void
}) {
  if (isLoading) {
    return (
      <div className="flex-1 p-4 text-sm text-muted-foreground">불러오는 중...</div>
    )
  }
  if (error) {
    return <div className="flex-1 p-4 text-sm text-destructive">{error}</div>
  }
  if (rows.length === 0) {
    return (
      <div className="flex-1 p-4 text-sm text-muted-foreground">
        아직 저장된 대화가 없다.
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-2 overflow-y-auto p-4">
      {rows.map((row) => (
        <div
          key={row.id}
          className="flex items-start gap-2 rounded-md border p-3 hover:bg-muted/50"
        >
          <button
            type="button"
            onClick={() => onOpen(row)}
            className="min-w-0 flex-1 text-left"
          >
            <div className="truncate text-sm font-medium">{row.title}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {row.user_name || "(삭제된 사용자)"} · {formatTimestamp(row.updated_at)}
            </div>
          </button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="대화 삭제"
            onClick={() => onDelete(row.id)}
          >
            <Trash2Icon className="size-4" />
          </Button>
        </div>
      ))}
    </div>
  )
}

/** ISO 문자열을 'MM-DD HH:mm' 로 줄여 표시한다. */
function formatTimestamp(value: string): string {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {message.sqlLog.map((entry, index) => (
        <SqlLogDetails key={index} entry={entry} />
      ))}
      {message.content && (
        <div className="rounded-lg border bg-muted/30 p-3 text-sm">
          <MarkdownBody>{message.content}</MarkdownBody>
        </div>
      )}
    </div>
  )
}

function SqlLogDetails({ entry }: { entry: SqlLogEntry }) {
  const summary = entry.error
    ? `조회 실패: ${entry.error}`
    : `${entry.purpose || "데이터 조회"} — ${entry.row_count ?? 0}행${
        entry.truncated ? " (상한 도달)" : ""
      }, ${entry.duration_ms ?? 0}ms`

  return (
    <details className="rounded-md border bg-background text-xs">
      <summary className="cursor-pointer px-3 py-2 text-muted-foreground">
        <DatabaseIcon className="mr-1 inline size-3" />
        {summary}
      </summary>
      {/* SQL은 한 줄이 길어 가로 스크롤보다 줄바꿈이 읽기 편하다. */}
      {entry.sql && (
        <pre className="border-t px-3 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all">
          {entry.sql}
        </pre>
      )}
    </details>
  )
}

/** 모델 답변의 표·목록을 화면 스타일에 맞춰 렌더링한다. */
function MarkdownBody({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }: { children?: ReactNode }) => (
          <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>
        ),
        ul: ({ children }: { children?: ReactNode }) => (
          <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>
        ),
        ol: ({ children }: { children?: ReactNode }) => (
          <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>
        ),
        h1: ({ children }: { children?: ReactNode }) => (
          <h3 className="mb-2 text-sm font-bold">{children}</h3>
        ),
        h2: ({ children }: { children?: ReactNode }) => (
          <h3 className="mb-2 text-sm font-bold">{children}</h3>
        ),
        h3: ({ children }: { children?: ReactNode }) => (
          <h3 className="mb-2 text-sm font-bold">{children}</h3>
        ),
        table: ({ children }: { children?: ReactNode }) => (
          <div className="mb-2 overflow-x-auto last:mb-0">
            <table className="w-full border-collapse text-xs">{children}</table>
          </div>
        ),
        th: ({ children }: { children?: ReactNode }) => (
          <th className="border px-2 py-1 text-left font-semibold">{children}</th>
        ),
        td: ({ children }: { children?: ReactNode }) => (
          <td className="border px-2 py-1">{children}</td>
        ),
        code: ({ children }: { children?: ReactNode }) => (
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
            {children}
          </code>
        ),
      }}
    >
      {children}
    </ReactMarkdown>
  )
}
