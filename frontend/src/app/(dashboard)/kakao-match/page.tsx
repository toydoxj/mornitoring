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

interface ReviewerStatus {
  user_id: number
  name: string
  email: string
  kakao_linked: boolean
  kakao_uuid: string | null
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
  const [reviewers, setReviewers] = useState<ReviewerStatus[]>([])
  const [friends, setFriends] = useState<KakaoFriend[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isFetchingFriends, setIsFetchingFriends] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedReviewer, setSelectedReviewer] = useState<ReviewerStatus | null>(null)
  const [search, setSearch] = useState("")
  const [scopeStatus, setScopeStatus] = useState<ScopeStatus | null>(null)

  const fetchReviewers = async () => {
    try {
      const { data } = await apiClient.get<ReviewerStatus[]>("/api/kakao/reviewers")
      setReviewers(data)
    } catch (err) {
      console.error("검토위원 조회 실패:", err)
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
    fetchReviewers()
    fetchScopeStatus()
  }, [])

  const handleOpenMatch = (reviewer: ReviewerStatus) => {
    setSelectedReviewer(reviewer)
    setSearch("")
    if (friends.length === 0) {
      fetchFriends()
    }
  }

  const handleMatch = async (uuid: string) => {
    if (!selectedReviewer) return
    try {
      await apiClient.post("/api/kakao/match", {
        user_id: selectedReviewer.user_id,
        kakao_uuid: uuid,
      })
      setSelectedReviewer(null)
      await Promise.all([fetchReviewers(), fetchFriends()])
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
      await Promise.all([fetchReviewers(), fetchFriends()])
    } catch (err) {
      console.error("해제 실패:", err)
    }
  }

  const matchedCount = reviewers.filter((r) => r.kakao_linked).length

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
            검토위원 {reviewers.length}명 중 {matchedCount}명 매칭됨
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
              <TableHead>이메일</TableHead>
              <TableHead className="w-[120px]">매칭 상태</TableHead>
              <TableHead className="w-[200px]">작업</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={5} className="h-32 text-center">
                  로딩 중...
                </TableCell>
              </TableRow>
            ) : reviewers.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="h-32 text-center text-muted-foreground">
                  검토위원이 없습니다
                </TableCell>
              </TableRow>
            ) : (
              reviewers.map((r) => (
                <TableRow key={r.user_id}>
                  <TableCell>{r.user_id}</TableCell>
                  <TableCell className="font-medium">{r.name}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">{r.email}</TableCell>
                  <TableCell>
                    {r.kakao_linked ? (
                      <Badge>매칭됨</Badge>
                    ) : (
                      <Badge variant="outline">미매칭</Badge>
                    )}
                  </TableCell>
                  <TableCell>
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
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={!!selectedReviewer} onOpenChange={(open) => !open && setSelectedReviewer(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {selectedReviewer?.name}님과 매칭할 카카오 친구 선택
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
    </div>
  )
}
