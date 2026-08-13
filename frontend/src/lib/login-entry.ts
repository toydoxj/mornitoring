/** 마지막 로그인 진입점 기억.
 *
 * 관리원은 카카오 없이 이메일 로그인(/manager-login)으로 들어오므로,
 * 로그아웃·세션 만료 시 카카오 로그인 화면(/login)으로 보내면 다시 들어올 수 없다.
 * 진입점을 남겨 두고 되돌아갈 경로를 결정한다.
 */

const STORAGE_KEY = "login_entry"
const MANAGER_ENTRY = "manager"

export const MANAGER_LOGIN_PATH = "/manager-login"
export const DEFAULT_LOGIN_PATH = "/login"

export function rememberLoginEntry(manager: boolean) {
  if (typeof window === "undefined") return
  if (manager) {
    localStorage.setItem(STORAGE_KEY, MANAGER_ENTRY)
  } else {
    localStorage.removeItem(STORAGE_KEY)
  }
}

/** 로그아웃/401 시 돌아갈 로그인 경로 */
export function getLoginPath(): string {
  if (typeof window === "undefined") return DEFAULT_LOGIN_PATH
  return localStorage.getItem(STORAGE_KEY) === MANAGER_ENTRY
    ? MANAGER_LOGIN_PATH
    : DEFAULT_LOGIN_PATH
}

export function clearLoginEntry() {
  if (typeof window === "undefined") return
  localStorage.removeItem(STORAGE_KEY)
}
