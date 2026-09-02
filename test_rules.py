# -*- coding: utf-8 -*-
"""
test_rules.py
=============
STEP 3 검증용 스크립트입니다.
아직 정식 pytest 등은 쓰지 않고, 실제 과거 데이터 120건에 rules.py를 돌려서
"규칙만으로 몇 %가 자동 처리되는지", "자동 처리된 것 중 과거 라벨과 몇 %가 일치하는지"를
직접 눈으로 확인하기 위한 스크립트입니다.

기대 결과:
- 알려진 오입력 1건(김형찬, 252만원)은 규칙과 다르게 나오는 게 "정상"입니다
  (규칙이 맞고 과거 데이터가 틀린 케이스이기 때문).
- 그 1건을 제외하면 규칙이 매칭된 거래는 전부 과거 라벨과 일치해야 합니다.
"""

import pandas as pd
import config
import rules

KNOWN_MISLABELED = {
    # (사용자, 상호, 사용금액): 이미 확인된 과거 오입력 건 -> 불일치가 나와도 정상
    ("김형찬", "양운 청주지웰점", 2529800.0): "100만원 초과 식당은 예외없이 동적요소관리비 규칙 확정",
}


def load_data():
    df = pd.read_excel("data/법인카드_사용내역.xlsx", sheet_name="법인카드 사용내역")
    df = df[df["No."].notna()].copy()
    # 과거 계정 표기를 표준 표기로 정규화 (정산_유류비 -> 유류비(정산) 등)
    df["계정_표준"] = df["계정"].replace(config.LEGACY_ACCOUNT_NORMALIZATION)
    return df


def main():
    df = load_data()

    matched_count = 0
    match_ok = 0
    match_diff = []
    unmatched_rows = []

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        result = rules.apply_rules(row_dict)

        if not result.matched:
            unmatched_rows.append(row_dict)
            continue

        matched_count += 1
        old_account = row_dict.get("계정_표준")
        key = (row_dict.get("사용자"), row_dict.get("상호"), row_dict.get("사용금액"))

        if pd.isna(old_account):
            # 과거 라벨 자체가 없는 행(합계행 등은 이미 걸렀으므로 여기 오면 안 됨)
            continue

        if result.account == old_account:
            match_ok += 1
        else:
            note = KNOWN_MISLABELED.get(key, "")
            match_diff.append({
                "사용자": row_dict.get("사용자"),
                "상호": row_dict.get("상호"),
                "금액": row_dict.get("사용금액"),
                "과거계정": old_account,
                "규칙판단": result.account,
                "규칙명": result.rule_name,
                "비고": note if note else "⚠ 미확인 불일치",
            })

    total = len(df)
    print(f"전체 거래 건수: {total}")
    print(f"규칙으로 자동 처리된 건수: {matched_count} ({matched_count/total:.1%})")
    print(f"AI/사람 검토로 넘어가는 건수: {len(unmatched_rows)} ({len(unmatched_rows)/total:.1%})")
    print()
    print(f"규칙 매칭 건 중 과거 라벨과 일치: {match_ok} / {matched_count}")
    print()

    if match_diff:
        print("=== 과거 라벨과 다른 건 (규칙 우선 적용) ===")
        for d in match_diff:
            print(d)
    print()

    print("=== 규칙으로 못 푼 거래 (업종별 건수) ===")
    unmatched_df = pd.DataFrame(unmatched_rows)
    print(unmatched_df["업종"].value_counts())
    print()
    print("=== 규칙으로 못 푼 거래 (계정별, 과거 라벨 기준) ===")
    print(unmatched_df["계정_표준"].value_counts(dropna=False))


if __name__ == "__main__":
    main()
