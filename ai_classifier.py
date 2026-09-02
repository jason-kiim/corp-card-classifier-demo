# -*- coding: utf-8 -*-
"""
ai_classifier.py
=================
rules.py로도, historical_cases.py의 유사사례만으로도 확신 있게 못 정하는 거래를
AI(Claude)에게 최종 판단을 요청하는 파일입니다.

보안 원칙 (프로젝트 14번 항목 + 대화에서 확정):
- 카드번호, 승인번호는 절대 AI에 전달하지 않습니다. (_build_safe_payload에서 제거)
- 사용자 이름은 실명 그대로 전달합니다 (소장님/소속팀 판단이 규칙에 중요하기 때문 - 확정된 결정).

동작 방식:
- ANTHROPIC_API_KEY 환경변수가 설정되어 있으면 실제 Claude API를 호출합니다.
- 설정되어 있지 않으면 config.USE_MOCK_AI(또는 이 파일의 MOCK 모드)로 동작해서
  실제 과금 없이 파이프라인 연결(입력 -> 프롬프트 -> 출력 파싱)만 테스트할 수 있게 합니다.
  -> API 키를 아직 안 받으셨어도 이 파일 구조와 나머지 파이프라인은 미리 확인 가능합니다.
"""

import json
import os
from dataclasses import dataclass
from typing import List, Optional

import config
from historical_cases import HistoricalCase

MODEL_NAME = "claude-sonnet-4-5-20250929"  # 나중에 실제 서비스에 맞는 모델로 조정 가능


@dataclass
class AIResult:
    account: str
    confidence: float
    reason: str
    needs_human_review: bool


# 회사 비용항목 규정을 AI에게 매번 설명하는 시스템 프롬프트.
# rules.py의 자연어 버전이라고 생각하면 됩니다 - AI가 "왜 이렇게 판단하는지"의 기준이 됩니다.
SYSTEM_PROMPT = f"""당신은 법인카드 사용내역을 보고 회사의 비용항목(계정)을 추천하는 보조 도구입니다.
아래 규칙은 이미 Rule Engine에서 처리되지 않고 당신에게 넘어온 거래에 대해서만 적용됩니다.
즉 편의점/할인점/카페/일반식당/유류비 같은 명확한 케이스는 이미 처리되었고,
당신에게는 상호명만으로 목적을 알기 어려운 거래(예: 쿠팡, 네이버페이 등 다품목 판매처)만 전달됩니다.

사용 가능한 비용항목 목록: {", ".join(config.ACCOUNTS)}

판단 시 참고할 점:
- 휴게실운영비: 칫솔/샴푸 등 생활용품 구매
- 소모품비: A4용지/볼펜/문구류 등 사무용 소모품 (특히 사용자가 총무 담당자인 경우가 많음)
- 행사비: 회사 내부 행사용 물품
- 안전시설비: 안전보건관리팀의 안전용품 구매
- 위 항목들은 상호명만으로 확정하기 어려우므로, 확신이 낮으면 반드시 needs_human_review를 true로 하세요.

반드시 아래 JSON 형식으로만 답하세요. 다른 설명은 붙이지 마세요.
{{
  "recommended_account": "<비용항목 중 하나>",
  "confidence": <0.0~1.0 사이 숫자>,
  "reason": "<한국어로 1~2문장, 판단 근거>",
  "needs_human_review": <true 또는 false>
}}
"""


def _build_safe_payload(txn: dict) -> dict:
    """
    AI에 보낼 최소 정보만 추립니다.
    카드번호/승인번호는 절대 포함하지 않습니다 (보안 원칙).
    """
    return {
        "사용자": txn.get("사용자"),
        "소속팀": txn.get("소속팀"),  # rules.get_team()으로 미리 채워서 넘겨주는 걸 권장
        "상호": txn.get("상호"),
        "업종": txn.get("업종"),
        "사용금액": txn.get("사용금액"),
    }


def _build_user_message(txn: dict, similar_cases: List[HistoricalCase]) -> str:
    payload = _build_safe_payload(txn)
    cases_text = "\n".join(
        f"- {c.user} / {c.merchant} / {c.industry} / {c.amount:,.0f}원 -> 과거 처리: {c.account} "
        f"(유사도 {c.similarity_score})"
        for c in similar_cases
    ) or "(참고할 만한 과거 유사사례 없음)"

    return f"""[분류할 거래]
{json.dumps(payload, ensure_ascii=False, indent=2)}

[참고할 과거 유사사례 (오입력 의심 건은 이미 제외됨)]
{cases_text}

위 정보를 참고해서 JSON 형식으로만 답하세요.
"""


def _mock_response(txn: dict, similar_cases: List[HistoricalCase]) -> AIResult:
    """
    API 키가 없을 때 파이프라인을 테스트하기 위한 가짜 응답.
    가장 유사도 높은 과거사례의 계정을 그대로 추천하되, confidence는 낮게 줘서
    (기본적으로 사람 검토가 필요하다는 걸 보여주기 위해) 항상 review 필요로 표시합니다.
    """
    if similar_cases:
        top = similar_cases[0]
        return AIResult(
            account=top.account,
            confidence=0.55,
            reason=f"[MOCK] 가장 유사한 과거사례({top.merchant}, {top.amount:,.0f}원)를 참고한 임시 추천입니다. "
                   f"실제 API 연결 전이므로 신뢰하지 마세요.",
            needs_human_review=True,
        )
    return AIResult(
        account="소모품비",
        confidence=0.3,
        reason="[MOCK] 참고할 과거사례가 없어 임의 추천입니다. 실제 API 연결 전 테스트용입니다.",
        needs_human_review=True,
    )


def classify_with_ai(txn: dict, similar_cases: List[HistoricalCase]) -> AIResult:
    """
    이 함수가 classifier.py에서 호출되는 진입점입니다.
    ANTHROPIC_API_KEY가 없으면 mock 응답을, 있으면 실제 API 응답을 반환합니다.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _mock_response(txn, similar_cases)

    # anthropic 패키지는 API 키가 준비된 이후 설치/테스트 예정입니다.
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    user_message = _build_user_message(txn, similar_cases)

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = response.content[0].text
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        # AI가 JSON 형식을 안 지켰을 경우를 대비한 안전장치.
        # 이 경우 신뢰할 수 없으므로 무조건 사람 검토로 보냅니다.
        return AIResult(
            account="미확정",
            confidence=0.0,
            reason=f"AI 응답을 JSON으로 해석하지 못했습니다. 원본: {raw_text[:200]}",
            needs_human_review=True,
        )

    confidence = float(parsed.get("confidence", 0.0))
    needs_review = bool(parsed.get("needs_human_review", False)) or (
        confidence < config.AI_CONFIDENCE_REVIEW_THRESHOLD
    )

    return AIResult(
        account=parsed.get("recommended_account", "미확정"),
        confidence=confidence,
        reason=parsed.get("reason", ""),
        needs_human_review=needs_review,
    )
