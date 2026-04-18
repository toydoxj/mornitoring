import axios from "axios"

const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  headers: { "Content-Type": "application/json" },
})

// 요청 인터셉터: JWT 토큰 자동 첨부
apiClient.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token")
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

// 응답 인터셉터: 401 시 로그인 페이지로 리다이렉트.
// race 방지: 여러 요청이 동시에 401을 받아도 logout/redirect는 한 번만.
// 또한 비인증 엔드포인트(/login, /password-setup, /kakao/callback 등)의 401은
// 운영 흐름의 정상 분기(잘못된 비번, 만료된 링크 등)이므로 강제 redirect 제외.
let _handlingAuthError = false
const AUTH_REDIRECT_EXEMPT_PATHS = [
  "/api/auth/login",
  "/api/auth/kakao/callback",
  "/api/auth/link-account",
  "/api/auth/password-setup",
  "/api/auth/password-setup/validate",
]

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && typeof window !== "undefined") {
      const url: string = error.config?.url ?? ""
      const isExempt = AUTH_REDIRECT_EXEMPT_PATHS.some((p) => url.includes(p))
      if (!isExempt && !_handlingAuthError) {
        _handlingAuthError = true
        localStorage.removeItem("access_token")
        // setTimeout 0으로 미루어 Promise.reject가 caller에 먼저 도달
        setTimeout(() => {
          window.location.href = "/login"
        }, 0)
      }
    }
    return Promise.reject(error)
  }
)

export default apiClient
