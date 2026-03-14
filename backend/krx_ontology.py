"""
KRX 데이터 온톨로지 + 자연어 → API 변환
==========================================
31개 API 엔드포인트 간의 관계를 정의하는 지식 지도(온톨로지).
LLM이 자연어를 정확한 API 호출로 변환할 때 이 지도를 참조합니다.

흐름 (초등학생 설명):
  1. 사용자가 "삼성전자 외국인 보유 추이" 같은 말을 합니다
  2. 이 모듈이 지식 지도를 보고 "어떤 API를 써야 하는지" 알려줍니다
  3. LLM(AI)이 지도를 참조해서 정확한 API 호출을 만듭니다
  4. 결과 데이터 + 차트 설정을 프론트엔드에 전달합니다
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from .krx_auth import get_krx_auth, KRX_AUTH_ENDPOINTS

logger = logging.getLogger(__name__)

# ============================================================================
# 온톨로지 — 엔드포인트 간 관계 정의
# ============================================================================

KRX_ONTOLOGY = {
    # ── 엔티티(종류) 정의 ──
    "entities": {
        "Stock": {
            "description": "개별 종목 (삼성전자, SK하이닉스 등)",
            "key_field": "ISU_SRT_CD",  # 종목 단축코드
            "name_field": "ISU_ABBRV",  # 종목명
            "relations": {
                "hasPrice": "all_stock_price",
                "hasMarketCap": "market_cap",
                "hasFundamental": "foreign_holding",  # PER/PBR/EPS/BPS 포함
                "hasForeignOwnership": "foreign_exhaustion",
                "hasShortSelling": "short_selling_all",
                "belongsToSector": "sector_price",
                "hasInvestorFlow": "investor_by_stock",
                "hasDailyHistory": "stock_daily",
                "hasShortSellingHistory": "short_selling_stock",
                "hasShortSellingBalance": "short_selling_balance",
            },
        },
        "Market": {
            "description": "시장 전체 (KOSPI, KOSDAQ)",
            "children": {
                "KOSPI": {"mktId": "STK", "description": "유가증권시장"},
                "KOSDAQ": {"mktId": "KSQ", "description": "코스닥시장"},
                "KONEX": {"mktId": "KNX", "description": "코넥스시장"},
            },
            "relations": {
                "hasIndex": "index_price",
                "hasIndexTrend": "index_trend",
                "hasInvestorSummary": "investor_summary",
                "hasInvestorTrend": "investor_trend",
                "hasInvestorDaily": "investor_daily",
                "hasTopNetBuying": "investor_top_net_buying",
                "hasProgramTrading": "program_trading",
                "hasProgramDaily": "program_daily",
                "hasShortSellingInvestor": "short_selling_investor",
                "hasShortSellingTop50": "short_selling_top50",
                "hasDividend": "dividend",
            },
        },
        "ETF": {
            "description": "상장지수펀드 (1,075개)",
            "relations": {"hasPrice": "etf_price"},
        },
        "ETN": {
            "description": "상장지수채권 (389개)",
            "relations": {"hasPrice": "etn_price"},
        },
        "ELW": {
            "description": "주식워런트증권 (2,964개)",
            "relations": {"hasPrice": "elw_price"},
        },
        "Bond": {
            "description": "채권 (국채, 회사채 등)",
            "relations": {
                "hasPrice": "bond_price",
                "hasYield": "bond_yield",
                "hasYieldTrend": "bond_yield_trend",
            },
        },
        "Derivative": {
            "description": "파생상품 (선물, 옵션)",
            "relations": {"hasPrice": "derivative_price"},
        },
        "Gold": {
            "description": "KRX 금시장",
            "relations": {"hasPrice": "gold_price"},
        },
        "IssuedSecurities": {
            "description": "발행증권 현황",
            "relations": {"hasData": "issued_securities"},
        },
    },

    # ── 시간 축 분류 ──
    "time_types": {
        "point_in_time": {
            "description": "특정 날짜 하루 데이터",
            "endpoints": [
                "all_stock_price", "market_cap", "market_trading",
                "foreign_holding", "foreign_exhaustion", "sector_price",
                "index_price", "etf_price", "etn_price", "elw_price",
                "short_selling_all", "short_selling_top50",
                "derivative_price", "bond_price", "bond_yield",
                "program_trading", "dividend", "issued_securities", "gold_price",
            ],
        },
        "date_range": {
            "description": "기간(시작~끝) 데이터",
            "endpoints": [
                "stock_daily", "index_trend",
                "investor_summary", "investor_trend", "investor_daily",
                "investor_by_stock", "investor_top_net_buying",
                "program_daily",
                "short_selling_stock", "short_selling_stock_daily",
                "short_selling_investor", "short_selling_balance",
                "bond_yield_trend",
            ],
        },
    },

    # ── 자주 쓰는 종목 코드 매핑 ──
    "stock_aliases": {
        "삼성전자": "KR7005930003",
        "SK하이닉스": "KR7000660001",
        "NAVER": "KR7035420009",
        "네이버": "KR7035420009",
        "카카오": "KR7035720002",
        "현대차": "KR7005380001",
        "현대자동차": "KR7005380001",
        "LG에너지솔루션": "KR7373220003",
        "기아": "KR7000270009",
        "셀트리온": "KR7068270008",
        "POSCO홀딩스": "KR7005490008",
        "포스코홀딩스": "KR7005490008",
        "KB금융": "KR7105560007",
        "신한지주": "KR7055550008",
        "삼성바이오로직스": "KR7207940008",
        "LG화학": "KR7051910008",
        "삼성SDI": "KR7006400006",
        "현대모비스": "KR7012330007",
        "삼성물산": "KR7028260008",
        "SK": "KR7034730000",
        "LG전자": "KR7066570003",
        "SK텔레콤": "KR7017670005",
        "KT": "KR7030200000",
        "삼성생명": "KR7032830002",
        "에코프로비엠": "KR7247540008",
        "에코프로": "KR7086520004",
        "한화에어로스페이스": "KR7012450003",
    },
}

# ============================================================================
# 자연어 → API 호출 변환 (LLM 사용)
# ============================================================================

SYSTEM_PROMPT = """당신은 KRX(한국거래소) 데이터 API 전문가입니다.
사용자의 자연어 질의를 분석하여 정확한 API 호출로 변환하세요.

## 사용 가능한 API 엔드포인트

### 단일 날짜 조회 (date 파라미터, YYYYMMDD)
- all_stock_price: 전종목 시세 (종가/등락률/거래량) — params: date, market(STK/KSQ)
- market_cap: 전종목 시가총액 — params: date, market
- market_trading: 시장 거래현황 — params: date, market
- foreign_holding: 외국인 보유+PER/PBR/EPS/BPS — params: date, market
- foreign_exhaustion: 외국인 한도소진률 — params: date, market
- sector_price: 업종별 시세 — params: date, market
- index_price: 지수 시세 (KOSPI/KOSDAQ 51개) — params: date
- etf_price: ETF 전종목 시세 — params: date
- etn_price: ETN 전종목 시세 — params: date
- elw_price: ELW 전종목 시세 — params: date
- short_selling_all: 공매도 전종목 — params: date, market
- short_selling_top50: 공매도 상위50 — params: date
- derivative_price: 파생상품 시세 — params: date, prodId
- bond_price: 채권 시세 — params: date
- bond_yield: 채권 수익률 — params: date
- program_trading: 프로그램매매 — params: date
- dividend: 배당현황 — params: date
- issued_securities: 발행증권 — params: date
- gold_price: 금 시세 — params: date

### 기간 조회 (start_date, end_date 파라미터)
- stock_daily: 개별종목 일별시세 — params: isuCd(종목코드), start_date, end_date
- index_trend: 지수 추이 — params: idxCd, start_date, end_date
- investor_summary: 투자자별 매매 기간합산 — params: start_date, end_date, market
- investor_trend: 투자자별 일별추이 — params: start_date, end_date, market
- investor_daily: 투자자별 세부분류 — params: start_date, end_date, market
- investor_by_stock: 종목별 투자자 매매 — params: isuCd, start_date, end_date
- investor_top_net_buying: 순매수 상위 — params: start_date, end_date, invstTpCd(9000=외국인,1000=기관)
- program_daily: 프로그램매매 일별 — params: start_date, end_date
- short_selling_stock: 종목 공매도 요약 — params: isuCd, start_date, end_date
- short_selling_stock_daily: 종목 공매도 일별 — params: isuCd, start_date, end_date
- short_selling_investor: 투자자별 공매도 — params: start_date, end_date
- short_selling_balance: 공매도 잔고 — params: isuCd, start_date, end_date
- bond_yield_trend: 채권수익률 추이 — params: start_date, end_date, bndKindTpCd(3000=국고3년)

## 종목 코드 매핑 (자주 쓰는 종목)
{stock_aliases}

## 응답 형식 (반드시 JSON으로만 응답)
```json
{{
  "intent": "질의 의도 요약 (한글)",
  "endpoints": [
    {{
      "name": "API 엔드포인트 이름",
      "params": {{"param1": "value1"}},
      "description": "이 호출이 가져오는 데이터 설명"
    }}
  ],
  "chart": {{
    "type": "bar|line|scatter|area|pie",
    "title": "차트 제목",
    "x": "X축 필드명 (API 응답 컬럼명)",
    "y": "Y축 필드명",
    "sort": "asc|desc|none",
    "limit": 20,
    "color_field": "색상 구분 필드 (선택)"
  }},
  "combine_strategy": "none|merge_by_key|side_by_side",
  "combine_key": "조인 키 필드명 (merge_by_key인 경우)"
}}
```

## 규칙
1. 오늘 날짜: {today}
2. 기간 미지정 시: 단일날짜는 오늘, 기간은 최근 30일
3. 시장 미지정 시: KOSPI(STK) 기본
4. 종목명이 나오면 반드시 stock_aliases에서 isuCd 코드 변환
5. 여러 데이터를 결합해야 하면 endpoints 배열에 여러 개 추가
6. chart.type은 데이터 특성에 맞게 선택:
   - 순위/비교 → bar
   - 시계열/추이 → line
   - 분포/관계 → scatter
   - 누적/비중 → area 또는 pie
7. JSON만 출력. 코드블록(```) 없이 순수 JSON만 출력하세요.
"""


def _today() -> str:
    d = datetime.now()
    wd = d.weekday()
    if wd == 5:
        d -= timedelta(days=1)
    elif wd == 6:
        d -= timedelta(days=2)
    return d.strftime("%Y%m%d")


async def natural_language_to_api(query: str) -> dict[str, Any]:
    """
    자연어 질의 → API 호출 계획 생성 (Gemini Flash 사용, 빠르고 저렴).

    Returns:
        {
            "intent": str,
            "endpoints": [{"name": str, "params": dict, "description": str}],
            "chart": {"type": str, "title": str, "x": str, "y": str, ...},
            "combine_strategy": str,
        }
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    stock_aliases_str = "\n".join(
        f"- {name}: {code}" for name, code in KRX_ONTOLOGY["stock_aliases"].items()
    )

    prompt = SYSTEM_PROMPT.format(
        stock_aliases=stock_aliases_str,
        today=_today(),
    )

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    payload = {
        "contents": [
            {"parts": [{"text": f"{prompt}\n\n사용자 질의: {query}"}]}
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
        },
    }

    start = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(
            f"{url}?key={api_key}",
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    latency_ms = int((time.time() - start) * 1000)

    if resp.status_code != 200:
        logger.error("Gemini API error: %s %s", resp.status_code, resp.text[:500])
        raise RuntimeError(f"Gemini API error: {resp.status_code}")

    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]

    # JSON 파싱 (코드블록 제거)
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    result = json.loads(text)
    result["latency_ms"] = latency_ms
    result["model"] = "gemini-2.0-flash"  # 최신 stable 모델

    return result


async def execute_nl_query(query: str) -> dict[str, Any]:
    """
    자연어 질의 → API 호출 계획 생성 → 실제 데이터 가져오기 → 차트 설정과 함께 반환.

    Returns:
        {
            "query": str,
            "intent": str,
            "chart": {...},
            "data": [...],
            "columns": [...],
            "rows": int,
            "latency_ms": int,
            "endpoints_called": [str],
        }
    """
    # 1단계: LLM으로 API 호출 계획 생성
    plan = await natural_language_to_api(query)
    logger.info("[NL] Plan for '%s': %s endpoints", query, len(plan.get("endpoints", [])))

    # 2단계: 계획에 따라 실제 데이터 가져오기
    auth = get_krx_auth()
    all_data = []
    all_columns = set()
    endpoints_called = []

    for ep in plan.get("endpoints", []):
        ep_name = ep["name"]
        params = ep.get("params", {})

        # date/start_date/end_date → KRX 파라미터 변환
        call_params = {}
        for k, v in params.items():
            if k == "date":
                cfg = KRX_AUTH_ENDPOINTS.get(ep_name, {})
                date_param = cfg.get("date_param", "trdDd")
                if date_param:
                    call_params[date_param] = v or _today()
            elif k == "start_date":
                call_params["strtDd"] = v
            elif k == "end_date":
                call_params["endDd"] = v or _today()
            elif k == "market":
                call_params["mktId"] = v
            else:
                call_params[k] = v

        # 기본 날짜 설정
        cfg = KRX_AUTH_ENDPOINTS.get(ep_name, {})
        if cfg.get("date_param") and cfg["date_param"] not in call_params:
            call_params[cfg["date_param"]] = _today()

        try:
            df = auth.fetch(ep_name, **call_params)
            if not df.empty:
                records = df.to_dict(orient="records")
                all_data.extend(records)
                all_columns.update(df.columns.tolist())
                endpoints_called.append(ep_name)
                logger.info("[NL] %s returned %d rows", ep_name, len(records))
        except Exception as e:
            logger.warning("[NL] Failed to fetch %s: %s", ep_name, str(e))

    # 3단계: 결합 전략 적용
    combine = plan.get("combine_strategy", "none")
    if combine == "merge_by_key" and len(endpoints_called) > 1:
        # TODO: 실제 JOIN 로직 (현재는 단순 합치기)
        pass

    return {
        "query": query,
        "intent": plan.get("intent", ""),
        "chart": plan.get("chart", {}),
        "data": all_data,
        "columns": sorted(all_columns) if all_columns else [],
        "rows": len(all_data),
        "latency_ms": plan.get("latency_ms", 0),
        "model": plan.get("model", ""),
        "endpoints_called": endpoints_called,
    }


# ============================================================================
# 온톨로지 메타 조회
# ============================================================================

def get_ontology_summary() -> dict[str, Any]:
    """온톨로지 요약 (프론트엔드 표시용)."""
    entities = {}
    for name, cfg in KRX_ONTOLOGY["entities"].items():
        entities[name] = {
            "description": cfg["description"],
            "endpoints": list(cfg.get("relations", {}).values()),
        }

    return {
        "entities": entities,
        "total_endpoints": len(KRX_AUTH_ENDPOINTS),
        "point_in_time_count": len(KRX_ONTOLOGY["time_types"]["point_in_time"]["endpoints"]),
        "date_range_count": len(KRX_ONTOLOGY["time_types"]["date_range"]["endpoints"]),
        "stock_aliases_count": len(KRX_ONTOLOGY["stock_aliases"]),
    }
