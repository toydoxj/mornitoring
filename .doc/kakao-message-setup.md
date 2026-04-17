# 카카오톡 메시지 알림 기능 구현 가이드

> 본 문서는 `검토위원 50명 알림 발송` 기능을 위한 카카오 메시지 API 도입 절차이다.
> 출처: 카카오 데브톡 공식 체크리스트(`devtalk.kakao.com/t/api-api/116052`)와 디벨로퍼스 공식 문서를 직접 수집해 정리.

---

## 1. 사전 결정 사항

### 1.1. API 선택

| API | 용도 | 본 프로젝트 적합성 |
|---|---|---|
| **나에게 보내기** (`/v2/api/talk/memo/default/send`) | 본인에게 발송 | 간사 본인 알림, 테스트용 |
| **친구에게 보내기** (`/v1/api/talk/friends/message/default/send`) | 친구로 등록되고 동의한 사용자에게 발송 | **검토위원 알림 메인 채널** |
| 카카오톡 공유(SDK) | 사용자가 직접 친구 선택 후 발송 | 권한 검수 불필요, 비가입 친구도 OK. 보조 수단 |
| 비즈메시지(알림톡) | 사업자 → 사용자 자동 발송 | 자동 일괄 발송 시 별도 검토 (유료, 별도 계약) |

**결정**: 1차 구현은 "친구에게 보내기" + "나에게 보내기" 조합. 자동 일괄 발송은 검수 반려 가능성이 있으므로, **간사가 수동으로 트리거하는 UX**로 설계한다.

### 1.2. 발송 제한 (권한 승인 후)

- 일간 쿼터: 카카오톡 메시지 전송 30,000건/일
- **발신자당: 100건/일**
- **수신자당: 100건/일**
- **발신자/수신자 pair 당: 20건/일** ← 동일 위원에게 반복 알림 시 주의
- 권한 승인 전(팀멤버 테스트): **30건/일**
- "나에게 보내기": 제한 없음, 검수 불필요

---

## 2. 친구 정보 제공 조건 (중요)

검토위원에게 발송하려면 **양쪽 모두 다음 조건을 만족해야** 한다.

1. 발신자(간사)와 수신자(검토위원) **둘 다** 본 시스템에 카카오 로그인되어 있어야 함
2. 둘 다 **`친구 목록 조회(friends)` + `메시지 전송(talk_message)` 동의항목에 동의**해야 함
3. 둘이 카카오톡에서 서로 친구로 등록되어 있어야 함
4. 위 조건을 만족하지 않은 친구는 친구 목록 API 응답에 **포함되지 않음**

→ 즉, **검토위원 50명 모두 본 시스템에 회원가입 + 동의 + 간사와 카톡 친구**여야 한다.

---

## 3. 구현 단계 (Stage 별)

### Stage A: 카카오 디벨로퍼스 앱 세팅

```
카카오 디벨로퍼스 (https://developers.kakao.com)
└── 내 애플리케이션 > 애플리케이션 추가하기
    ├── 앱 이름: "구조안전 모니터링"
    ├── 사업자명: (조직명)
    └── 카테고리: 비즈니스
```

- **앱 키 4종** 발급 → `backend/.env`에 저장
  - `KAKAO_REST_API_KEY` (서버 → 카카오 API 호출용)
  - `KAKAO_JAVASCRIPT_KEY` (프론트엔드 SDK용, 선택)
  - `KAKAO_NATIVE_APP_KEY` (네이티브, 본 프로젝트는 미사용)
  - `KAKAO_ADMIN_KEY` (어드민 작업용, 절대 노출 금지)

### Stage B: 플랫폼/Redirect URI 등록

- **앱 > 플랫폼 > Web 플랫폼 등록**
  - `http://localhost:3000` (개발)
  - `https://(운영 도메인)` (운영)
- **카카오 로그인 > Redirect URI**
  - `http://localhost:3000/auth/kakao/callback`
  - `https://(운영 도메인)/auth/kakao/callback`

### Stage C: 카카오 로그인 활성화 + 동의항목 설정

`내 애플리케이션 > 제품 설정 > 카카오 로그인` ON

`동의항목` 메뉴에서 다음 항목을 활성화:

| 항목 | 권한 단계 | 검수 전 설정 | 검수 후 설정 |
|---|---|---|---|
| `profile_nickname` (닉네임) | 개인정보 | 필수 동의 | 필수 동의 |
| `account_email` (이메일) | 개인정보 | 선택 동의 | 선택 동의 |
| **`friends`** (서비스 내 친구목록) | 개인정보 | **이용 중 동의만 가능** | 선택/필수 가능 |
| **`talk_message`** (카카오톡 메시지 전송) | 접근권한 | 필수 동의 | 필수 동의 |

> **주의**: `friends`는 검수 전에는 "이용 중 동의"만 가능하다. REST API로 호출 시 `insufficient scopes` 에러가 나면 **추가 항목 동의 받기**(`/oauth/authorize?scope=friends,talk_message`)로 재동의를 받아야 한다.

### Stage D: 백엔드 구현

#### D-1. OAuth2 인증 플로우

```
1. 프론트엔드: GET https://kauth.kakao.com/oauth/authorize
   ?client_id={REST_API_KEY}
   &redirect_uri={REDIRECT_URI}
   &response_type=code
   &scope=profile_nickname,account_email,friends,talk_message

2. 콜백: 카카오 → /auth/kakao/callback?code=xxx

3. 백엔드: POST https://kauth.kakao.com/oauth/token
   - access_token, refresh_token 획득
   - DB(users 테이블)에 토큰 저장 + kakao_id 저장

4. 사용자정보 조회: GET https://kapi.kakao.com/v2/user/me
   - 최초 1회 반드시 호출 → 미호출 시 배치로 연결 해제됨
```

#### D-2. 친구 목록 조회

```
GET https://kapi.kakao.com/v1/api/talk/friends
  Headers: Authorization: Bearer {access_token}
  Query: limit=100, offset=0, order=asc

응답: friends[].uuid 를 DB에 저장 (검토위원 매칭용)
```

#### D-3. 친구에게 메시지 발송

```
POST https://kapi.kakao.com/v1/api/talk/friends/message/default/send
  Headers: Authorization: Bearer {access_token}
  Body (x-www-form-urlencoded):
    receiver_uuids = ["uuid1","uuid2",...]   # 최대 5명 단위 권장
    template_object = {JSON 템플릿}
```

> 자주 겪는 에러:
> - **`failed to parse parameter`** → JSON으로 보내지 말고 반드시 `x-www-form-urlencoded` 사용
> - **`Cannot contain a receiver who is identical to the sender`** → 발신자 본인 UUID는 제외
> - **`given account is not connected to any talk user`** → 카카오톡 미연동 계정 (제외 처리)
> - **`insufficient scopes`** → 추가 항목 동의 필요

### Stage E: 메시지 템플릿 등록

`디벨로퍼스 > 메시지 > 메시지 템플릿 빌더`에서 사전 등록:

| 템플릿 ID | 용도 | 변수 |
|---|---|---|
| `T001_assign` | 배정 알림 | 위원명, 건축물명, 마감일 |
| `T002_resubmit` | N차 보완 요청 | 위원명, 차수, 부적합 사유 |
| `T003_complete` | 검토 완료 | 위원명, 건축물명 |
| `T004_reminder` | 마감 임박 | 위원명, 잔여 일수 |

→ 사용자 정의 템플릿 ID로 호출 시 `template_id` 파라미터 사용.

### Stage F: 권한 검수 신청

다음을 모두 완료하고 신청:

1. **비즈앱 전환**: `앱 > 일반 > 비즈니스 정보 > 사업자 정보 등록`
   - 사업자등록증 업로드 (개인 개발자는 별도 FAQ 절차)
2. **팀멤버에 개발자/간사 1명 등록**해서 실제 동작 영상/캡처 확보
3. **`앱 > 추가 기능 신청 > 카카오톡 친구/메시지`** → "신청"
   - 첨부: 동작 영상(30초 내외), 사용 목적서, 화면 설계
   - 두 권한(친구목록 + 메시지)을 **함께 신청 가능**
4. 심사 결과는 팀멤버 이메일로 통보 (영업일 3~7일)

---

## 4. 구현 체크리스트

### 단계 1: 카카오 디벨로퍼스 세팅
- [ ] 카카오 디벨로퍼스 앱 생성
- [ ] REST API Key를 `backend/.env`의 `KAKAO_REST_API_KEY`에 저장
- [ ] Web 플랫폼에 `localhost:3000` + 운영 도메인 등록
- [ ] Redirect URI 2종 등록(개발/운영)
- [ ] 카카오 로그인 활성화 ON

### 단계 2: 동의항목 설정
- [ ] `profile_nickname` 필수 동의 설정
- [ ] `account_email` 선택 동의 설정
- [ ] `friends` 이용 중 동의 활성화 (검수 전)
- [ ] `talk_message` 필수 동의 설정

### 단계 3: 백엔드 구현
- [ ] `routers/auth.py`에 `/auth/kakao/login`, `/auth/kakao/callback` 라우트 추가
- [ ] `models/User`에 `kakao_id`, `kakao_access_token`, `kakao_refresh_token`, `kakao_uuid` 컬럼 추가 (마이그레이션)
- [ ] `engines/kakao_client.py` 신규: 토큰 발급/갱신, 사용자정보 조회, 친구목록 조회, 메시지 발송 함수
- [ ] 토큰 만료 시 자동 갱신 로직 (`refresh_token`으로 재발급)
- [ ] 사용자정보 조회 API를 **로그인 직후 1회 반드시 호출** (연결 유지)
- [ ] 메시지 발송은 **반드시 `application/x-www-form-urlencoded`** 로 전송
- [ ] 발신자 본인 UUID 제외 로직
- [ ] `given account is not connected` 에러 시 해당 수신자 스킵 + 로그
- [ ] pair 당 20건/일 카운터 (DB에 일별 발송 이력 테이블)

### 단계 4: 프론트엔드 구현
- [ ] 로그인 페이지에 "카카오로 로그인" 버튼 추가
- [ ] 검토위원 매칭 화면: 친구 목록 → 검토위원과 매칭 (kakao_uuid 저장)
- [ ] 알림 발송 화면: 수신자 다중 선택 + 템플릿 선택 + 미리보기 + **수동 "발송" 버튼**
- [ ] 발송 결과 토스트 (성공/실패 수신자 분리 표시)

### 단계 5: 메시지 템플릿
- [ ] 디벨로퍼스 콘솔에서 4개 템플릿 등록(`T001`~`T004`)
- [ ] 백엔드에 `TEMPLATE_IDS` 상수 정의

### 단계 6: 검수 전 테스트
- [ ] 팀멤버에 본인 + 동료 1명 등록
- [ ] "나에게 보내기"로 발송 동작 확인
- [ ] 팀멤버 간 "친구에게 보내기" 발송 동작 확인
- [ ] 동영상 또는 캡처 5장 이상 확보 (검수 제출용)

### 단계 7: 권한 검수
- [ ] 사업자 정보 등록 → 비즈앱 전환 완료
- [ ] `추가 기능 신청 > 카카오톡 친구/메시지`에서 친구목록 + 메시지 권한 함께 신청
- [ ] 동작 영상 + 사용 목적서 첨부
- [ ] 심사 통과 확인 (이메일 수신)

### 단계 8: 운영 전환
- [ ] 운영 도메인 Redirect URI 추가
- [ ] `friends` 동의항목을 "선택 동의"로 변경 (전체 사용자 대상 가능)
- [ ] 검토위원 50명에게 회원가입 + 동의 + 카카오톡 친구 추가 안내
- [ ] pair 당 20건/일 제한 모니터링 대시보드

---

## 5. 알아두면 좋은 함정

### 5.1. 토큰 자동 해제 (KOE006 등)
- 액세스 토큰만 받고 **사용자정보 조회 API를 한 번도 안 호출**하면 카카오 배치가 정기적으로 **연결을 끊는다**.
- → 로그인 직후 `/v2/user/me` 1회 호출은 필수.

### 5.2. UUID 사용 규칙
- `receiver_uuids`는 **반드시 친구 목록 API에서 받은 UUID**여야 함
- 다른 디벨로퍼스 앱에서 받은 UUID는 사용 불가 (앱마다 UUID가 다름)

### 5.3. 자동 발송 정책 위반
- 사용자가 직접 트리거하지 않은 자동 발송은 검수 반려 사유.
- 본 프로젝트는 "간사가 발송 버튼 클릭"이라는 명시적 트리거가 있으므로 OK.
- **마감일 자동 리마인더(크론)는 검수 시 별도 설명 필요** → 위험하면 알림톡(비즈메시지)로 분리.

### 5.4. 50명 동시 발송 시
- 친구에게 보내기는 한 번에 최대 5명까지 권장.
- 50명 발송 시 10회 분할 호출 + 사이에 짧은 sleep 권장.
- 일별 pair 20건 제한이 있으므로 같은 위원에게 하루 21번째 발송은 실패.

---

## 6. 참고 링크

| 자료 | URL |
|---|---|
| 종합 체크리스트 (가장 중요) | https://devtalk.kakao.com/t/api-api/116052 |
| 메시지 API 권한 신청 방법 | https://devtalk.kakao.com/t/api-how-to-request-permission-for-messaging-api/80421 |
| 친구 API 권한 신청 방법 | https://devtalk.kakao.com/t/api-how-to-request-permission-for-the-retrieving-list-of-friends-api/56783 |
| 비즈앱 전환 방법 | https://devtalk.kakao.com/t/topic/56132 |
| 자주 겪는 에러 FAQ | https://devtalk.kakao.com/t/faq-api-api/82152 |
| 쿼터 정책 | https://developers.kakao.com/docs/latest/ko/getting-started/quota |
| Next.js 예제 코드 | https://devtalk.kakao.com/t/rest-api-next-js/142181 |
| Python(Flask) 예제 코드 | https://devtalk.kakao.com/t/rest-api-python-flask/134383 |
| REST API 공식 문서 (메시지) | https://developers.kakao.com/docs/latest/ko/kakaotalk-message/rest-api |
| REST API 공식 문서 (친구목록) | https://developers.kakao.com/docs/latest/ko/kakaotalk-social/rest-api#get-friends |
