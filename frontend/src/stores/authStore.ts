import { create } from "zustand"
import apiClient from "@/lib/api/client"
import type { User } from "@/types"

interface AuthState {
  user: User | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  fetchMe: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoading: true,

  login: async (email, password) => {
    const formData = new URLSearchParams()
    formData.append("username", email)
    formData.append("password", password)

    const { data } = await apiClient.post("/api/auth/login", formData, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    })
    localStorage.setItem("access_token", data.access_token)

    // 로그인 후 사용자 정보 가져오기
    const { data: user } = await apiClient.get("/api/auth/me")
    set({ user })
  },

  logout: () => {
    localStorage.removeItem("access_token")
    set({ user: null })
    window.location.href = "/login"
  },

  fetchMe: async () => {
    try {
      const token = localStorage.getItem("access_token")
      if (!token) {
        set({ user: null, isLoading: false })
        return
      }
      const { data } = await apiClient.get("/api/auth/me")
      set({ user: data, isLoading: false })
    } catch {
      set({ user: null, isLoading: false })
    }
  },
}))
