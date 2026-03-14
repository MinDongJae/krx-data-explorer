"""
네이버 금융 스크래퍼 — KRX 로그인 없이 모든 데이터 수집
=========================================================
네이버 금융 웹사이트의 각 탭에서 KRX 데이터를 가져옵니다.
(네이버가 KRX에서 데이터를 받아서 보여주는 것을 우리가 다시 가져오는 방식)

지원 데이터:
1. 시가총액 순위 (KOSPI/KOSDAQ 전 종목)
2. 재무정보 (PER, PBR, EPS, BPS, 배당수익률)
3. 투자자별 매매동향 (외국인/기관 순매수)
4. ETF 전체 목록 + 데이터 (JSON API!)
5. 실시간 지수 (코스피, 코스닥, 코스피200)
6. 주가 OHLCV (시가/고가/저가/종가/거래량)
"""

import ast
import logging
import time
from io import StringIO
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ============================================================================
# 공통 설정
# ============================================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/",
}

# 요청 간 최소 대기 시간 (초) — IP 차단 방지
REQUEST_DELAY = 0.5


def _get(url: str, params: dict = None, timeout: int = 15) -> requests.Response:
    """네이버 금융에 GET 요청 (User-Agent 헤더 필수)"""
    resp = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY)
    return resp


# ============================================================================
# 1. 시가총액 순위 (전 종목)
# ============================================================================

def get_market_cap_ranking(
    market: str = "KOSPI",
    pages: int = 3,
) -> pd.DataFrame:
    """
    네이버 금융 → '시가총액' 탭에서 전 종목 시가총액 순위 가져오기
    (마치 반에서 키 순서대로 줄 세우듯, 회사를 가치 순서로 정렬)

    market: "KOSPI" (sosok=0) 또는 "KOSDAQ" (sosok=1)
    pages: 몇 페이지까지 가져올지 (1페이지 = 50종목)
    """
    sosok = 0 if market == "KOSPI" else 1
    url = "https://finance.naver.com/sise/sise_market_sum.naver"

    all_rows = []
    for page in range(1, pages + 1):
        try:
            resp = _get(url, params={"sosok": sosok, "page": page})
            # HTML 테이블 파싱
            tables = pd.read_html(StringIO(resp.text), encoding="euc-kr")
            for df in tables:
                if "종목명" in df.columns:
                    # 빈 행 제거
                    df = df.dropna(subset=["종목명"])
                    all_rows.append(df)
        except Exception as e:
            logger.warning(f"시가총액 페이지 {page} 실패: {e}")
            continue

    if not all_rows:
        return pd.DataFrame()

    result = pd.concat(all_rows, ignore_index=True)

    # 컬럼명 정리 (네이버 페이지 기준)
    # N, 종목명, 현재가, 전일비, 등락률, 시가총액, 상장주식수, 외국인비율, 거래량, PER, ROE
    rename_map = {
        "N": "순위",
        "현재가": "종가",
        "전일비": "전일대비",
    }
    result = result.rename(columns=rename_map)

    return result


# ============================================================================
# 2. 재무정보 (PER, PBR, EPS, BPS 등)
# ============================================================================

def get_financial_info(ticker: str) -> dict:
    """
    네이버 금융 → 종목 '기업정보' 탭에서 재무지표 가져오기
    (회사의 성적표 같은 것 — 얼마나 돈을 잘 버는지, 비싼지 싼지 알 수 있음)

    Returns: {"PER": 12.5, "PBR": 1.2, "EPS": 5700, "BPS": 59000, ...}
    """
    url = f"https://finance.naver.com/item/main.naver?code={ticker}"

    try:
        resp = _get(url)
        tables = pd.read_html(StringIO(resp.text), encoding="euc-kr")

        result = {}

        # 투자지표 테이블 찾기 (PER, EPS 등이 있는 테이블)
        for df in tables:
            cols = [str(c) for c in df.columns]
            text = " ".join(cols + [str(v) for v in df.values.flatten()])

            if "PER" in text and "EPS" in text:
                # 테이블에서 값 추출
                for _, row in df.iterrows():
                    row_str = [str(v) for v in row.values]
                    for i, val in enumerate(row_str):
                        if "PER" in val and i + 1 < len(row_str):
                            try:
                                result["PER"] = float(row_str[i + 1].replace(",", "").replace("배", ""))
                            except (ValueError, IndexError):
                                pass
                        if "PBR" in val and i + 1 < len(row_str):
                            try:
                                result["PBR"] = float(row_str[i + 1].replace(",", "").replace("배", ""))
                            except (ValueError, IndexError):
                                pass
                        if "EPS" in val and "BPS" not in val and i + 1 < len(row_str):
                            try:
                                result["EPS"] = float(row_str[i + 1].replace(",", "").replace("원", ""))
                            except (ValueError, IndexError):
                                pass
                        if "BPS" in val and i + 1 < len(row_str):
                            try:
                                result["BPS"] = float(row_str[i + 1].replace(",", "").replace("원", ""))
                            except (ValueError, IndexError):
                                pass

            if "배당수익률" in text:
                for _, row in df.iterrows():
                    row_str = [str(v) for v in row.values]
                    for i, val in enumerate(row_str):
                        if "배당수익률" in val and i + 1 < len(row_str):
                            try:
                                result["배당수익률"] = float(row_str[i + 1].replace(",", "").replace("%", ""))
                            except (ValueError, IndexError):
                                pass

        return result

    except Exception as e:
        logger.warning(f"재무정보 조회 실패 ({ticker}): {e}")
        return {}


def get_financial_statements(
    ticker: str,
    fin_typ: int = 0,
    freq_typ: str = "Y",
) -> pd.DataFrame:
    """
    네이버 금융 → 기업실적분석 탭 (연간/분기 재무제표)

    fin_typ: 0=주요재무, 3=IFRS별도, 4=IFRS연결
    freq_typ: "Y"=연간, "Q"=분기
    """
    url = f"http://companyinfo.stock.naver.com/v1/company/ajax/cF1001.aspx"
    params = {
        "cmp_cd": ticker,
        "fin_typ": fin_typ,
        "freq_typ": freq_typ,
    }

    try:
        resp = _get(url, params=params)
        tables = pd.read_html(StringIO(resp.text))
        if tables:
            return tables[0]
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"재무제표 조회 실패 ({ticker}): {e}")
        return pd.DataFrame()


# ============================================================================
# 3. 투자자별 매매동향 (외국인/기관)
# ============================================================================

def get_investor_trading(
    ticker: str,
    pages: int = 1,
) -> pd.DataFrame:
    """
    네이버 금융 → '외국인·기관 매매동향' 탭
    (외국인과 큰 기관들이 이 종목을 사는지 파는지 알려줌)
    """
    url = "https://finance.naver.com/item/frgn.naver"
    all_rows = []

    for page in range(1, pages + 1):
        try:
            resp = _get(url, params={"code": ticker, "page": page})
            tables = pd.read_html(StringIO(resp.text), encoding="euc-kr")
            for df in tables:
                # MultiIndex 컬럼 → 단일 레벨로 변환
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = ["_".join(str(c) for c in col).strip("_") for col in df.columns]
                # 빈 행 제거
                df = df.dropna(how="all")
                # 날짜 컬럼이 있는 테이블만 (실제 데이터 테이블)
                col_str = " ".join(str(c) for c in df.columns)
                if ("날짜" in col_str or "일자" in col_str) and len(df) > 2:
                    all_rows.append(df)
        except Exception as e:
            logger.warning(f"투자자 매매동향 페이지 {page} 실패: {e}")
            continue

    if not all_rows:
        return pd.DataFrame()

    return pd.concat(all_rows, ignore_index=True)


# ============================================================================
# 4. ETF 전체 목록 (JSON API — 가장 깨끗한 엔드포인트!)
# ============================================================================

def get_etf_list(
    sort_by: str = "market_sum",
    order: str = "desc",
) -> list[dict]:
    """
    네이버 금융 ETF API → 순수 JSON 반환!
    (ETF는 여러 주식을 한 묶음으로 만든 상품 — 도시락처럼 여러 반찬이 한 박스에)

    sort_by: "market_sum"(시가총액), "quant"(거래량) 등
    """
    url = "https://finance.naver.com/api/sise/etfItemList.nhn"
    params = {
        "etfType": 0,  # 0=전체
        "targetColumn": sort_by,
        "sortOrder": order,
    }

    try:
        resp = _get(url, params=params)
        data = resp.json()
        # 응답 구조: {"resultCode": "success", "result": {"etfItemList": [...]}}
        items = data.get("result", {}).get("etfItemList", [])
        return items
    except Exception as e:
        logger.warning(f"ETF 목록 조회 실패: {e}")
        return []


# ============================================================================
# 5. 실시간 지수 (코스피, 코스닥 등)
# ============================================================================

def get_realtime_index(
    indices: list[str] = None,
) -> list[dict]:
    """
    네이버 금융 실시간 지수 API
    (주식 시장 전체의 온도계 — 시장이 오르는지 내리는지 한눈에)

    indices: ["KOSPI", "KOSDAQ", "KPI200"] 등
    """
    if indices is None:
        indices = ["KOSPI", "KOSDAQ", "KPI200"]

    query = ",".join(f"SERVICE_INDEX:{idx}" for idx in indices)
    url = "https://polling.finance.naver.com/api/realtime"
    params = {"query": query}

    try:
        resp = _get(url, params=params)
        data = resp.json()
        results = []
        for item_key, item_data in data.get("result", {}).get("areas", [{}])[0].get("datas", {}).items() if isinstance(data.get("result", {}).get("areas"), list) else []:
            results.append(item_data)

        # 더 안정적인 파싱
        areas = data.get("result", {}).get("areas", [])
        results = []
        for area in areas:
            for item in area.get("datas", []):
                results.append(item)

        return results
    except Exception as e:
        logger.warning(f"실시간 지수 조회 실패: {e}")
        return []


# ============================================================================
# 6. 주가 OHLCV (네이버 차트 API)
# ============================================================================

def get_ohlcv(
    ticker: str,
    start: str = "20260101",
    end: str = "20261231",
    timeframe: str = "day",
) -> pd.DataFrame:
    """
    네이버 금융 차트 API — 주가 데이터
    (pykrx의 네이버 소스와 동일한 곳에서 가져옴)

    timeframe: "day"(일봉), "week"(주봉), "month"(월봉)
    """
    url = "https://api.finance.naver.com/siseJson.naver"
    params = {
        "symbol": ticker,
        "requestType": 1,
        "startTime": start,
        "endTime": end,
        "timeframe": timeframe,
    }

    try:
        resp = _get(url, params=params)
        # 응답이 JavaScript 배열 형태 (순수 JSON이 아님)
        # [["20240102",66100,66300,65600,65800,10456789, ...], ...]
        text = resp.text.strip()
        data = ast.literal_eval(text)

        if not data:
            return pd.DataFrame()

        # 첫 행이 헤더일 수 있음
        if isinstance(data[0][0], str) and not data[0][0].isdigit():
            data = data[1:]

        df = pd.DataFrame(data)
        # 컬럼: 날짜, 시가, 고가, 저가, 종가, 거래량, 외국인소진율
        col_names = ["날짜", "시가", "고가", "저가", "종가", "거래량"]
        if len(df.columns) >= 6:
            df.columns = col_names + list(df.columns[6:])

        # 날짜 정리
        df["날짜"] = df["날짜"].astype(str).str.strip().str.replace("'", "")
        df["날짜"] = pd.to_datetime(df["날짜"], format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["날짜"])
        df = df.set_index("날짜")

        # 숫자 변환
        for col in ["시가", "고가", "저가", "종가", "거래량"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 등락률 계산
        df["등락률"] = df["종가"].pct_change() * 100

        return df.sort_index()

    except Exception as e:
        logger.warning(f"OHLCV 조회 실패 ({ticker}): {e}")
        return pd.DataFrame()


# ============================================================================
# 7. 종목 목록 (시가총액 페이지에서 추출)
# ============================================================================

def get_stock_list(
    market: str = "KOSPI",
    pages: int = 5,
) -> pd.DataFrame:
    """
    네이버 금융 시가총액 페이지에서 종목코드 + 이름 추출
    (KOSPI 약 950개, KOSDAQ 약 1700개 종목)
    """
    import re

    sosok = 0 if market == "KOSPI" else 1
    url = "https://finance.naver.com/sise/sise_market_sum.naver"

    results = []
    for page in range(1, pages + 1):
        try:
            resp = _get(url, params={"sosok": sosok, "page": page})
            # HTML에서 종목코드 추출 (code=XXXXXX 패턴)
            codes = re.findall(r'code=(\d{6})', resp.text)
            # 종목명 추출 (class="tltle" 뒤의 텍스트)
            names = re.findall(r'class="tltle"[^>]*>([^<]+)<', resp.text)

            for code, name in zip(codes, names):
                if code not in [r["종목코드"] for r in results]:
                    results.append({
                        "종목코드": code,
                        "종목명": name.strip(),
                        "시장": market,
                    })
        except Exception as e:
            logger.warning(f"종목목록 페이지 {page} 실패: {e}")
            continue

    return pd.DataFrame(results)


# ============================================================================
# 8. 등락률 순위 (상승/하락)
# ============================================================================

def get_price_change_ranking(
    direction: str = "rise",
    market: str = "KOSPI",
) -> pd.DataFrame:
    """
    네이버 금융 → 상승/하락 종목 순위
    (오늘 가장 많이 오른 종목, 가장 많이 내린 종목)

    direction: "rise"(상승) / "fall"(하락)
    """
    if direction == "rise":
        url = "https://finance.naver.com/sise/sise_rise.naver"
    else:
        url = "https://finance.naver.com/sise/sise_fall.naver"

    sosok = "01" if market == "KOSPI" else "02"

    try:
        resp = _get(url, params={"sosok": sosok})
        tables = pd.read_html(StringIO(resp.text), encoding="euc-kr")
        for df in tables:
            if "종목명" in df.columns and len(df) > 3:
                df = df.dropna(subset=["종목명"])
                return df
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"등락률 순위 조회 실패: {e}")
        return pd.DataFrame()


# ============================================================================
# 9. 업종별 분류
# ============================================================================

def get_sector_list() -> pd.DataFrame:
    """
    네이버 금융 → 업종별 시세
    (음식업, 반도체업, 은행업 등 분야별로 분류)
    """
    url = "https://finance.naver.com/sise/sise_group.naver"
    params = {"type": "upjong"}

    try:
        resp = _get(url, params=params)
        tables = pd.read_html(StringIO(resp.text), encoding="euc-kr")
        for df in tables:
            if len(df) > 5:
                df = df.dropna(how="all")
                # MultiIndex 컬럼 → 단일 레벨
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = ["_".join(dict.fromkeys(str(c) for c in col)).strip("_") for col in df.columns]
                return df
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"업종별 분류 조회 실패: {e}")
        return pd.DataFrame()


# ============================================================================
# 10. 투자자별 매매동향 (시장 전체)
# ============================================================================

def get_investor_trend_daily(
    market: str = "KOSPI",
) -> pd.DataFrame:
    """
    네이버 금융 → 투자자별 매매동향 (일별)
    (외국인, 기관, 개인이 시장 전체에서 얼마나 사고팔았는지)
    """
    url = "https://finance.naver.com/sise/investorDealTrendDay.naver"

    try:
        resp = _get(url)
        tables = pd.read_html(StringIO(resp.text), encoding="euc-kr")
        for df in tables:
            df = df.dropna(how="all")
            if len(df) > 3:
                # MultiIndex 컬럼 → 단일 레벨
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = ["_".join(str(c) for c in col).strip("_") for col in df.columns]
                return df
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"투자자별 매매동향 조회 실패: {e}")
        return pd.DataFrame()


# ============================================================================
# 11. 일별 시세 (시가/고가/저가/종가/거래량 - HTML 테이블)
# ============================================================================

def get_daily_price(
    ticker: str,
    pages: int = 3,
) -> pd.DataFrame:
    """
    네이버 금융 → 일별시세 탭 (HTML 테이블)
    (최근 며칠간의 주가 데이터를 테이블로 가져옴)
    """
    url = "https://finance.naver.com/item/sise_day.naver"
    all_rows = []

    for page in range(1, pages + 1):
        try:
            resp = _get(url, params={"code": ticker, "page": page})
            tables = pd.read_html(StringIO(resp.text), encoding="euc-kr")
            for df in tables:
                if "날짜" in df.columns:
                    df = df.dropna(subset=["날짜"])
                    all_rows.append(df)
        except Exception as e:
            logger.warning(f"일별시세 페이지 {page} 실패: {e}")
            continue

    if not all_rows:
        return pd.DataFrame()

    result = pd.concat(all_rows, ignore_index=True)
    # 날짜 정렬
    if "날짜" in result.columns:
        result["날짜"] = pd.to_datetime(result["날짜"], errors="coerce")
        result = result.dropna(subset=["날짜"]).sort_values("날짜")
    return result


# ============================================================================
# 12. 외국인 보유현황 추이 (개별 종목)
# ============================================================================

def get_foreign_holding(
    ticker: str,
    pages: int = 2,
) -> pd.DataFrame:
    """
    네이버 금융 → 외국인/기관 매매동향 탭에서 외국인 보유 비율 추이
    (외국인이 이 회사 주식을 얼마나 갖고 있는지의 변화)
    """
    url = "https://finance.naver.com/item/frgn.naver"
    all_rows = []

    for page in range(1, pages + 1):
        try:
            resp = _get(url, params={"code": ticker, "page": page})
            tables = pd.read_html(StringIO(resp.text), encoding="euc-kr")
            for df in tables:
                # MultiIndex 컬럼 → 단일 레벨
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = ["_".join(str(c) for c in col).strip("_") for col in df.columns]
                df = df.dropna(how="all")
                col_str = " ".join(str(c) for c in df.columns)
                if ("날짜" in col_str or "일자" in col_str) and len(df) > 2:
                    all_rows.append(df)
        except Exception as e:
            logger.warning(f"외국인 보유현황 페이지 {page} 실패: {e}")
            continue

    if not all_rows:
        return pd.DataFrame()
    return pd.concat(all_rows, ignore_index=True)


# ============================================================================
# 13. 업종별 종목 목록 (특정 업종의 종목들)
# ============================================================================

def get_sector_stocks(no: str) -> pd.DataFrame:
    """
    네이버 금융 → 특정 업종에 속한 종목 목록
    (예: 반도체 업종에 어떤 회사들이 있는지)
    """
    url = "https://finance.naver.com/sise/sise_group_detail.naver"

    try:
        resp = _get(url, params={"type": "upjong", "no": no})
        tables = pd.read_html(StringIO(resp.text), encoding="euc-kr")
        for df in tables:
            if "종목명" in df.columns and len(df) > 1:
                df = df.dropna(subset=["종목명"])
                return df
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"업종별 종목 조회 실패: {e}")
        return pd.DataFrame()


# ============================================================================
# 테스트 코드
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("1. 시가총액 순위")
    print("=" * 60)
    df = get_market_cap_ranking("KOSPI", pages=1)
    if not df.empty:
        print(df.head(5).to_string())
    print()

    print("=" * 60)
    print("2. 재무정보 (삼성전자)")
    print("=" * 60)
    info = get_financial_info("005930")
    print(info)
    print()

    print("=" * 60)
    print("3. 투자자별 매매 (삼성전자)")
    print("=" * 60)
    df = get_investor_trading("005930", pages=1)
    if not df.empty:
        print(df.head(5).to_string())
    print()

    print("=" * 60)
    print("4. ETF 목록 (JSON API)")
    print("=" * 60)
    etfs = get_etf_list()
    if etfs:
        for etf in etfs[:3]:
            print(f"  {etf.get('itemcode')}: {etf.get('itemname')} "
                  f"현재가={etf.get('nowVal')} 시총={etf.get('marketSum')}")
    print()

    print("=" * 60)
    print("5. 실시간 지수")
    print("=" * 60)
    indices = get_realtime_index()
    for idx in indices:
        print(f"  {idx}")
    print()

    print("=" * 60)
    print("6. OHLCV (삼성전자 최근)")
    print("=" * 60)
    df = get_ohlcv("005930", "20260310", "20260313")
    if not df.empty:
        print(df.to_string())
    print()

    print("=" * 60)
    print("7. 종목 목록 (KOSPI)")
    print("=" * 60)
    df = get_stock_list("KOSPI", pages=1)
    if not df.empty:
        print(f"  {len(df)}개 종목")
        print(df.head(5).to_string())
