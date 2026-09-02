# -*- coding: utf-8 -*-
"""
historical_cases.py
====================
"과거 정상 처리 사례 검색" 담당 파일입니다.

프로젝트 지시사항(10번, STEP 4)에 따라:
- 120건 정도의 소규모 데이터로 별도 머신러닝 모델을 학습시키지 않고,
  단순 유사도 검색(Historical Case Retrieval)으로 시작합니다.
- 현재 업무 규칙과 충돌하는 오입력 의심 건은 "정상 학습 사례"에서 제외합니다.
  (편의점=동적요소관리비인데 과거에 식대보조로 잘못 적힌 사례가 있었다면,
   그걸 AI가 정상 사례로 참고하면 안 된다는 게 이 프로젝트의 핵심 요구사항입니다.)

이 파일이 하는 일은 rules.py가 답을 못 낸 거래(예: 전자상거래(다품목))에 대해
"이거랑 비슷한 과거 거래들이 어떻게 처리됐는지" 찾아서 ai_classifier.py에 넘겨주는 것입니다.
AI는 이 사례들을 참고자료로만 쓰고, 최종 판단은 ai_classifier.py에서 합니다.
"""

from dataclasses import dataclass
from typing import List, Optional
import pandas as pd

import config

# 오입력이 확인됐거나(EXCLUDE) 애매해서 학습 사례로 쓰기엔 위험한 건(REVIEW_ONLY)들.
# key: (사용자, 상호, 사용금액) / value: 사유
# STEP 4에서 대화로 확정된 내용을 그대로 반영했습니다.
EXCLUDED_FROM_HISTORY = {
    ("김형찬", "양운 청주지웰점", 2529800.0):
        "100만원 초과 식당은 예외없이 동적요소관리비 규칙과 충돌하는 오입력 의심 건",
    ("김재승", "루트커피 현대커넥트점", 54000.0):
        "카페 5만원 기준에 근소 초과 - 재검토 권장 건이라 학습사례로는 보수적으로 제외",
}


@dataclass
class HistoricalCase:
    user: str
    merchant: str
    industry: str
    amount: float
    account: str
    similarity_score: float


def load_historical_cases(excel_path: str = "data/법인카드_사용내역.xlsx") -> pd.DataFrame:
    """
    과거 Excel을 읽어서:
    1. 공백/합계행 제거
    2. 계정 표기를 표준 이름으로 정규화 (정산_유류비 -> 유류비(정산) 등)
    3. 오입력/애매 사례 플래그(is_excluded 컬�럼) 추가
    를 한 DataFrame을 반환합니다. (행 자체를 지우지 않고 플래그만 남기는 이유는
    나중에 "왜 제외됐는지"를 화면에 보여주기 위해서입니다.)
    """
    df = pd.read_excel(excel_path, sheet_name="법인카드 사용내역")
    df = df[df["No."].notna()].copy()
    df["계정_표준"] = df["계정"].replace(config.LEGACY_ACCOUNT_NORMALIZATION)

    def _is_excluded(row):
        key = (row["사용자"], row["상호"], row["사용금액"])
        return key in EXCLUDED_FROM_HISTORY

    df["is_excluded"] = df.apply(_is_excluded, axis=1)
    return df


def _amount_similarity(a: float, b: float) -> float:
    """
    금액이 비슷할수록 1.0에 가깝고, 차이가 클수록 0에 가까운 점수.
    단순 방식: 두 금액의 비율(작은 값/큰 값)을 그대로 점수로 사용.
    예: 10,000원과 12,000원 -> 0.83 / 10,000원과 100,000원 -> 0.1
    """
    if a is None or b is None or a == 0 or b == 0:
        return 0.0
    lo, hi = sorted([abs(a), abs(b)])
    return lo / hi


def find_similar_cases(
    new_txn: dict,
    historical_df: Optional[pd.DataFrame] = None,
    top_n: int = 3,
    include_excluded: bool = False,
) -> List[HistoricalCase]:
    """
    new_txn: {"사용자":..., "상호":..., "업종":..., "사용금액":...} 형태의 신규 거래.
    historical_df: load_historical_cases()의 결과. 안 넘기면 새로 로드함.

    점수 계산 방식 (단순 가중치 합, 데이터 120건 규모에 맞춘 실용적인 방식):
      - 업종이 같으면 +3점 (가장 중요한 신호)
      - 상호가 완전히 같으면 +2점 / 상호명이 서로 일부 포함관계면 +1점
      - 금액 유사도 * 1점 (0~1 사이)
    총점 상위 top_n개를 반환합니다.
    """
    if historical_df is None:
        historical_df = load_historical_cases()

    candidates = historical_df
    if not include_excluded:
        candidates = candidates[~candidates["is_excluded"]]

    scored = []
    for _, row in candidates.iterrows():
        score = 0.0
        if row.get("업종") == new_txn.get("업종"):
            score += 3.0

        merchant_hist = str(row.get("상호") or "")
        merchant_new = str(new_txn.get("상호") or "")
        if merchant_hist and merchant_new:
            if merchant_hist == merchant_new:
                score += 2.0
            elif merchant_hist in merchant_new or merchant_new in merchant_hist:
                score += 1.0

        score += _amount_similarity(row.get("사용금액"), new_txn.get("사용금액"))

        if score > 0:
            scored.append(HistoricalCase(
                user=row.get("사용자"),
                merchant=row.get("상호"),
                industry=row.get("업종"),
                amount=row.get("사용금액"),
                account=row.get("계정_표준"),
                similarity_score=round(score, 2),
            ))

    scored.sort(key=lambda c: c.similarity_score, reverse=True)
    return scored[:top_n]
