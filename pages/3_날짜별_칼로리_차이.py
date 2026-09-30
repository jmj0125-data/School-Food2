
import calendar
import re
from datetime import date

import pandas as pd
import requests
import streamlit as st


# --------------------------------------------------
# 페이지 설정
# --------------------------------------------------

st.title("📊 날짜별 칼로리 비교")
st.caption("선택한 학교의 한 달간 중식 칼로리를 비교합니다.")


# --------------------------------------------------
# NEIS API 설정
# --------------------------------------------------

API_KEY = st.secrets["NEIS_API_KEY"]

SCHOOL_URL = "https://open.neis.go.kr/hub/schoolInfo"
MEAL_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"


# --------------------------------------------------
# 학교 검색
# --------------------------------------------------

def expand_school_name(name):
    """학교 약칭을 정식 명칭으로 변환합니다."""

    replacements = {
        "여고": "여자고등학교",
        "남고": "남자고등학교",
        "여중": "여자중학교",
        "남중": "남자중학교",
        "초": "초등학교",
        "중": "중학교",
        "고": "고등학교",
    }

    for short, full in replacements.items():
        if name.endswith(short):
            return name[:-len(short)] + full

    return name


def search_schools(keyword):
    """학교명을 검색합니다."""

    params = {
        "KEY": API_KEY,
        "Type": "json",
        "SCHUL_NM": keyword,
        "pIndex": 1,
        "pSize": 100,
    }

    response = requests.get(SCHOOL_URL, params=params, timeout=15)
    response.raise_for_status()

    data = response.json()

    if "schoolInfo" not in data:
        return []

    return data["schoolInfo"][1].get("row", [])


def find_schools(keyword):
    """정식 명칭 검색이 실패하면 약칭으로 재검색합니다."""

    schools = search_schools(keyword)

    if not schools:
        expanded = expand_school_name(keyword)

        if expanded != keyword:
            schools = search_schools(expanded)

    return schools


# --------------------------------------------------
# 월간 급식 데이터 조회
# --------------------------------------------------

def get_monthly_meals(school, year, month):
    """선택한 학교의 한 달간 중식 데이터를 모두 가져옵니다."""

    last_day = calendar.monthrange(year, month)[1]

    start_date = f"{year}{month:02d}01"
    end_date = f"{year}{month:02d}{last_day:02d}"

    page_size = 100

    params = {
        "KEY": API_KEY,
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": school["ATPT_OFCDC_SC_CODE"],
        "SD_SCHUL_CODE": school["SD_SCHUL_CODE"],
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": start_date,
        "MLSV_TO_YMD": end_date,
        "pIndex": 1,
        "pSize": page_size,
    }

    response = requests.get(MEAL_URL, params=params, timeout=20)
    response.raise_for_status()

    data = response.json()

    if "mealServiceDietInfo" not in data:
        return []

    info = data["mealServiceDietInfo"]

    # API 응답의 전체 건수 확인
    total_count = info[0]["head"][0].get("list_total_count", 0)

    if total_count == 0:
        return []

    all_rows = []

    # 첫 페이지 데이터
    all_rows.extend(info[1].get("row", []))

    # 전체 건수를 받을 때까지 추가 요청
    total_pages = (total_count + page_size - 1) // page_size

    for page in range(2, total_pages + 1):
        params["pIndex"] = page

        response = requests.get(
            MEAL_URL,
            params=params,
            timeout=20,
        )
        response.raise_for_status()

        page_data = response.json()

        if "mealServiceDietInfo" not in page_data:
            break

        rows = page_data["mealServiceDietInfo"][1].get("row", [])
        all_rows.extend(rows)

    return all_rows


# --------------------------------------------------
# 메뉴 정리
# --------------------------------------------------

def parse_menu(menu_text):
    """메뉴를 분리하고 알레르기 번호를 제거합니다."""

    if not menu_text:
        return []

    # <br/>, <br>, <br /> 모두 처리
    menu_items = re.split(r"<br\s*/?>", menu_text, flags=re.IGNORECASE)

    cleaned = []

    for item in menu_items:
        item = item.strip()

        # 메뉴 뒤에 붙은 알레르기 번호 제거
        # 예: 돈까스(1.2.5.6.10) → 돈까스
        item = re.sub(r"\s*\([^)]*\)\s*$", "", item)

        item = item.strip()

        if item:
            cleaned.append(item)

    return cleaned


# --------------------------------------------------
# 화면 구성
# --------------------------------------------------

st.subheader("1. 학교 선택")

keyword = st.text_input(
    "학교 이름",
    placeholder="예: 서울고등학교",
)

if "calorie_school_results" not in st.session_state:
    st.session_state.calorie_school_results = []

if st.button("학교 검색"):
    if not keyword.strip():
        st.warning("학교 이름을 입력해 주세요.")
    else:
        try:
            st.session_state.calorie_school_results = find_schools(
                keyword.strip()
            )

            if not st.session_state.calorie_school_results:
                st.warning("검색 결과가 없습니다.")

        except requests.RequestException as e:
            st.error(f"학교 검색 중 오류가 발생했습니다: {e}")


schools = st.session_state.calorie_school_results

selected_school = None

if schools:
    school_options = {
        (
            f"{school['SCHUL_NM']} "
            f"({school['ATPT_OFCDC_SC_NM']})"
        ): school
        for school in schools
    }

    selected_name = st.selectbox(
        "검색 결과",
        options=list(school_options.keys()),
    )

    selected_school = school_options[selected_name]


# --------------------------------------------------
# 월 선택
# --------------------------------------------------

st.subheader("2. 조회할 월 선택")

today = date.today()

col1, col2 = st.columns(2)

with col1:
    selected_year = st.number_input(
        "연도",
        min_value=2000,
        max_value=2100,
        value=today.year,
        step=1,
    )

with col2:
    selected_month = st.selectbox(
        "월",
        options=list(range(1, 13)),
        index=today.month - 1,
        format_func=lambda m: f"{m}월",
    )


# --------------------------------------------------
# 칼로리 분석
# --------------------------------------------------

if st.button("월간 칼로리 분석", type="primary"):

    if selected_school is None:
        st.warning("먼저 학교를 검색하고 선택해 주세요.")

    else:
        try:
            with st.spinner("급식 데이터를 불러오는 중입니다..."):

                rows = get_monthly_meals(
                    selected_school,
                    int(selected_year),
                    selected_month,
                )

            if not rows:
                st.info("선택한 달에 등록된 중식 데이터가 없습니다.")

            else:
                records = []

                for row in rows:
                    meal_date = row.get("MLSV_YMD", "")
                    menu_text = row.get("DDISH_NM", "")
                    calorie_text = row.get("CAL_INFO", "")

                    # 날짜별 메뉴 정리
                    menu_items = parse_menu(menu_text)

                    # 칼로리 숫자 추출
                    calorie_match = re.search(
                        r"\d+(?:\.\d+)?",
                        calorie_text,
                    )

                    if not calorie_match:
                        continue

                    calories = float(calorie_match.group())

                    # 같은 날 같은 메뉴는 한 번만 기록
                    unique_menu = list(dict.fromkeys(menu_items))

                    records.append({
                        "날짜": meal_date,
                        "칼로리": calories,
                        "메뉴": ", ".join(unique_menu),
                    })

                if not records:
                    st.warning("분석할 수 있는 칼로리 데이터가 없습니다.")

                else:
                    df = pd.DataFrame(records)

                    # 같은 날짜에 여러 급식 데이터가 있을 경우
                    # 날짜별로 하나만 남김
                    df = (
                        df.sort_values("칼로리", ascending=False)
                        .drop_duplicates(subset=["날짜"], keep="first")
                    )

                    # 칼로리 내림차순 정렬 후 TOP 10
                    top10 = (
                        df.sort_values(
                            "칼로리",
                            ascending=False,
                        )
                        .head(10)
                        .copy()
                    )

                    top10["날짜"] = pd.to_datetime(
                        top10["날짜"],
                        format="%Y%m%d",
                    ).dt.strftime("%m월 %d일")

                    st.subheader(
                        f"🏆 {selected_year}년 {selected_month}월 "
                        "중식 칼로리 TOP 10"
                    )

                    st.caption(
                        f"총 {len(df)}일의 급식 데이터를 분석했습니다."
                    )

                    # 가장 높은 칼로리가 위에 오도록 순서 유지
                    chart_df = top10[
                        ["날짜", "칼로리"]
                    ].set_index("날짜")

                    st.bar_chart(
                        chart_df,
                        horizontal=True,
                        height=450,
                    )

                    st.subheader("3. TOP 10 상세 내역")

                    display_df = top10[
                        ["날짜", "칼로리", "메뉴"]
                    ].copy()

                    display_df.insert(
                        0,
                        "순위",
                        range(1, len(display_df) + 1),
                    )

                    display_df["칼로리"] = (
                        display_df["칼로리"].map(
                            lambda x: f"{x:,.1f} kcal"
                        )
                    )

                    st.dataframe(
                        display_df,
                        use_container_width=True,
                        hide_index=True,
                    )

                    st.subheader("4. 월간 칼로리 통계")

                    col1, col2, col3 = st.columns(3)

                    with col1:
                        st.metric(
                            "최고 칼로리",
                            f"{df['칼로리'].max():,.1f} kcal",
                        )

                    with col2:
                        st.metric(
                            "최저 칼로리",
                            f"{df['칼로리'].min():,.1f} kcal",
                        )

                    with col3:
                        st.metric(
                            "월평균 칼로리",
                            f"{df['칼로리'].mean():,.1f} kcal",
                        )

        except requests.RequestException as e:
            st.error(f"급식 데이터 조회 중 오류가 발생했습니다: {e}")

        except (KeyError, IndexError, ValueError) as e:
            st.error(f"데이터 처리 중 오류가 발생했습니다: {e}")
