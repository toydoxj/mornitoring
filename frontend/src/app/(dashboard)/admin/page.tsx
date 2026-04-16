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

const ROLE_OPTIONS: { value: UserRole; label: string }[] = [
  { value: "team_leader", label: "팀장" },
  { value: "chief_secretary", label: "총괄간사" },
  { value: "secretary", label: "간사" },
  { value: "reviewer", label: "검토위원" },
]

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
    password: "",
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")

  // 수정 다이얼로그
  const [editTarget, setEditTarget] = useState<User | null>(null)
  const [editData, setEditData] = useState({
    name: "",
    phone: "",
    role: "reviewer" as UserRole,
    is_active: true,
  })

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

  useEffect(() => {
    fetchUsers()
  }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError("")
    try {
      await apiClient.post("/api/users", formData)
      setCreateOpen(false)
      setFormData({ name: "", email: "", role: "reviewer", phone: "", password: "" })
      fetchUsers()
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

  const openEdit = (user: User) => {
    setEditTarget(user)
    setEditData({
      name: user.name,
      phone: user.phone || "",
      role: user.role,
      is_active: user.is_active,
    })
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">사용자 관리</h1>
          <p className="text-sm text-muted-foreground">총 {total}명</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>사용자 등록</Button>
      </div>

      {/* 사용자 목록 */}
      <div className="rounded-md border bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[60px]">ID</TableHead>
              <TableHead>이름</TableHead>
              <TableHead>이메일</TableHead>
              <TableHead className="w-[100px]">역할</TableHead>
              <TableHead className="w-[120px]">전화번호</TableHead>
              <TableHead className="w-[80px]">상태</TableHead>
              <TableHead className="w-[140px]">관리</TableHead>
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
                  <TableCell>
                    <Badge variant={user.is_active ? "default" : "secondary"}>
                      {user.is_active ? "활성" : "비활성"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button size="sm" variant="outline" onClick={() => openEdit(user)}>
                        수정
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
            <div className="space-y-2">
              <Label>비밀번호</Label>
              <Input
                type="password"
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                required
              />
            </div>
            {error && <p className="text-sm text-red-500">{error}</p>}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "등록 중..." : "등록"}
            </Button>
          </form>
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
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "저장 중..." : "저장"}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
