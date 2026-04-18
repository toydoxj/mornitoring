"use client"

import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
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
import type { KakaoScopesStatus, SetupStatus, User, UserRole } from "@/types"
import { KAKAO_SCOPES_LABELS, ROLE_LABELS, SETUP_STATUS_LABELS } from "@/types"

interface UserListResponse {
  items: User[]
  total: number
}

interface KakaoFriend {
  uuid: string
  profile_nickname: string | null
  profile_thumbnail_image: string | null
  favorite: boolean
  matched_user_id: number | null
  matched_user_name: string | null
}

interface ScopeItem {
  id: string
  display_name: string | null
  type: string | null
  using: boolean
  agreed: boolean
  revocable: boolean
}

interface ScopeStatus {
  kakao_linked: boolean
  all_agreed: boolean
  missing_scopes: string[]
  scopes: ScopeItem[]
  reauthorize_url: string | null
}

interface UserScopeDiagnosis {
  user_id: number
  user_name: string
  kakao_id: string | null
  oauth_linked: boolean
  token_expired: boolean
  all_agreed: boolean | null
  missing_scopes: string[]
  scopes: ScopeItem[]
  error: string | null
}

const ROLE_OPTIONS: { value: UserRole; label: string }[] = [
  { value: "team_leader", label: "팀장" },
  { value: "chief_secretary", label: "총괄간사" },
  { value: "secretary", label: "간사" },
  { value: "reviewer", label: "검토위원" },
]

const SCOPE_LABELS: Record<string, string> = {
  profile_nickname: "닉네임",
  friends: "카카오톡 친구 목록",
  talk_message: "카카오톡 메시지 전송",
  account_email: "이메일",
}

export default function AdminPage() {
  const [users, setUsers] = useState<User[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)

  // 등록 다이얼로그
  const [createOpen, setCreateOpen] = useState(false)
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    role: "reviewer" as UserRole,
    phone: "",
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")

  // 엑셀 일괄 등록
  const [bulkUploading, setBulkUploading] = useState(false)
  const [bulkResult, setBulkResult] = useState<{
    created: number
    skipped: number
    accounts?: { email: string; name: string; initial_password: string }[]
  } | null>(null)
  const [credentialDialog, setCredentialDialog] = useState<{
    title: string
    userName: string
    initialPassword: string
  } | null>(null)
  const [credentialCopied, setCredentialCopied] = useState(false)

  // 초대 발송 결과 다이얼로그 (manual fallback 시 setup_url 노출용)
  const [inviteDialog, setInviteDialog] = useState<{
    userName: string
    setupUrl: string
    expiresAt: string
    error?: string | null
  } | null>(null)
  const [inviteCopied, setInviteCopied] = useState(false)
  const [invitingUserId, setInvitingUserId] = useState<number | null>(null)

  // 일괄 발송 관련
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set())
  const [bulkInviting, setBulkInviting] = useState(false)
  const [autoSendInviteOnImport, setAutoSendInviteOnImport] = useState(true)
  const [bulkInviteResult, setBulkInviteResult] = useState<{
    summary: {
      total: number
      kakao_sent: number
      manual: number
      failed: number
      sender_error: string | null
    }
    results: Array<{
      user_id: number
      name: string
      delivery: string
      expires_at: string
      setup_url: string | null
      error: string | null
    }>
  } | null>(null)

  // 수정 다이얼로그
  const [editTarget, setEditTarget] = useState<User | null>(null)
  const [editData, setEditData] = useState({
    name: "",
    phone: "",
    role: "reviewer" as UserRole,
    is_active: true,
  })

  // 카카오 매칭 관련
  const [scopeStatus, setScopeStatus] = useState<ScopeStatus | null>(null)
  const [friends, setFriends] = useState<KakaoFriend[]>([])
  const [isFetchingFriends, setIsFetchingFriends] = useState(false)
  const [friendError, setFriendError] = useState<string | null>(null)
  const [matchTarget, setMatchTarget] = useState<User | null>(null)
  const [friendSearch, setFriendSearch] = useState("")
  const [diagnosis, setDiagnosis] = useState<UserScopeDiagnosis | null>(null)
  const [diagnosisLoading, setDiagnosisLoading] = useState(false)

  // 비번 미설정자 필터 (운영자가 재발송 대상 식별)
  const [showUnsetupOnly, setShowUnsetupOnly] = useState(false)

  const fetchUsers = async () => {
    try {
      const { data } = await apiClient.get<UserListResponse>("/api/users", {
        params: { size: 100 },
      })
      setUsers(data.items)
      setTotal(data.total)
    } catch (err) {
      console.error("사용자 목록 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }

  // 미설정자 = setup_completed 외 (pending/expired/not_invited)
  const visibleUsers = showUnsetupOnly
    ? users.filter((u) => u.setup_status && u.setup_status !== "setup_completed")
    : users
  const unsetupCount = users.filter(
    (u) => u.setup_status && u.setup_status !== "setup_completed"
  ).length

  const fetchScopeStatus = async () => {
    try {
      const { data } = await apiClient.get<ScopeStatus>("/api/kakao/me/scopes")
      setScopeStatus(data)
    } catch (err) {
      console.error("동의 항목 조회 실패:", err)
    }
  }

  const fetchFriends = async () => {
    setIsFetchingFriends(true)
    setFriendError(null)
    try {
      const { data } = await apiClient.get<{ items: KakaoFriend[] }>("/api/kakao/friends")
      setFriends(data.items)
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "친구 목록 조회 실패"
      setFriendError(msg)
    } finally {
      setIsFetchingFriends(false)
    }
  }

  useEffect(() => {
    fetchUsers()
    fetchScopeStatus()
  }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError("")
    try {
      const { data } = await apiClient.post<{ name: string; initial_password: string }>(
        "/api/users", formData
      )
      setCreateOpen(false)
      const createdName = data.name
      setFormData({ name: "", email: "", role: "reviewer", phone: "" })
      fetchUsers()
      setCredentialDialog({
        title: "사용자 등록 완료",
        userName: createdName,
        initialPassword: data.initial_password,
      })
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail || "등록 실패")
    } finally {
      setSubmitting(false)
    }
  }

  const handleEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editTarget) return
    setSubmitting(true)
    try {
      await apiClient.patch(`/api/users/${editTarget.id}`, editData)
      setEditTarget(null)
      fetchUsers()
    } catch (err) {
      console.error("수정 실패:", err)
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (userId: number, userName: string) => {
    if (!confirm(`${userName} 사용자를 삭제하시겠습니까?`)) return
    try {
      await apiClient.delete(`/api/users/${userId}`)
      fetchUsers()
    } catch (err) {
      console.error("삭제 실패:", err)
    }
  }

  const handleBulkUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setBulkUploading(true)
    setBulkResult(null)
    try {
      const formData = new FormData()
      formData.append("file", file)
      const { data } = await apiClient.post(
        `/api/users/import-excel?auto_send_invite=${autoSendInviteOnImport}`,
        formData,
        { headers: { "Content-Type": "multipart/form-data" } },
      )
      setBulkResult(data)
      // 등록 시 자동 발송 결과가 있으면 일괄 결과 다이얼로그도 띄움
      if (data.invite_summary) {
        setBulkInviteResult({
          summary: data.invite_summary,
          results: data.invite_results || [],
        })
      }
      fetchUsers()
    } catch {
      setBulkResult({ created: 0, skipped: 0 })
    } finally {
      setBulkUploading(false)
      e.target.value = ""
    }
  }

  const handleSendInvite = async (userId: number, userName: string, kakaoMatched: boolean) => {
    const message = kakaoMatched
      ? `${userName}에게 초대를 발송할까요?\n\n카카오로 발송되며, 실패 시 수동 전달용 링크가 화면에 표시됩니다.`
      : `${userName}은 카카오 매칭이 안 되어 있습니다.\n\n수동 전달용 링크가 화면에 표시됩니다. 별도 채널(SMS/이메일 등)로 전달해주세요. 진행하시겠습니까?`
    if (!confirm(message)) return
    setInvitingUserId(userId)
    try {
      const { data } = await apiClient.post<{
        delivery: string
        setup_url: string
        expires_at: string
        purpose: string
        error?: string | null
      }>(`/api/users/${userId}/send-invite`)

      if (data.delivery === "kakao" && !data.error) {
        // 카카오 발송 성공 → 토스트성 알림 + 사용자 목록 갱신은 불필요(상태 변화 없음)
        alert(`${userName}에게 카카오 메시지로 초대 링크를 발송했습니다.`)
      } else {
        // manual fallback (미매칭 또는 카카오 발송 실패) → 다이얼로그로 setup_url 노출
        setInviteDialog({
          userName,
          setupUrl: data.setup_url,
          expiresAt: data.expires_at,
          error: data.error,
        })
        setInviteCopied(false)
      }
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "초대 발송 실패"
      alert(msg)
    } finally {
      setInvitingUserId(null)
    }
  }

  const toggleUserSelection = (userId: number) => {
    setSelectedUserIds((prev) => {
      const next = new Set(prev)
      if (next.has(userId)) {
        next.delete(userId)
      } else {
        next.add(userId)
      }
      return next
    })
  }

  const toggleAllUsers = () => {
    if (selectedUserIds.size === users.length && users.length > 0) {
      setSelectedUserIds(new Set())
    } else {
      setSelectedUserIds(new Set(users.map((u) => u.id)))
    }
  }

  const handleBulkSendInvite = async () => {
    const ids = Array.from(selectedUserIds)
    if (ids.length === 0) return
    if (!confirm(`선택한 ${ids.length}명에게 초대를 발송하시겠습니까?\n\n카카오 매칭자는 카카오로 발송되며, 미매칭자는 화면에 수동 전달용 링크가 표시됩니다.`)) {
      return
    }
    setBulkInviting(true)
    try {
      const { data } = await apiClient.post(
        "/api/users/bulk-send-invite",
        { user_ids: ids },
      )
      setBulkInviteResult(data)
      setSelectedUserIds(new Set())
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "일괄 발송 실패"
      alert(msg)
    } finally {
      setBulkInviting(false)
    }
  }

  const handleCopyToken = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url)
    } catch {
      // 무시 — 사용자가 수동 선택 가능
    }
  }

  const handleCopyInviteUrl = async () => {
    if (!inviteDialog) return
    try {
      await navigator.clipboard.writeText(inviteDialog.setupUrl)
      setInviteCopied(true)
    } catch {
      // 일부 브라우저(http 환경)에서 clipboard 실패 — 사용자가 수동 선택 가능하므로 무시
    }
  }

  const handleResetPassword = async (userId: number, userName: string) => {
    if (!confirm(`${userName}의 비밀번호를 초기화하시겠습니까?`)) return
    try {
      const { data } = await apiClient.post<{ initial_password: string }>(
        `/api/users/${userId}/reset-password`
      )
      setCredentialDialog({
        title: "비밀번호 초기화 완료",
        userName,
        initialPassword: data.initial_password,
      })
    } catch (err) {
      console.error("초기화 실패:", err)
    }
  }

  const openEdit = (user: User) => {
    setEditTarget(user)
    setEditData({
      name: user.name,
      phone: user.phone || "",
      role: user.role,
      is_active: user.is_active,
    })
  }

  // --- 카카오 매칭 핸들러 ---
  const handleOpenMatch = (user: User) => {
    setMatchTarget(user)
    setFriendSearch("")
    if (friends.length === 0) {
      fetchFriends()
    }
  }

  const handleMatch = async (uuid: string) => {
    if (!matchTarget) return
    try {
      await apiClient.post("/api/kakao/match", {
        user_id: matchTarget.id,
        kakao_uuid: uuid,
      })
      setMatchTarget(null)
      await Promise.all([fetchUsers(), fetchFriends()])
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "매칭 실패"
      alert(msg)
    }
  }

  const handleUnmatch = async (userId: number) => {
    if (!confirm("매칭을 해제하시겠습니까?")) return
    try {
      await apiClient.delete(`/api/kakao/match/${userId}`)
      await Promise.all([fetchUsers(), fetchFriends()])
    } catch (err) {
      console.error("해제 실패:", err)
    }
  }

  const handleDiagnose = async (user: User) => {
    setDiagnosisLoading(true)
    setDiagnosis({
      user_id: user.id,
      user_name: user.name,
      kakao_id: null,
      oauth_linked: false,
      token_expired: false,
      all_agreed: null,
      missing_scopes: [],
      scopes: [],
      error: null,
    })
    try {
      const { data } = await apiClient.get<UserScopeDiagnosis>(
        `/api/kakao/user/${user.id}/scopes`
      )
      setDiagnosis(data)
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "진단 실패"
      setDiagnosis({
        user_id: user.id,
        user_name: user.name,
        kakao_id: null,
        oauth_linked: false,
        token_expired: false,
        all_agreed: null,
        missing_scopes: [],
        scopes: [],
        error: msg,
      })
    } finally {
      setDiagnosisLoading(false)
    }
  }

  const linkedCount = users.filter((u) => u.kakao_linked).length
  const matchedCount = users.filter((u) => u.kakao_matched).length

  const filteredFriends = friends.filter((f) => {
    const nick = (f.profile_nickname ?? "").toLowerCase()
    return nick.includes(friendSearch.toLowerCase())
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">사용자 관리</h1>
          <p className="text-sm text-muted-foreground">
            전체 {total}명 · 카카오 로그인 {linkedCount}명 · 친구 매칭 {matchedCount}명 ·
            <span className={unsetupCount > 0 ? "text-amber-700 font-medium ml-1" : "ml-1"}>
              비번 미설정 {unsetupCount}명
            </span>
          </p>
          <label className="mt-1 inline-flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
            <input
              type="checkbox"
              checked={showUnsetupOnly}
              onChange={(e) => setShowUnsetupOnly(e.target.checked)}
              className="h-3.5 w-3.5"
            />
            비번 미설정자만 보기
          </label>
        </div>
        <div className="flex gap-2 items-center">
          <Button
            variant="outline"
            onClick={fetchFriends}
            loading={isFetchingFriends}
            loadingText="불러오는 중..."
          >
            친구 목록 새로고침
          </Button>
          <label
            className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer"
            title="카카오 미매칭 사용자는 수동 전달 링크가 화면에 표시됩니다"
          >
            <input
              type="checkbox"
              checked={autoSendInviteOnImport}
              onChange={(e) => setAutoSendInviteOnImport(e.target.checked)}
              className="h-3.5 w-3.5"
            />
            등록 후 자동 초대 발송
          </label>
          <label className="cursor-pointer">
            <Input
              type="file"
              accept=".xlsx,.xls"
              onChange={handleBulkUpload}
              disabled={bulkUploading}
              className="hidden"
            />
            <span className="inline-flex h-9 items-center justify-center rounded-md border px-4 text-sm font-medium hover:bg-accent cursor-pointer">
              {bulkUploading ? "처리 중..." : "엑셀 일괄등록"}
            </span>
          </label>
          {bulkResult && (
            <div className="w-full space-y-2">
              <span className="text-xs text-muted-foreground">
                등록 {bulkResult.created}명 / 스킵 {bulkResult.skipped}명
              </span>
              {bulkResult.accounts && bulkResult.accounts.length > 0 && (
                <textarea
                  readOnly
                  className="w-full rounded-md border p-2 text-xs font-mono"
                  rows={Math.min(bulkResult.accounts.length + 1, 12)}
                  value={
                    "이메일\t이름\t초기비밀번호\n" +
                    bulkResult.accounts
                      .map((a) => `${a.email}\t${a.name}\t${a.initial_password}`)
                      .join("\n")
                  }
                />
              )}
            </div>
          )}
          <Button onClick={() => setCreateOpen(true)}>사용자 등록</Button>
        </div>
      </div>

      {/* 내 카카오 동의 상태 배너 */}
      {scopeStatus && (
        <div
          className={`rounded-md border p-3 text-sm ${
            !scopeStatus.kakao_linked
              ? "border-amber-200 bg-amber-50 text-amber-800"
              : scopeStatus.all_agreed
                ? "border-green-200 bg-green-50 text-green-800"
                : "border-red-200 bg-red-50 text-red-800"
          }`}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-1">
              {!scopeStatus.kakao_linked ? (
                <p className="font-medium">
                  내 카카오 계정 연동이 필요합니다. 먼저 카카오 로그인을 진행해주세요.
                </p>
              ) : scopeStatus.all_agreed ? (
                <p className="font-medium">내 카카오 동의가 모두 완료되었습니다.</p>
              ) : (
                <>
                  <p className="font-medium">
                    내 카카오 추가 동의가 필요합니다:{" "}
                    {scopeStatus.missing_scopes.map((s) => SCOPE_LABELS[s] ?? s).join(", ")}
                  </p>
                </>
              )}
              <div className="flex flex-wrap gap-2 pt-1">
                {scopeStatus.scopes
                  .filter((s) => ["profile_nickname", "friends", "talk_message", "account_email"].includes(s.id))
                  .map((s) => (
                    <Badge
                      key={s.id}
                      variant={s.agreed ? "default" : "outline"}
                      className={s.agreed ? "" : "border-red-300 text-red-700"}
                    >
                      {(SCOPE_LABELS[s.id] ?? s.id)}: {s.agreed ? "동의" : "미동의"}
                    </Badge>
                  ))}
              </div>
            </div>
            {scopeStatus.reauthorize_url && (
              <Button
                size="sm"
                onClick={() => { window.location.href = scopeStatus.reauthorize_url! }}
              >
                추가 동의받기
              </Button>
            )}
          </div>
        </div>
      )}

      {friendError && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {friendError}
        </div>
      )}

      {/* 일괄 발송 액션 바 */}
      {selectedUserIds.size > 0 && (
        <div className="flex items-center justify-between rounded-md border bg-blue-50 px-3 py-2 text-sm">
          <span>
            <strong>{selectedUserIds.size}명</strong> 선택됨
          </span>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setSelectedUserIds(new Set())}
            >
              선택 해제
            </Button>
            <Button
              size="sm"
              loading={bulkInviting}
              loadingText="발송 중..."
              onClick={handleBulkSendInvite}
            >
              선택한 {selectedUserIds.size}명에게 일괄 초대 발송
            </Button>
          </div>
        </div>
      )}

      {/* 사용자 목록 */}
      <div className="rounded-md border bg-white overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[40px] text-center">
                <input
                  type="checkbox"
                  checked={users.length > 0 && selectedUserIds.size === users.length}
                  onChange={toggleAllUsers}
                  aria-label="전체 선택"
                  className="h-4 w-4"
                />
              </TableHead>
              <TableHead className="w-[60px]">ID</TableHead>
              <TableHead>이름</TableHead>
              <TableHead>이메일</TableHead>
              <TableHead className="w-[100px]">역할</TableHead>
              <TableHead className="w-[120px]">전화번호</TableHead>
              <TableHead className="w-[100px] text-center">카카오 로그인</TableHead>
              <TableHead className="w-[100px] text-center">친구 매칭</TableHead>
              <TableHead className="w-[90px] text-center">동의</TableHead>
              <TableHead className="w-[100px] text-center">비번 상태</TableHead>
              <TableHead className="w-[80px] text-center">상태</TableHead>
              <TableHead className="w-[260px] text-center">관리</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={12} className="h-32 text-center">
                  로딩 중...
                </TableCell>
              </TableRow>
            ) : users.length === 0 ? (
              <TableRow>
                <TableCell colSpan={12} className="h-32 text-center text-muted-foreground">
                  등록된 사용자가 없습니다
                </TableCell>
              </TableRow>
            ) : (
              visibleUsers.map((user) => (
                <TableRow key={user.id}>
                  <TableCell className="text-center">
                    <input
                      type="checkbox"
                      checked={selectedUserIds.has(user.id)}
                      onChange={() => toggleUserSelection(user.id)}
                      aria-label={`${user.name} 선택`}
                      className="h-4 w-4"
                    />
                  </TableCell>
                  <TableCell>{user.id}</TableCell>
                  <TableCell className="font-medium">{user.name}</TableCell>
                  <TableCell>{user.email}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{ROLE_LABELS[user.role]}</Badge>
                  </TableCell>
                  <TableCell>{user.phone || "-"}</TableCell>
                  <TableCell className="text-center">
                    {user.kakao_linked ? (
                      <Badge>완료</Badge>
                    ) : (
                      <Badge variant="outline">미완료</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-center">
                    {user.kakao_matched ? (
                      <Badge>매칭됨</Badge>
                    ) : (
                      <Badge variant="outline">미매칭</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-center">
                    {(() => {
                      const s = user.kakao_scopes_status as KakaoScopesStatus | undefined
                      if (!s || s === "unknown") {
                        return (
                          <Badge
                            variant="outline"
                            className="bg-gray-100 text-gray-500 border-gray-300"
                            title="진단 버튼으로 확인"
                          >
                            {KAKAO_SCOPES_LABELS.unknown}
                          </Badge>
                        )
                      }
                      const cls =
                        s === "ok"
                          ? "bg-green-100 text-green-700 border-green-300"
                          : "bg-red-100 text-red-700 border-red-300"
                      const tooltip = user.kakao_scopes_checked_at
                        ? `진단: ${new Date(user.kakao_scopes_checked_at).toLocaleString("ko-KR")}`
                        : undefined
                      return (
                        <Badge variant="outline" className={cls} title={tooltip}>
                          {KAKAO_SCOPES_LABELS[s]}
                        </Badge>
                      )
                    })()}
                  </TableCell>
                  <TableCell className="text-center">
                    {(() => {
                      const s = user.setup_status as SetupStatus | undefined
                      if (!s) return <Badge variant="outline">-</Badge>
                      const cls =
                        s === "setup_completed"
                          ? "bg-gray-100 text-gray-700 border-gray-300"
                          : s === "pending"
                            ? "bg-blue-100 text-blue-700 border-blue-300"
                            : s === "expired"
                              ? "bg-amber-100 text-amber-800 border-amber-300"
                              : "bg-red-100 text-red-700 border-red-300"
                      const tooltip = user.last_invite_sent_at
                        ? `마지막 발송: ${new Date(user.last_invite_sent_at).toLocaleString("ko-KR")}`
                        : undefined
                      return (
                        <Badge variant="outline" className={cls} title={tooltip}>
                          {SETUP_STATUS_LABELS[s]}
                        </Badge>
                      )
                    })()}
                  </TableCell>
                  <TableCell className="text-center">
                    <Badge variant={user.is_active ? "default" : "secondary"}>
                      {user.is_active ? "활성" : "비활성"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1 justify-center flex-wrap">
                      <Button size="sm" variant="outline" onClick={() => handleOpenMatch(user)}>
                        {user.kakao_matched ? "매칭 변경" : "매칭"}
                      </Button>
                      {user.kakao_matched && (
                        <Button size="sm" variant="ghost" onClick={() => handleUnmatch(user.id)}>
                          해제
                        </Button>
                      )}
                      {user.kakao_linked && (
                        <Button size="sm" variant="ghost" onClick={() => handleDiagnose(user)}>
                          진단
                        </Button>
                      )}
                      <Button size="sm" variant="outline" onClick={() => openEdit(user)}>
                        수정
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        loading={invitingUserId === user.id}
                        loadingText="발송 중..."
                        onClick={() => handleSendInvite(user.id, user.name, !!user.kakao_matched)}
                      >
                        초대 발송
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleResetPassword(user.id, user.name)}
                      >
                        PW초기화
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => handleDelete(user.id, user.name)}
                      >
                        삭제
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* 사용자 등록 다이얼로그 */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>사용자 등록</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="space-y-2">
              <Label>이름</Label>
              <Input
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                required
              />
            </div>
            <div className="space-y-2">
              <Label>이메일</Label>
              <Input
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                required
              />
            </div>
            <div className="space-y-2">
              <Label>역할</Label>
              <select
                className="w-full rounded-md border px-3 py-2 text-sm"
                value={formData.role}
                onChange={(e) => setFormData({ ...formData, role: e.target.value as UserRole })}
              >
                {ROLE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label>전화번호</Label>
              <Input
                value={formData.phone}
                onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                placeholder="010-0000-0000"
              />
            </div>
            <p className="text-sm text-muted-foreground">
              등록 완료 시 일회용 초기 비밀번호가 화면에 표시됩니다. 사용자에게 전달하고 최초 로그인 시 변경하도록 안내해주세요.
            </p>
            {error && <p className="text-sm text-red-500">{error}</p>}
            <Button type="submit" className="w-full" loading={submitting} loadingText="등록 중...">
              등록
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      {/* 초기 비밀번호 표시 다이얼로그 (등록/리셋 공통) */}
      <Dialog
        open={!!credentialDialog}
        onOpenChange={(open) => {
          if (!open) {
            setCredentialDialog(null)
            setCredentialCopied(false)
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{credentialDialog?.title}</DialogTitle>
          </DialogHeader>
          {credentialDialog && (
            <div className="space-y-3">
              <p className="text-sm">
                <strong>{credentialDialog.userName}</strong>의 초기 비밀번호입니다.
                사용자에게 안전한 채널로 전달해주세요.
              </p>
              <div className="flex items-center gap-2 rounded-md border bg-muted p-2">
                <code className="flex-1 font-mono text-base tracking-wider">
                  {credentialDialog.initialPassword}
                </code>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(credentialDialog.initialPassword)
                      setCredentialCopied(true)
                      setTimeout(() => setCredentialCopied(false), 1500)
                    } catch {
                      setCredentialCopied(false)
                    }
                  }}
                >
                  {credentialCopied ? "복사됨" : "복사"}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                최초 로그인 시 사용자가 반드시 비밀번호를 변경해야 합니다.
                이 창을 닫으면 비밀번호를 다시 볼 수 없으니 먼저 복사하세요.
              </p>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* 일괄 발송 결과 다이얼로그 */}
      <Dialog
        open={!!bulkInviteResult}
        onOpenChange={(open) => !open && setBulkInviteResult(null)}
      >
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>일괄 초대 발송 결과</DialogTitle>
          </DialogHeader>
          {bulkInviteResult && (
            <div className="space-y-4">
              {/* 요약 카드 */}
              <div className="grid grid-cols-4 gap-2 text-center text-sm">
                <div className="rounded-md border bg-gray-50 p-2">
                  <div className="text-xs text-muted-foreground">총</div>
                  <div className="text-lg font-bold">{bulkInviteResult.summary.total}</div>
                </div>
                <div className="rounded-md border border-green-200 bg-green-50 p-2">
                  <div className="text-xs text-green-700">카카오 발송</div>
                  <div className="text-lg font-bold text-green-700">{bulkInviteResult.summary.kakao_sent}</div>
                </div>
                <div className="rounded-md border border-amber-200 bg-amber-50 p-2">
                  <div className="text-xs text-amber-700">수동 전달 필요</div>
                  <div className="text-lg font-bold text-amber-700">{bulkInviteResult.summary.manual}</div>
                </div>
                <div className="rounded-md border border-red-200 bg-red-50 p-2">
                  <div className="text-xs text-red-700">실패</div>
                  <div className="text-lg font-bold text-red-700">{bulkInviteResult.summary.failed}</div>
                </div>
              </div>

              {bulkInviteResult.summary.sender_error && (
                <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
                  카카오 발신자 토큰 사용 불가 — {bulkInviteResult.summary.sender_error}.
                  카카오 매칭 사용자도 모두 수동 전달 링크로 표시됩니다.
                </div>
              )}

              {/* 수동 전달 필요 (가장 중요 — 펼침) */}
              {bulkInviteResult.results.some((r) => r.delivery === "manual" && !r.error) && (
                <details open className="rounded-md border">
                  <summary className="cursor-pointer p-2 text-sm font-medium bg-amber-50 flex items-center justify-between">
                    <span>수동 전달 필요 — 아래 링크를 사용자에게 SMS/이메일로 전달</span>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        const tsv =
                          "이름\t링크\n" +
                          bulkInviteResult.results
                            .filter((r) => r.delivery === "manual" && !r.error && r.setup_url)
                            .map((r) => `${r.name}\t${r.setup_url}`)
                            .join("\n")
                        handleCopyToken(tsv)
                      }}
                    >
                      전체 복사
                    </Button>
                  </summary>
                  <div className="space-y-1 p-2">
                    {bulkInviteResult.results
                      .filter((r) => r.delivery === "manual" && !r.error)
                      .map((r) => (
                        <div key={r.user_id} className="flex items-center gap-2 rounded border bg-white p-2 text-xs">
                          <div className="w-20 font-medium">{r.name}</div>
                          <code className="flex-1 break-all font-mono text-[10px] text-muted-foreground">
                            {r.setup_url}
                          </code>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => r.setup_url && handleCopyToken(r.setup_url)}
                          >
                            복사
                          </Button>
                        </div>
                      ))}
                  </div>
                </details>
              )}

              {/* 카카오 발송 완료 (접힘) */}
              {bulkInviteResult.results.some((r) => r.delivery === "kakao" && !r.error) && (
                <details className="rounded-md border">
                  <summary className="cursor-pointer p-2 text-sm font-medium bg-green-50">
                    카카오 발송 완료 ({bulkInviteResult.results.filter((r) => r.delivery === "kakao" && !r.error).length}명)
                  </summary>
                  <ul className="space-y-0.5 p-2 text-xs">
                    {bulkInviteResult.results
                      .filter((r) => r.delivery === "kakao" && !r.error)
                      .map((r) => (
                        <li key={r.user_id}>{r.name}</li>
                      ))}
                  </ul>
                </details>
              )}

              {/* 실패 (접힘) */}
              {bulkInviteResult.results.some((r) => r.error) && (
                <details className="rounded-md border">
                  <summary className="cursor-pointer p-2 text-sm font-medium bg-red-50">
                    실패 ({bulkInviteResult.results.filter((r) => r.error).length}명)
                  </summary>
                  <ul className="space-y-0.5 p-2 text-xs">
                    {bulkInviteResult.results
                      .filter((r) => r.error)
                      .map((r) => (
                        <li key={r.user_id}>
                          <span className="font-medium">{r.name}</span>: {r.error}
                        </li>
                      ))}
                  </ul>
                </details>
              )}

              <p className="text-xs text-muted-foreground">
                이 창을 닫으면 수동 전달용 링크를 다시 볼 수 없습니다. 먼저 복사하세요.
              </p>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* 초대 발송 결과 다이얼로그 (manual fallback 시 setup_url 노출) */}
      <Dialog
        open={!!inviteDialog}
        onOpenChange={(open) => {
          if (!open) {
            setInviteDialog(null)
            setInviteCopied(false)
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>초대 링크 (수동 전달)</DialogTitle>
          </DialogHeader>
          {inviteDialog && (
            <div className="space-y-3">
              {inviteDialog.error ? (
                <p className="text-sm text-amber-700">
                  카카오 발송 실패 — {inviteDialog.error}. 아래 링크를 다른 채널로 전달해주세요.
                </p>
              ) : (
                <p className="text-sm">
                  <strong>{inviteDialog.userName}</strong>은 카카오 매칭이 안 되어 있습니다.
                  아래 링크를 SMS·이메일 등 별도 채널로 전달해주세요.
                </p>
              )}
              <div className="flex items-center gap-2 rounded-md border bg-muted p-2">
                <code className="flex-1 break-all font-mono text-xs">
                  {inviteDialog.setupUrl}
                </code>
                <Button size="sm" variant="outline" onClick={handleCopyInviteUrl}>
                  {inviteCopied ? "복사됨" : "복사"}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                만료: {new Date(inviteDialog.expiresAt).toLocaleString("ko-KR")}.
                72시간 내 사용자가 링크에서 직접 비밀번호를 설정해야 합니다.
                이 창을 닫으면 같은 링크를 다시 볼 수 없습니다.
              </p>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* 사용자 수정 다이얼로그 */}
      <Dialog open={!!editTarget} onOpenChange={(open) => !open && setEditTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>사용자 수정</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleEdit} className="space-y-4">
            <div className="space-y-2">
              <Label>이름</Label>
              <Input
                value={editData.name}
                onChange={(e) => setEditData({ ...editData, name: e.target.value })}
                required
              />
            </div>
            <div className="space-y-2">
              <Label>역할</Label>
              <select
                className="w-full rounded-md border px-3 py-2 text-sm"
                value={editData.role}
                onChange={(e) => setEditData({ ...editData, role: e.target.value as UserRole })}
              >
                {ROLE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label>전화번호</Label>
              <Input
                value={editData.phone}
                onChange={(e) => setEditData({ ...editData, phone: e.target.value })}
              />
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="is_active"
                checked={editData.is_active}
                onChange={(e) => setEditData({ ...editData, is_active: e.target.checked })}
              />
              <Label htmlFor="is_active">활성 상태</Label>
            </div>
            <Button type="submit" className="w-full" loading={submitting} loadingText="저장 중...">
              저장
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      {/* 카카오 친구 매칭 다이얼로그 */}
      <Dialog open={!!matchTarget} onOpenChange={(open) => !open && setMatchTarget(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {matchTarget?.name}님과 매칭할 카카오 친구 선택
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              placeholder="닉네임으로 검색..."
              value={friendSearch}
              onChange={(e) => setFriendSearch(e.target.value)}
            />
            <div className="max-h-[400px] overflow-y-auto rounded-md border">
              {isFetchingFriends ? (
                <div className="p-8 text-center text-sm text-muted-foreground">
                  친구 목록을 불러오는 중...
                </div>
              ) : filteredFriends.length === 0 ? (
                <div className="p-8 text-center text-sm text-muted-foreground">
                  표시할 친구가 없습니다
                </div>
              ) : (
                <ul className="divide-y">
                  {filteredFriends.map((f) => (
                    <li key={f.uuid} className="flex items-center gap-3 p-3">
                      {f.profile_thumbnail_image ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={f.profile_thumbnail_image}
                          alt=""
                          className="h-10 w-10 rounded-full"
                        />
                      ) : (
                        <div className="h-10 w-10 rounded-full bg-gray-200" />
                      )}
                      <div className="flex-1">
                        <p className="font-medium">
                          {f.profile_nickname || "(닉네임 없음)"}
                        </p>
                        {f.matched_user_name && (
                          <p className="text-xs text-muted-foreground">
                            현재 {f.matched_user_name}님과 매칭됨
                          </p>
                        )}
                      </div>
                      <Button size="sm" onClick={() => handleMatch(f.uuid)}>
                        선택
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* 사용자별 카카오 진단 다이얼로그 */}
      <Dialog open={!!diagnosis} onOpenChange={(open) => !open && setDiagnosis(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {diagnosis?.user_name}님 카카오 동의 항목 진단
            </DialogTitle>
          </DialogHeader>
          {diagnosisLoading ? (
            <p className="text-sm text-muted-foreground">확인 중...</p>
          ) : diagnosis ? (
            <div className="space-y-3 text-sm">
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">카카오 로그인:</span>
                {diagnosis.oauth_linked ? <Badge>완료</Badge> : <Badge variant="outline">미완료</Badge>}
              </div>
              {diagnosis.kakao_id && (
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">카카오 ID:</span>
                  <code className="text-xs">{diagnosis.kakao_id}</code>
                </div>
              )}
              {diagnosis.error ? (
                <div className="rounded-md border border-red-200 bg-red-50 p-3 text-red-700">
                  {diagnosis.error}
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">전체 동의 상태:</span>
                    {diagnosis.all_agreed === null ? (
                      <Badge variant="outline">확인 불가</Badge>
                    ) : diagnosis.all_agreed ? (
                      <Badge>모두 동의</Badge>
                    ) : (
                      <Badge variant="destructive">일부 미동의</Badge>
                    )}
                  </div>
                  {diagnosis.missing_scopes.length > 0 && (
                    <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-amber-800">
                      <p className="font-medium">미동의 항목:</p>
                      <p className="text-xs">
                        {diagnosis.missing_scopes.map((s) => SCOPE_LABELS[s] ?? s).join(", ")}
                      </p>
                      <p className="mt-2 text-xs">
                        해당 사용자가 본 서비스에 다시 로그인하여 추가 동의를 진행해야 합니다.
                      </p>
                    </div>
                  )}
                  <div>
                    <p className="mb-2 text-muted-foreground">동의 항목 상세:</p>
                    <div className="flex flex-wrap gap-2">
                      {diagnosis.scopes
                        .filter((s) =>
                          ["profile_nickname", "friends", "talk_message", "account_email"].includes(s.id)
                        )
                        .map((s) => (
                          <Badge
                            key={s.id}
                            variant={s.agreed ? "default" : "outline"}
                            className={s.agreed ? "" : "border-red-300 text-red-700"}
                          >
                            {SCOPE_LABELS[s.id] ?? s.id}: {s.agreed ? "동의" : "미동의"}
                          </Badge>
                        ))}
                    </div>
                  </div>
                </>
              )}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}
