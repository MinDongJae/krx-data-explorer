"""
데이터 익스플로러 API 라우터
================================
KRX ID/PW 로그인 → 31개 데이터 엔드포인트 + 자연어 질의 + 온톨로지 제공
프론트엔드: krxdata.co.kr/data-explore/

모든 엔드포인트는 /api/data-explore/ prefix로 노출됩니다.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .krx_auth import get_krx_auth, KRX_AUTH_ENDPOINTS
from .krx_ontology import execute_nl_query, get_ontology_summary

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 자연어 질의 요청 모델 ──

class NLQueryRequest(BaseModel):
    query: str
    execute: bool = True


def _today() -> str:
    """오늘 날짜 (YYYYMMDD). 주말이면 직전 금요일."""
    d = datetime.now()
    wd = d.weekday()
    if wd == 5:  # Saturday
        d -= timedelta(days=1)
    elif wd == 6:  # Sunday
        d -= timedelta(days=2)
    return d.strftime("%Y%m%d")


def _df_to_response(df, endpoint_key: str, extra: dict = None) -> JSONResponse:
    """DataFrame → JSON 응답"""
    records = df.to_dict(orient="records") if not df.empty else []
    body = {
        "endpoint": endpoint_key,
        "rows": len(records),
        "columns": list(df.columns) if not df.empty else [],
        "data": records,
    }
    if extra:
        body.update(extra)
    return JSONResponse(body)


# ── 메타 엔드포인트 ──

@router.get("/status")
async def status():
    """KRX 로그인 상태 확인"""
    auth = get_krx_auth()
    return auth.status()


@router.get("/endpoints")
async def list_endpoints():
    """사용 가능한 엔드포인트 목록"""
    eps = []
    for name, cfg in KRX_AUTH_ENDPOINTS.items():
        eps.append({
            "name": name,
            "description": cfg["desc"],
            "date_param": cfg.get("date_param"),
        })
    return {"total": len(eps), "endpoints": eps}


@router.get("/ontology")
async def ontology():
    """온톨로지(지식 지도) 요약 — 엔티티/관계/시간축 구조"""
    return get_ontology_summary()


@router.get("/nl-query")
async def nl_query(
    q: str = Query(description="자연어 질의 (예: 코스피 시가총액 상위 20개 막대차트)"),
):
    """
    자연어 질의 → API 호출 → 데이터 + 차트 설정 반환.
    GET 방식 (CloudFront OAC + AWS_IAM 호환).
    """
    try:
        result = await execute_nl_query(q)
        return JSONResponse(result)
    except Exception as e:
        logger.error("[NL] Error: %s", str(e))
        return JSONResponse(
            {"error": str(e), "query": q},
            status_code=500,
        )


# ── 단일 날짜 조회 엔드포인트 ──

@router.get("/all-stock-price")
async def all_stock_price(
    date: str = Query(default=None, description="YYYYMMDD"),
    market: str = Query(default="STK", description="STK/KSQ/KNX"),
):
    auth = get_krx_auth()
    df = auth.fetch("all_stock_price", trdDd=date or _today(), mktId=market)
    return _df_to_response(df, "all_stock_price", {"date": date or _today()})


@router.get("/market-cap")
async def market_cap(
    date: str = Query(default=None),
    market: str = Query(default="STK"),
):
    auth = get_krx_auth()
    df = auth.fetch("market_cap", trdDd=date or _today(), mktId=market)
    return _df_to_response(df, "market_cap", {"date": date or _today()})


@router.get("/market-trading")
async def market_trading(date: str = Query(default=None), market: str = Query(default="STK")):
    auth = get_krx_auth()
    df = auth.fetch("market_trading", trdDd=date or _today(), mktId=market)
    return _df_to_response(df, "market_trading")


@router.get("/foreign-holding")
async def foreign_holding(date: str = Query(default=None), market: str = Query(default="STK")):
    auth = get_krx_auth()
    df = auth.fetch("foreign_holding", trdDd=date or _today(), mktId=market)
    return _df_to_response(df, "foreign_holding")


@router.get("/foreign-exhaustion")
async def foreign_exhaustion(date: str = Query(default=None), market: str = Query(default="STK")):
    auth = get_krx_auth()
    df = auth.fetch("foreign_exhaustion", trdDd=date or _today(), mktId=market)
    return _df_to_response(df, "foreign_exhaustion")


@router.get("/sector-price")
async def sector_price(date: str = Query(default=None), market: str = Query(default="STK")):
    auth = get_krx_auth()
    df = auth.fetch("sector_price", trdDd=date or _today(), mktId=market)
    return _df_to_response(df, "sector_price")


@router.get("/index-price")
async def index_price(date: str = Query(default=None)):
    auth = get_krx_auth()
    df = auth.fetch("index_price", trdDd=date or _today())
    return _df_to_response(df, "index_price")


@router.get("/etf-price")
async def etf_price(date: str = Query(default=None)):
    auth = get_krx_auth()
    df = auth.fetch("etf_price", trdDd=date or _today())
    return _df_to_response(df, "etf_price")


@router.get("/etn-price")
async def etn_price(date: str = Query(default=None)):
    auth = get_krx_auth()
    df = auth.fetch("etn_price", trdDd=date or _today())
    return _df_to_response(df, "etn_price")


@router.get("/elw-price")
async def elw_price(date: str = Query(default=None)):
    auth = get_krx_auth()
    df = auth.fetch("elw_price", trdDd=date or _today())
    return _df_to_response(df, "elw_price")


@router.get("/short-selling-all")
async def short_selling_all(date: str = Query(default=None), market: str = Query(default="STK")):
    auth = get_krx_auth()
    df = auth.fetch("short_selling_all", trdDd=date or _today(), mktId=market)
    return _df_to_response(df, "short_selling_all")


@router.get("/short-selling-top50")
async def short_selling_top50(date: str = Query(default=None)):
    auth = get_krx_auth()
    df = auth.fetch("short_selling_top50", trdDd=date or _today())
    return _df_to_response(df, "short_selling_top50")


@router.get("/derivative-price")
async def derivative_price(
    date: str = Query(default=None),
    prodId: str = Query(default="KRDRVFUK2I", description="상품코드"),
):
    auth = get_krx_auth()
    df = auth.fetch("derivative_price", trdDd=date or _today(), prodId=prodId)
    return _df_to_response(df, "derivative_price")


@router.get("/bond-price")
async def bond_price(date: str = Query(default=None)):
    auth = get_krx_auth()
    df = auth.fetch("bond_price", trdDd=date or _today())
    return _df_to_response(df, "bond_price")


@router.get("/bond-yield")
async def bond_yield(date: str = Query(default=None)):
    auth = get_krx_auth()
    df = auth.fetch("bond_yield", trdDd=date or _today())
    return _df_to_response(df, "bond_yield")


@router.get("/program-trading")
async def program_trading(date: str = Query(default=None)):
    auth = get_krx_auth()
    df = auth.fetch("program_trading", trdDd=date or _today())
    return _df_to_response(df, "program_trading")


@router.get("/dividend")
async def dividend(date: str = Query(default=None)):
    auth = get_krx_auth()
    df = auth.fetch("dividend", trdDd=date or _today())
    return _df_to_response(df, "dividend")


@router.get("/issued-securities")
async def issued_securities(date: str = Query(default=None)):
    auth = get_krx_auth()
    df = auth.fetch("issued_securities", trdDd=date or _today())
    return _df_to_response(df, "issued_securities")


@router.get("/gold-price")
async def gold_price(date: str = Query(default=None)):
    auth = get_krx_auth()
    df = auth.fetch("gold_price", trdDd=date or _today())
    return _df_to_response(df, "gold_price")


# ── 기간 조회 엔드포인트 ──

@router.get("/stock-daily")
async def stock_daily(
    isuCd: str = Query(description="종목코드 (예: KR7005930003)"),
    start_date: str = Query(description="YYYYMMDD"),
    end_date: str = Query(default=None),
):
    auth = get_krx_auth()
    df = auth.fetch("stock_daily", isuCd=isuCd, strtDd=start_date, endDd=end_date or _today())
    return _df_to_response(df, "stock_daily")


@router.get("/index-trend")
async def index_trend(
    idxCd: str = Query(default="1", description="지수코드"),
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
):
    auth = get_krx_auth()
    sd = start_date or (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    df = auth.fetch("index_trend", idxCd=idxCd, strtDd=sd, endDd=end_date or _today())
    return _df_to_response(df, "index_trend")


@router.get("/investor-summary")
async def investor_summary(
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
    market: str = Query(default="STK"),
):
    auth = get_krx_auth()
    sd = start_date or (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    df = auth.fetch("investor_summary", strtDd=sd, endDd=end_date or _today(), mktId=market)
    return _df_to_response(df, "investor_summary")


@router.get("/investor-trend")
async def investor_trend(
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
    market: str = Query(default="STK"),
):
    auth = get_krx_auth()
    sd = start_date or (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    df = auth.fetch("investor_trend", strtDd=sd, endDd=end_date or _today(), mktId=market)
    return _df_to_response(df, "investor_trend")


@router.get("/investor-daily")
async def investor_daily(
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
    market: str = Query(default="STK"),
):
    auth = get_krx_auth()
    sd = start_date or (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    df = auth.fetch("investor_daily", strtDd=sd, endDd=end_date or _today(), mktId=market)
    return _df_to_response(df, "investor_daily")


@router.get("/investor-by-stock")
async def investor_by_stock(
    isuCd: str = Query(description="종목코드"),
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
):
    auth = get_krx_auth()
    sd = start_date or (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    df = auth.fetch("investor_by_stock", isuCd=isuCd, strtDd=sd, endDd=end_date or _today())
    return _df_to_response(df, "investor_by_stock")


@router.get("/investor-top-net-buying")
async def investor_top_net_buying(
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
    invstTpCd: str = Query(default="9000", description="9000=외국인, 1000=기관"),
):
    auth = get_krx_auth()
    sd = start_date or (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    df = auth.fetch("investor_top_net_buying", strtDd=sd, endDd=end_date or _today(), invstTpCd=invstTpCd)
    return _df_to_response(df, "investor_top_net_buying")


@router.get("/program-daily")
async def program_daily(
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
):
    auth = get_krx_auth()
    sd = start_date or (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    df = auth.fetch("program_daily", strtDd=sd, endDd=end_date or _today())
    return _df_to_response(df, "program_daily")


@router.get("/short-selling-stock")
async def short_selling_stock(
    isuCd: str = Query(description="종목코드"),
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
):
    auth = get_krx_auth()
    sd = start_date or (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    df = auth.fetch("short_selling_stock", isuCd=isuCd, strtDd=sd, endDd=end_date or _today())
    return _df_to_response(df, "short_selling_stock")


@router.get("/short-selling-stock-daily")
async def short_selling_stock_daily(
    isuCd: str = Query(description="종목코드"),
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
):
    auth = get_krx_auth()
    sd = start_date or (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    df = auth.fetch("short_selling_stock_daily", isuCd=isuCd, strtDd=sd, endDd=end_date or _today())
    return _df_to_response(df, "short_selling_stock_daily")


@router.get("/short-selling-investor")
async def short_selling_investor(
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
):
    auth = get_krx_auth()
    sd = start_date or (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    df = auth.fetch("short_selling_investor", strtDd=sd, endDd=end_date or _today())
    return _df_to_response(df, "short_selling_investor")


@router.get("/short-selling-balance")
async def short_selling_balance(
    isuCd: str = Query(description="종목코드"),
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
):
    auth = get_krx_auth()
    sd = start_date or (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    df = auth.fetch("short_selling_balance", isuCd=isuCd, strtDd=sd, endDd=end_date or _today())
    return _df_to_response(df, "short_selling_balance")


@router.get("/bond-yield-trend")
async def bond_yield_trend(
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
    bndKindTpCd: str = Query(default="3000", description="3000=국고3년"),
):
    auth = get_krx_auth()
    sd = start_date or (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    df = auth.fetch("bond_yield_trend", strtDd=sd, endDd=end_date or _today(), bndKindTpCd=bndKindTpCd)
    return _df_to_response(df, "bond_yield_trend")
