# -*- coding: utf-8 -*-
"""
rules.py
========
"명확한 업무 규칙"만 담당하는 Rule Engine입니다.
여기서 답이 나오면(=RuleResult.matched == True) AI를 호출하지 않고 바로 그 결과를 씁니다.
여기서 답이 안 나오면(=matched == False) 그 거래는 classifier.py가 다음 단계
(과거사례 검색 -> AI 판단 -> 사람 검토)로 넘깁니다.

설계 원칙 (프로젝트 지시사항 7번, "AI에게 모든 것을 맡기지 마라"):
- 이 파일의 함수들은 절대 "추측"하지 않습니다. 조건이 딱 맞을 때만 계정을 반환하고,
  조건이 애매하면 반드시 None(=모름)을 반환합니다.
- 규칙 우선순위는 config.py가 아니라 이 파일의 RULE_FUNCTIONS 리스트 순서로 결정됩니다.
  즉 "0순위 소장님 규칙"을 가장 먼저 두고, 그 다음 업종 규칙, 그 다음 소속팀 규칙 순으로 시도합니다.
"""

from dataclasses import dataclass
from typing import Optional, Callable, List

import config


@dataclass
class RuleResult:
    matched: bool                 # 규칙이 이 거래를 처리했는지 여부
    account: Optional[str] = None # 매칭됐다면 어떤 계정인지
    confidence: Optional[float] = None  # 규칙 기반이므로 보통 1.0(확신) 또는 낮은 값(사람확인 유도)
    reason: str = ""              # 왜 이렇게 판단했는지 사람이 읽을 수 있는 설명
    rule_name: str = ""           # 어떤 규칙이 적용됐는지 (디버깅/감사용)


def _no_match() -> RuleResult:
    return RuleResult(matched=False)


def normalize_user(name: Optional[str]) -> Optional[str]:
    """과거 데이터의 오탈자 등을 조직도 표준 이름으로 변환합니다. (예: 이상현 -> 이상헌)"""
    if name is None:
        return None
    return config.USER_NAME_ALIASES.get(name, name)


def get_team(user: Optional[str]) -> Optional[str]:
    user = normalize_user(user)
    return config.USER_TO_TEAM.get(user)


# ---------------------------------------------------------------------------
# 0순위: 소장님(백홍) 특수 규칙
# ---------------------------------------------------------------------------
def rule_director(row: dict) -> RuleResult:
    user = normalize_user(row.get("사용자"))
    if user != config.DIRECTOR_NAME:
        return _no_match()

    industry = row.get("업종")

    if industry == "상품권판매":
        return RuleResult(
            matched=True, account="접대비", confidence=1.0,
            reason="소장님 + 상품권 구매 → 접대비 규칙",
            rule_name="director_gift_card",
        )

    if industry in config.RESTAURANT_INDUSTRIES or industry == config.CAFE_INDUSTRY:
        # 과거 사례상 식대보조로 처리되기도 했던 애매한 영역이라,
        # 규칙으로 "확정"하지 않고 추천은 주되 confidence를 낮게 줘서 사람이 확인하게 합니다.
        return RuleResult(
            matched=True, account="조직활성화비", confidence=0.6,
            reason="소장님 + 식당/카페 이용 → 조직활성화비로 추천하나, "
                   "개인 식사일 수도 있어 확인이 필요합니다.",
            rule_name="director_meal",
        )

    return _no_match()


# ---------------------------------------------------------------------------
# 1순위: 업종 기반 규칙
# ---------------------------------------------------------------------------
def rule_dynamic_element_industry(row: dict) -> RuleResult:
    industry = row.get("업종")
    if industry in config.DYNAMIC_ELEMENT_INDUSTRIES:
        note = ""
        if industry == "백화점":
            note = " (⚠ 백화점은 데이터 기반으로 추가된 규칙이라 확인 필요)"
        return RuleResult(
            matched=True, account="동적요소관리비", confidence=1.0,
            reason=f"업종 '{industry}' → 동적요소관리비 규칙{note}",
            rule_name="dynamic_element_industry",
        )
    return _no_match()


def rule_cafe(row: dict) -> RuleResult:
    if row.get("업종") != config.CAFE_INDUSTRY:
        return _no_match()

    amount = row.get("사용금액") or 0
    if amount <= config.CAFE_THRESHOLD_KRW:
        account = "식대보조"
    else:
        account = "동적요소관리비"
    return RuleResult(
        matched=True, account=account, confidence=1.0,
        reason=f"카페 이용, 금액 {amount:,.0f}원 (기준 {config.CAFE_THRESHOLD_KRW:,}원)",
        rule_name="cafe_amount_threshold",
    )


def rule_restaurant(row: dict) -> RuleResult:
    industry = row.get("업종")
    if industry not in config.RESTAURANT_INDUSTRIES:
        return _no_match()

    amount = row.get("사용금액") or 0
    if amount > config.RESTAURANT_LIMIT_KRW:
        return RuleResult(
            matched=True, account="동적요소관리비", confidence=1.0,
            reason=f"식당 이용금액 {amount:,.0f}원이 {config.RESTAURANT_LIMIT_KRW:,}원 초과 (예외없음)",
            rule_name="restaurant_over_limit",
        )
    return RuleResult(
        matched=True, account="식대보조", confidence=1.0,
        reason=f"일반 식당 이용, {config.RESTAURANT_LIMIT_KRW:,}원 이하",
        rule_name="restaurant_normal",
    )


def rule_admin_fee(row: dict) -> RuleResult:
    merchant = row.get("상호") or ""
    amount = row.get("사용금액") or 0

    for kw in config.ADMIN_FEE_MERCHANT_KEYWORDS:
        if kw in merchant:
            return RuleResult(
                matched=True, account="지급수수료-일반", confidence=1.0,
                reason=f"상호명에 '{kw}' 포함 → 행정/등기 수수료",
                rule_name="admin_fee_keyword",
            )

    if merchant in config.PG_FEE_MERCHANTS and amount <= config.PG_FEE_MAX_KRW:
        return RuleResult(
            matched=True, account="지급수수료-일반", confidence=0.9,
            reason=f"'{merchant}' 소액 결제({amount:,.0f}원) → PG/카드 결제수수료로 추정",
            rule_name="pg_fee",
        )

    return _no_match()


def rule_postage(row: dict) -> RuleResult:
    merchant = row.get("상호") or ""
    for kw in config.POSTAGE_MERCHANT_KEYWORDS:
        if kw in merchant:
            return RuleResult(
                matched=True, account="우편료", confidence=0.95,
                reason=f"상호명에 '{kw}' 포함 (⚠ 과거 데이터에 사례가 없어 임시 규칙)",
                rule_name="postage_keyword",
            )
    return _no_match()


# ---------------------------------------------------------------------------
# 2순위: 소속팀 기반 규칙 (유류비 / 차량유지비-수선비)
# ---------------------------------------------------------------------------
def rule_fuel_and_vehicle_repair(row: dict) -> RuleResult:
    industry = row.get("업종")
    user = row.get("사용자")
    team = get_team(user)

    if industry in config.FUEL_INDUSTRIES:
        is_settlement = (team == config.RESOURCE_CIRCULATION_TEAM)
        account = "유류비(정산)" if is_settlement else "유류비(비정산)"
        return RuleResult(
            matched=True, account=account, confidence=1.0,
            reason=f"주유 관련 이용, 사용자 소속팀 '{team}' "
                   f"({'자원순환팀 → 정산' if is_settlement else '자원순환팀 아님 → 비정산'})",
            rule_name="fuel_team_based",
        )

    if industry in config.VEHICLE_REPAIR_INDUSTRIES:
        is_settlement = (team == config.RESOURCE_CIRCULATION_TEAM)
        account = "차량유지비-수선비(정산)" if is_settlement else "차량유지비-수선비(비정산)"
        return RuleResult(
            matched=True, account=account, confidence=1.0,
            reason=f"차량 수선 관련 이용, 사용자 소속팀 '{team}' "
                   f"({'자원순환팀 → 정산' if is_settlement else '자원순환팀 아님 → 비정산'})",
            rule_name="vehicle_repair_team_based",
        )

    return _no_match()


# ---------------------------------------------------------------------------
# 규칙 실행 순서 (중요: 이 순서가 우선순위입니다)
# ---------------------------------------------------------------------------
RULE_FUNCTIONS: List[Callable[[dict], RuleResult]] = [
    rule_director,                  # 0순위: 소장님 특수 규칙
    rule_admin_fee,                 # 1순위: 행정/PG 수수료 (업종 무관, 먼저 걸러냄)
    rule_postage,                   # 1순위: 우편료
    rule_dynamic_element_industry,  # 1순위: 편의점/할인점/제과점/백화점
    rule_cafe,                      # 1순위: 카페 금액기준
    rule_restaurant,                # 1순위: 식당 금액기준
    rule_fuel_and_vehicle_repair,   # 2순위: 유류비/차량유지비 (소속팀 기준)
]


def apply_rules(row: dict) -> RuleResult:
    """
    거래 1건(dict)을 받아 RULE_FUNCTIONS를 순서대로 시도합니다.
    첫 번째로 matched=True를 반환하는 규칙의 결과를 그대로 돌려줍니다.
    끝까지 아무 규칙도 매칭되지 않으면 matched=False인 RuleResult를 반환합니다.
    (이 경우 classifier.py가 과거사례 검색 -> AI 판단 단계로 넘깁니다.)
    """
    for rule_fn in RULE_FUNCTIONS:
        result = rule_fn(row)
        if result.matched:
            return result
    return _no_match()
