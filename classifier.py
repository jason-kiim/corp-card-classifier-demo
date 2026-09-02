# -*- coding: utf-8 -*-
"""
classifier.py
==============
전체 파이프라인을 하나로 연결하는 파일입니다.

거래 1건 -> rules.py(규칙) -> (안 풀리면) historical_cases.py(유사사례 검색)
       -> ai_classifier.py(AI 판단) -> 최종 결과(계정/신뢰도/근거/검토필요여부)

이 파일 하나만 보면 "전체 흐름이 프로젝트 기획서의 파이프라인과 똑같이 동작하는지"
확인할 수 있게 만드는 게 목적입니다. (app.py에서는 이 파일의 classify_transaction만 호출하면 됩니다.)
"""

from dataclasses import dataclass
from typing import Optional

import rules
import historical_cases as hc
import ai_classifier


@dataclass
class ClassificationResult:
    account: str
    confidence: float
    reason: str
    needs_human_review: bool
    source: str  # "rule" | "ai" 어느 단계에서 결정됐는지 (감사/디버깅용)


def classify_transaction(
    txn: dict,
    historical_df=None,
) -> ClassificationResult:
    """
    txn: {"사용자":.., "상호":.., "업종":.., "사용금액":.., ...} - 카드번호/승인번호는 없어도 됨
         (rules.py는 카드번호를 쓰지 않으므로 애초에 필요 없습니다)
    """
    # 1단계: Rule Engine
    rule_result = rules.apply_rules(txn)
    if rule_result.matched:
        return ClassificationResult(
            account=rule_result.account,
            confidence=rule_result.confidence,
            reason=rule_result.reason,
            needs_human_review=rule_result.confidence < 0.8,
            source=f"rule:{rule_result.rule_name}",
        )

    # 2단계: 과거 유사사례 검색
    similar_cases = hc.find_similar_cases(txn, historical_df=historical_df, top_n=3)

    # 3단계: AI 판단 (유사사례를 참고자료로 함께 전달)
    txn_for_ai = dict(txn)
    txn_for_ai["소속팀"] = rules.get_team(txn.get("사용자"))
    ai_result = ai_classifier.classify_with_ai(txn_for_ai, similar_cases)

    return ClassificationResult(
        account=ai_result.account,
        confidence=ai_result.confidence,
        reason=ai_result.reason,
        needs_human_review=ai_result.needs_human_review,
        source="ai",
    )
