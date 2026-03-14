"""
KRX Data Explorer 백엔드 서버
==============================
- PyKRX 라이브러리로 한국 주식 데이터 제공
- 네이버 소스 활용 (로그인 불필요)
- IP 프록시 로테이션으로 차단 방지
- FastAPI + Uvicorn
"""

import datetime
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pykrx import stock, bond

from proxy_rotator import init_proxy_rotation, get_proxy_status
from krx_direct import get_krx_fetcher, krx_direct_status, KRX_OUT_ENDPOINTS
from krx_auth import get_krx_auth, KRX_AUTH_ENDPOINTS
import naver_finance as nf

# ============================================================================
# 주요 종목 리스트 (KRX ticker_list API 깨진 상태 대비용)
# get_market_ticker_name()은 정상 작동하므로 이름 조회는 가능
# ============================================================================

MAJOR_TICKERS = {
    "KOSPI": [
        "005930", "000660", "373220", "005380", "005490",
        "035420", "006400", "051910", "068270", "028260",
        "105560", "055550", "003550", "066570", "034730",
        "017670", "030200", "032830", "035720", "012330",
        "096770", "003670", "033780", "010130", "000270",
        "086790", "015760", "034020", "036570", "011200",
        "009150", "316140", "018260", "024110", "000810",
        "003490", "010950", "047050", "009540", "138040",
    ],
    "KOSDAQ": [
        "247540", "086520", "196170", "403870", "058470",
        "293490", "041510", "068760", "035760", "112040",
        "145020", "383310", "328130", "377300", "036930",
        "357780", "006730", "091990", "095340", "095660",
    ],
}


# ============================================================================
# 로깅 설정
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("krx-backend")


# ============================================================================
# 앱 시작/종료 이벤트
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작할 때 프록시 풀 초기화"""
    logger.info("=== KRX Data Explorer 백엔드 시작 ===")
    try:
        init_proxy_rotation(min_proxies=2, max_proxies=5)
        logger.info("프록시 패치 적용 완료 (수집은 백그라운드 진행)")
    except Exception as e:
        logger.warning(f"프록시 초기화 실패 (직접 연결 사용): {e}")

    # KRX outerLoader 직접 수집기 초기화 (세션 미리 생성)
    try:
        fetcher = get_krx_fetcher()
        fetcher._ensure_session()
        logger.info("KRX 직접 수집기 초기화 완료 (outerLoader 세션)")
    except Exception as e:
        logger.warning(f"KRX 직접 수집기 초기화 실패: {e}")

    # KRX ID/PW 로그인 초기화 (인증 데이터 접근용)
    try:
        auth = get_krx_auth()
        session = auth.get_authenticated_session()
        if session:
            logger.info(f"KRX ID/PW 로그인 성공 (MBR_NO={auth._member_no})")
        else:
            logger.warning("KRX ID/PW 로그인 실패 — 인증 데이터 사용 불가")
    except Exception as e:
        logger.warning(f"KRX 로그인 초기화 실패: {e}")

    yield
    logger.info("=== 백엔드 종료 ===")


app = FastAPI(
    title="KRX Data Explorer API",
    description="PyKRX + 프록시 로테이션 기반 한국 주식 데이터 API",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS (프론트엔드에서 접근 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174", "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# 유틸리티
# ============================================================================

def today_str() -> str:
    """오늘 날짜를 YYYYMMDD 형식으로"""
    return datetime.date.today().strftime("%Y%m%d")


def business_day_str(days_ago: int = 0) -> str:
    """최근 영업일 (주말/공휴일 건너뛰기는 간단히 처리)"""
    d = datetime.date.today() - datetime.timedelta(days=days_ago)
    # 토요일→금요일, 일요일→금요일
    if d.weekday() == 5:
        d -= datetime.timedelta(days=1)
    elif d.weekday() == 6:
        d -= datetime.timedelta(days=2)
    return d.strftime("%Y%m%d")


def df_to_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame을 JSON-safe한 리스트로 변환"""
    if df.empty:
        return []
    df = df.copy()
    # MultiIndex 컬럼 → 단일 레벨
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join(dict.fromkeys(str(c) for c in col)).strip("_") for col in df.columns]
    # index를 컬럼으로
    if df.index.name or not isinstance(df.index, pd.RangeIndex):
        df = df.reset_index()
    # datetime → 문자열
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
    # to_dict 후 NaN/Inf를 None으로 변환 (JSON 호환)
    import math
    records = df.to_dict(orient="records")
    for row in records:
        for key, val in row.items():
            if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                row[key] = None
    return records


def safe_pykrx_call(func, *args, **kwargs):
    """PyKRX 호출을 안전하게 감싸기 (에러 시 빈 DataFrame 반환)"""
    try:
        logger.info(f"PyKRX 호출: {func.__name__}(args={args}, kwargs={kwargs})")
        result = func(*args, **kwargs)
        if isinstance(result, pd.DataFrame):
            logger.info(f"PyKRX 결과: {func.__name__} -> {len(result)}행, cols={list(result.columns)}")
        time.sleep(0.5)  # IP 차단 방지용 최소 딜레이
        return result
    except Exception as e:
        logger.error(f"PyKRX 호출 실패 ({func.__name__}): {e}", exc_info=True)
        return pd.DataFrame()


# ============================================================================
# API 엔드포인트
# ============================================================================

@app.get("/")
def root():
    """서버 상태 확인"""
    return {
        "status": "ok",
        "service": "KRX Data Explorer API",
        "version": "4.0.0",
        "proxy": get_proxy_status(),
        "krx_direct": krx_direct_status(),
        "krx_auth": get_krx_auth().status(),
    }


@app.get("/api/proxy/status")
def proxy_status():
    """프록시 상태 확인"""
    return get_proxy_status()


@app.get("/api/proxy/refresh")
def proxy_refresh():
    """프록시 풀 새로고침"""
    try:
        pool = init_proxy_rotation(min_proxies=3, max_proxies=8)
        return {"success": True, "count": pool.count}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────
# 1. 종목 목록 (네이버 소스 기반 - KRX ticker_list 깨진 상태 대비)
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/list")
def get_stock_list(
    market: str = Query("ALL", description="KOSPI / KOSDAQ / ALL"),
    pages: int = Query(3, description="페이지 수 (1페이지=50종목)"),
):
    """상장 종목 코드 + 이름 목록 (네이버 금융에서 가져옴)"""
    markets_to_query = ["KOSPI", "KOSDAQ"] if market == "ALL" else [market]
    all_results = []

    for mkt in markets_to_query:
        df = nf.get_stock_list(mkt, pages=pages)
        if not df.empty:
            all_results.extend(df.to_dict(orient="records"))

    return {"count": len(all_results), "data": all_results}


# ─────────────────────────────────────────────────────────
# 2. 주가 OHLCV (네이버 소스 = 로그인 불필요!)
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/ohlcv")
def get_stock_ohlcv(
    ticker: str = Query(..., description="종목코드 (예: 005930)"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    freq: str = Query("d", description="d=일별, m=월별, y=연별"),
    adjusted: bool = Query(True, description="True=네이버(수정주가), False=KRX(원본)"),
):
    """
    개별 종목 주가 데이터 (시가/고가/저가/종가/거래량)

    adjusted=True (기본값) → 네이버 금융에서 가져옴 (로그인 불필요!)
    adjusted=False → KRX에서 가져옴
    """
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")

    df = safe_pykrx_call(
        stock.get_market_ohlcv_by_date, start, end, ticker, freq=freq, adjusted=adjusted
    )
    name = stock.get_market_ticker_name(ticker)

    return {
        "ticker": ticker,
        "name": name,
        "source": "naver" if adjusted else "krx",
        "start": start,
        "end": end,
        "count": len(df),
        "data": df_to_records(df),
    }


# ─────────────────────────────────────────────────────────
# 3. 전체 시장 데이터 (특정일 전 종목)
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/all-markets")
def get_all_markets(
    market: str = Query("ALL", description="KOSPI / KOSDAQ / ALL"),
    top_n: int = Query(50, description="상위 N개 종목"),
    days: int = Query(5, description="최근 N 거래일"),
):
    """
    주요 종목 최근 OHLCV (네이버 소스 - 로그인 불필요!)
    각 종목의 최근 종가/등락률/거래량을 가져옵니다.
    """
    end = business_day_str(0)
    start = (datetime.date.today() - datetime.timedelta(days=days + 5)).strftime("%Y%m%d")

    markets_to_query = ["KOSPI", "KOSDAQ"] if market == "ALL" else [market]
    results = []

    for mkt in markets_to_query:
        tickers = MAJOR_TICKERS.get(mkt, [])[:top_n]
        for t in tickers:
            try:
                name = stock.get_market_ticker_name(t)
                df = stock.get_market_ohlcv_by_date(start, end, t, adjusted=True)
                if df.empty:
                    continue
                last = df.iloc[-1]
                results.append({
                    "종목코드": t,
                    "종목명": name,
                    "시장": mkt,
                    "종가": int(last["종가"]),
                    "시가": int(last["시가"]),
                    "고가": int(last["고가"]),
                    "저가": int(last["저가"]),
                    "거래량": int(last["거래량"]),
                    "등락률": round(float(last["등락률"]), 2),
                    "기준일": df.index[-1].strftime("%Y-%m-%d"),
                })
                time.sleep(0.3)  # IP 차단 방지
            except Exception as e:
                logger.warning(f"종목 {t} 조회 실패: {e}")
                continue

    # 거래량 기준 정렬
    results.sort(key=lambda x: x.get("거래량", 0), reverse=True)

    return {
        "market": market,
        "source": "naver",
        "count": len(results),
        "data": results[:top_n],
    }


# ─────────────────────────────────────────────────────────
# 4. 시가총액
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/market-cap")
def get_market_cap(
    market: str = Query("KOSPI"),
    top_n: int = Query(50),
):
    """종목별 시가총액 순위 (네이버 금융에서 가져옴)"""
    pages = max(1, top_n // 50 + 1)
    df = nf.get_market_cap_ranking(market, pages=pages)

    if df.empty:
        return {"market": market, "source": "naver", "count": 0, "data": []}

    # '토론' 등 불필요한 컬럼 제거, NaN 처리
    drop_cols = [c for c in df.columns if c in ("토론",)]
    df = df.drop(columns=drop_cols, errors="ignore")
    df = df.head(top_n)

    return {
        "market": market,
        "source": "naver",
        "count": len(df),
        "data": df_to_records(df),
    }


# ─────────────────────────────────────────────────────────
# 5. 재무지표 (PER, PBR 등)
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/fundamental")
def get_fundamental(
    ticker: str = Query(None, description="종목코드 (없으면 시가총액 상위에서 수집)"),
    market: str = Query("KOSPI"),
    top_n: int = Query(20),
):
    """
    재무지표 (PER/PBR/EPS/BPS/배당수익률) — 네이버 금융에서 가져옴
    개별 종목 or 시가총액 상위 종목의 재무정보 일괄 수집
    """
    if ticker:
        # 개별 종목
        info = nf.get_financial_info(ticker)
        name = stock.get_market_ticker_name(ticker)
        if info:
            info["종목코드"] = ticker
            info["종목명"] = name
        return {"source": "naver", "count": 1 if info else 0, "data": [info] if info else []}

    # 시가총액 상위 종목의 재무정보 일괄 수집
    # 먼저 시가총액 페이지에서 종목코드 추출
    stock_df = nf.get_stock_list(market, pages=1)
    if stock_df.empty:
        return {"source": "naver", "count": 0, "data": []}

    results = []
    for _, row in stock_df.head(top_n).iterrows():
        code = row["종목코드"]
        name = row["종목명"]
        info = nf.get_financial_info(code)
        if info:
            info["종목코드"] = code
            info["종목명"] = name
            info["시장"] = market
            results.append(info)

    return {
        "market": market,
        "source": "naver",
        "count": len(results),
        "data": results,
    }


# ─────────────────────────────────────────────────────────
# 6. 투자자별 매매동향
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/investor-trading")
def get_investor_trading(
    ticker: str = Query("005930"),
    date: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: str = Query("STK", description="STK=유가증권, KSQ=코스닥"),
    pages: int = Query(2, description="네이버 폴백 시 페이지 수"),
):
    """
    투자자별 매매동향
    1순위: KRX 직접 (outerLoader OTP)
    2순위: pykrx
    3순위: 네이버 금융
    """
    name = stock.get_market_ticker_name(ticker)
    source = "krx_direct"

    # 1순위: KRX 직접 수집 (투자자별 전체시장)
    krx = get_krx_fetcher()
    if date:
        df = krx.fetch("investor_trading", trdDd=date, mktId=market)
    else:
        df = krx.fetch("investor_trading", trdDd=business_day_str(1), mktId=market)

    # 2순위: pykrx
    if df.empty:
        source = "krx"
        end_d = end or business_day_str(1)
        start_d = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
        df = safe_pykrx_call(stock.get_market_trading_volume_by_investor, start_d, end_d, ticker)

    # 3순위: 네이버 폴백
    if df.empty:
        source = "naver"
        df = nf.get_investor_trading(ticker, pages=pages)

    return {
        "ticker": ticker,
        "name": name,
        "source": source,
        "count": len(df),
        "data": df_to_records(df),
    }


# ─────────────────────────────────────────────────────────
# 7. 외국인 보유 현황
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/foreign")
def get_foreign_holding(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
    top_n: int = Query(30),
):
    """외국인 보유/한도 소진율"""
    date = date or business_day_str(1)

    df = safe_pykrx_call(
        stock.get_exhaustion_rates_of_foreign_investment, date, market=market
    )
    if df.empty:
        return {"date": date, "count": 0, "data": []}

    df.index.name = "종목코드"
    df = df.reset_index()
    df["종목명"] = df["종목코드"].apply(lambda t: stock.get_market_ticker_name(t))
    df = df.head(top_n)

    return {
        "date": date,
        "market": market,
        "count": len(df),
        "data": df_to_records(df),
    }


# ─────────────────────────────────────────────────────────
# 8. 공매도
# ─────────────────────────────────────────────────────────

@app.get("/api/short-selling/balance")
def get_shorting_balance(
    ticker: str = Query("005930"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """공매도 잔고 (주가 하락에 베팅한 거래)"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")

    df = safe_pykrx_call(
        stock.get_shorting_balance_by_date, start, end, ticker
    )
    name = stock.get_market_ticker_name(ticker)

    return {
        "ticker": ticker,
        "name": name,
        "count": len(df),
        "data": df_to_records(df),
    }


@app.get("/api/short-selling/top50")
def get_shorting_top50(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
):
    """공매도 비율 상위 50종목"""
    date = date or business_day_str(1)

    df = safe_pykrx_call(stock.get_shorting_balance_top50, date, market)
    if df.empty:
        return {"date": date, "count": 0, "data": []}

    df.index.name = "종목코드"
    df = df.reset_index()

    return {"date": date, "market": market, "count": len(df), "data": df_to_records(df)}


# ─────────────────────────────────────────────────────────
# 9. 지수 (코스피200 같은 시장 온도계)
# ─────────────────────────────────────────────────────────

@app.get("/api/index/list")
def get_index_list(
    market: str = Query("KOSPI"),
    date: Optional[str] = None,
):
    """지수 목록"""
    date = date or business_day_str(1)

    indices = safe_pykrx_call(stock.get_index_ticker_list, date, market=market)
    if not isinstance(indices, list):
        return {"count": 0, "data": []}

    results = []
    for idx in indices:
        name = stock.get_index_ticker_name(idx)
        results.append({"지수코드": idx, "지수명": name})

    return {"date": date, "market": market, "count": len(results), "data": results}


@app.get("/api/index/ohlcv")
def get_index_ohlcv(
    ticker: str = Query("1028", description="지수코드 (1028=코스피200)"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """지수 OHLCV"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")

    df = safe_pykrx_call(stock.get_index_ohlcv, start, end, ticker)
    name = stock.get_index_ticker_name(ticker)

    return {
        "ticker": ticker,
        "name": name,
        "count": len(df),
        "data": df_to_records(df),
    }


# ─────────────────────────────────────────────────────────
# 10. 채권 수익률
# ─────────────────────────────────────────────────────────

@app.get("/api/bond/yields")
def get_bond_yields(
    date: Optional[str] = None,
):
    """장외 채권 수익률 (국고채/회사채/CD 등 11종)"""
    date = date or business_day_str(1)

    df = safe_pykrx_call(bond.get_otc_treasury_yields, date)
    return {"date": date, "count": len(df), "data": df_to_records(df)}


@app.get("/api/bond/yields/history")
def get_bond_yield_history(
    bond_type: str = Query("국고채3년"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """특정 채권 수익률 추이"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")

    df = safe_pykrx_call(bond.get_otc_treasury_yields, start, end, bond_type)
    return {
        "bond_type": bond_type,
        "count": len(df),
        "data": df_to_records(df),
    }


# ─────────────────────────────────────────────────────────
# 11. ETF (네이버 금융 JSON API — 로그인 불필요!)
# ─────────────────────────────────────────────────────────

@app.get("/api/etf/list")
def get_etf_list(
    sort_by: str = Query("market_sum", description="정렬 기준"),
    top_n: int = Query(50),
):
    """ETF 전체 목록 (네이버 금융 JSON API — 1000+개 ETF)"""
    items = nf.get_etf_list(sort_by=sort_by)

    return {
        "source": "naver",
        "count": min(len(items), top_n),
        "total": len(items),
        "data": items[:top_n],
    }


@app.get("/api/etf/ohlcv")
def get_etf_ohlcv(
    ticker: str = Query("069500", description="ETF 종목코드"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """ETF OHLCV (네이버 차트 API — ETF도 주식과 같은 방식으로 조회)"""
    end = end or business_day_str(0)
    start = start or (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")

    df = nf.get_ohlcv(ticker, start, end)
    return {
        "ticker": ticker,
        "source": "naver",
        "count": len(df),
        "data": df_to_records(df),
    }


# ─────────────────────────────────────────────────────────
# 12. 실시간 지수 (네이버 금융 polling API)
# ─────────────────────────────────────────────────────────

@app.get("/api/index/realtime")
def get_realtime_index():
    """실시간 코스피/코스닥/코스피200 지수"""
    data = nf.get_realtime_index(["KOSPI", "KOSDAQ", "KPI200"])
    return {"source": "naver", "count": len(data), "data": data}


# ─────────────────────────────────────────────────────────
# 13. 자연어 질의 (간단한 매핑)
# ─────────────────────────────────────────────────────────

class NLQueryRequest(BaseModel):
    query: str
    execute: bool = True


@app.post("/api/natural-language")
def natural_language_query(req: NLQueryRequest):
    """자연어 → API 변환 (간단한 키워드 매칭)"""
    q = req.query.lower()

    # 간단한 의도 분류
    if any(kw in q for kw in ["삼성전자", "005930"]):
        ticker = "005930"
    elif any(kw in q for kw in ["sk하이닉스", "000660"]):
        ticker = "000660"
    else:
        ticker = None

    if any(kw in q for kw in ["주가", "ohlcv", "가격", "시세"]):
        intent = "ohlcv"
    elif any(kw in q for kw in ["시가총액", "시총"]):
        intent = "market-cap"
    elif any(kw in q for kw in ["per", "pbr", "재무"]):
        intent = "fundamental"
    elif any(kw in q for kw in ["외국인", "외인"]):
        intent = "foreign"
    elif any(kw in q for kw in ["공매도", "숏"]):
        intent = "short-selling"
    elif any(kw in q for kw in ["채권", "금리", "국고채"]):
        intent = "bond"
    elif any(kw in q for kw in ["지수", "코스피200"]):
        intent = "index"
    else:
        intent = "all-markets"

    # 실행
    result = None
    if req.execute:
        try:
            if intent == "ohlcv" and ticker:
                data = get_stock_ohlcv(ticker=ticker)
                result = {"success": True, "data": data["data"][:20], "count": data["count"]}
            elif intent == "market-cap":
                data = get_market_cap()
                result = {"success": True, "data": data["data"][:20], "count": data["count"]}
            elif intent == "fundamental":
                data = get_fundamental()
                result = {"success": True, "data": data["data"][:20], "count": data["count"]}
            elif intent == "foreign":
                data = get_foreign_holding()
                result = {"success": True, "data": data["data"][:20], "count": data["count"]}
            elif intent == "bond":
                data = get_bond_yields()
                result = {"success": True, "data": data["data"], "count": data["count"]}
            else:
                data = get_all_markets()
                result = {"success": True, "data": data["data"][:20], "count": data["count"]}
        except Exception as e:
            result = {"success": False, "error": str(e)}

    return {
        "query": req.query,
        "intent": intent,
        "confidence": 0.8,
        "method": "keyword-matching",
        "endpoint": f"/api/{intent}",
        "parameters": {"ticker": ticker} if ticker else {},
        "latency_ms": 0,
        "executed": req.execute,
        "result": result,
    }


# ─────────────────────────────────────────────────────────
# 14. 거래량/거래대금 분석
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/trading-volume")
def get_trading_volume(
    ticker: str = Query("005930"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """개별 종목 거래량 추이"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_market_trading_volume_by_date, start, end, ticker)
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "count": len(df), "data": df_to_records(df)}


@app.get("/api/stocks/trading-value")
def get_trading_value(
    ticker: str = Query("005930"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """개별 종목 거래대금 추이"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_market_trading_value_by_date, start, end, ticker)
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "count": len(df), "data": df_to_records(df)}


@app.get("/api/stocks/trading-by-investor")
def get_trading_by_investor(
    ticker: str = Query("005930"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    kind: str = Query("volume", description="volume 또는 value"),
):
    """투자자별 거래량/거래대금 (KRX → 네이버 폴백)"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    if kind == "value":
        df = safe_pykrx_call(stock.get_market_trading_value_by_investor, start, end, ticker)
    else:
        df = safe_pykrx_call(stock.get_market_trading_volume_by_investor, start, end, ticker)
    source = "krx"
    if df.empty:
        df = nf.get_investor_trading(ticker, pages=2)
        source = "naver"
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "kind": kind, "source": source, "count": len(df), "data": df_to_records(df)}


@app.get("/api/stocks/trading-value-volume")
def get_trading_value_volume_snapshot(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
):
    """특정일 전 종목 거래량+거래대금 스냅샷"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_market_trading_value_and_volume_by_ticker, date, market=market)
    return {"date": date, "market": market, "count": len(df), "data": df_to_records(df)}


# ─────────────────────────────────────────────────────────
# 15. 시가총액 추이/스냅샷 (pykrx 직접)
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/market-cap-by-date")
def get_market_cap_by_date(
    ticker: str = Query("005930"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """개별 종목 시가총액 추이 (KRX → 네이버 폴백)"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_market_cap_by_date, start, end, ticker)
    source = "krx"
    if df.empty:
        # 네이버 일별시세로 폴백 (시가총액 직접 추이는 없지만 가격+거래량 제공)
        df = nf.get_daily_price(ticker, pages=5)
        source = "naver"
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "source": source, "count": len(df), "data": df_to_records(df)}


@app.get("/api/stocks/market-cap-snapshot")
def get_market_cap_snapshot(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
    top_n: int = Query(50),
):
    """특정일 전 종목 시가총액 스냅샷 (KRX → 네이버 폴백)"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_market_cap_by_ticker, date, market=market)
    source = "krx"
    if df.empty:
        # 네이버 시가총액 순위로 폴백
        pages = max(1, top_n // 50 + 1)
        df = nf.get_market_cap_ranking(market, pages=pages)
        source = "naver"
    if not df.empty:
        if "시가총액" in df.columns:
            df = df.sort_values("시가총액", ascending=False)
        df = df.head(top_n)
    return {"date": date, "market": market, "source": source, "count": len(df), "data": df_to_records(df)}


# ─────────────────────────────────────────────────────────
# 16. 펀더멘털 추이/스냅샷 (pykrx 직접)
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/fundamental-by-date")
def get_fundamental_by_date(
    ticker: str = Query("005930"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """개별 종목 PER/PBR/EPS/BPS 추이 (KRX → 네이버 폴백)"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_market_fundamental_by_date, start, end, ticker)
    source = "krx"
    if df.empty:
        # 네이버에서 현재 PER/PBR/EPS/BPS 가져오기 (추이는 아니지만 현재값 제공)
        info = nf.get_financial_info(ticker)
        if info:
            df = pd.DataFrame([info])
        source = "naver"
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "source": source, "count": len(df), "data": df_to_records(df)}


@app.get("/api/stocks/fundamental-snapshot")
def get_fundamental_snapshot(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
    top_n: int = Query(50),
):
    """특정일 전 종목 PER/PBR/EPS/BPS 스냅샷 (KRX → 네이버 폴백)"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_market_fundamental_by_ticker, date, market=market)
    source = "krx"
    if df.empty:
        # 네이버 시가총액 순위에 PER/ROE 포함
        df = nf.get_market_cap_ranking(market, pages=max(1, top_n // 50 + 1))
        source = "naver"
    if not df.empty:
        df = df.head(top_n)
    return {"date": date, "market": market, "source": source, "count": len(df), "data": df_to_records(df)}


# ─────────────────────────────────────────────────────────
# 17. 등락률/업종분류/주요변동
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/price-change")
def get_price_change(
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: str = Query("KOSPI"),
    top_n: int = Query(50),
):
    """전 종목 등락률 (KRX → 네이버 폴백)"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_market_price_change_by_ticker, start, end, market=market)
    source = "krx"
    if df.empty:
        df = nf.get_price_change_ranking("rise", market)
        source = "naver"
    if not df.empty:
        if "등락률" in df.columns:
            df = df.sort_values("등락률", ascending=False)
        df = df.head(top_n)
    return {"start": start, "end": end, "market": market, "source": source, "count": len(df), "data": df_to_records(df)}


@app.get("/api/stocks/sector")
def get_sector_classifications(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
):
    """
    업종 분류
    1순위: KRX 직접 (outerLoader OTP)
    2순위: pykrx
    3순위: 네이버 폴백
    """
    date = date or business_day_str(1)
    source = "krx_direct"
    mkt = "STK" if market == "KOSPI" else "KSQ"

    # 1순위: KRX 직접
    krx = get_krx_fetcher()
    df = krx.fetch("sector", trdDd=date, mktId=mkt)

    # 2순위: pykrx
    if df.empty:
        source = "krx"
        df = safe_pykrx_call(stock.get_market_sector_classifications, date, market=market)

    # 3순위: 네이버
    if df.empty:
        source = "naver"
        df = nf.get_sector_list()

    return {"date": date, "market": market, "source": source, "count": len(df), "data": df_to_records(df)}


@app.get("/api/stocks/major-changes")
def get_major_changes(
    date: Optional[str] = None,
    market: str = Query("ALL"),
):
    """주요 변동 사항 (IPO/상장폐지 등)"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_stock_major_changes, date, market=market)
    return {"date": date, "count": len(df), "data": df_to_records(df)}


@app.get("/api/stocks/ohlcv-snapshot")
def get_ohlcv_snapshot(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
    top_n: int = Query(50),
):
    """특정일 전 종목 OHLCV 스냅샷 (KRX → 네이버 폴백)"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_market_ohlcv_by_ticker, date, market=market)
    source = "krx"
    if df.empty:
        # 네이버 시가총액 페이지에 현재가/거래량 포함
        df = nf.get_market_cap_ranking(market, pages=max(1, top_n // 50 + 1))
        source = "naver"
    if not df.empty:
        if "거래량" in df.columns:
            df = df.sort_values("거래량", ascending=False)
        df = df.head(top_n)
    return {"date": date, "market": market, "source": source, "count": len(df), "data": df_to_records(df)}


# ─────────────────────────────────────────────────────────
# 18. 투자자별 순매수
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/net-purchases")
def get_net_purchases(
    ticker: str = Query("005930"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """투자자별 순매수 금액 추이"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_market_net_purchases_of_equities, start, end, ticker)
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "count": len(df), "data": df_to_records(df)}


@app.get("/api/stocks/net-purchases-snapshot")
def get_net_purchases_snapshot(
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: str = Query("KOSPI"),
    investor: str = Query("외국인합계"),
    top_n: int = Query(30),
):
    """특정 기간 투자자별 순매수 종목 순위"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=7)).strftime("%Y%m%d")
    df = safe_pykrx_call(
        stock.get_market_net_purchases_of_equities_by_ticker, start, end, market=market, investor=investor
    )
    if not df.empty:
        df = df.sort_values("순매수거래대금", ascending=False).head(top_n)
    return {"start": start, "end": end, "market": market, "investor": investor, "count": len(df), "data": df_to_records(df)}


# ─────────────────────────────────────────────────────────
# 19. 지수 심화
# ─────────────────────────────────────────────────────────

@app.get("/api/index/ohlcv-snapshot")
def get_index_ohlcv_snapshot(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
):
    """특정일 전체 지수 OHLCV 스냅샷"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_index_ohlcv_by_ticker, date, market=market)
    return {"date": date, "market": market, "count": len(df), "data": df_to_records(df)}


@app.get("/api/index/fundamental")
def get_index_fundamental_history(
    ticker: str = Query("1028", description="지수코드"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """지수 PER/PBR/배당수익률 추이"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_index_fundamental_by_date, start, end, ticker)
    name = stock.get_index_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "count": len(df), "data": df_to_records(df)}


@app.get("/api/index/fundamental-snapshot")
def get_index_fundamental_snapshot(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
):
    """특정일 전체 지수 PER/PBR/배당수익률 스냅샷"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_index_fundamental_by_ticker, date, market=market)
    return {"date": date, "market": market, "count": len(df), "data": df_to_records(df)}


@app.get("/api/index/composition")
def get_index_composition(
    ticker: str = Query("1028", description="지수코드"),
    date: Optional[str] = None,
):
    """지수 구성 종목 (PDF: Portfolio Deposit File)"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_index_portfolio_deposit_file, date, ticker)
    name = stock.get_index_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "date": date, "count": len(df), "data": df_to_records(df)}


@app.get("/api/index/price-change")
def get_index_price_change(
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: str = Query("KOSPI"),
):
    """전체 지수 등락률 (기간 수익률)"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_index_price_change_by_ticker, start, end, market=market)
    return {"start": start, "end": end, "market": market, "count": len(df), "data": df_to_records(df)}


@app.get("/api/index/listing-date")
def get_index_listing_date(
    ticker: str = Query("1028"),
):
    """지수 상장일 (메타 정보)"""
    result = safe_pykrx_call(stock.get_index_listing_date, ticker)
    name = stock.get_index_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "listing_date": str(result) if result else None}


# ─────────────────────────────────────────────────────────
# 20. ETF 심화
# ─────────────────────────────────────────────────────────

@app.get("/api/etf/ticker-list")
def get_etf_ticker_list_krx(
    date: Optional[str] = None,
):
    """ETF 종목코드 목록 (KRX)"""
    date = date or business_day_str(1)
    tickers = safe_pykrx_call(stock.get_etf_ticker_list, date)
    if not isinstance(tickers, list):
        return {"count": 0, "data": []}
    results = []
    for t in tickers:
        name = stock.get_etf_ticker_name(t)
        results.append({"종목코드": t, "종목명": name})
    return {"date": date, "count": len(results), "data": results}


@app.get("/api/etf/ohlcv-krx")
def get_etf_ohlcv_krx(
    ticker: str = Query("069500"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """ETF OHLCV 추이 (KRX 직접)"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_etf_ohlcv_by_date, start, end, ticker)
    name = stock.get_etf_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "count": len(df), "data": df_to_records(df)}


@app.get("/api/etf/ohlcv-snapshot")
def get_etf_ohlcv_snapshot(
    date: Optional[str] = None,
    top_n: int = Query(50),
):
    """특정일 전체 ETF OHLCV 스냅샷"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_etf_ohlcv_by_ticker, date)
    if not df.empty:
        df = df.sort_values("거래량", ascending=False).head(top_n)
    return {"date": date, "count": len(df), "data": df_to_records(df)}


@app.get("/api/etf/price-change")
def get_etf_price_change(
    start: Optional[str] = None,
    end: Optional[str] = None,
    top_n: int = Query(50),
):
    """전체 ETF 등락률 (기간 수익률)"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_etf_price_change_by_ticker, start, end)
    if not df.empty:
        df = df.sort_values("등락률", ascending=False).head(top_n)
    return {"start": start, "end": end, "count": len(df), "data": df_to_records(df)}


@app.get("/api/etf/tracking-error")
def get_etf_tracking_error(
    date: Optional[str] = None,
    top_n: int = Query(50),
):
    """ETF 추적오차 (벤치마크 대비 괴리)"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_etf_tracking_error, date)
    if not df.empty:
        df = df.head(top_n)
    return {"date": date, "count": len(df), "data": df_to_records(df)}


@app.get("/api/etf/price-deviation")
def get_etf_price_deviation(
    date: Optional[str] = None,
    top_n: int = Query(50),
):
    """ETF 괴리율 (NAV 대비 시장가 차이)"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_etf_price_deviation, date)
    if not df.empty:
        df = df.head(top_n)
    return {"date": date, "count": len(df), "data": df_to_records(df)}


@app.get("/api/etf/holdings")
def get_etf_holdings(
    ticker: str = Query("069500"),
    date: Optional[str] = None,
):
    """ETF 구성 종목 (PDF: Portfolio Deposit File)"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_etf_portfolio_deposit_file, date, ticker)
    name = stock.get_etf_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "date": date, "count": len(df), "data": df_to_records(df)}


@app.get("/api/etf/isin")
def get_etf_isin(
    ticker: str = Query("069500"),
):
    """ETF ISIN 코드 조회"""
    isin = safe_pykrx_call(stock.get_etf_isin, ticker)
    name = stock.get_etf_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "isin": str(isin) if isin else None}


@app.get("/api/etf/trading-volume-value")
def get_etf_trading_volume_value(
    date: Optional[str] = None,
    top_n: int = Query(50),
):
    """ETF 거래량/거래대금 스냅샷"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_etf_trading_volume_and_value, date)
    if not df.empty:
        df = df.head(top_n)
    return {"date": date, "count": len(df), "data": df_to_records(df)}


# ─────────────────────────────────────────────────────────
# 21. ETN / ELW / 레버리지 목록
# ─────────────────────────────────────────────────────────

@app.get("/api/etn/list")
def get_etn_list(
    date: Optional[str] = None,
):
    """ETN 종목 목록"""
    date = date or business_day_str(1)
    tickers = safe_pykrx_call(stock.get_etn_ticker_list, date)
    if not isinstance(tickers, list):
        return {"count": 0, "data": []}
    results = []
    for t in tickers:
        name = stock.get_etn_ticker_name(t)
        results.append({"종목코드": t, "종목명": name})
    return {"date": date, "count": len(results), "data": results}


@app.get("/api/elw/list")
def get_elw_list(
    date: Optional[str] = None,
):
    """ELW 종목 목록"""
    date = date or business_day_str(1)
    tickers = safe_pykrx_call(stock.get_elw_ticker_list, date)
    if not isinstance(tickers, list):
        return {"count": 0, "data": []}
    results = []
    for t in tickers:
        name = stock.get_elw_ticker_name(t)
        results.append({"종목코드": t, "종목명": name})
    return {"date": date, "count": len(results), "data": results}


@app.get("/api/etx/list")
def get_etx_list(
    date: Optional[str] = None,
):
    """레버리지/인버스 ETF 목록"""
    date = date or business_day_str(1)
    tickers = safe_pykrx_call(stock.get_etx_ticker_list, date)
    if not isinstance(tickers, list):
        return {"count": 0, "data": []}
    results = []
    for t in tickers:
        results.append({"종목코드": t})
    return {"date": date, "count": len(results), "data": results}


# ─────────────────────────────────────────────────────────
# 22. 공매도 심화
# ─────────────────────────────────────────────────────────

@app.get("/api/short-selling/volume")
def get_shorting_volume(
    ticker: str = Query("005930"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """공매도 거래량 추이"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_shorting_volume_by_date, start, end, ticker)
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "count": len(df), "data": df_to_records(df)}


@app.get("/api/short-selling/volume-snapshot")
def get_shorting_volume_snapshot(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
    top_n: int = Query(30),
):
    """특정일 전 종목 공매도 거래량 스냅샷"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_shorting_volume_by_ticker, date, market=market)
    if not df.empty:
        df = df.sort_values("공매도거래량", ascending=False).head(top_n)
    return {"date": date, "market": market, "count": len(df), "data": df_to_records(df)}


@app.get("/api/short-selling/volume-top50")
def get_shorting_volume_top50(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
):
    """공매도 거래량 상위 50종목"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_shorting_volume_top50, date, market)
    return {"date": date, "market": market, "count": len(df), "data": df_to_records(df)}


@app.get("/api/short-selling/value")
def get_shorting_value(
    ticker: str = Query("005930"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """공매도 거래대금 추이"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_shorting_value_by_date, start, end, ticker)
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "count": len(df), "data": df_to_records(df)}


@app.get("/api/short-selling/value-snapshot")
def get_shorting_value_snapshot(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
    top_n: int = Query(30),
):
    """특정일 전 종목 공매도 거래대금 스냅샷"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_shorting_value_by_ticker, date, market=market)
    if not df.empty:
        df = df.head(top_n)
    return {"date": date, "market": market, "count": len(df), "data": df_to_records(df)}


@app.get("/api/short-selling/balance-snapshot")
def get_shorting_balance_snapshot(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
    top_n: int = Query(30),
):
    """특정일 전 종목 공매도 잔고 스냅샷"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_shorting_balance_by_ticker, date, market=market)
    if not df.empty:
        df = df.head(top_n)
    return {"date": date, "market": market, "count": len(df), "data": df_to_records(df)}


@app.get("/api/short-selling/investor")
def get_shorting_by_investor(
    ticker: str = Query("005930"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    kind: str = Query("volume", description="volume 또는 value"),
):
    """투자자별 공매도 거래량/거래대금"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    if kind == "value":
        df = safe_pykrx_call(stock.get_shorting_investor_value_by_date, start, end, ticker)
    else:
        df = safe_pykrx_call(stock.get_shorting_investor_volume_by_date, start, end, ticker)
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "kind": kind, "count": len(df), "data": df_to_records(df)}


@app.get("/api/short-selling/status")
def get_shorting_status(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
):
    """공매도 가능/불가능 종목 현황"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_shorting_status_by_date, date, market=market)
    return {"date": date, "market": market, "count": len(df), "data": df_to_records(df)}


# ─────────────────────────────────────────────────────────
# 23. 외국인 투자 추이
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/foreign-by-date")
def get_foreign_by_date(
    ticker: str = Query("005930"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """외국인 보유/한도 소진율 추이 (KRX → 네이버 폴백)"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_exhaustion_rates_of_foreign_investment_by_date, start, end, ticker)
    source = "krx"
    if df.empty:
        df = nf.get_foreign_holding(ticker, pages=3)
        source = "naver"
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "source": source, "count": len(df), "data": df_to_records(df)}


# ─────────────────────────────────────────────────────────
# 24. 선물 (파생상품)
# ─────────────────────────────────────────────────────────

@app.get("/api/futures/list")
def get_future_list(
    date: Optional[str] = None,
):
    """선물 종목 목록"""
    date = date or business_day_str(1)
    tickers = safe_pykrx_call(stock.get_future_ticker_list, date)
    if not isinstance(tickers, list):
        return {"count": 0, "data": []}
    results = []
    for t in tickers[:50]:  # 선물은 많으므로 50개 제한
        name = stock.get_future_ticker_name(t)
        results.append({"종목코드": t, "종목명": name})
    return {"date": date, "count": len(results), "data": results}


@app.get("/api/futures/ohlcv")
def get_future_ohlcv(
    ticker: str = Query(..., description="선물 종목코드"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """선물 OHLCV 추이"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")
    df = safe_pykrx_call(stock.get_future_ohlcv, start, end, ticker)
    name = stock.get_future_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "count": len(df), "data": df_to_records(df)}


@app.get("/api/futures/ohlcv-snapshot")
def get_future_ohlcv_snapshot(
    date: Optional[str] = None,
):
    """특정일 전체 선물 OHLCV 스냅샷"""
    date = date or business_day_str(1)
    df = safe_pykrx_call(stock.get_future_ohlcv_by_ticker, date)
    return {"date": date, "count": len(df), "data": df_to_records(df)}


# ─────────────────────────────────────────────────────────
# 25. 유틸리티 (영업일 조회)
# ─────────────────────────────────────────────────────────

@app.get("/api/util/business-days")
def get_business_day_list(
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """영업일 목록 조회"""
    end = end or business_day_str(0)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    days = safe_pykrx_call(stock.get_business_days, start, end)
    if not isinstance(days, list):
        days = list(days) if days is not None else []
    return {"start": start, "end": end, "count": len(days), "data": [str(d) for d in days]}


@app.get("/api/util/previous-business-days")
def get_previous_bdays(
    n: int = Query(5, description="최근 N 영업일"),
):
    """최근 N 영업일 조회"""
    days = safe_pykrx_call(stock.get_previous_business_days, n=n)
    if not isinstance(days, list):
        days = list(days) if days is not None else []
    return {"n": n, "count": len(days), "data": [str(d) for d in days]}


@app.get("/api/util/nearest-business-day")
def get_nearest_bday(
    date: Optional[str] = None,
):
    """가장 가까운 영업일 조회"""
    date = date or datetime.date.today().strftime("%Y%m%d")
    result = safe_pykrx_call(stock.get_nearest_business_day_in_a_week, date)
    return {"input_date": date, "nearest_business_day": str(result) if result else None}


# ─────────────────────────────────────────────────────────
# 26. 종목 목록 (pykrx 직접)
# ─────────────────────────────────────────────────────────

@app.get("/api/stocks/ticker-list")
def get_ticker_list_krx(
    date: Optional[str] = None,
    market: str = Query("KOSPI"),
):
    """종목코드 목록 (KRX 직접 — 불안정할 수 있음)"""
    date = date or business_day_str(1)
    tickers = safe_pykrx_call(stock.get_market_ticker_list, date, market=market)
    if not isinstance(tickers, list):
        return {"count": 0, "data": [], "note": "KRX API 불안정 — /api/stocks/list 사용 권장"}
    results = []
    for t in tickers:
        name = stock.get_market_ticker_name(t)
        results.append({"종목코드": t, "종목명": name})
    return {"date": date, "market": market, "count": len(results), "data": results}


# ─────────────────────────────────────────────────────────
# 27. 네이버 전용 엔드포인트 (KRX 우회)
# ─────────────────────────────────────────────────────────

@app.get("/api/naver/price-ranking")
def get_naver_price_ranking(
    direction: str = Query("rise", description="rise=상승 / fall=하락"),
    market: str = Query("KOSPI"),
):
    """등락률 순위 (네이버 금융 — 장중만 데이터 있음)"""
    df = nf.get_price_change_ranking(direction, market)
    return {"direction": direction, "market": market, "source": "naver", "count": len(df), "data": df_to_records(df)}


@app.get("/api/naver/sector-list")
def get_naver_sector_list():
    """업종별 시세 (네이버 금융)"""
    df = nf.get_sector_list()
    return {"source": "naver", "count": len(df), "data": df_to_records(df)}


@app.get("/api/naver/investor-trend")
def get_naver_investor_trend(
    market: str = Query("KOSPI"),
):
    """투자자별 매매동향 — 시장 전체 (네이버 금융)"""
    df = nf.get_investor_trend_daily(market)
    return {"market": market, "source": "naver", "count": len(df), "data": df_to_records(df)}


@app.get("/api/naver/daily-price")
def get_naver_daily_price(
    ticker: str = Query("005930"),
    pages: int = Query(3, description="페이지 수 (1페이지=10일)"),
):
    """일별 시세 — 개별 종목 (네이버 금융 HTML)"""
    df = nf.get_daily_price(ticker, pages=pages)
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "source": "naver", "count": len(df), "data": df_to_records(df)}


@app.get("/api/naver/foreign-holding")
def get_naver_foreign_holding(
    ticker: str = Query("005930"),
    pages: int = Query(3),
):
    """외국인 보유현황 추이 (네이버 금융)"""
    df = nf.get_foreign_holding(ticker, pages=pages)
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "source": "naver", "count": len(df), "data": df_to_records(df)}


@app.get("/api/naver/financial-statements")
def get_naver_financial_statements(
    ticker: str = Query("005930"),
    freq: str = Query("Y", description="Y=연간, Q=분기"),
):
    """재무제표 (네이버 금융 — 연간/분기 실적)"""
    df = nf.get_financial_statements(ticker, freq_typ=freq)
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "freq": freq, "source": "naver", "count": len(df), "data": df_to_records(df)}


# ─────────────────────────────────────────────────────────
# 28. KRX 직접 수집 엔드포인트 (outerLoader 우회)
# ─────────────────────────────────────────────────────────

@app.get("/api/krx-direct/status")
def get_krx_direct_status():
    """KRX 직접 접속 상태 + 사용 가능한 엔드포인트 목록"""
    return krx_direct_status()


@app.get("/api/krx-direct/investor-trading")
def get_krx_direct_investor_trading(
    date: Optional[str] = None,
    market: str = Query("STK", description="STK=유가증권, KSQ=코스닥"),
):
    """투자자별 매매동향 — KRX 직접 수집 (outerLoader OTP)"""
    date = date or business_day_str(1)
    krx = get_krx_fetcher()
    df = krx.fetch("investor_trading", trdDd=date, mktId=market)
    return {"date": date, "market": market, "source": "krx_direct", "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-direct/investor-daily")
def get_krx_direct_investor_daily(
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: str = Query("STK"),
):
    """투자자별 일별 순매수 추이 — KRX 직접"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    krx = get_krx_fetcher()
    df = krx.fetch("investor_daily", strtDd=start, endDd=end, mktId=market)
    return {"start": start, "end": end, "market": market, "source": "krx_direct", "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-direct/investor-detail")
def get_krx_direct_investor_detail(
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: str = Query("STK"),
):
    """투자자별 세부 분류 (금융투자/보험/투신 등) — KRX 직접"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    krx = get_krx_fetcher()
    df = krx.fetch("investor_detail", strtDd=start, endDd=end, mktId=market)
    return {"start": start, "end": end, "market": market, "source": "krx_direct", "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-direct/sector")
def get_krx_direct_sector(
    date: Optional[str] = None,
    market: str = Query("STK"),
):
    """업종 분류 — KRX 직접"""
    date = date or business_day_str(1)
    krx = get_krx_fetcher()
    df = krx.fetch("sector", trdDd=date, mktId=market)
    return {"date": date, "market": market, "source": "krx_direct", "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-direct/issued-securities")
def get_krx_direct_issued_securities(
    date: Optional[str] = None,
):
    """발행증권 현황 (ELS/DLS 등) — KRX 직접 (대량 데이터!)"""
    date = date or business_day_str(1)
    krx = get_krx_fetcher()
    df = krx.fetch("issued_securities", trdDd=date)
    return {"date": date, "source": "krx_direct", "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-direct/price-ranking")
def get_krx_direct_price_ranking(
    date: Optional[str] = None,
    market: str = Query("STK"),
):
    """등락률 랭킹 — KRX 직접"""
    date = date or business_day_str(1)
    krx = get_krx_fetcher()
    df = krx.fetch("price_ranking", trdDd=date, mktId=market)
    return {"date": date, "market": market, "source": "krx_direct", "count": len(df), "data": df_to_records(df)}


# ─────────────────────────────────────────────────────────
# 29. KRX 인증 데이터 엔드포인트 (ID/PW 로그인 방식)
#     outerLoader(28번)보다 더 많은 데이터에 접근 가능!
# ─────────────────────────────────────────────────────────

@app.get("/api/krx-auth/status")
def get_krx_auth_status():
    """KRX 인증 로그인 상태 + 사용 가능한 엔드포인트 목록"""
    return get_krx_auth().status()


@app.get("/api/krx-auth/all-stock-price")
def get_krx_auth_all_stock_price(
    date: Optional[str] = None,
    market: str = Query("STK", description="STK=유가증권, KSQ=코스닥"),
):
    """전체 종목 시세 — KRX 인증 (종가/등락률/거래량 등, ~951개 종목)"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("all_stock_price", trdDd=date, mktId=market)
    return {"date": date, "market": market, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/market-cap")
def get_krx_auth_market_cap(
    date: Optional[str] = None,
    market: str = Query("STK"),
):
    """시가총액 — KRX 인증 (상장주수, 시가총액 등)"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("market_cap", trdDd=date, mktId=market)
    return {"date": date, "market": market, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/foreign-holding")
def get_krx_auth_foreign_holding(
    date: Optional[str] = None,
    market: str = Query("STK"),
):
    """외국인 보유 + PER/PBR/EPS/배당수익률 — KRX 인증 (~920개 종목)"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("foreign_holding", trdDd=date, mktId=market)
    return {"date": date, "market": market, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/sector-price")
def get_krx_auth_sector_price(
    date: Optional[str] = None,
    market: str = Query("STK"),
):
    """업종별 종목 분류 및 시세 — KRX 인증"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("sector_price", trdDd=date, mktId=market)
    return {"date": date, "market": market, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/index-price")
def get_krx_auth_index_price(
    date: Optional[str] = None,
):
    """KOSPI/KOSDAQ 지수 시세 — KRX 인증 (51개 지수)"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("index_price", trdDd=date)
    return {"date": date, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/investor-daily")
def get_krx_auth_investor_daily(
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: str = Query("STK"),
):
    """투자자별 일별 순매수 추이 — KRX 인증 (금융투자/보험/투신/은행 등)"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    auth = get_krx_auth()
    df = auth.fetch("investor_daily", strtDd=start, endDd=end, mktId=market)
    return {"start": start, "end": end, "market": market, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/program-trading")
def get_krx_auth_program_trading(
    date: Optional[str] = None,
    market: str = Query("STK"),
):
    """프로그램 매매 (차익/비차익 거래) — KRX 인증"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("program_trading", trdDd=date, mktId=market)
    return {"date": date, "market": market, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/etf-price")
def get_krx_auth_etf_price(
    date: Optional[str] = None,
):
    """ETF 전종목 시세 — KRX 인증 (1075개+ ETF)"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("etf_price", trdDd=date)
    return {"date": date, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/stock-daily")
def get_krx_auth_stock_daily(
    ticker: str = Query(..., description="종목코드 (예: 005930)"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """개별 종목 일별 시세 — KRX 인증 (종가/시가/고가/저가/거래량)"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    auth = get_krx_auth()
    isu_cd = f"KR7{ticker}003"  # KRX 종목코드 변환
    df = auth.fetch("stock_daily", isuCd=isu_cd, isuCd2=isu_cd,
                    strtDd=start, endDd=end)
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "start": start, "end": end,
            "source": "krx_auth", "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/investor-trend")
def get_krx_auth_investor_trend(
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: str = Query("STK"),
):
    """투자자별 일별추이 (기관/외국인/개인 3분류) — KRX 인증"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    auth = get_krx_auth()
    df = auth.fetch("investor_trend", strtDd=start, endDd=end, mktId=market)
    return {"start": start, "end": end, "market": market, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/investor-by-stock")
def get_krx_auth_investor_by_stock(
    ticker: str = Query(..., description="종목코드 (예: 005930)"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """개별 종목 투자자별 매매동향 — KRX 인증 (13개 투자자 유형)"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    auth = get_krx_auth()
    isu_cd = f"KR7{ticker}003"
    df = auth.fetch("investor_by_stock", isuCd=isu_cd, strtDd=start, endDd=end)
    name = stock.get_market_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "start": start, "end": end,
            "source": "krx_auth", "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/market-trading")
def get_krx_auth_market_trading(
    date: Optional[str] = None,
    market: str = Query("STK"),
):
    """시장 거래현황 (거래정지/정리매매/관리종목 여부 포함) — KRX 인증"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("market_trading", trdDd=date, mktId=market)
    return {"date": date, "market": market, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/program-daily")
def get_krx_auth_program_daily(
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: str = Query("STK"),
):
    """프로그램매매 일별추이 (차익/비차익/합계) — KRX 인증"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    auth = get_krx_auth()
    df = auth.fetch("program_daily", strtDd=start, endDd=end, mktId=market)
    return {"start": start, "end": end, "market": market, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/foreign-exhaustion")
def get_krx_auth_foreign_exhaustion(
    date: Optional[str] = None,
    market: str = Query("STK"),
):
    """외국인 보유한도 소진률 — KRX 인증 (종목별 외국인 한도/잔여)"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("foreign_exhaustion", trdDd=date, mktId=market)
    return {"date": date, "market": market, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/dividend")
def get_krx_auth_dividend(
    date: Optional[str] = None,
    market: str = Query("STK"),
):
    """업종별 배당현황 — KRX 인증"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("dividend", trdDd=date, mktId=market)
    return {"date": date, "market": market, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/index-trend")
def get_krx_auth_index_trend(
    start: Optional[str] = None,
    end: Optional[str] = None,
    index_code: str = Query("1001", description="지수코드 (1001=코스피)"),
    index_class: str = Query("02", description="02=KOSPI, 03=KOSDAQ"),
):
    """개별 지수 시세추이 — KRX 인증"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    auth = get_krx_auth()
    df = auth.fetch("index_trend", strtDd=start, endDd=end,
                    idxCd=index_code, idxIndMidclssCd=index_class)
    return {"start": start, "end": end, "index_code": index_code,
            "source": "krx_auth", "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/elw-price")
def get_krx_auth_elw_price(
    date: Optional[str] = None,
):
    """ELW 전종목 시세 — KRX 인증"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("elw_price", trdDd=date)
    return {"date": date, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/bond-price")
def get_krx_auth_bond_price(
    date: Optional[str] = None,
):
    """국채/채권 시세 — KRX 인증"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("bond_price", trdDd=date)
    return {"date": date, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/issued-securities")
def get_krx_auth_issued_securities(
    date: Optional[str] = None,
):
    """발행증권 현황 (ELS/DLS 등) — KRX 인증 (1282개+)"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("issued_securities", trdDd=date)
    return {"date": date, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/investor-summary")
def get_krx_auth_investor_summary(
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: str = Query("STK"),
):
    """투자자별 매매동향 기간합산 — KRX 인증 (13개 투자자 유형)"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    auth = get_krx_auth()
    df = auth.fetch("investor_summary", strtDd=start, endDd=end, mktId=market)
    return {"start": start, "end": end, "market": market, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/investor-top-net-buying")
def get_krx_auth_investor_top(
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: str = Query("STK"),
    investor: str = Query("9000", description="9000=외국인, 1000=기관"),
):
    """투자자별 순매수 상위 종목 — KRX 인증"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    auth = get_krx_auth()
    df = auth.fetch("investor_top_net_buying", strtDd=start, endDd=end,
                    mktId=market, invstTpCd=investor)
    return {"start": start, "end": end, "market": market, "investor": investor,
            "source": "krx_auth", "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/short-selling-all")
def get_krx_auth_short_selling_all(
    date: Optional[str] = None,
    market: str = Query("STK"),
):
    """공매도 전체 종목별 현황 — KRX 인증 (~951개)"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("short_selling_all", trdDd=date, mktId=market)
    return {"date": date, "market": market, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/short-selling-stock")
def get_krx_auth_short_selling_stock(
    ticker: str = Query(..., description="종목코드 (예: 005930)"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """개별 종목 공매도 요약 — KRX 인증"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    auth = get_krx_auth()
    isu_cd = f"KR7{ticker}003"
    df = auth.fetch("short_selling_stock", isuCd=isu_cd, strtDd=start, endDd=end)
    return {"ticker": ticker, "start": start, "end": end, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/short-selling-stock-daily")
def get_krx_auth_short_selling_stock_daily(
    ticker: str = Query(..., description="종목코드 (예: 005930)"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """개별 종목 공매도 일별추이 — KRX 인증"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    auth = get_krx_auth()
    isu_cd = f"KR7{ticker}003"
    df = auth.fetch("short_selling_stock_daily", isuCd=isu_cd, strtDd=start, endDd=end)
    return {"ticker": ticker, "start": start, "end": end, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/short-selling-investor")
def get_krx_auth_short_selling_investor(
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """투자자별 공매도 거래 일별추이 — KRX 인증"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    auth = get_krx_auth()
    df = auth.fetch("short_selling_investor", strtDd=start, endDd=end)
    return {"start": start, "end": end, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/short-selling-top50")
def get_krx_auth_short_selling_top50(
    date: Optional[str] = None,
):
    """공매도 거래 상위 50 종목 — KRX 인증"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("short_selling_top50", trdDd=date)
    return {"date": date, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/short-selling-balance")
def get_krx_auth_short_selling_balance(
    ticker: str = Query(..., description="종목코드 (예: 005930)"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """개별 종목 공매도 잔고 추이 — KRX 인증"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    auth = get_krx_auth()
    isu_cd = f"KR7{ticker}003"
    df = auth.fetch("short_selling_balance", isuCd=isu_cd, strtDd=start, endDd=end)
    return {"ticker": ticker, "start": start, "end": end, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/derivative-price")
def get_krx_auth_derivative_price(
    date: Optional[str] = None,
    product: str = Query("KRDRVFUK2I", description="KRDRVFUK2I=코스피선물, KRDRVOPK2I=코스피옵션, KRDRVFUUSD=달러선물"),
):
    """파생상품 시세 (선물/옵션) — KRX 인증"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("derivative_price", trdDd=date, prodId=product)
    return {"date": date, "product": product, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/etn-price")
def get_krx_auth_etn_price(
    date: Optional[str] = None,
):
    """ETN 전종목 시세 — KRX 인증 (389개)"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("etn_price", trdDd=date)
    return {"date": date, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/bond-yield")
def get_krx_auth_bond_yield(
    date: Optional[str] = None,
):
    """채권 수익률 (국고/회사채/CD 등) — KRX 인증"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("bond_yield", trdDd=date)
    return {"date": date, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/bond-yield-trend")
def get_krx_auth_bond_yield_trend(
    start: Optional[str] = None,
    end: Optional[str] = None,
    bond_type: str = Query("3000", description="3000=국고3년, 3007=국고5년, 3013=국고10년"),
):
    """채권 수익률 추이 — KRX 인증"""
    end = end or business_day_str(1)
    start = start or (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    auth = get_krx_auth()
    df = auth.fetch("bond_yield_trend", strtDd=start, endDd=end, bndKindTpCd=bond_type)
    return {"start": start, "end": end, "bond_type": bond_type, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/gold-price")
def get_krx_auth_gold_price(
    date: Optional[str] = None,
):
    """금 시세 (KRX 금시장) — KRX 인증"""
    date = date or business_day_str(1)
    auth = get_krx_auth()
    df = auth.fetch("gold_price", trdDd=date)
    return {"date": date, "source": "krx_auth",
            "count": len(df), "data": df_to_records(df)}


@app.get("/api/krx-auth/custom")
def get_krx_auth_custom(
    bld: str = Query(..., description="KRX bld 경로"),
):
    """커스텀 KRX bld 경로로 직접 데이터 가져오기 — KRX 인증"""
    auth = get_krx_auth()
    result = auth.fetch_json(bld)
    return {"bld": bld, "source": "krx_auth", "data": result}


# ============================================================================
# 서버 실행
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
