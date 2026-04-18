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
import type { User, UserRole } from "@/types"
import { ROLE_LABELS } from "@/types"

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
      const { data } = await apiClient.post("/api/users/import-excel", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      setBulkResult(data)
      fetchUsers()
    } catch {
      setBulkResult({ created: 0, skipped: 0 })
    } finally {
      setBulkUploading(false)
      e.target.value = ""
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
            전체 {total}명 · 카카오 로그인 {linkedCount}명 · 친구 매칭 {matchedCount}명
          </p>
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

      {/* 사용자 목록 */}
      <div className="rounded-md border bg-white overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[60px]">ID</TableHead>
              <TableHead>이름</TableHead>
              <TableHead>이메일</TableHead>
              <TableHead className="w-[100px]">역할</TableHead>
              <TableHead className="w-[120px]">전화번호</TableHead>
              <TableHead className="w-[100px] text-center">카카오 로그인</TableHead>
              <TableHead className="w-[100px] text-center">친구 매칭</TableHead>
              <TableHead className="w-[80px] text-center">상태</TableHead>
              <TableHead className="w-[260px] text-center">관리</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={9} className="h-32 text-center">
                  로딩 중...
                </TableCell>
              </TableRow>
            ) : users.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} className="h-32 text-center text-muted-foreground">
                  등록된 사용자가 없습니다
                </TableCell>
              </TableRow>
            ) : (
              users.map((user) => (
                <TableRow key={user.id}>
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
