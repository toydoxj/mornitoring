import axios from "axios"

/** FastAPI detail 파싱. 422는 [{loc, msg, type}] 형태로 온다. */
function extractDetail(data: unknown): string | null {
  if (typeof data === "string") return data.trim() || null
  if (!data || typeof data !== "object") return null

  const detail = (data as { detail?: unknown }).detail
  if (typeof detail === "string") return detail.trim() || null
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) =>
        item !== null && typeof item === "object" && "msg" in item
          ? String((item as { msg: unknown }).msg)
          : String(item)
      )
      .filter((msg) => msg.length > 0)
    return messages.length > 0 ? messages.join(", ") : null
  }
  return null
}

/**
 * 요청 실패 원인을 화면에 그대로 노출할 문구 목록으로 변환.
 *
 * 기존에는 업로드/검증 실패를 모두 "서버 연결을 확인해주세요" 하나로 뭉개서
 * 권한 거부(403) · 검증 거부(400) · 서버 오류(500) · 응답 없음(프로세스 재시작,
 * 네트워크 단절)을 구분할 수 없었다. 원인별로 다음 행동이 다르므로 나눠서 보여준다.
 */
export function describeApiError(
  err: unknown,
  fallback = "요청을 처리하지 못했습니다"
): string[] {
  if (!axios.isAxiosError(err)) {
    const message = err instanceof Error ? err.message : ""
    return [message || fallback]
  }

  const status = err.response?.status
  if (!status) {
    // 응답 자체가 없는 경우 — 서버 프로세스 재시작(메모리 초과 등), 네트워크 단절, CORS 차단
    if (err.code === "ECONNABORTED" || err.code === "ETIMEDOUT") {
      return ["서버 응답이 지연되어 요청이 중단되었습니다. 잠시 후 다시 시도해주세요."]
    }
    return [
      "서버에서 응답이 오지 않았습니다. 잠시 후 다시 시도하고, 반복되면 관리자에게 알려주세요.",
      `상세: ${err.code ?? "NETWORK_ERROR"} (${err.message})`,
    ]
  }

  const detail = extractDetail(err.response?.data)

  if (status === 413) {
    return [detail ?? "파일 크기가 허용 범위를 초과했습니다"]
  }
  if (status >= 500) {
    return [
      `서버 오류가 발생했습니다 (HTTP ${status})`,
      ...(detail ? [`상세: ${detail}`] : []),
      "잠시 후 다시 시도하고, 반복되면 관리자에게 알려주세요.",
    ]
  }
  return [detail ?? `${fallback} (HTTP ${status})`]
}
