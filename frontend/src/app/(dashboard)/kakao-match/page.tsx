"use client"

import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
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
import { useAuthStore } from "@/stores/authStore"

type UserRole = "team_leader" | "chief_secretary" | "secretary" | "reviewer"

interface UserStatus {
  user_id: number
  name: string
  email: string
  role: UserRole
  kakao_oauth_linked: boolean
  kakao_linked: boolean
  kakao_uuid: string | null
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

const ROLE_LABELS: Record<UserRole, string> = {
  team_leader: "팀장",
  chief_secretary: "총괄간사",
  secretary: "간사",
  reviewer: "검토위원",
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

const SCOPE_LABELS: Record<string, string> = {
  profile_nickname: "닉네임",
  friends: "카카오톡 친구 목록",
  talk_message: "카카오톡 메시지 전송",
  account_email: "이메일",
}

export default function KakaoMatchPage() {
  const currentUser = useAuthStore((s) => s.user)
  const [users, setUsers] = useState<UserStatus[]>([])
  const [friends, setFriends] = useState<KakaoFriend[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isFetchingFriends, setIsFetchingFriends] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedUser, setSelectedUser] = useState<UserStatus | null>(null)
  const [search, setSearch] = useState("")
  const [scopeStatus, setScopeStatus] = useState<ScopeStatus | null>(null)
  const [diagnosis, setDiagnosis] = useState<UserScopeDiagnosis | null>(null)
  const [diagnosisLoading, setDiagnosisLoading] = useState(false)

  const fetchUsers = async () => {
    try {
      const { data } = await apiClient.get<UserStatus[]>("/api/kakao/reviewers")
      setUsers(data)
    } catch (err) {
      console.error("사용자 조회 실패:", err)
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
    setError(null)
    try {
      const { data } = await apiClient.get<{ items: KakaoFriend[] }>("/api/kakao/friends")
      setFriends(data.items)
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "친구 목록 조회 실패. 카카오 로그인 또는 권한을 확인해주세요."
      setError(msg)
    } finally {
      setIsFetchingFriends(false)
    }
  }

  useEffect(() => {
    fetchUsers()
    fetchScopeStatus()
  }, [])

  const handleOpenMatch = (user: UserStatus) => {
    setSelectedUser(user)
    setSearch("")
    if (friends.length === 0) {
      fetchFriends()
    }
  }

  const handleMatch = async (uuid: string) => {
    if (!selectedUser) return
    try {
      await apiClient.post("/api/kakao/match", {
        user_id: selectedUser.user_id,
        kakao_uuid: uuid,
      })
      setSelectedUser(null)
      await Promise.all([fetchUsers(), fetchFriends()])
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "매칭 실패"
      alert(msg)
    }
  }

  const handleDiagnose = async (user: UserStatus) => {
    setDiagnosisLoading(true)
    setDiagnosis({
      user_id: user.user_id,
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
        `/api/kakao/user/${user.user_id}/scopes`
      )
      setDiagnosis(data)
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "진단 실패"
      setDiagnosis({
        user_id: user.user_id,
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

  const handleUnmatch = async (userId: number) => {
    if (!confirm("매칭을 해제하시겠습니까?")) return
    try {
      await apiClient.delete(`/api/kakao/match/${userId}`)
      await Promise.all([fetchUsers(), fetchFriends()])
    } catch (err) {
      console.error("해제 실패:", err)
    }
  }

  const matchedCount = users.filter((r) => r.kakao_linked).length
  const oauthLinkedCount = users.filter((r) => r.kakao_oauth_linked).length

  const filteredFriends = friends.filter((f) => {
    const nick = (f.profile_nickname ?? "").toLowerCase()
    return nick.includes(search.toLowerCase())
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">카카오 친구 매칭</h1>
          <p className="text-sm text-muted-foreground">
            전체 {users.length}명 · 카카오 로그인 {oauthLinkedCount}명 · 매칭 {matchedCount}명
          </p>
        </div>
        <Button onClick={fetchFriends} disabled={isFetchingFriends}>
          {isFetchingFriends ? "로딩 중..." : "친구 목록 새로고침"}
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

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
                <p className="font-medium">카카오 계정이 연동되어 있지 않습니다. 먼저 카카오 로그인을 진행해주세요.</p>
              ) : scopeStatus.all_agreed ? (
                <p className="font-medium">필수 동의 항목이 모두 활성화되었습니다.</p>
              ) : (
                <>
                  <p className="font-medium">
                    추가 동의가 필요합니다:
                    {" "}
                    {scopeStatus.missing_scopes.map((s) => SCOPE_LABELS[s] ?? s).join(", ")}
                  </p>
                  <p className="text-xs">
                    아래 버튼을 눌러 카카오 추가 동의를 받아주세요. 친구 목록/메시지 발송을 사용하려면 모두 동의해야 합니다.
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
                variant="default"
                onClick={() => {
                  window.location.href = scopeStatus.reauthorize_url!
                }}
              >
                추가 동의받기
              </Button>
            )}
          </div>
        </div>
      )}

      <div className="rounded-md border bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[60px]">ID</TableHead>
              <TableHead>이름</TableHead>
              <TableHead className="w-[100px]">역할</TableHead>
              <TableHead>이메일</TableHead>
              <TableHead className="w-[120px]">카카오 로그인</TableHead>
              <TableHead className="w-[120px]">친구 매칭</TableHead>
              <TableHead className="w-[260px]">작업</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7} className="h-32 text-center">
                  로딩 중...
                </TableCell>
              </TableRow>
            ) : users.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="h-32 text-center text-muted-foreground">
                  사용자가 없습니다
                </TableCell>
              </TableRow>
            ) : (
              users.map((r) => {
                const isSelf = currentUser?.id === r.user_id
                return (
                <TableRow key={r.user_id}>
                  <TableCell>{r.user_id}</TableCell>
                  <TableCell className="font-medium">
                    {r.name}
                    {isSelf && <span className="ml-2 text-xs text-muted-foreground">(본인)</span>}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{ROLE_LABELS[r.role]}</Badge>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{r.email}</TableCell>
                  <TableCell>
                    {r.kakao_oauth_linked ? (
                      <Badge>완료</Badge>
                    ) : (
                      <Badge variant="outline">미완료</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {isSelf ? (
                      <Badge variant="secondary">자동 처리</Badge>
                    ) : r.kakao_linked ? (
                      <Badge>매칭됨</Badge>
                    ) : (
                      <Badge variant="outline">미매칭</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {isSelf ? (
                      <span className="text-xs text-muted-foreground">나에게 보내기 자동 사용</span>
                    ) : (
                    <div className="flex gap-2">
                      <Button size="sm" variant="outline" onClick={() => handleOpenMatch(r)}>
                        {r.kakao_linked ? "변경" : "매칭"}
                      </Button>
                      {r.kakao_linked && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleUnmatch(r.user_id)}
                        >
                          해제
                        </Button>
                      )}
                      {r.kakao_oauth_linked && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleDiagnose(r)}
                        >
                          진단
                        </Button>
                      )}
                    </div>
                    )}
                  </TableCell>
                </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={!!selectedUser} onOpenChange={(open) => !open && setSelectedUser(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {selectedUser?.name}님과 매칭할 카카오 친구 선택
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              placeholder="닉네임으로 검색..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
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
                {diagnosis.oauth_linked ? (
                  <Badge>완료</Badge>
                ) : (
                  <Badge variant="outline">미완료</Badge>
                )}
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
                        {diagnosis.missing_scopes
                          .map((s) => SCOPE_LABELS[s] ?? s)
                          .join(", ")}
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
                          [
                            "profile_nickname",
                            "friends",
                            "talk_message",
                            "account_email",
                          ].includes(s.id)
                        )
                        .map((s) => (
                          <Badge
                            key={s.id}
                            variant={s.agreed ? "default" : "outline"}
                            className={s.agreed ? "" : "border-red-300 text-red-700"}
                          >
                            {SCOPE_LABELS[s.id] ?? s.id}:{" "}
                            {s.agreed ? "동의" : "미동의"}
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
