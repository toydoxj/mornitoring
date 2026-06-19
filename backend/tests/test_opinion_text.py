from engines.opinion_text import clean_opinion_detail_content


def test_clean_opinion_detail_content_removes_comma_source_and_page_marks():
    assert (
        clean_opinion_detail_content(
            '설하중 반영 여부 확인 바람, "구조계산서", 8~9 page, KDS 41 12 00 4.1'
        )
        == "설하중 반영 여부 확인 바람, KDS 41 12 00 4.1"
    )


def test_clean_opinion_detail_content_removes_p_dot_page_marks():
    assert (
        clean_opinion_detail_content(
            "슬래브 하중 확인 필요, 구조도면, p.8, 구조 평면도"
        )
        == "슬래브 하중 확인 필요, 구조 평면도"
    )


def test_clean_opinion_detail_content_removes_attached_p_dot_page_marks():
    assert (
        clean_opinion_detail_content(
            "구조계산서p.55 슬래브 판해석에서 전이벽체 확인 필요"
        )
        == "슬래브 판해석에서 전이벽체 확인 필요"
    )


def test_clean_opinion_detail_content_removes_source_page_parentheses():
    assert (
        clean_opinion_detail_content(
            "하중 리스트와 불일치하여 수정 필요(구조계산서: 53 page), 구조계산서"
        )
        == "하중 리스트와 불일치하여 수정 필요"
    )


def test_clean_opinion_detail_content_keeps_meaningful_document_words():
    assert clean_opinion_detail_content("구조계산서 누락") == "구조계산서 누락"
    assert (
        clean_opinion_detail_content("구조도면 일반사항 개요 확인 필요")
        == "구조도면 일반사항 개요 확인 필요"
    )
