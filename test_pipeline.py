# -*- coding: utf-8 -*-
"""
test_pipeline.py
=================
classifier.py 전체 파이프라인(Rule -> 과거사례 -> AI)을 실제 120건 데이터로 돌려보는 스크립트.
AI 부분은 아직 API 키가 없으므로 mock 모드로 동작합니다 (ai_classifier.py 참고).
실제 API 연결 후 다시 돌리면 mock 대신 진짜 Claude 응답으로 같은 통계를 볼 수 있습니다.
"""

import pandas as pd
import classifier
import historical_cases as hc


def main():
    df = hc.load_historical_cases()

    rows = []
    for _, row in df.iterrows():
        txn = row.to_dict()
        result = classifier.classify_transaction(txn, historical_df=df)
        rows.append({
            "사용자": txn["사용자"],
            "상호": txn["상호"],
            "금액": txn["사용금액"],
            "과거계정": txn["계정_표준"],
            "AI추천": result.account,
            "신뢰도": result.confidence,
            "검토필요": result.needs_human_review,
            "판단출처": result.source,
        })

    result_df = pd.DataFrame(rows)

    total = len(result_df)
    auto = (~result_df["검토필요"]).sum()
    review = result_df["검토필요"].sum()

    print(f"전체 {total}건 / 자동확정 {auto}건({auto/total:.1%}) / 검토필요 {review}건({review/total:.1%})")
    print()
    print("=== 판단출처별 건수 ===")
    print(result_df["판단출처"].value_counts())
    print()
    print("=== 검토 필요로 표시된 거래 ===")
    print(result_df[result_df["검토필요"]][["사용자", "상호", "금액", "과거계정", "AI추천", "신뢰도", "판단출처"]].to_string())

    result_df.to_excel("data/파이프라인_테스트결과.xlsx", index=False)
    print("\n결과를 data/파이프라인_테스트결과.xlsx 로 저장했습니다.")


if __name__ == "__main__":
    main()
