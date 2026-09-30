
import calendar
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st


# ==========================================
# 기본 설정
# ==========================================

API_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"
SCHOOL_API = "https://open.neis.go.kr/hub/schoolInfo"

KST = ZoneInfo("Asia/Seoul")
today = datetime.now(KST).date()


# ==========================================
# API 요청
# ==========================================

def request_api(url, params):

    try:
        response = requests.get(
            url,
            params=params,
            timeout=10
        )

        response.raise_for_status()
        return response.json()

    except (requests.exceptions.RequestException, ValueError):
        return None


# ==========================================
# 학교 검색
# ==========================================

def expand_school_name(name):

    name = name.strip()

    replacements = [
        ("여고", "여자고등학교"),
        ("남고", "남자고등학교"),
        ("여중", "여자중학교"),
        ("남중", "남자중학교"),
        ("초", "초등학교"),
        ("중", "중학교"),
        ("고", "고등학교"),
    ]

    expanded_names = []

    for short, full in replacements:

        if name.endswith(short):

            expanded = name[:-len(short)] + full

            if expanded != name:
                expanded_names.append(expanded)

    return expanded_names


def search_schools(name):

    name = name.strip()

    if not name:
        return [], False

    search_names = [name]
    search_names.extend(expand_school_name(name))

    found_schools = []
    seen_codes = set()
    api_error = False

    for search_name in search_names:

        params = {
            "Type": "json",
            "SCHUL_NM": search_name,
        }

        data = request_api(SCHOOL_API, params)

        if data is None:
            api_error = True
            continue

        if "schoolInfo" not in data:
            continue

        try:
            rows = data["schoolInfo"][1]["row"]

        except (KeyError, IndexError, TypeError):
            continue

        for school in rows:

            school_code = school.get("SD_SCHUL_CODE")
            office_code = school.get("ATPT_OFCDC_SC_CODE")

            if not school_code or not office_code:
                continue

            unique_key = (office_code, school_code)

            if unique_key in seen_codes:
                continue

            seen_codes.add(unique_key)
            found_schools.append(school)

    return found_schools, api_error


# ==========================================
# 급식 정보 조회
# ==========================================

@st.cache_data(ttl=3600)
def get_meal(office_code, school_code, date_string):

    params = {
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": office_code,
        "SD_SCHUL_CODE": school_code,
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": date_string,
        "MLSV_TO_YMD": date_string,
    }

    data = request_api(API_URL, params)

    if data is None:
        return None, "error"

    if "mealServiceDietInfo" not in data:

        result = data.get("RESULT", {})

        if result.get("CODE") == "INFO-200":
            return None, "no_meal"

        return None, "error"

    try:
        rows = data["mealServiceDietInfo"][1]["row"]

    except (KeyError, IndexError, TypeError):
        return None, "no_meal"

    if not rows:
        return None, "no_meal"

    return rows[0], "success"


# ==========================================
# 메뉴 처리
# ==========================================

FRUIT_KEYWORDS = [
    "사과", "배", "포도", "귤", "감귤",
    "오렌지", "한라봉", "천혜향", "레드향",
    "딸기", "수박", "참외", "멜론",
    "바나나", "키위", "파인애플",
    "복숭아", "자두", "체리", "블루베리",
    "망고", "용과", "석류", "감",
    "홍시", "곶감", "토마토", "방울토마토",
    "자몽", "레몬", "매실", "유자",
    "코코넛", "후르츠", "과일",
]


def parse_menu(menu_text):

    if not menu_text:
        return []

    menu_text = re.sub(
        r"<br\s*/?>",
        "\n",
        menu_text,
        flags=re.IGNORECASE
    )

    menu_text = re.sub(r"<[^>]+>", "", menu_text)

    return [
        item.strip()
        for item in menu_text.splitlines()
        if item.strip()
    ]


def normalize_menu(menu):

    return re.sub(
        r"\([^)]*\)",
        "",
        menu
    ).strip()


def find_fruits(menus):

    fruits = []

    for menu in menus:

        clean_name = normalize_menu(menu)

        if any(
            keyword in clean_name
            for keyword in FRUIT_KEYWORDS
        ):

            fruits.append(menu)

    return fruits


# ==========================================
# 월별 날짜 생성
# ==========================================

def get_month_dates(selected_date):

    year = selected_date.year
    month = selected_date.month

    last_day = calendar.monthrange(year, month)[1]

    return [
        datetime(year, month, day).date()
        for day in range(1, last_day + 1)
    ]


# ==========================================
# 화면: 학교 선택
# ==========================================

st.title("🍎 우리 학교 달력별 급식")

st.caption(
    "학교를 선택하면 해당 학교의 날짜별 중식과 "
    "월별 과일 반찬 제공 현황을 확인할 수 있습니다."
)

st.divider()

st.header("1. 학교 선택")

school_name = st.text_input(
    "학교 이름을 입력하세요.",
    placeholder="예: 송탄고, 평택고등학교",
    key="fruit_school_search"
)

if "fruit_schools" not in st.session_state:
    st.session_state.fruit_schools = []

if "fruit_search_done" not in st.session_state:
    st.session_state.fruit_search_done = False


if st.button("학교 검색", key="fruit_search_button"):

    if not school_name.strip():

        st.warning("학교 이름을 입력해 주세요.")

    else:

        with st.spinner("학교 정보를 검색하고 있습니다..."):

            schools, api_error = search_schools(school_name)

        st.session_state.fruit_schools = schools
        st.session_state.fruit_search_done = True
        st.session_state.fruit_api_error = api_error


selected_school = None

if st.session_state.fruit_search_done:

    schools = st.session_state.fruit_schools

    if schools:

        school_options = {}

        for school in schools:

            label = (
                f"{school['SCHUL_NM']} "
                f"({school['LCTN_SC_NM']})"
            )

            school_options[label] = school

        selected_label = st.selectbox(
            "조회할 학교를 선택하세요.",
            options=list(school_options.keys()),
            key="fruit_school_select"
        )

        selected_school = school_options[selected_label]

        st.success(
            f"선택한 학교: {selected_school['SCHUL_NM']} "
            f"({selected_school['LCTN_SC_NM']})"
        )

    else:

        if st.session_state.get("fruit_api_error"):

            st.error(
                "학교 정보를 불러오지 못했습니다. "
                "잠시 후 다시 시도해 주세요."
            )

        else:

            st.info(
                "검색 결과가 없습니다. "
                "학교 이름을 확인해 주세요."
            )


# ==========================================
# 화면: 날짜 선택
# ==========================================

st.divider()

st.header("2. 날짜 선택")

selected_date = st.date_input(
    "급식 날짜",
    value=today,
    format="YYYY-MM-DD",
    key="fruit_selected_date"
)


# ==========================================
# 선택한 학교의 급식 조회
# ==========================================

if selected_school is None:

    st.info("먼저 학교를 검색하고 선택해 주세요.")

else:

    office_code = selected_school["ATPT_OFCDC_SC_CODE"]
    school_code = selected_school["SD_SCHUL_CODE"]
    school_title = selected_school["SCHUL_NM"]

    selected_date_string = selected_date.strftime("%Y%m%d")

    st.divider()

    st.header("3. 날짜별 급식")

    st.subheader(
        f"📅 {selected_date.strftime('%Y년 %m월 %d일')} 중식"
    )

    with st.spinner("급식 정보를 불러오는 중입니다..."):

        selected_meal, selected_status = get_meal(
            office_code,
            school_code,
            selected_date_string
        )

    if selected_status == "error":

        st.error(
            "급식 정보를 불러오지 못했습니다. "
            "잠시 후 다시 시도해 주세요."
        )

    elif selected_status == "no_meal":

        st.info("급식이 없는 날입니다.")

    else:

        with st.container(border=True):

            st.markdown(f"### 🏫 {school_title}")

            menus = parse_menu(
                selected_meal.get("DDISH_NM", "")
            )

            if menus:

                st.markdown("#### 🍽️ 오늘의 메뉴")

                for menu in menus:
                    st.markdown(f"- {menu}")

            else:

                st.info("등록된 메뉴가 없습니다.")

            calorie = selected_meal.get(
                "CAL_INFO",
                ""
            ).strip()

            fruits = find_fruits(menus)

            st.divider()

            col1, col2 = st.columns(2)

            with col1:

                st.metric(
                    "총 열량",
                    calorie if calorie else "정보 없음"
                )

            with col2:

                st.metric(
                    "과일 반찬",
                    f"{len(fruits)}개"
                )

            if fruits:

                st.success(
                    "🍎 과일 반찬: " + ", ".join(fruits)
                )

            else:

                st.caption(
                    "오늘은 확인된 과일 반찬이 없습니다."
                )

            origin = selected_meal.get(
                "ORPLC_INFO",
                ""
            ).strip()

            if origin:

                with st.expander("원산지 정보 보기"):
                    st.text(origin)


    # ======================================
    # 월별 통계
    # ======================================

    st.divider()

    st.header("4. 월별 과일 반찬 통계")

    st.caption(
        f"{school_title} · "
        f"{selected_date.year}년 {selected_date.month}월"
    )

    month_dates = get_month_dates(selected_date)

    fruit_days = []
    no_fruit_days = []
    no_meal_days = []
    error_days = []

    total_fruit_items = 0

    monthly_results = []

    progress = st.progress(0)

    for index, current_date in enumerate(month_dates):

        date_string = current_date.strftime("%Y%m%d")

        meal, status = get_meal(
            office_code,
            school_code,
            date_string
        )

        if status == "error":

            error_days.append(current_date)

            monthly_results.append({
                "날짜": current_date.strftime("%m월 %d일"),
                "급식 여부": "조회 오류",
                "과일 반찬": "-",
                "과일 개수": 0,
                "칼로리": "-",
            })

        elif status == "no_meal":

            no_meal_days.append(current_date)

            monthly_results.append({
                "날짜": current_date.strftime("%m월 %d일"),
                "급식 여부": "급식 없음",
                "과일 반찬": "-",
                "과일 개수": 0,
                "칼로리": "-",
            })

        else:

            menus = parse_menu(
                meal.get("DDISH_NM", "")
            )

            fruits = find_fruits(menus)

            calorie = meal.get(
                "CAL_INFO",
                ""
            ).strip()

            if fruits:

                fruit_days.append(current_date)

                total_fruit_items += len(fruits)

                fruit_text = ", ".join(fruits)

            else:

                no_fruit_days.append(current_date)

                fruit_text = "없음"

            monthly_results.append({
                "날짜": current_date.strftime("%m월 %d일"),
                "급식 여부": "급식 있음",
                "과일 반찬": fruit_text,
                "과일 개수": len(fruits),
                "칼로리": calorie if calorie else "정보 없음",
            })

        progress.progress(
            (index + 1) / len(month_dates)
        )

    progress.empty()


    # ======================================
    # 통계 카드
    # ======================================

    st.subheader("📊 월별 통계")

    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric(
            "과일 반찬 제공일",
            f"{len(fruit_days)}일"
        )

    with col2:

        st.metric(
            "과일 반찬 미제공일",
            f"{len(no_fruit_days)}일"
        )

    with col3:

        st.metric(
            "과일 반찬 총 개수",
            f"{total_fruit_items}개"
        )


    # ======================================
    # 전체 날짜별 표
    # ======================================

    st.subheader("📋 날짜별 급식 및 과일 반찬 현황")

    st.dataframe(
        monthly_results,
        use_container_width=True,
        hide_index=True
    )


    # ======================================
    # 과일 제공일 / 미제공일
    # ======================================

    st.divider()

    col1, col2 = st.columns(2)

    weekdays = [
        "월", "화", "수", "목", "금", "토", "일"
    ]

    with col1:

        st.subheader("🍎 과일 반찬이 나온 날")

        if fruit_days:

            fruit_table = [
                {
                    "날짜": day.strftime("%m월 %d일"),
                    "요일": weekdays[day.weekday()],
                }
                for day in fruit_days
            ]

            st.dataframe(
                fruit_table,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.info(
                "이번 달에는 과일 반찬이 제공되지 않았습니다."
            )

    with col2:

        st.subheader("🥗 과일 반찬이 나오지 않은 날")

        if no_fruit_days:

            no_fruit_table = [
                {
                    "날짜": day.strftime("%m월 %d일"),
                    "요일": weekdays[day.weekday()],
                }
                for day in no_fruit_days
            ]

            st.dataframe(
                no_fruit_table,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.info(
                "이번 달에는 급식이 제공된 모든 날에 "
                "과일 반찬이 있었습니다."
            )


    # ======================================
    # 급식 미제공일
    # ======================================

    st.divider()

    st.subheader("📌 급식이 없는 날")

    if no_meal_days:

        st.info(
            "급식이 없는 날입니다. "
            "주말이나 방학 등으로 급식 정보가 등록되지 않은 날짜입니다."
        )

        no_meal_table = [
            {
                "날짜": day.strftime("%m월 %d일"),
                "요일": weekdays[day.weekday()],
            }
            for day in no_meal_days
        ]

        st.dataframe(
            no_meal_table,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.success(
            "이번 달의 모든 날짜에 급식 정보가 등록되어 있습니다."
        )


    if error_days:

        st.warning(
            f"총 {len(error_days)}일의 데이터를 불러오지 못했습니다. "
            "해당 날짜는 통계에서 확정적으로 분류하지 않았습니다."
        )
