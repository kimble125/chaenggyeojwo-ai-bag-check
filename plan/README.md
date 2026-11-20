# 기획안 (A4 2쪽 이내)

넣을 것은 주최 측이 정한 8가지다. 원고는 `plan/build_plan.py`의 ROWS 하나이고, 거기서 세 가지를 만든다(2026-11-20).

- `python3 plan/build_plan.py` → `gabangssok_plan.docx`(Word), `gabangssok_plan.html`(인쇄용), `proposal.md`(글), `img/`(화면 줄, 동작 구조도)
- **내는 파일: `gabangssok_plan.pdf`**. `gabangssok_plan.html`을 브라우저에서 A4로 인쇄해 만든 것이다(A4 2쪽, 글자가 살아 있음). 원고를 고치면 다시 인쇄한다
- `python3 plan/render_pdf.py` → `gabangssok_plan_image.pdf`: 브라우저 없이 그려 만든 예비본(2쪽, 글자가 그림이라 복사는 안 됨)
- Word 파일의 쪽 나눔은 Word에서 열어 확인하지 못했다(만든 컴퓨터에 Word가 없음). 내는 것은 PDF를 권한다

## 주최 측 샘플 양식

`plan/elice_plan_template_sample.pptx` (엘리스 플랫폼 '[샘플] 기획안 양식'에서 받음, 필수 아님). 한 장에 아래 칸이 있다.

팀명 / 팀 구성원 / 해결하고 싶은 문제 / 문제를 겪는 사람 / 제작할 AI 서비스명 / 서비스 제작 목적 / 서비스 기대 효과 / 서비스 활용 방식 / 제작에 활용할 AI·도구 / 핵심 기능(3가지) / 다른 서비스와의 차별점 / 역할 분담

표지에 참가 부문(성인)도 적는다.
