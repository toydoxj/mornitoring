import { create } from "zustand"
import apiClient from "@/lib/api/client"
import { getLoginPath, rememberLoginEntry } from "@/lib/login-entry"
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

interface LoginOptions {
  /** 관리원 전용 로그인 엔드포인트 사용 (관리원이 아니면 403) */
  manager?: boolean
}

interface AuthState {
  user: User | null
  accessToken: string | null
  isLoading: boolean
  login: (
    email: string,
    password: string,
    options?: LoginOptions
  ) => Promise<LoginResult>
  logout: () => void
  fetchMe: (options?: FetchMeOptions) => Promise<void>
}

let fetchMePromise: Promise<void> | null = null

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  accessToken: null,
  isLoading: true,

  login: async (email, password, options = {}) => {
    const formData = new URLSearchParams()
    formData.append("username", email)
    formData.append("password", password)

    const endpoint = options.manager
      ? "/api/auth/manager/login"
      : "/api/auth/login"
    const { data } = await apiClient.post<LoginResponse>(endpoint, formData, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    })
    localStorage.setItem("access_token", data.access_token)
    rememberLoginEntry(Boolean(options.manager))

    // 로그인 후 사용자 정보 가져오기
    const { data: user } = await apiClient.get<User>("/api/auth/me")
    set({ user, accessToken: data.access_token, isLoading: false })

    return { mustChangePassword: data.must_change_password }
  },

  logout: () => {
    const loginPath = getLoginPath()
    localStorage.removeItem("access_token")
    sessionStorage.removeItem("kakao_scope_checked")
    set({ user: null, accessToken: null, isLoading: false })
    window.location.href = loginPath
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
