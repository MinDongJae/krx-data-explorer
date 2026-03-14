"""
KRX Data Explorer — MCP 서버
============================
KRX 시장 데이터를 AI가 직접 호출할 수 있는 MCP 도구로 제공합니다.

사용법:
  python krx_mcp.py                    # stdio 모드 (Claude Desktop 등)
  python krx_mcp.py --transport sse    # SSE 모드 (웹 클라이언트)

설정:
  환경변수 KRX_ID, KRX_PW 또는 기본값(goguma) 사용
"""

import asyncio
import datetime
import json
import logging
from typing import Optional

from fastmcp import FastMCP
from krx_auth import get_krx_auth, KRX_AUTH_ENDPOINTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "KRX Data Explorer",
    instructions="한국거래소(KRX) 시장 데이터 31개 도구. 주식·ETF·채권·파생·공매도·투자자 등",
)


def _today() -> str:
    return datetime.date.today().strftime("%Y%m%d")

def _week_ago() -> str:
    return (datetime.date.today() - datetime.timedelta(days=7)).strftime("%Y%m%d")


def _df_to_result(df) -> dict:
    if df.empty:
        return {"rows": 0, "error": "데이터 없음 (휴장일이거나 파라미터 확인 필요)"}
    return {
        "rows": len(df),
        "columns": list(df.columns),
        "data": df.head(100).to_dict(orient="records"),
        "truncated": len(df) > 100,
    }


# ============================================================================
# 단일날짜 도구 — date_param = "trdDd"
# ============================================================================

# 단일날짜 엔드포인트용 공통 팩토리
def _make_single(name: str, config: dict):
    async def tool_fn(
        date: Optional[str] = None,
        mktId: Optional[str] = None,
        isuCd: Optional[str] = None,
        prodId: Optional[str] = None,
    ) -> dict:
        auth = get_krx_auth()
        params = {config["date_param"]: date or _today()}
        if mktId is not None:
            params["mktId"] = mktId
        if isuCd is not None:
            params["isuCd"] = isuCd
        if prodId is not None:
            params["prodId"] = prodId
        df = await asyncio.to_thread(auth.fetch, name, **params)
        return _df_to_result(df)
    tool_fn.__name__ = name
    tool_fn.__doc__ = config["desc"] + "\n\ndate: YYYYMMDD (미입력시 오늘). mktId: STK(코스피)/KSQ(코스닥). prodId: 파생상품ID."
    return tool_fn

for _name, _config in KRX_AUTH_ENDPOINTS.items():
    if _config.get("date_param") == "trdDd":
        mcp.tool(name=_name, description=_config["desc"])(_make_single(_name, _config))


# ============================================================================
# 기간 도구 — date_param = None (strtDd/endDd)
# ============================================================================

def _make_range(name: str, config: dict):
    async def tool_fn(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        mktId: Optional[str] = None,
        isuCd: Optional[str] = None,
        invstTpCd: Optional[str] = None,
        idxCd: Optional[str] = None,
    ) -> dict:
        auth = get_krx_auth()
        params = {
            "strtDd": start_date or _week_ago(),
            "endDd": end_date or _today(),
        }
        if mktId is not None:
            params["mktId"] = mktId
        if isuCd is not None:
            params["isuCd"] = isuCd
        if invstTpCd is not None:
            params["invstTpCd"] = invstTpCd
        if idxCd is not None:
            params["idxCd"] = idxCd
        df = await asyncio.to_thread(auth.fetch, name, **params)
        return _df_to_result(df)
    tool_fn.__name__ = name
    tool_fn.__doc__ = (
        config["desc"]
        + "\n\nstart_date/end_date: YYYYMMDD (미입력시 최근 7일). "
        "mktId: STK/KSQ. isuCd: 종목코드. invstTpCd: 투자자유형(9000=외국인,1000=기관). idxCd: 지수코드."
    )
    return tool_fn

for _name, _config in KRX_AUTH_ENDPOINTS.items():
    if _config.get("date_param") is None:
        mcp.tool(name=_name, description=_config["desc"])(_make_range(_name, _config))


# ============================================================================
# 유틸리티 도구
# ============================================================================

@mcp.tool(description="사용 가능한 모든 KRX 데이터 엔드포인트 목록과 파라미터 정보")
async def list_endpoints() -> dict:
    result = []
    for name, config in KRX_AUTH_ENDPOINTS.items():
        dp = config.get("date_param")
        result.append({
            "name": name,
            "description": config["desc"],
            "date_type": "single (date)" if dp == "trdDd" else "range (start_date, end_date)",
            "default_params": config.get("default_params", {}),
        })
    return {"total": len(result), "endpoints": result}


@mcp.tool(description="KRX 로그인 상태 확인")
async def login_status() -> dict:
    auth = get_krx_auth()
    return await asyncio.to_thread(auth.status)


@mcp.tool(description="커스텀 KRX bld 경로로 직접 데이터 조회")
async def custom_query(bld: str, params_json: Optional[str] = None) -> dict:
    """KRX_AUTH_ENDPOINTS에 없는 bld 경로도 직접 조회.
    bld: dbms/MDC/STAT/standard/MDCSTAT01501
    params_json: 추가 파라미터 JSON 문자열 (예: '{"mktId":"STK","trdDd":"20260314"}')
    """
    auth = get_krx_auth()
    extra = {}
    if params_json:
        try:
            extra = json.loads(params_json)
        except json.JSONDecodeError:
            return {"error": "params_json이 유효한 JSON이 아닙니다"}
    result = await asyncio.to_thread(auth.fetch_json, bld, **extra)
    if not result:
        return {"error": "데이터 없음"}
    return result


# ============================================================================
if __name__ == "__main__":
    import sys
    transport = "stdio"
    if "--transport" in sys.argv:
        idx = sys.argv.index("--transport")
        if idx + 1 < len(sys.argv):
            transport = sys.argv[idx + 1]
    mcp.run(transport=transport)
