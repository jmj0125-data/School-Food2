
import re
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st


# ==========================================
# 기본 설정
# ==========================================

st.set_page_config(
    page_title="학교 별 급식비교",
    page_icon="🍱",
    layout="wide"
)

SCHOOL_API = "https://open.neis.go.kr/hub/schoolInfo"
MEAL_API = "https://open.neis.go.kr/hub/mealServiceDietInfo"

KST = ZoneInfo("Asia/Seoul")

st.title("🍱 학교 별 급식비교")
st.caption("나이스 교육정보 개방 포털의 데이터를 이용한 학교별 중식 비교 서비스")


# ==========================================
# API 요청 함수
# ==========================================

def request_api(url, params):
    """나이스 API 요청 및 JSON 반환"""

    try:
        response = requests.get(
            url,
            params=params,
            timeout=10
        )

        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException:
        return None

    except ValueError:
        return None


# ==========================================
# 학교 이름 검색
# ==========================================

def expand_school_name(name):
    """학교 약칭을 정식 명칭으로 확장"""

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
    """학교 이름으로 검색하고, 결과가 없으면 약칭을 확장해 재검색"""

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

        # 조회 결과가 없는 경우
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

def get_meal(school, date):
    """선택한 학교의 특정 날짜 중식 조회"""

    date_string = date.strftime("%Y%m%d")

    params = {
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": school["ATPT_OFCDC_SC_CODE"],
        "SD_SCHUL_CODE": school["SD_SCHUL_CODE"],
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": date_string,
        "MLSV_TO_YMD": date_string,
        "pSize": "1000",
        "pIndex": "1",
    }

    data = request_api(MEAL_API, params)

    if data is None:
        return None, "api_error"

    if "mealServiceDietInfo" not in data:
        result = data.get("RESULT", {})

        if result.get("CODE") == "INFO-200":
            return None, "no_meal"

        return None, "api_error"

    try:
        rows = data["mealServiceDietInfo"][1]["row"]

    except (KeyError, IndexError, TypeError):
        return None, "no_meal"

    for row in rows:
        if row.get("MLSV_YMD") == date_string:
            return row, "success"

    return None, "no_meal"


# ==========================================
# 메뉴 정리 및 반찬 추출
# ==========================================

def parse_menu(menu_text):
    """급식 메뉴를 개별 항목으로 분리"""

    if not menu_text:
        return []

    # HTML 줄바꿈 태그 처리
    menu_text = re.sub(
        r"<br\s*/?>",
        "\n",
        menu_text,
        flags=re.IGNORECASE
    )

    # HTML 태그 제거
    menu_text = re.sub(r"<[^>]+>", "", menu_text)

    menus = []

    for item in menu_text.splitlines():
        item = item.strip()

        if item:
            menus.append(item)

    return menus


def normalize_menu(item):
    """알레르기 번호를 제외하고 메뉴 이름 정리"""

    item = re.sub(r"\([^)]*\)", "", item)
    item = re.sub(r"\s+", " ", item)

    return item.strip()


def is_side_dish(item):
    """밥과 국·찌개 등 주식 및 국물류를 제외한 반찬 판별"""

    name = normalize_menu(item)

    excluded_keywords = [
        "밥",
        "죽",
        "국",
        "탕",
        "찌개",
        "전골",
        "스프",
        "수프",
        "누룽지",
        "숭늉",
        "음료",
        "주스",
        "쥬스",
        "우유",
        "요구르트",
        "요거트",
        "과일",
        "케이크",
        "쿠키",
        "빵",
        "떡",
        "아이스크림",
        "푸딩",
        "젤리",
    ]

    # 후식 및 주식에 해당하는 항목 제외
    if any(keyword in name for keyword in excluded_keywords):
        return False

    return True


# ==========================================
# 화면: 학교 검색
# ==========================================

st.header("1. 학교 선택")

school_name = st.text_input(
    "학교 이름을 입력하세요.",
    placeholder="예: 수도여고, 서울고등학교"
)

if "schools" not in st.session_state:
    st.session_state.schools = []

if "search_done" not in st.session_state:
    st.session_state.search_done = False


if st.button("학교 검색", type="primary"):
    if not school_name.strip():
        st.warning("학교 이름을 입력해 주세요.")

    else:
        with st.spinner("학교 정보를 검색하고 있습니다..."):
            schools, api_error = search_schools(school_name)

        st.session_state.schools = schools
        st.session_state.search_done = True
        st.session_state.api_error = api_error


if st.session_state.search_done:

    schools = st.session_state.schools

    if schools:
        st.success(f"총 {len(schools)}개의 학교를 찾았습니다.")

        school_options = {}

        for school in schools:
            school_label = (
                f"{school['SCHUL_NM']} "
                f"({school['LCTN_SC_NM']})"
            )

            school_options[school_label] = school

        selected_labels = st.multiselect(
            "비교할 학교를 선택하세요. (여러 학교 선택 가능)",
            options=list(school_options.keys()),
            placeholder="학교를 선택하세요."
        )

        selected_schools = [
            school_options[label]
            for label in selected_labels
        ]

    else:
        selected_schools = []

        if st.session_state.get("api_error"):
            st.error(
                "학교 정보를 불러오지 못했습니다. "
                "잠시 후 다시 시도해 주세요."
            )
        else:
            st.info(
                "해당 학교를 찾을 수 없습니다. "
                "학교 이름을 확인하거나 다른 이름으로 검색해 주세요."
            )

else:
    selected_schools = []


# ==========================================
# 화면: 날짜 선택
# ==========================================

st.divider()

st.header("2. 급식 날짜 선택")

today = datetime.now(KST).date()

selected_date = st.date_input(
    "조회할 날짜",
    value=today,
    format="YYYY-MM-DD"
)


# ==========================================
# 화면: 급식 비교
# ==========================================

st.divider()

st.header("3. 학교별 급식 비교")

if not selected_schools:
    st.info("먼저 학교를 검색하고 비교할 학교를 선택해 주세요.")

else:

    if st.button("급식 비교하기", type="primary"):

        meal_results = []

        progress = st.progress(0)

        for index, school in enumerate(selected_schools):

            meal, status = get_meal(school, selected_date)

            meal_results.append({
                "school": school,
                "meal": meal,
                "status": status,
            })

            progress.progress(
                (index + 1) / len(selected_schools)
            )

        st.session_state.meal_results = meal_results
        st.session_state.meal_date = selected_date

        progress.empty()


# ==========================================
# 급식 결과 출력
# ==========================================

if (
    "meal_results" in st.session_state
    and st.session_state.meal_date == selected_date
):

    meal_results = st.session_state.meal_results

    st.subheader(
        f"📅 {selected_date.strftime('%Y년 %m월 %d일')} 중식"
    )

    successful_results = []

    # 학교별 메뉴 카드 출력
    for result in meal_results:

        school = result["school"]
        meal = result["meal"]
        status = result["status"]

        school_name = school["SCHUL_NM"]
        region = school["LCTN_SC_NM"]

        with st.container(border=True):

            st.markdown(
                f"### 🏫 {school_name} "
                f"<small>({region})</small>",
                unsafe_allow_html=True
            )

            if status == "no_meal":
                st.info("해당 날짜에는 등록된 중식이 없습니다.")
                continue

            if status == "api_error":
                st.error(
                    "급식 정보를 불러오지 못했습니다. "
                    "잠시 후 다시 시도해 주세요."
                )
                continue

            successful_results.append(result)

            menus = parse_menu(meal.get("DDISH_NM", ""))

            if menus:
                st.markdown("**🍽️ 메뉴**")

                for menu in menus:
                    st.markdown(f"- {menu}")

            else:
                st.info("등록된 메뉴 정보가 없습니다.")

            calorie = meal.get("CAL_INFO", "").strip()

            if calorie:
                st.metric("총 열량", calorie)

            else:
                st.caption("열량 정보가 등록되지 않았습니다.")


    # ======================================
    # 학교별 반찬 빈도 비교
    # ======================================

    st.divider()

    st.header("4. 학교별 반찬 빈도 비교")

    if len(successful_results) < 2:

        st.info(
            "반찬 비교를 위해서는 급식 정보가 있는 "
            "학교가 최소 2곳 필요합니다."
        )

    else:

        # 학교별 반찬 목록
        school_side_dishes = {}

        # 전체 반찬의 학교별 등장 횟수
        dish_counter = Counter()

        for result in successful_results:

            school = result["school"]
            meal = result["meal"]

            school_label = (
                f"{school['SCHUL_NM']} "
                f"({school['LCTN_SC_NM']})"
            )

            menus = parse_menu(meal.get("DDISH_NM", ""))

            # 한 학교에서 같은 반찬이 중복되어도 1회만 계산
            side_dishes = set()

            for menu in menus:

                if is_side_dish(menu):

                    normalized = normalize_menu(menu)

                    if normalized:
                        side_dishes.add(normalized)

            school_side_dishes[school_label] = side_dishes

            dish_counter.update(side_dishes)

        if not dish_counter:

            st.info("비교할 반찬 정보가 없습니다.")

        else:

            # 가장 적은 학교에서 제공된 반찬
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
                "제공 학교 수는 해당 메뉴를 제공한 학교의 수를 의미합니다."
            )

            # 전체 반찬 빈도 표
            with st.expander("전체 반찬 제공 횟수 보기"):

                all_rows = []

                for dish, count in sorted(
                    dish_counter.items(),
                    key=lambda item: (item[1], item[0])
                ):

                    all_rows.append({
                        "반찬": dish,
                        "제공 학교 수": count,
                        "제공 학교": ", ".join([
                            school_name
                            for school_name, dishes in school_side_dishes.items()
                            if dish in dishes
                        ]),
                    })

                st.dataframe(
                    all_rows,
                    use_container_width=True,
                    hide_index=True
                )
