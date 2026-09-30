import re
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st


st.set_page_config(
    page_title="학교별 급식 반찬 비교",
    page_icon="🍱",
    layout="wide",
)

SCHOOL_API_URL = "https://open.neis.go.kr/hub/schoolInfo"
MEAL_API_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"


# ---------------------------------------------------------
# NEIS 인증키
# ---------------------------------------------------------
def get_neis_key():
    """Streamlit Secrets에 저장한 NEIS_KEY를 가져온다."""
    return st.secrets.get("NEIS_KEY", "")


# ---------------------------------------------------------
# 학교 검색
# ---------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def search_schools(keyword):
    params = {
        "Type": "json",
        "SCHUL_NM": keyword,
        "pSize": 5,
        "pIndex": 1,
    }

    key = get_neis_key()
    if key:
        params["KEY"] = key

    try:
        r = requests.get(SCHOOL_API_URL, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return [], f"학교 검색 오류: {e}"

    if "schoolInfo" not in data or len(data["schoolInfo"]) < 2:
        return [], None

    rows = data["schoolInfo"][1].get("row", [])

    schools = []
    for row in rows:
        schools.append({
            "학교명": row.get("SCHUL_NM", ""),
            "교육청코드": row.get("ATPT_OFCDC_SC_CODE", ""),
            "학교코드": row.get("SD_SCHUL_CODE", ""),
            "지역": row.get("LCTN_SC_NM", ""),
            "학교급": row.get("SCHUL_KND_SC_NM", ""),
        })

    return schools, None


# ---------------------------------------------------------
# 급식 조회
# ---------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def get_meals(office_code, school_code, start_ymd, end_ymd):
    key = get_neis_key()

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

    if key:
        params["KEY"] = key

    try:
        r = requests.get(MEAL_API_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return [], 0, f"급식 조회 오류: {e}"

    if "mealServiceDietInfo" not in data:
        code = data.get("RESULT", {}).get("CODE", "")
        if code == "INFO-200":
            return [], 0, None
        return [], 0, f"NEIS 응답 오류: {code or '알 수 없음'}"

    info = data["mealServiceDietInfo"]

    total_count = 0
    try:
        total_count = int(info[0]["head"][0]["list_total_count"])
    except Exception:
        pass

    rows = []
    if len(info) > 1:
        rows = info[1].get("row", [])

    # 인증키가 있고 1000건보다 많으면 추가 페이지 조회
    if key and total_count > len(rows):
        pages = (total_count + 999) // 1000

        for page in range(2, pages + 1):
            page_params = params.copy()
            page_params["pIndex"] = page

            try:
                pr = requests.get(
                    MEAL_API_URL,
                    params=page_params,
                    timeout=15,
                )
                pr.raise_for_status()
                pdata = pr.json()

                if (
                    "mealServiceDietInfo" in pdata
                    and len(pdata["mealServiceDietInfo"]) > 1
                ):
                    rows.extend(
                        pdata["mealServiceDietInfo"][1].get("row", [])
                    )
            except Exception:
                break

    return rows, total_count, None


# ---------------------------------------------------------
# 메뉴 정리
# ---------------------------------------------------------
def clean_menu(menu):
    menu = str(menu).strip()

    menu = re.sub(
        r"<br\s*/?>",
        "\n",
        menu,
        flags=re.IGNORECASE,
    )
    menu = re.sub(r"<[^>]+>", "", menu)
    menu = re.sub(r"\s+", " ", menu).strip()

    # 알레르기 번호 제거
    menu = re.sub(
        r"\s*\((?:\d+(?:[.,]\d+)*)\)\s*$",
        "",
        menu,
    ).strip()

    return menu


def split_menus(ddish_nm):
    text = re.sub(
        r"<br\s*/?>",
        "\n",
        str(ddish_nm),
        flags=re.IGNORECASE,
    )

    menus = []

    for item in re.split(r"\n+", text):
        item = clean_menu(item)
        if item:
            menus.append(item)

    return menus


# ---------------------------------------------------------
# 반찬 분류
# ---------------------------------------------------------
def is_basic_menu(menu):
    normalized = re.sub(r"\s+", "", menu)

    keywords = [
        # 밥/주식
        "밥", "죽", "리조또", "볶음밥", "비빔밥", "덮밥",
        "주먹밥", "김밥", "국수", "우동", "소바",
        "파스타", "스파게티", "짜장면", "짬뽕",

        # 국/찌개/탕
        "국", "탕", "찌개", "전골", "스프", "수프",
        "육개장", "된장국", "미역국", "콩나물국",
        "북엇국", "김치국", "순두부찌개",

        # 김치
        "김치", "깍두기", "겉절이", "백김치", "나박김치",
        "열무김치", "총각김치", "배추김치",

        # 후식/음료
        "과일", "사과", "배", "귤", "오렌지", "바나나",
        "포도", "수박", "딸기", "키위", "요구르트",
        "요거트", "주스", "쥬스", "음료", "우유",
        "푸딩", "떡", "빵", "쿠키", "케이크",
        "아이스크림", "후식",
    ]

    return any(word in normalized for word in keywords)


def make_frequency(rows, exclude_basic=True):
    counts = {}

    for row in rows:
        for menu in split_menus(row.get("DDISH_NM", "")):
            if exclude_basic and is_basic_menu(menu):
                continue
            counts[menu] = counts.get(menu, 0) + 1

    return counts


# ---------------------------------------------------------
# 화면
# ---------------------------------------------------------
st.title("🍱 학교별 급식 반찬 비교")
st.caption(
    "여러 학교를 선택하면 같은 반찬의 등장 횟수를 학교별로 나란히 비교합니다."
)

st.sidebar.header("조회 설정")

today = date.today()

default_end = today - timedelta(days=1)
default_start = default_end - timedelta(days=30)

start_date = st.sidebar.date_input(
    "조회 시작일",
    value=default_start,
)

end_date = st.sidebar.date_input(
    "조회 종료일",
    value=default_end,
)

exclude_basic = st.sidebar.checkbox(
    "밥·국/찌개·김치·후식류 제외",
    value=True,
)

if start_date > end_date:
    st.error("조회 시작일이 종료일보다 늦습니다.")
    st.stop()


# ---------------------------------------------------------
# 학교 검색
# ---------------------------------------------------------
st.subheader("① 학교 선택")

keyword = st.text_input(
    "학교 이름을 검색하세요",
    placeholder="예: 송탄고",
)

selected_schools = []

if keyword.strip():
    schools, error = search_schools(keyword.strip())

    if error:
        st.error(error)
    elif not schools:
        st.info("검색 결과가 없습니다.")
    else:
        options = [
            f"{s['학교명']} · {s['지역']} · {s['학교급']}"
            for s in schools
        ]

        option_map = dict(zip(options, schools))

        selected = st.multiselect(
            "비교할 학교를 선택하세요. 여러 학교를 선택할 수 있습니다.",
            options=options,
        )

        selected_schools = [
            option_map[x]
            for x in selected
        ]
else:
    st.info("예: 송탄고, 평택고, 한광고처럼 학교 이름의 일부를 입력하세요.")


if not selected_schools:
    st.stop()


# ---------------------------------------------------------
# 급식 데이터 조회
# ---------------------------------------------------------
st.divider()
st.subheader("② 학교별 급식 데이터 불러오기")

start_ymd = start_date.strftime("%Y%m%d")
end_ymd = end_date.strftime("%Y%m%d")

all_counts = {}
school_meal_days = {}
errors = {}

progress = st.progress(0)

for i, school in enumerate(selected_schools):
    name = school["학교명"]

    rows, total, error = get_meals(
        school["교육청코드"],
        school["학교코드"],
        start_ymd,
        end_ymd,
    )

    if error:
        errors[name] = error
    else:
        all_counts[name] = make_frequency(
            rows,
            exclude_basic=exclude_basic,
        )
        school_meal_days[name] = len(rows)

    progress.progress((i + 1) / len(selected_schools))

progress.empty()

if errors:
    for name, error in errors.items():
        st.error(f"{name}: {error}")

if not all_counts:
    st.warning("조회된 급식 데이터가 없습니다.")
    st.stop()


# ---------------------------------------------------------
# 학교별 요약
# ---------------------------------------------------------
st.subheader("③ 학교별 비교")

st.caption(
    f"조회 기간: {start_date.strftime('%Y.%m.%d')} ~ "
    f"{end_date.strftime('%Y.%m.%d')}"
)

summary_rows = []

for school_name, counts in all_counts.items():
    if counts:
        min_count = min(counts.values())
        rarest = sorted(
            [menu for menu, count in counts.items() if count == min_count]
        )

        summary_rows.append({
            "학교": school_name,
            "급식일수": school_meal_days.get(school_name, 0),
            "가장 적게 나온 횟수": min_count,
            "가장 적게 나온 반찬": ", ".join(rarest),
        })

summary = pd.DataFrame(summary_rows)

if not summary.empty:
    summary = summary.sort_values(
        ["가장 적게 나온 횟수", "학교"],
        ascending=[True, True],
    )

    st.dataframe(
        summary,
        use_container_width=True,
        hide_index=True,
        column_config={
            "급식일수": st.column_config.NumberColumn(
                "급식일수",
                format="%d일",
            ),
            "가장 적게 나온 횟수": st.column_config.NumberColumn(
                "가장 적게 나온 횟수",
                format="%d회",
            ),
        },
    )


# ---------------------------------------------------------
# 핵심 비교표
# ---------------------------------------------------------
st.subheader("④ 반찬별 학교 비교")

st.caption(
    "각 행은 하나의 반찬입니다. 숫자가 작을수록 해당 학교에서 드물게 나온 반찬입니다."
)

# 모든 학교에 등장한 반찬뿐 아니라,
# 선택한 학교 중 어느 한 곳에라도 등장한 반찬을 모두 표시
all_menus = set()

for counts in all_counts.values():
    all_menus.update(counts.keys())

comparison_rows = []

for menu in all_menus:
    row = {"반찬": menu}

    values = []

    for school_name in all_counts:
        count = all_counts[school_name].get(menu, 0)
        row[school_name] = count
        values.append(count)

    # 선택한 학교들의 합계와 최솟값을 정렬용으로 저장
    row["_최소횟수"] = min(values)
    row["_합계"] = sum(values)

    comparison_rows.append(row)

comparison = pd.DataFrame(comparison_rows)

if comparison.empty:
    st.info("비교할 반찬 데이터가 없습니다.")
else:
    # 가장 적게 나온 학교의 횟수가 작은 반찬부터,
    # 그 다음 전체 학교 합계가 작은 순서
    comparison = comparison.sort_values(
        ["_최소횟수", "_합계", "반찬"],
        ascending=[True, True, True],
    ).reset_index(drop=True)

    comparison = comparison.drop(
        columns=["_최소횟수", "_합계"]
    )

    column_config = {
        "반찬": st.column_config.TextColumn(
            "반찬",
            width="large",
        )
    }

    for school_name in all_counts:
        column_config[school_name] = st.column_config.NumberColumn(
            school_name,
            format="%d회",
        )

    st.dataframe(
        comparison,
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
        height=min(700, 100 + len(comparison) * 35),
    )


# ---------------------------------------------------------
# 학교별 '적게 나온 반찬'만 따로 보기
# ---------------------------------------------------------
st.subheader("⑤ 학교별 적게 나온 반찬")

st.caption(
    "각 학교에서 가장 적게 나온 횟수와 같은 반찬들을 학교별로 묶어 보여줍니다."
)

for school_name, counts in all_counts.items():
    if not counts:
        continue

    min_count = min(counts.values())

    rarest = sorted(
        [
            (menu, count)
            for menu, count in counts.items()
            if count == min_count
        ],
        key=lambda x: x[0],
    )

    rarest_df = pd.DataFrame(
        rarest,
        columns=["반찬", "등장 횟수"],
    )

    with st.expander(
        f"🏫 {school_name}  —  가장 적게 나온 횟수: {min_count}회",
        expanded=True,
    ):
        st.dataframe(
            rarest_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "반찬": st.column_config.TextColumn("반찬"),
                "등장 횟수": st.column_config.NumberColumn(
                    "등장 횟수",
                    format="%d회",
                ),
            },
        )


# ---------------------------------------------------------
# 안내
# ---------------------------------------------------------
st.divider()

with st.expander("ℹ️ 집계 기준"):
    st.markdown(
        """
- NEIS 학교기본정보에서 학교 이름 일부를 검색합니다.
- 검색 결과에서 여러 학교를 선택할 수 있습니다.
- 선택한 학교의 교육청 코드와 학교 코드로 중식 급식을 조회합니다.
- `DDISH_NM`의 `<br/>`를 기준으로 메뉴를 나눕니다.
- 메뉴 뒤에 붙은 알레르기 번호는 제거합니다.
- 기본 설정에서는 밥·국/찌개·김치·후식류를 제외합니다.
- 같은 메뉴가 조회 기간에 몇 번 등장했는지를 학교별로 계산합니다.
- **반찬별 학교 비교표에서는 같은 반찬을 같은 행에 놓고 학교별 횟수를 나란히 보여줍니다.**
        """
    )

with st.expander("🔑 Streamlit Cloud Secrets 설정"):
    st.markdown(
        """
이 앱에는 NEIS 인증키를 직접 입력하거나 저장하지 않습니다.

Streamlit Cloud의 **Settings → Secrets**에 아래 형식으로 인증키를 따로 입력하세요.

```toml
NEIS_KEY = "실제_인증키"
```

앱은 실행할 때 Streamlit Secrets에서 `NEIS_KEY`를 읽어 NEIS API 요청에 사용합니다.
        """
    )
