import re
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st


# =========================================================
# 기본 설정
# =========================================================
st.set_page_config(
    page_title="학교별 급식 반찬 빈도",
    page_icon="🍱",
    layout="wide",
)

SCHOOL_API_URL = "https://open.neis.go.kr/hub/schoolInfo"
MEAL_API_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"

st.title("🍱 학교별 급식 반찬 빈도")
st.caption("여러 학교를 선택하고, 한 달 동안 적게 나온 반찬부터 비교해 보세요.")


# =========================================================
# NEIS API
# =========================================================
def get_neis_key():
    """Streamlit Secrets에 NEIS_KEY가 있으면 사용."""
    try:
        return st.secrets["NEIS_KEY"]
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def search_schools(school_name):
    """학교 이름 일부를 이용해 학교 목록 검색."""
    params = {
        "Type": "json",
        "SCHUL_NM": school_name,
        "pSize": 5,
        "pIndex": 1,
    }

    key = get_neis_key()
    if key:
        params["KEY"] = key

    try:
        response = requests.get(SCHOOL_API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        return [], f"학교 검색 중 오류가 발생했습니다: {e}"
    except ValueError:
        return [], "학교 검색 결과를 읽을 수 없습니다."

    if "schoolInfo" not in data or len(data["schoolInfo"]) < 2:
        return [], None

    rows = data["schoolInfo"][1].get("row", [])

    schools = []
    for row in rows:
        schools.append(
            {
                "학교명": row.get("SCHUL_NM", ""),
                "교육청코드": row.get("ATPT_OFCDC_SC_CODE", ""),
                "학교코드": row.get("SD_SCHUL_CODE", ""),
                "지역": row.get("LCTN_SC_NM", ""),
                "학교급": row.get("SCHUL_KND_SC_NM", ""),
            }
        )

    return schools, None


@st.cache_data(ttl=3600, show_spinner=False)
def get_meals(
    office_code,
    school_code,
    start_ymd,
    end_ymd,
):
    """지정한 학교의 중식 급식 정보를 가져온다."""
    params = {
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": office_code,
        "SD_SCHUL_CODE": school_code,
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": start_ymd,
        "MLSV_TO_YMD": end_ymd,
        "pSize": 1000,
        "pIndex": 1,
    }

    key = get_neis_key()
    if key:
        params["KEY"] = key

    try:
        response = requests.get(MEAL_API_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        return [], 0, f"급식 정보를 가져오는 중 오류가 발생했습니다: {e}"
    except ValueError:
        return [], 0, "급식 API 응답을 읽을 수 없습니다."

    if "mealServiceDietInfo" not in data:
        result_code = None
        try:
            result_code = data.get("RESULT", {}).get("CODE")
        except Exception:
            pass

        if result_code == "INFO-200":
            return [], 0, None

        return [], 0, f"NEIS 응답 오류: {result_code or '알 수 없는 오류'}"

    meal_info = data["mealServiceDietInfo"]

    total_count = 0
    try:
        total_count = int(meal_info[0]["head"][0].get("list_total_count", 0))
    except Exception:
        pass

    rows = []
    if len(meal_info) > 1:
        rows = meal_info[1].get("row", [])

    # 인증키가 있으면 pSize=1000으로 한 번에 충분히 가져오지만,
    # 혹시 1000건을 넘는 경우를 대비해 페이지를 추가로 요청한다.
    if key and total_count > len(rows):
        pages = (total_count + 999) // 1000

        for page in range(2, pages + 1):
            page_params = params.copy()
            page_params["pIndex"] = page

            try:
                page_response = requests.get(
                    MEAL_API_URL,
                    params=page_params,
                    timeout=15,
                )
                page_response.raise_for_status()
                page_data = page_response.json()

                if "mealServiceDietInfo" in page_data and len(page_data["mealServiceDietInfo"]) > 1:
                    rows.extend(page_data["mealServiceDietInfo"][1].get("row", []))
            except Exception:
                break

    return rows, total_count, None


# =========================================================
# 메뉴 정리
# =========================================================
def clean_menu_name(menu):
    """급식 메뉴 뒤의 알레르기 번호를 제거한다."""
    menu = str(menu).strip()

    # NEIS 메뉴의 <br>, <br/>, <br /> 처리
    menu = re.sub(r"<br\s*/?>", "\n", menu, flags=re.IGNORECASE)

    # HTML 태그 제거
    menu = re.sub(r"<[^>]+>", "", menu)

    # 줄바꿈/공백 정리
    menu = re.sub(r"\s+", " ", menu).strip()

    # 마지막의 알레르기 번호 제거
    # 예: (1,2,5,6,13,15,16,18), (5.6), (1.5.6)
    menu = re.sub(
        r"\s*\((?:\d+(?:[.,]\d+)*)\)\s*$",
        "",
        menu,
    ).strip()

    return menu


def split_menus(ddish_nm):
    """DDISH_NM을 개별 메뉴로 분리한다."""
    text = re.sub(r"<br\s*/?>", "\n", str(ddish_nm), flags=re.IGNORECASE)

    result = []
    for item in re.split(r"\n+", text):
        item = clean_menu_name(item)

        if not item:
            continue

        # 불필요한 공백 정리
        item = re.sub(r"\s+", " ", item).strip()

        if item:
            result.append(item)

    return result


# =========================================================
# '반찬 중심' 필터
# =========================================================
def is_excluded_menu(menu):
    """
    반찬 빈도를 볼 때 제외할 가능성이 높은 메뉴.
    학교마다 명칭이 달라 완벽한 분류가 아니므로
    화면에서 제외 여부를 직접 켜고 끌 수 있게 한다.
    """
    normalized = re.sub(r"\s+", "", menu)

    # 주식류
    staple_keywords = [
        "밥",
        "죽",
        "리조또",
        "볶음밥",
        "비빔밥",
        "덮밥",
        "주먹밥",
        "김밥",
        "국수",
        "우동",
        "소바",
        "파스타",
        "스파게티",
        "짜장면",
        "짬뽕",
    ]

    # 국/탕/찌개/전골/스프류
    soup_keywords = [
        "국",
        "탕",
        "찌개",
        "전골",
        "스프",
        "수프",
        "육개장",
        "된장국",
        "미역국",
        "콩나물국",
        "북엇국",
        "김치국",
        "순두부찌개",
    ]

    # 김치류
    kimchi_keywords = [
        "김치",
        "깍두기",
        "겉절이",
        "백김치",
        "나박김치",
        "열무김치",
        "총각김치",
        "배추김치",
    ]

    # 후식/음료류
    dessert_keywords = [
        "과일",
        "사과",
        "배",
        "귤",
        "오렌지",
        "바나나",
        "포도",
        "수박",
        "딸기",
        "키위",
        "요구르트",
        "요거트",
        "주스",
        "쥬스",
        "음료",
        "우유",
        "푸딩",
        "떡",
        "빵",
        "쿠키",
        "케이크",
        "아이스크림",
        "후식",
    ]

    all_keywords = (
        staple_keywords
        + soup_keywords
        + kimchi_keywords
        + dessert_keywords
    )

    return any(keyword in normalized for keyword in all_keywords)


def make_frequency_table(rows, exclude_basic_items=True):
    """급식 행을 반찬별 등장 횟수 표로 변환한다."""
    counts = {}

    for row in rows:
        menu_text = row.get("DDISH_NM", "")
        menus = split_menus(menu_text)

        for menu in menus:
            if exclude_basic_items and is_excluded_menu(menu):
                continue

            counts[menu] = counts.get(menu, 0) + 1

    if not counts:
        return pd.DataFrame(columns=["반찬", "등장 횟수"])

    df = pd.DataFrame(
        [
            {"반찬": menu, "등장 횟수": count}
            for menu, count in counts.items()
        ]
    )

    # 적게 나온 반찬이 먼저 오고, 같은 횟수에서는 가나다순
    df = df.sort_values(
        by=["등장 횟수", "반찬"],
        ascending=[True, True],
        kind="stable",
    ).reset_index(drop=True)

    return df


# =========================================================
# 날짜 설정
# =========================================================
today = date.today()
default_start = today - timedelta(days=30)
default_end = today - timedelta(days=1)

st.sidebar.header("🔎 조회 설정")

start_date = st.sidebar.date_input(
    "조회 시작일",
    value=default_start,
)

end_date = st.sidebar.date_input(
    "조회 종료일",
    value=default_end,
)

exclude_basic_items = st.sidebar.checkbox(
    "밥·국/찌개·김치·후식류 제외",
    value=True,
    help="반찬 중심으로 보기 위한 기능입니다. 학교별 메뉴 이름에 따라 일부 항목은 분류가 다를 수 있습니다.",
)

if start_date > end_date:
    st.error("조회 시작일은 종료일보다 빠르거나 같아야 합니다.")
    st.stop()


# =========================================================
# 학교 검색
# =========================================================
st.subheader("1. 학교 찾기")

search_text = st.text_input(
    "학교 이름을 입력하세요",
    placeholder="예: 송탄고",
)

schools = []

if search_text.strip():
    with st.spinner("학교를 검색하고 있습니다..."):
        schools, school_error = search_schools(search_text.strip())

    if school_error:
        st.error(school_error)
    elif not schools:
        st.info("검색 결과가 없습니다. 학교 이름의 일부를 다시 입력해 보세요.")
    else:
        st.caption(f"검색 결과 {len(schools)}개")

        school_labels = [
            f"{school['학교명']}  ·  {school['지역']}  ·  {school['학교급']}"
            for school in schools
        ]

        label_to_school = dict(zip(school_labels, schools))

        selected_labels = st.multiselect(
            "조회할 학교를 선택하세요. 여러 학교를 동시에 선택할 수 있습니다.",
            options=school_labels,
        )

        selected_schools = [
            label_to_school[label]
            for label in selected_labels
        ]
else:
    selected_schools = []
    st.info("학교 이름의 일부를 입력하면 검색 결과가 나타납니다.")


# =========================================================
# 조회
# =========================================================
st.divider()
st.subheader("2. 학교별 반찬 빈도")

if not selected_schools:
    st.info("먼저 조회할 학교를 하나 이상 선택하세요.")
    st.stop()

period_text = (
    f"{start_date.strftime('%Y.%m.%d')} ~ "
    f"{end_date.strftime('%Y.%m.%d')}"
)

st.write(f"**조회 기간:** {period_text}")
st.write(f"**선택한 학교:** {len(selected_schools)}곳")

if not get_neis_key():
    st.warning(
        "현재 NEIS_KEY가 설정되어 있지 않습니다. "
        "학교 검색은 가능하지만, 급식 API는 인증키가 없으면 최대 5건만 반환될 수 있습니다. "
        "한 달 전체 급식을 정확히 조회하려면 Streamlit Secrets에 NEIS_KEY를 설정하세요."
    )

start_ymd = start_date.strftime("%Y%m%d")
end_ymd = end_date.strftime("%Y%m%d")

results = []
frequency_tables = {}

progress = st.progress(0)
status = st.empty()

for index, school in enumerate(selected_schools):
    school_name = school["학교명"]
    status.write(f"급식 정보를 가져오는 중: **{school_name}**")

    rows, total_count, error = get_meals(
        school["교육청코드"],
        school["학교코드"],
        start_ymd,
        end_ymd,
    )

    if error:
        results.append(
            {
                "학교명": school_name,
                "상태": "오류",
                "급식일수": 0,
                "가장 적게 나온 반찬": "-",
                "횟수": "-",
                "오류": error,
            }
        )
    elif not rows:
        results.append(
            {
                "학교명": school_name,
                "상태": "급식 없음",
                "급식일수": 0,
                "가장 적게 나온 반찬": "-",
                "횟수": "-",
                "오류": "",
            }
        )
    else:
        frequency_df = make_frequency_table(
            rows,
            exclude_basic_items=exclude_basic_items,
        )

        frequency_tables[school_name] = frequency_df

        if frequency_df.empty:
            results.append(
                {
                    "학교명": school_name,
                    "상태": "메뉴 없음",
                    "급식일수": len(rows),
                    "가장 적게 나온 반찬": "-",
                    "횟수": "-",
                    "오류": "",
                }
            )
        else:
            min_count = int(frequency_df["등장 횟수"].min())
            rarest = frequency_df.loc[
                frequency_df["등장 횟수"] == min_count,
                "반찬",
            ].tolist()

            results.append(
                {
                    "학교명": school_name,
                    "상태": "정상",
                    "급식일수": len(rows),
                    "가장 적게 나온 반찬": ", ".join(rarest[:5])
                    + (" ..." if len(rarest) > 5 else ""),
                    "횟수": min_count,
                    "오류": "",
                }
            )

    progress.progress((index + 1) / len(selected_schools))

status.empty()
progress.empty()


# =========================================================
# 한눈에 보는 요약
# =========================================================
summary_df = pd.DataFrame(results)

if not summary_df.empty:
    st.markdown("### 📊 학교별 가장 적게 나온 반찬")

    display_summary = summary_df[
        ["학교명", "상태", "급식일수", "가장 적게 나온 반찬", "횟수"]
    ].copy()

    # 정상 학교는 최저 횟수가 적은 학교부터 표시
    display_summary["_sort"] = pd.to_numeric(
        display_summary["횟수"],
        errors="coerce",
    )

    display_summary = (
        display_summary
        .sort_values(
            by=["_sort", "학교명"],
            ascending=[True, True],
            na_position="last",
        )
        .drop(columns="_sort")
        .reset_index(drop=True)
    )

    st.dataframe(
        display_summary,
        use_container_width=True,
        hide_index=True,
    )


# =========================================================
# 학교별 상세 결과
# =========================================================
st.markdown("### 🍽️ 학교별 상세 반찬 목록")

for school in selected_schools:
    school_name = school["학교명"]

    if school_name not in frequency_tables:
        continue

    df = frequency_tables[school_name]

    with st.expander(f"🏫 {school_name}", expanded=True):
        if df.empty:
            st.info("조건에 맞는 반찬 데이터가 없습니다.")
            continue

        st.caption(
            f"총 {len(df)}종의 메뉴가 확인되었습니다. "
            "등장 횟수가 적은 메뉴부터 정렬되어 있습니다."
        )

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "반찬": st.column_config.TextColumn(
                    "반찬",
                    width="large",
                ),
                "등장 횟수": st.column_config.NumberColumn(
                    "등장 횟수",
                    format="%d회",
                ),
            },
        )

        min_count = int(df["등장 횟수"].min())
        rarest_df = df[df["등장 횟수"] == min_count]

        st.write(
            f"**가장 적게 나온 메뉴: {min_count}회**  "
            f"({', '.join(rarest_df['반찬'].tolist())})"
        )


# =========================================================
# 안내
# =========================================================
st.divider()

with st.expander("ℹ️ 집계 방법"):
    st.markdown(
        """
- NEIS 학교기본정보에서 학교 이름 일부를 검색합니다.
- 선택한 학교의 교육청 코드와 학교 코드를 이용해 급식 정보를 찾습니다.
- `MMEAL_SC_CODE=2`를 사용하여 **중식**만 조회합니다.
- `DDISH_NM`의 `<br/>`를 기준으로 메뉴를 나눕니다.
- 메뉴 뒤에 붙은 알레르기 번호는 제거합니다.
- 기본 설정에서는 **밥·국/찌개·김치·후식류를 제외**하여 반찬 중심으로 집계합니다.
- 같은 반찬이 조회 기간에 몇 번 등장했는지 세고, **적게 나온 순서대로 정렬**합니다.
        """
    )

with st.expander("🔑 Streamlit Cloud에서 NEIS 인증키 설정"):
    st.markdown(
        """
급식 데이터를 한 달 전체 조회하려면 Streamlit Cloud의 **Settings → Secrets**에 다음처럼 입력하세요.

```toml
NEIS_KEY = "여기에_나이스_인증키"
```

인증키가 설정되면 급식 조회에서 `pSize=1000`을 사용할 수 있어 한 달치 데이터를 충분히 가져올 수 있습니다.
        """
    )
