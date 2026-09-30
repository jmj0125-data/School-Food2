
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st


# ==========================================
# 기본 설정
# ==========================================

st.set_page_config(
    page_title="학교 별 급식",
    page_icon="🍱",
    layout="wide"
)

SCHOOL_API = "https://open.neis.go.kr/hub/schoolInfo"
MEAL_API = "https://open.neis.go.kr/hub/mealServiceDietInfo"

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
# 학교 이름 확장
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


# ==========================================
# 학교 검색
# ==========================================

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
# 급식 조회
# ==========================================

def get_meal(school, selected_date):

    date_string = selected_date.strftime("%Y%m%d")

    params = {
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": school["ATPT_OFCDC_SC_CODE"],
        "SD_SCHUL_CODE": school["SD_SCHUL_CODE"],
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": date_string,
        "MLSV_TO_YMD": date_string,
    }

    data = request_api(MEAL_API, params)

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


# ==========================================
# 화면
# ==========================================

st.title("🍱 학교 별 급식")
st.caption("학교를 검색하고 원하는 날짜의 중식 메뉴를 확인하세요.")

st.divider()

st.header("1. 학교 검색")

school_name = st.text_input(
    "학교 이름",
    placeholder="예: 송탄고, 평택고등학교"
)

if "main_schools" not in st.session_state:
    st.session_state.main_schools = []

if "main_search_done" not in st.session_state:
    st.session_state.main_search_done = False


if st.button("학교 검색", type="primary"):

    if not school_name.strip():

        st.warning("학교 이름을 입력해 주세요.")

    else:

        with st.spinner("학교 정보를 검색하고 있습니다..."):

            schools, api_error = search_schools(school_name)

        st.session_state.main_schools = schools
        st.session_state.main_search_done = True
        st.session_state.main_api_error = api_error


selected_school = None

if st.session_state.main_search_done:

    schools = st.session_state.main_schools

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
            options=list(school_options.keys())
        )

        selected_school = school_options[selected_label]

    else:

        if st.session_state.get("main_api_error"):

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
# 날짜 선택 및 급식 출력
# ==========================================

st.divider()

st.header("2. 날짜별 중식 조회")

selected_date = st.date_input(
    "급식 날짜",
    value=today,
    format="YYYY-MM-DD"
)

if selected_school is None:

    st.info("먼저 학교를 검색하고 선택해 주세요.")

else:

    if st.button("급식 조회", type="primary"):

        with st.spinner("급식 정보를 불러오는 중입니다..."):

            meal, status = get_meal(
                selected_school,
                selected_date
            )

        st.session_state.main_meal = meal
        st.session_state.main_meal_status = status
        st.session_state.main_meal_school = (
            selected_school["ATPT_OFCDC_SC_CODE"],
            selected_school["SD_SCHUL_CODE"]
        )
        st.session_state.main_meal_date = selected_date


    current_school_key = (
        selected_school["ATPT_OFCDC_SC_CODE"],
        selected_school["SD_SCHUL_CODE"]
    )

    if (
        "main_meal_status" in st.session_state
        and st.session_state.get("main_meal_school") == current_school_key
        and st.session_state.get("main_meal_date") == selected_date
    ):

        meal = st.session_state.main_meal
        status = st.session_state.main_meal_status

        st.divider()

        st.subheader(
            f"📅 {selected_date.strftime('%Y년 %m월 %d일')} 중식"
        )

        if status == "error":

            st.error(
                "급식 정보를 불러오지 못했습니다. "
                "잠시 후 다시 시도해 주세요."
            )

        elif status == "no_meal":

            st.info("급식이 없는 날입니다.")

        else:

            with st.container(border=True):

                st.markdown(
                    f"### 🏫 {selected_school['SCHUL_NM']}"
                )

                menus = parse_menu(
                    meal.get("DDISH_NM", "")
                )

                st.markdown("#### 🍽️ 오늘의 메뉴")

                if menus:

                    for menu in menus:
                        st.markdown(f"- {menu}")

                else:

                    st.info("등록된 메뉴가 없습니다.")

                st.divider()

                calorie = meal.get(
                    "CAL_INFO",
                    ""
                ).strip()

                st.metric(
                    "총 열량",
                    calorie if calorie else "정보 없음"
                )

                origin = meal.get(
                    "ORPLC_INFO",
                    ""
                ).strip()

                if origin:

                    with st.expander("원산지 정보 보기"):
                        st.text(origin)
