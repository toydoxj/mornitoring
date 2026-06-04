import { create } from "zustand"
import apiClient from "@/lib/api/client"
import type { User } from "@/types"

interface LoginResult {
  mustChangePassword: boolean
}

interface LoginResponse {
  access_token: string
  must_change_password: boolean
}

interface FetchMeOptions {
  force?: boolean
}

interface AuthState {
  user: User | null
  accessToken: string | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<LoginResult>
  logout: () => void
  fetchMe: (options?: FetchMeOptions) => Promise<void>
}

let fetchMePromise: Promise<void> | null = null

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  accessToken: null,
  isLoading: true,

  login: async (email, password) => {
    const formData = new URLSearchParams()
    formData.append("username", email)
    formData.append("password", password)

    const { data } = await apiClient.post<LoginResponse>("/api/auth/login", formData, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    })
    localStorage.setItem("access_token", data.access_token)

    // 로그인 후 사용자 정보 가져오기
    const { data: user } = await apiClient.get<User>("/api/auth/me")
    set({ user, accessToken: data.access_token, isLoading: false })

    return { mustChangePassword: data.must_change_password }
  },

  logout: () => {
    localStorage.removeItem("access_token")
    sessionStorage.removeItem("kakao_scope_checked")
    set({ user: null, accessToken: null, isLoading: false })
    window.location.href = "/login"
  },

  fetchMe: async (options = {}) => {
    const token = localStorage.getItem("access_token")
    if (!token) {
      set({ user: null, accessToken: null, isLoading: false })
      return
    }

    const state = get()
    if (!options.force && state.user && state.accessToken === token) {
      set({ isLoading: false })
      return
    }

    if (!options.force && fetchMePromise) {
      await fetchMePromise
      return
    }

    fetchMePromise = (async () => {
      try {
        const { data } = await apiClient.get<User>("/api/auth/me")
        set({ user: data, accessToken: token, isLoading: false })
      } catch {
        set({ user: null, accessToken: null, isLoading: false })
      }
    })()

    try {
      await fetchMePromise
    } finally {
      fetchMePromise = null
    }
  },
}))
