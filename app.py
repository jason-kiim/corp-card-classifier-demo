# -*- coding: utf-8 -*-
"""
app.py
======
Streamlit UI. 사용 흐름은 프로젝트 기획서 STEP 7 그대로입니다.
1. 법인카드 Excel 업로드
2. "분석 시작" 버튼 -> classifier.py로 전체 거래 분류
3. 결과 표로 확인 (AI추천/신뢰도/판단근거/검토여부)
4. 표에서 "최종확정계정" 칸을 직접 수정 가능
5. "확정 및 다운로드" -> 최종 Excel 다운로드

실행 방법 (재승님 컴퓨터에서):
    pip install streamlit pandas openpyxl
    streamlit run app.py
그러면 브라우저가 자동으로 열립니다 (보통 http://localhost:8501).

주의: 이 파일은 이 대화(클라우드 작업환경)에서는 streamlit 설치가 막혀 있어 직접 실행해서
화면을 보여드리지는 못했습니다. 문법 오류는 없는지만 확인했고, 실제 화면 동작은
재승님 컴퓨터에서 처음 실행해보시면서 같이 확인하면 됩니다.
"""

import io
import os
import pandas as pd
import streamlit as st

import config
import classifier
import historical_cases as hc

# Streamlit Community Cloud에서는 API 키를 os.environ이 아니라 st.secrets로 관리합니다.
# (Settings > Secrets에 ANTHROPIC_API_KEY = "sk-ant-..." 형태로 저장)
# ai_classifier.py는 os.environ만 확인하므로, 여기서 secrets 값을 환경변수로 옮겨줍니다.
# 로컬 컴퓨터에서 실행할 때는 st.secrets에 아무것도 없으므로 이 부분은 그냥 조용히 넘어갑니다.
try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass

def confidence_badge(pct: float) -> str:
    """
    신뢰도(0~100)를 색깔 있는 동그라미 이모지 + 퍼센트 문자열로 바꿉니다.
    (Streamlit의 편집 가능한 표(data_editor)는 셀 배경색을 직접 칠하는 기능을 지원하지 않아서,
     이모지로 초록/노랑/빨강을 표현하는 방식을 대신 사용합니다.)
    100%에 가까울수록 초록, 0%에 가까울수록 빨강이 되도록 3단계로 나눴습니다.
    """
    if pct >= 80:
        emoji = "🟢"
    elif pct >= 50:
        emoji = "🟡"
    else:
        emoji = "🔴"
    return f"{emoji} {pct:.0f}%"


def review_badge(status: str) -> str:
    return "🔴 검토" if status == "검토" else "🟢 자동"


st.set_page_config(page_title="법인카드 비용분류 지원 시스템", layout="wide")

st.title("법인카드 비용분류 업무지원 시스템 (V1)")
st.caption(
    "규칙 기반 자동분류 + AI 판단 + 사람 최종 검토 구조입니다. "
    "AI가 모든 걸 대신 정하지 않고, 확신이 낮은 거래만 검토를 요청합니다."
)

if not st.session_state.get("_ai_key_warned"):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.warning(
            "ANTHROPIC_API_KEY가 설정되어 있지 않아 AI 판단이 필요한 거래는 "
            "지금 mock(임시) 응답으로 표시됩니다. 실제 서비스 전에는 반드시 API 키를 연결하세요.",
            icon="⚠️",
        )
    st.session_state["_ai_key_warned"] = True


# ---------------------------------------------------------------------------
# 1. 업로드
# ---------------------------------------------------------------------------
uploaded_file = st.file_uploader("법인카드 사용내역 Excel을 업로드하세요", type=["xlsx"])

if uploaded_file is None:
    st.info("Excel 파일을 업로드하면 분석을 시작할 수 있습니다.")
    st.stop()

raw_df = pd.read_excel(uploaded_file)
# "No." 컬럼이 없거나 비어있는 합계/공백행 제거 (원본 데이터 구조 기준)
if "No." in raw_df.columns:
    raw_df = raw_df[raw_df["No."].notna()].copy()

st.success(f"{len(raw_df)}건의 거래를 불러왔습니다.")
with st.expander("업로드한 원본 데이터 미리보기"):
    st.dataframe(raw_df, use_container_width=True)


# ---------------------------------------------------------------------------
# 2. 분석 시작
# ---------------------------------------------------------------------------
if st.button("분석 시작", type="primary"):
    historical_df = hc.load_historical_cases()  # 과거 유사사례 검색용 고정 데이터셋

    progress = st.progress(0, text="분류 중...")
    results = []
    n = len(raw_df)
    for i, (_, row) in enumerate(raw_df.iterrows()):
        txn = row.to_dict()
        result = classifier.classify_transaction(txn, historical_df=historical_df)
        results.append({
            "AI추천계정": result.account,
            # 화면 표시용으로 0~100 사이 값으로 저장 (result.confidence는 0.0~1.0 사이 값)
            "AI신뢰도": round(result.confidence * 100, 1),
            "AI판단근거": result.reason,
            "검토필요여부": "검토" if result.needs_human_review else "자동",
            "판단출처": result.source,
        })
        progress.progress((i + 1) / n, text=f"분류 중... ({i+1}/{n})")

    progress.empty()

    result_df = raw_df.reset_index(drop=True).join(pd.DataFrame(results))
    result_df["최종확정계정"] = result_df["AI추천계정"]  # 초기값 = AI 추천값 (사람이 수정 가능)

    st.session_state["result_df"] = result_df


# ---------------------------------------------------------------------------
# 3~5. 결과 확인 / 수정 / 확정 및 다운로드
# ---------------------------------------------------------------------------
if "result_df" in st.session_state:
    result_df = st.session_state["result_df"]

    total = len(result_df)
    auto_count = (result_df["검토필요여부"] == "자동").sum()
    review_count = (result_df["검토필요여부"] == "검토").sum()

    col1, col2, col3 = st.columns(3)
    col1.metric("전체 거래", f"{total}건")
    col2.metric("자동확정", f"{auto_count}건", f"{auto_count/total:.1%}")
    col3.metric("검토 필요", f"{review_count}건", f"{review_count/total:.1%}")

    st.subheader("분류 결과 (최종확정계정 칸을 클릭해서 직접 수정할 수 있습니다)")

    display_cols = [c for c in ["승인번호", "사용자", "상호", "사용금액", "업종",
                                 "AI추천계정", "AI신뢰도", "AI판단근거",
                                 "검토필요여부", "최종확정계정"] if c in result_df.columns]

    # 화면에만 보여줄 표시용 표를 따로 만듭니다.
    # (result_df 원본은 숫자/원문 그대로 유지해야 최종 Excel 다운로드에 깨끗하게 나갑니다.
    #  이모지는 화면 표시용일 뿐, 다운로드 파일에는 안 들어갑니다.)
    display_df = result_df[display_cols].copy()
    display_df["AI신뢰도"] = display_df["AI신뢰도"].apply(confidence_badge)
    display_df["검토필요여부"] = display_df["검토필요여부"].apply(review_badge)

    edited_df = st.data_editor(
        display_df,
        column_config={
            "최종확정계정": st.column_config.SelectboxColumn(
                "최종확정계정", options=config.ACCOUNTS, required=True,
            ),
        },
        disabled=[c for c in display_cols if c != "최종확정계정"],
        use_container_width=True,
        key="editor",
    )

    # 사람이 AI 추천과 다르게 수정했는지 여부 계산
    result_df["최종확정계정"] = edited_df["최종확정계정"]
    result_df["사용자수정여부"] = result_df["최종확정계정"] != result_df["AI추천계정"]

    st.divider()

    if st.button("확정 및 Excel 다운로드 생성", type="primary"):
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            result_df.to_excel(writer, index=False, sheet_name="법인카드 분류결과")
        buffer.seek(0)

        st.download_button(
            label="최종 결과 Excel 다운로드",
            data=buffer,
            file_name="법인카드_비용분류_결과.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        st.success(
            f"확정 완료: 전체 {total}건 중 사람이 수정한 건 "
            f"{result_df['사용자수정여부'].sum()}건입니다."
        )
