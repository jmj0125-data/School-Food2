
import calendar
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import streamlit as st


# ==========================================
# 기본 설정
# ==========================================

st.set_page_config(
    page_title="우리 학교 달력별 급식",
    page_icon="🍎",
    layout="wide"
)

API_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"

# 송탄고등학교
OFFICE_CODE = "J10"
SCHOOL_CODE = "7530480"

KST = ZoneInfo("Asia/Seoul")

today = datetime.now(KST).date()


# ==========================================
# 과일 판별 기준
# ==========================================

FRUIT_KEYWORDS = [
    "사과",
    "배",
    "포도",
    "귤",
    "감귤",
    "오렌지",
    "한라봉",
    "천혜향",
    "레드향",
    "딸기",
    "수박",
    "참외",
    "멜론",
    "바나나",
    "키위",
    "골드키위",
    "파인애플",
    "복숭아",
    "자두",
    "체리",
    "블루베리",
    "망고",
    "용과",
    "석류",
    "감",
    "홍시",
    "곶감",
    "토마토",
    "방울토마토",
    "자몽",
    "레몬",
    "매실",
    "유자",
    "코코넛",
    "후르츠",
    "과일",
]


# ==========================================
# API 요청
# ==========================================

@st.cache_data(ttl=3600)
def get_meal(date_string):

    params = {
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": OFFICE_CODE,
        "SD_SCHUL_CODE": SCHOOL_CODE,
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": date_string,
        "MLSV_TO_YMD": date_string,
    }

    try:
        response = requests.get(
            API_URL,
            params=params,
            timeout=10
        )

        response.raise_for_status()
        data = response.json()

    except (requests.exceptions.RequestException, ValueError):
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
# 달력 데이터 생성
# ==========================================

def get_month_dates(selected_date):

    year = selected_date.year
    month = selected_date.month

    last_day = calendar.monthrange(year, month)[1]

    return [
        date(year, month, day)
        for day in range(1, last_day + 1)
    ]


# ==========================================
# 화면 구성
# ==========================================

st.title("🍎 우리 학교 달력별 급식")

st.caption(
    "송탄고등학교의 날짜별 중식과 월별 과일 반찬 제공 현황을 확인합니다."
)

st.divider()

st.header("1. 날짜별 급식 조회")

selected_date = st.date_input(
    "날짜를 선택하세요.",
    value=today,
    format="YYYY-MM-DD"
)

selected_date_string = selected_date.strftime("%Y%m%d")

with st.spinner("급식 정보를 불러오는 중입니다..."):

    selected_meal, selected_status = get_meal(
        selected_date_string
    )


# ==========================================
# 선택한 날짜의 급식 카드
# ==========================================

st.subheader(
    f"📅 {selected_date.strftime('%Y년 %m월 %d일')} 중식"
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

        st.markdown("### 🏫 송탄고등학교")

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

        st.divider()

        col1, col2 = st.columns(2)

        with col1:

            st.metric(
                "총 열량",
                calorie if calorie else "정보 없음"
            )

        with col2:

            fruits = find_fruits(menus)

            st.metric(
                "과일 반찬",
                f"{len(fruits)}개"
            )

        if fruits:

            st.success(
                "🍎 과일 반찬: " + ", ".join(fruits)
            )

        else:

            st.caption("오늘은 확인된 과일 반찬이 없습니다.")

        origin = selected_meal.get(
            "ORPLC_INFO",
            ""
        ).strip()

        if origin:

            with st.expander("원산지 정보 보기"):
                st.text(origin)


# ==========================================
# 월별 과일 반찬 통계
# ==========================================

st.divider()

st.header("2. 월별 과일 반찬 통계")

st.caption(
    "선택한 날짜가 속한 달을 기준으로 통계를 계산합니다."
)

month_dates = get_month_dates(selected_date)

fruit_days = []
no_fruit_days = []
no_meal_days = []
error_days = []

fruit_count = 0
total_fruit_items = 0

monthly_results = []

progress = st.progress(0)

for index, current_date in enumerate(month_dates):

    date_string = current_date.strftime("%Y%m%d")

    meal, status = get_meal(date_string)

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

            fruit_count += 1
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


# ==========================================
# 통계 카드
# ==========================================

st.subheader(
    f"📊 {selected_date.year}년 {selected_date.month}월 통계"
)

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


# ==========================================
# 날짜별 현황 표
# ==========================================

st.subheader("📋 날짜별 과일 반찬 현황")

st.dataframe(
    monthly_results,
    use_container_width=True,
    hide_index=True
)


# ==========================================
# 과일 제공일 / 미제공일
# ==========================================

st.divider()

col1, col2 = st.columns(2)

with col1:

    st.subheader("🍎 과일 반찬이 나온 날")

    if fruit_days:

        fruit_table = [
            {
                "날짜": day.strftime("%m월 %d일"),
                "요일": ["월", "화", "수", "목", "금", "토", "일"][day.weekday()],
            }
            for day in fruit_days
        ]

        st.dataframe(
            fruit_table,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info("이번 달에는 과일 반찬이 제공되지 않았습니다.")


with col2:

    st.subheader("🥗 과일 반찬이 나오지 않은 날")

    if no_fruit_days:

        no_fruit_table = [
            {
                "날짜": day.strftime("%m월 %d일"),
                "요일": ["월", "화", "수", "목", "금", "토", "일"][day.weekday()],
            }
            for day in no_fruit_days
        ]

        st.dataframe(
            no_fruit_table,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info("이번 달에는 급식이 제공된 모든 날에 과일 반찬이 있었습니다.")


# ==========================================
# 급식 미제공일 안내
# ==========================================

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
            "요일": ["월", "화", "수", "목", "금", "토", "일"][day.weekday()],
        }
        for day in no_meal_days
    ]

    st.dataframe(
        no_meal_table,
        use_container_width=True,
        hide_index=True
    )

else:

    st.success("이번 달의 모든 날짜에 급식 정보가 등록되어 있습니다.")


if error_days:

    st.warning(
        f"총 {len(error_days)}일의 데이터를 불러오지 못했습니다. "
        "해당 날짜는 통계에서 확정적으로 분류하지 않았습니다."
    )

