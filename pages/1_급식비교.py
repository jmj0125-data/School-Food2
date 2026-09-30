
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st


# ==========================================
# 기본 설정
# ==========================================

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


def normalize_menu(item):

    item = re.sub(r"\([^)]*\)", "", item)
    item = re.sub(r"\s+", " ", item)

    return item.strip()


def is_side_dish(item):

    name = normalize_menu(item)

    excluded_keywords = [
        "밥", "죽", "국", "탕", "찌개",
        "전골", "스프", "수프", "누룽지",
        "숭늉", "음료", "주스", "쥬스",
        "우유", "요구르트", "요거트",
        "과일", "케이크", "쿠키", "빵",
        "떡", "아이스크림", "푸딩", "젤리",
    ]

    return not any(
        keyword in name
        for keyword in excluded_keywords
    )


# ==========================================
# 화면: 학교 검색
# ==========================================

st.title("🍱 학교별 급식 비교")

st.caption(
    "여러 학교의 중식 메뉴와 반찬 제공 현황을 비교합니다."
)

st.divider()

st.header("1. 학교 검색")

school_name = st.text_input(
    "학교 이름을 입력하세요.",
    placeholder="예: 송탄고, 평택고등학교",
    key="compare_school_search"
)

if "comparison_schools" not in st.session_state:
    st.session_state.comparison_schools = {}

if "compare_search_done" not in st.session_state:
    st.session_state.compare_search_done = False


if st.button("학교 검색", type="primary"):

    if not school_name.strip():

        st.warning("학교 이름을 입력해 주세요.")

    else:

        with st.spinner("학교 정보를 검색하고 있습니다..."):

            schools, api_error = search_schools(school_name)

        st.session_state.compare_schools = schools
        st.session_state.compare_search_done = True
        st.session_state.compare_api_error = api_error


if st.session_state.compare_search_done:

    schools = st.session_state.compare_schools

    if schools:

        school_options = {}

        for school in schools:

            label = (
                f"{school['SCHUL_NM']} "
                f"({school['LCTN_SC_NM']})"
            )

            school_options[label] = school

        selected_labels = st.multiselect(
            "비교 목록에 추가할 학교를 선택하세요.",
            options=list(school_options.keys()),
            placeholder="학교를 선택하세요."
        )

        if st.button("➕ 비교 목록에 추가"):

            added_count = 0

            for label in selected_labels:

                school = school_options[label]

                school_key = (
                    school["ATPT_OFCDC_SC_CODE"],
                    school["SD_SCHUL_CODE"]
                )

                if school_key not in st.session_state.comparison_schools:

                    st.session_state.comparison_schools[school_key] = school

                    added_count += 1

            if added_count:

                st.success(
                    f"{added_count}개 학교를 추가했습니다."
                )

            else:

                st.info(
                    "새로 추가할 학교가 없습니다. "
                    "이미 목록에 있는 학교일 수 있습니다."
                )

    else:

        if st.session_state.get("compare_api_error"):

            st.error("학교 정보를 불러오지 못했습니다.")

        else:

            st.info("검색 결과가 없습니다.")


# ==========================================
# 비교 목록 관리
# ==========================================

st.divider()

st.header("2. 비교할 학교 목록")

comparison_schools = st.session_state.comparison_schools

if comparison_schools:

    st.caption(
        f"현재 {len(comparison_schools)}개 학교가 선택되어 있습니다."
    )

    schools_to_remove = []

    for school_key, school in comparison_schools.items():

        col1, col2 = st.columns([5, 1])

        with col1:

            st.markdown(
                f"🏫 **{school['SCHUL_NM']}** "
                f"({school['LCTN_SC_NM']})"
            )

        with col2:

            if st.button(
                "삭제",
                key=f"remove_{school_key[0]}_{school_key[1]}"
            ):

                schools_to_remove.append(school_key)

    for school_key in schools_to_remove:

        del st.session_state.comparison_schools[school_key]

    if schools_to_remove:
        st.rerun()

    if st.button("🗑️ 비교 목록 전체 삭제"):

        st.session_state.comparison_schools = {}
        st.session_state.pop("comparison_results", None)

        st.rerun()

else:

    st.info("비교할 학교를 먼저 추가해 주세요.")


# ==========================================
# 날짜 선택
# ==========================================

st.divider()

st.header("3. 비교 날짜 선택")

selected_date = st.date_input(
    "급식 날짜",
    value=today,
    format="YYYY-MM-DD",
    key="compare_date"
)


# ==========================================
# 급식 비교 실행
# ==========================================

selected_schools = list(
    st.session_state.comparison_schools.values()
)

if not selected_schools:

    st.info("비교 목록에 학교를 추가해 주세요.")

elif len(selected_schools) < 2:

    st.info("학교별 비교를 위해서는 최소 2개 학교가 필요합니다.")

else:

    if st.button("🔍 급식 비교하기", type="primary"):

        results = []

        progress = st.progress(0)

        for index, school in enumerate(selected_schools):

            meal, status = get_meal(
                school,
                selected_date
            )

            results.append({
                "school": school,
                "meal": meal,
                "status": status,
            })

            progress.progress(
                (index + 1) / len(selected_schools)
            )

        progress.empty()

        st.session_state.comparison_results = results
        st.session_state.comparison_date = selected_date


# ==========================================
# 비교 결과 출력
# ==========================================

if (
    "comparison_results" in st.session_state
    and st.session_state.comparison_date == selected_date
):

    results = st.session_state.comparison_results

    st.divider()

    st.header(
        f"📊 {selected_date.strftime('%Y년 %m월 %d일')} 급식 비교 결과"
    )

    successful_results = []

    for result in results:

        school = result["school"]
        meal = result["meal"]
        status = result["status"]

        with st.container(border=True):

            st.markdown(
                f"### 🏫 {school['SCHUL_NM']} "
                f"({school['LCTN_SC_NM']})"
            )

            if status == "no_meal":

                st.info("급식이 없는 날입니다.")
                continue

            if status == "error":

                st.error("급식 정보를 불러오지 못했습니다.")
                continue

            successful_results.append(result)

            menus = parse_menu(
                meal.get("DDISH_NM", "")
            )

            st.markdown("**🍽️ 메뉴**")

            for menu in menus:
                st.markdown(f"- {menu}")

            calorie = meal.get(
                "CAL_INFO",
                ""
            ).strip()

            st.metric(
                "총 열량",
                calorie if calorie else "정보 없음"
            )


    # ======================================
    # 반찬 빈도 비교
    # ======================================

    st.divider()

    st.header("4. 학교별 반찬 빈도 비교")

    if len(successful_results) < 2:

        st.info(
            "반찬 비교를 위해서는 급식 정보가 있는 학교가 최소 2곳 필요합니다."
        )

    else:

        school_side_dishes = {}
        dish_counter = {}

        for result in successful_results:

            school = result["school"]
            meal = result["meal"]

            school_label = (
                f"{school['SCHUL_NM']} "
                f"({school['LCTN_SC_NM']})"
            )

            menus = parse_menu(
                meal.get("DDISH_NM", "")
            )

            side_dishes = set()

            for menu in menus:

                if is_side_dish(menu):

                    normalized = normalize_menu(menu)

                    if normalized:
                        side_dishes.add(normalized)

            school_side_dishes[school_label] = side_dishes

            for dish in side_dishes:

                dish_counter[dish] = (
                    dish_counter.get(dish, 0) + 1
                )


        if not dish_counter:

            st.info("비교할 반찬 정보가 없습니다.")

        else:

            min_count = min(dish_counter.values())

            rare_dishes = sorted([
                dish
                for dish, count in dish_counter.items()
                if count == min_count
            ])

            st.markdown(
                f"**가장 적게 제공된 반찬: {min_count}개 학교**"
            )

            rare_rows = []

            for dish in rare_dishes:

                serving_schools = [
                    school_name
                    for school_name, dishes in school_side_dishes.items()
                    if dish in dishes
                ]

                rare_rows.append({
                    "반찬": dish,
                    "제공 학교 수": f"{min_count} / {len(successful_results)}",
                    "제공 학교": ", ".join(serving_schools),
                })

            st.dataframe(
                rare_rows,
                use_container_width=True,
                hide_index=True
            )

            st.caption(
                "※ 밥, 국·찌개, 음료 및 후식류는 반찬 비교에서 제외합니다. "
                "한 학교에서 같은 반찬이 중복되어도 한 번만 집계합니다."
            )

            with st.expander("전체 반찬 제공 횟수 보기"):

                all_rows = []

                for dish, count in sorted(
                    dish_counter.items(),
                    key=lambda item: (item[1], item[0])
                ):

                    serving_schools = [
                        school_name
                        for school_name, dishes in school_side_dishes.items()
                        if dish in dishes
                    ]

                    all_rows.append({
                        "반찬": dish,
                        "제공 학교 수": count,
                        "제공 학교": ", ".join(serving_schools),
                    })

                st.dataframe(
                    all_rows,
                    use_container_width=True,
                    hide_index=True
                )
