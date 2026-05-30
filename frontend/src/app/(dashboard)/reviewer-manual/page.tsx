import Link from "next/link"
import type { LucideIcon } from "lucide-react"
import {
  AlertTriangle,
  Bell,
  BookOpenCheck,
  CheckCircle2,
  ClipboardList,
  FileSpreadsheet,
  HelpCircle,
  MessageSquare,
  UploadCloud,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"

interface ManualStep {
  step: string
  title: string
  description: string
  details: string[]
  icon: LucideIcon
}

interface GuideSection {
  title: string
  description: string
  items: string[]
  icon: LucideIcon
}

interface FaqItem {
  question: string
  answer: string
}

const workflowSteps: ManualStep[] = [
  {
    step: "1",
    title: "로그인과 알림 확인",
    description: "초대받은 계정으로 로그인한 뒤 카카오 알림 연동 상태를 확인합니다.",
    details: [
      "카카오 연동 안내 배너가 보이면 버튼을 눌러 동의를 완료합니다.",
      "알림이 오지 않으면 카카오 연동과 추가 동의 상태를 먼저 확인합니다.",
    ],
    icon: Bell,
  },
  {
    step: "2",
    title: "공지사항과 토론방 확인",
    description: "검토 기준, 제출 일정, 공유 이슈가 올라와 있는지 먼저 확인합니다.",
    details: [
      "새 공지는 업무 변경 사항일 수 있으므로 검토 시작 전에 확인합니다.",
      "토론방에는 여러 검토위원이 함께 참고할 수 있는 공통 논의가 등록됩니다.",
    ],
    icon: MessageSquare,
  },
  {
    step: "3",
    title: "내 검토 대상 조회",
    description: "상단 메뉴의 내 검토 대상에서 배정된 건축물을 확인합니다.",
    details: [
      "관리번호, 주소, 현재 단계, 최근 판정, 제출 예정일을 함께 확인합니다.",
      "관리번호를 누르면 건축물 기본정보와 검토 진행 현황을 볼 수 있습니다.",
    ],
    icon: ClipboardList,
  },
  {
    step: "4",
    title: "검토서 업로드",
    description: "검토가 끝나면 해당 행의 업로드 버튼으로 검토서 파일을 제출합니다.",
    details: [
      ".xlsm 파일만 업로드할 수 있으며 파일명은 관리번호로 시작해야 합니다.",
      "업로드 전 미리보기 검증 결과를 확인하고, 문제가 없을 때 최종 업로드합니다.",
    ],
    icon: UploadCloud,
  },
  {
    step: "5",
    title: "문의 등록",
    description: "검토서 제출 전 확인이 필요한 사항은 문의 버튼으로 남깁니다.",
    details: [
      "관리번호별 문의가 저장되어 간사와 이력을 함께 확인할 수 있습니다.",
      "도면, 산정 근거, 단계 판단처럼 처리가 멈추는 사유를 구체적으로 작성합니다.",
    ],
    icon: HelpCircle,
  },
]

const guideSections: GuideSection[] = [
  {
    title: "대시보드",
    description: "내 업무의 시작점입니다.",
    items: [
      "내 검토 대상 건수와 제출 일정 현황을 확인합니다.",
      "내가 받은 카카오 알림, 공지사항, 토론방 최신 글을 빠르게 확인합니다.",
    ],
    icon: BookOpenCheck,
  },
  {
    title: "내 검토 대상",
    description: "검토위원이 가장 자주 사용하는 화면입니다.",
    items: [
      "현재 단계가 예비검토인지 보완검토인지 확인합니다.",
      "제출 예정일이 임박했거나 지난 건을 우선 처리합니다.",
      "검토 완료 후 업로드 버튼으로 검토서를 제출합니다.",
    ],
    icon: ClipboardList,
  },
  {
    title: "건축물 상세",
    description: "관리번호를 눌렀을 때 열리는 상세 화면입니다.",
    items: [
      "기본정보, 고위험군 여부, 검토 진행 타임라인을 확인합니다.",
      "이전 단계 검토 의견과 판정 이력을 참고합니다.",
      "해당 건축물 문의 이력을 확인해 중복 질의를 줄입니다.",
    ],
    icon: CheckCircle2,
  },
  {
    title: "검토서 업로드 창",
    description: "파일 검증과 최종 제출을 나누어 처리합니다.",
    items: [
      "파일을 선택하거나 드래그하면 먼저 미리보기 검증이 실행됩니다.",
      "검증 오류가 있으면 메시지를 확인한 뒤 파일을 수정해서 다시 선택합니다.",
      "부적정 사례 검토가 필요하면 최종 업로드 전에 체크합니다.",
    ],
    icon: FileSpreadsheet,
  },
]

const cautions = [
  "이미 제출된 단계에서 재업로드하면 기존 검토서 파일이 삭제되고 새 파일로 대체됩니다.",
  "부적정 사례 검토 필요로 등록된 건은 이후 화면에서 임의로 해제할 수 없습니다.",
  "검토서의 관리번호와 시스템의 관리번호가 다르면 업로드 검증에 실패할 수 있습니다.",
  "검토 대상이 목록에 보이지 않으면 배정 여부를 간사에게 먼저 확인합니다.",
]

const faqs: FaqItem[] = [
  {
    question: "검토 대상이 보이지 않으면 어떻게 하나요?",
    answer: "내 검토 대상은 본인에게 배정된 건만 표시됩니다. 배정 누락 또는 이름 매칭 문제일 수 있으니 담당 간사에게 관리번호와 함께 확인을 요청하세요.",
  },
  {
    question: "검토서 검증이 실패했습니다.",
    answer: "파일 확장자, 파일명 관리번호, 검토서 양식, 필수 입력값을 먼저 확인하세요. 오류 메시지가 특정 항목을 알려주면 그 내용을 수정한 뒤 다시 업로드합니다.",
  },
  {
    question: "검토 중 질문이 생겼습니다.",
    answer: "내 검토 대상 목록의 문의 버튼이나 건축물 상세 화면의 문의사항 영역을 사용하세요. 질문에는 관리번호, 현재 단계, 확인이 필요한 도면 또는 산정 항목을 함께 적는 것이 좋습니다.",
  },
  {
    question: "카카오 알림이 오지 않습니다.",
    answer: "상단 안내 배너가 남아 있다면 카카오 연동 또는 추가 동의를 완료해야 합니다. 연동 후에도 알림이 오지 않으면 카카오 친구 매칭 상태를 관리자에게 확인해달라고 요청하세요.",
  },
]

export default function ReviewerManualPage() {
  return (
    <div className="space-y-6">
      <section className="rounded-md border bg-white p-5 sm:p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl space-y-3">
            <Badge variant="secondary" className="w-fit">
              검토위원 전용
            </Badge>
            <div className="space-y-2">
              <h1 className="text-2xl font-bold sm:text-3xl">검토위원 매뉴얼</h1>
              <p className="text-sm leading-6 text-muted-foreground sm:text-base">
                배정 건 확인부터 검토서 업로드, 문의 등록까지 검토위원이 자주 사용하는 흐름을
                실제 메뉴 기준으로 정리했습니다.
              </p>
            </div>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row lg:shrink-0">
            <Link href="/my-reviews">
              <Button className="w-full sm:w-auto">
                <ClipboardList />
                내 검토 대상
              </Button>
            </Link>
            <Link href="/announcements">
              <Button variant="outline" className="w-full sm:w-auto">
                <Bell />
                공지사항
              </Button>
            </Link>
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-xl font-semibold">기본 업무 흐름</h2>
          <p className="text-sm text-muted-foreground">
            검토 시작 전 확인부터 제출 후 문의까지 순서대로 진행합니다.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {workflowSteps.map((item) => (
            <StepCard key={item.step} item={item} />
          ))}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        {guideSections.map((section) => (
          <GuideCard key={section.title} section={section} />
        ))}
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.7fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600" />
              제출 전 확인 사항
            </CardTitle>
            <CardDescription>
              업로드 전에 확인하면 재작업을 줄일 수 있는 항목입니다.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-3">
              {cautions.map((caution) => (
                <li key={caution} className="flex gap-2 text-sm leading-6">
                  <CheckCircle2 className="mt-1 h-4 w-4 shrink-0 text-emerald-600" />
                  <span>{caution}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>파일 제출 기준</CardTitle>
            <CardDescription>
              시스템 검증이 확인하는 주요 조건입니다.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <FileRule label="파일 형식" value=".xlsm" />
            <Separator />
            <FileRule label="파일명" value="관리번호로 시작" />
            <Separator />
            <FileRule label="제출 방식" value="미리보기 검증 후 업로드" />
            <Separator />
            <FileRule label="재제출" value="기존 파일 대체" />
          </CardContent>
        </Card>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-xl font-semibold">자주 묻는 질문</h2>
          <p className="text-sm text-muted-foreground">
            검토 진행 중 자주 생기는 상황을 정리했습니다.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {faqs.map((faq) => (
            <Card key={faq.question}>
              <CardHeader>
                <CardTitle className="text-base">{faq.question}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-6 text-muted-foreground">{faq.answer}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
    </div>
  )
}

function StepCard({ item }: { item: ManualStep }) {
  const Icon = item.icon

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <Badge variant="outline" className="h-7 w-7 justify-center rounded-full p-0">
            {item.step}
          </Badge>
          <Icon className="h-5 w-5 text-muted-foreground" />
        </div>
        <CardTitle>{item.title}</CardTitle>
        <CardDescription>{item.description}</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {item.details.map((detail) => (
            <li key={detail} className="text-sm leading-6 text-muted-foreground">
              {detail}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

function GuideCard({ section }: { section: GuideSection }) {
  const Icon = section.icon

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted">
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0 space-y-1">
            <CardTitle>{section.title}</CardTitle>
            <CardDescription>{section.description}</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {section.items.map((item) => (
            <li key={item} className="flex gap-2 text-sm leading-6 text-muted-foreground">
              <CheckCircle2 className="mt-1 h-4 w-4 shrink-0 text-emerald-600" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

function FileRule({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}
