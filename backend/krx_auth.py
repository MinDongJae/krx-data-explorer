"""
KRX ID/PW 로그인 세션 관리 + 데이터 수집 모듈
================================================
KRX 데이터마켓(data.krx.co.kr)에 아이디/비밀번호로 로그인하고,
인증된 세션으로 모든 시장 데이터를 가져옵니다.

흐름 (초등학생 설명):
  1. KRX 로그인 페이지에 아이디/비밀번호를 보냅니다 (학교 홈페이지 로그인처럼)
  2. 로그인 성공하면 "출입증"(JSESSIONID 쿠키)을 받아요
  3. 이 출입증으로 KRX의 모든 데이터를 가져올 수 있어요
  4. 출입증이 만료되면(25분) 자동으로 다시 로그인해요

특징:
  - 브라우저 필요 없음! 순수 requests POST로 로그인
  - CAPTCHA 없음 (KRX 자체 계정은 CAPTCHA 안 걸림)
  - 중복 로그인 자동 처리 (skipDup=Y)
  - 세션 만료 자동 감지 + 재로그인

사용법:
  auth = get_krx_auth()
  data = auth.fetch_data("dbms/MDC/STAT/standard/MDCSTAT01501", mktId="STK", trdDd="20260312")
"""

import json
import logging
import os
import time
import threading
from typing import Optional

import requests
import pandas as pd

logger = logging.getLogger(__name__)

# 세션 유효 시간 (KRX는 30분이지만 안전하게 25분)
SESSION_MAX_AGE = 25 * 60

# KRX URL
KRX_LOGIN_PAGE = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
KRX_LOGIN_API = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
KRX_DATA_API = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"

# ============================================================================
# KRX 인증 데이터 엔드포인트 매핑
# (로그인 후 getJsonData.cmd로 접근 가능한 데이터)
# ============================================================================

KRX_AUTH_ENDPOINTS = {
    # ========== 주식 시세 ==========
    "all_stock_price": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT01501",
        "desc": "전체 종목 시세 (종가, 등락률, 거래량 등) — 951개",
        "response_key": "OutBlock_1",
        "default_params": {"mktId": "STK", "share": "1", "money": "1"},
        "date_param": "trdDd",
    },
    "stock_daily": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT01701",
        "desc": "개별 종목 일별 시세 (종가/시가/고가/저가/거래량)",
        "response_key": "output",
        "default_params": {},
        "date_param": None,  # isuCd, strtDd, endDd
    },
    "market_cap": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT01901",
        "desc": "전체 종목 시가총액 (상장주수, 시가총액 등) — 951개",
        "response_key": "OutBlock_1",
        "default_params": {"mktId": "STK", "share": "1"},
        "date_param": "trdDd",
    },
    "market_trading": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02001",
        "desc": "시장 거래현황 (거래정지/정리매매/관리종목 여부 포함) — 951개",
        "response_key": "OutBlock_1",
        "default_params": {"mktId": "STK"},
        "date_param": "trdDd",
    },
    # ========== 외국인/PER/PBR ==========
    "foreign_holding": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT03501",
        "desc": "외국인 보유 + PER/PBR/EPS/BPS/배당수익률 — 920개",
        "response_key": "output",
        "default_params": {"mktId": "STK", "share": "1"},
        "date_param": "trdDd",
    },
    "foreign_exhaustion": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT03701",
        "desc": "외국인 보유한도 소진률 (종목별 외국인 한도/잔여) — 951개",
        "response_key": "output",
        "default_params": {"mktId": "STK"},
        "date_param": "trdDd",
    },
    # ========== 업종/지수 ==========
    "sector_price": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT03901",
        "desc": "업종별 종목 분류 및 시세 — 951개",
        "response_key": "block1",
        "default_params": {"mktId": "STK"},
        "date_param": "trdDd",
    },
    "index_price": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT00101",
        "desc": "KOSPI/KOSDAQ 지수 시세 (51개 지수)",
        "response_key": "output",
        "default_params": {"idxIndMidclssCd": "02"},
        "date_param": "trdDd",
    },
    "index_trend": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT00401",
        "desc": "개별 지수 시세추이 (코스피/코스닥 상세 지수 정보) — 50개",
        "response_key": "output",
        "default_params": {"idxIndMidclssCd": "02"},
        "date_param": None,  # strtDd, endDd, idxCd
    },
    # ========== 투자자별 ==========
    "investor_summary": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02201",
        "desc": "투자자별 매매동향 기간합산 (13개 투자자 유형별) — strtDd/endDd 필수!",
        "response_key": "output",
        "default_params": {"mktId": "STK"},
        "date_param": None,  # strtDd, endDd
    },
    "investor_trend": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02202",
        "desc": "투자자별 일별추이 (기관/외국인/개인 3분류)",
        "response_key": "output",
        "default_params": {"mktId": "STK", "inqTpCd": "1", "trdVolVal": "2", "askBid": "3"},
        "date_param": None,  # strtDd, endDd
    },
    "investor_daily": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02203",
        "desc": "투자자별 일별 세부분류 (금융투자/보험/투신/은행 등)",
        "response_key": "output",
        "default_params": {"mktId": "STK", "inqTpCd": "2", "trdVolVal": "2", "askBid": "3"},
        "date_param": None,  # strtDd, endDd
    },
    "investor_by_stock": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02301",
        "desc": "개별 종목 투자자별 매매동향 (13개 투자자 유형별)",
        "response_key": "output",
        "default_params": {"inqTpCd": "1", "trdVolVal": "2", "askBid": "3"},
        "date_param": None,  # isuCd, strtDd, endDd
    },
    "investor_top_net_buying": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02401",
        "desc": "투자자별 순매수 상위 종목 (외국인/기관별) — 920개",
        "response_key": "output",
        "default_params": {"mktId": "STK", "invstTpCd": "9000"},  # 9000=외국인, 1000=기관
        "date_param": None,  # strtDd, endDd
    },
    # ========== 프로그램 매매 ==========
    "program_trading": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02501",
        "desc": "프로그램 매매 종목별 (차익/비차익) — 149개",
        "response_key": "output",
        "default_params": {"mktId": "STK"},
        "date_param": "trdDd",
    },
    "program_daily": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02601",
        "desc": "프로그램매매 일별추이 (차익/비차익/합계)",
        "response_key": "output",
        "default_params": {"mktId": "STK"},
        "date_param": None,  # strtDd, endDd
    },
    # ========== ETF/ETN/ELW ==========
    "etf_price": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT04301",
        "desc": "ETF 전종목 시세 — 1,075개",
        "response_key": "output",
        "default_params": {"mktId": "STK"},
        "date_param": "trdDd",
    },
    "etn_price": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT06401",
        "desc": "ETN 전종목 시세 — 389개",
        "response_key": "output",
        "default_params": {},
        "date_param": "trdDd",
    },
    "elw_price": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT08301",
        "desc": "ELW 전종목 시세 — 2,964개",
        "response_key": "output",
        "default_params": {},
        "date_param": "trdDd",
    },
    # ========== 공매도 ==========
    "short_selling_all": {
        "bld": "dbms/MDC/STAT/srt/MDCSTAT30101",
        "desc": "공매도 전체 종목별 현황 — 951개 (inqCond 필수!)",
        "response_key": "OutBlock_1",
        "default_params": {"mktId": "STK", "inqCond": "STMFRTSCIFDRFS"},
        "date_param": "trdDd",
    },
    "short_selling_stock": {
        "bld": "dbms/MDC/STAT/srt/MDCSTAT30001",
        "desc": "개별 종목 공매도 요약 (일별 공매도량/금액)",
        "response_key": "OutBlock_1",
        "default_params": {},
        "date_param": None,  # isuCd, strtDd, endDd
    },
    "short_selling_stock_daily": {
        "bld": "dbms/MDC/STAT/srt/MDCSTAT30102",
        "desc": "개별 종목 공매도 일별추이 (거래비중 포함)",
        "response_key": "OutBlock_1",
        "default_params": {},
        "date_param": None,  # isuCd, strtDd, endDd
    },
    "short_selling_investor": {
        "bld": "dbms/MDC/STAT/srt/MDCSTAT30301",
        "desc": "투자자별 공매도 거래 일별추이",
        "response_key": "OutBlock_1",
        "default_params": {"inqCondTpCd": "1", "mktTpCd": "1"},
        "date_param": None,  # strtDd, endDd
    },
    "short_selling_top50": {
        "bld": "dbms/MDC/STAT/srt/MDCSTAT30401",
        "desc": "공매도 거래 상위 50 종목",
        "response_key": "OutBlock_1",
        "default_params": {"mktTpCd": "1"},
        "date_param": "trdDd",
    },
    "short_selling_balance": {
        "bld": "dbms/MDC/STAT/srt/MDCSTAT30502",
        "desc": "개별 종목 공매도 잔고 추이",
        "response_key": "OutBlock_1",
        "default_params": {},
        "date_param": None,  # isuCd, strtDd, endDd
    },
    # ========== 파생상품 ==========
    "derivative_price": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT12501",
        "desc": "파생상품 시세 (선물/옵션) — prodId로 상품 선택",
        "response_key": "output",
        "default_params": {"prodId": "KRDRVFUK2I", "mktTpCd": "T", "rghtTpCd": "T"},
        "date_param": "trdDd",
    },
    # ========== 채권 ==========
    "bond_price": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT06101",
        "desc": "국채/채권 시세 (일별 거래내역) — 309개",
        "response_key": "output",
        "default_params": {"bndTpCd": "1"},
        "date_param": "trdDd",
    },
    "bond_yield": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT11401",
        "desc": "채권 수익률 (국고/회사채/CD 등 11개 만기)",
        "response_key": "output",
        "default_params": {"inqTpCd": "T"},
        "date_param": "trdDd",
    },
    "bond_yield_trend": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT11402",
        "desc": "채권 수익률 추이 (개별 만기 일별)",
        "response_key": "output",
        "default_params": {"inqTpCd": "E", "bndKindTpCd": "3000"},  # 3000=국고3년
        "date_param": None,  # strtDd, endDd
    },
    # ========== 배당/발행증권/금 ==========
    "dividend": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT03801",
        "desc": "업종별 배당현황 (배당수익률, 시가총액 비중 등)",
        "response_key": "block1",
        "default_params": {"mktId": "STK"},
        "date_param": "trdDd",
    },
    "issued_securities": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT17701",
        "desc": "발행증권 현황 (ELS, DLS, ELB 등) — 1,282개",
        "response_key": "output",
        "default_params": {},
        "date_param": "trdDd",
    },
    "gold_price": {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT14901",
        "desc": "금 시세 (KRX 금시장)",
        "response_key": "output",
        "default_params": {"share": "1", "money": "1"},
        "date_param": "trdDd",
    },
}


class KRXAuth:
    """KRX 인증 세션 관리자 — ID/PW 로그인 방식

    마치 학교 도서관 카드처럼:
      - 한 번 로그인하면 25분간 유효
      - 만료되면 자동으로 다시 로그인
      - 여러 요청을 동시에 보내도 안전 (스레드 락)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._session: Optional[requests.Session] = None
        self._session_created_at: float = 0
        self._logged_in: bool = False
        self._member_no: Optional[str] = None

    def get_authenticated_session(self) -> Optional[requests.Session]:
        """인증된 requests 세션을 반환합니다.

        Returns:
            인증된 세션. 로그인 실패 시 None
        """
        now = time.time()

        # 세션이 아직 유효한지 확인
        if (
            self._session is not None
            and self._logged_in
            and (now - self._session_created_at) < SESSION_MAX_AGE
        ):
            return self._session

        # 세션 만료 → 재로그인
        with self._lock:
            # Double-check (다른 스레드가 이미 갱신했을 수 있음)
            if (
                self._session is not None
                and self._logged_in
                and (time.time() - self._session_created_at) < SESSION_MAX_AGE
            ):
                return self._session

            krx_id = os.environ.get("KRX_ID", "goguma")
            krx_pw = os.environ.get("KRX_PW", "mindongjaE1!")

            if self._login(krx_id, krx_pw):
                return self._session
            return None

    def _login(self, krx_id: str, krx_pw: str) -> bool:
        """KRX에 ID/PW로 로그인"""
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
        })

        try:
            # Step 1: 로그인 페이지 → JSESSIONID 쿠키
            s.get(KRX_LOGIN_PAGE, timeout=15)
            time.sleep(0.3)

            # Step 2: ID/PW 전송
            resp = s.post(
                KRX_LOGIN_API,
                data={"mbrId": krx_id, "pw": krx_pw, "skipDup": "Y"},
                headers={
                    "Referer": KRX_LOGIN_PAGE,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=15,
            )

            result = resp.json()
            error_code = result.get("_error_code", "")
            mbr_no = result.get("MBR_NO")

            # 로그인 성공 판단: CD001이거나 MBR_NO가 있으면 성공
            if error_code == "CD001" or mbr_no:
                self._member_no = mbr_no
                self._session = s
                self._session_created_at = time.time()
                self._logged_in = True

                s.headers.update({
                    "Referer": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd",
                    "X-Requested-With": "XMLHttpRequest",
                })

                logger.info(f"KRX 로그인 성공 (MBR_NO={self._member_no})")
                return True
            else:
                logger.error(f"KRX 로그인 실패: {error_code} - {result.get('_error_message')}")
                return False

        except Exception as e:
            logger.error(f"KRX 로그인 예외: {e}", exc_info=True)
            return False

    def fetch_json(self, bld: str, **params) -> dict:
        """인증된 세션으로 KRX JSON 데이터를 가져옵니다.

        Args:
            bld: KRX 데이터 경로
            **params: 추가 파라미터

        Returns:
            KRX 응답 JSON. 실패 시 빈 딕셔너리
        """
        session = self.get_authenticated_session()
        if not session:
            return {}

        data = {"bld": bld, "locale": "ko_KR"}
        data.update(params)

        try:
            resp = session.post(KRX_DATA_API, data=data, timeout=30)
            text = resp.text.strip()

            # 비정상 응답 감지 (HTML 에러 페이지 또는 LOGOUT)
            if not text.startswith("{") or "LOGOUT" in text:
                logger.warning("KRX 세션 만료 — 재로그인")
                self._logged_in = False
                session = self.get_authenticated_session()
                if not session:
                    return {}
                resp = session.post(KRX_DATA_API, data=data, timeout=30)
                text = resp.text.strip()
                if not text.startswith("{"):
                    return {}

            return resp.json()

        except Exception as e:
            logger.error(f"KRX 데이터 수집 실패 (bld={bld}): {e}")
            return {}

    def fetch(self, endpoint_key: str, **params) -> pd.DataFrame:
        """KRX_AUTH_ENDPOINTS에 정의된 엔드포인트로 DataFrame을 가져옵니다.

        Args:
            endpoint_key: 엔드포인트 키 (예: "all_stock_price")
            **params: 추가/오버라이드 파라미터

        Returns:
            pandas DataFrame
        """
        ep = KRX_AUTH_ENDPOINTS.get(endpoint_key)
        if not ep:
            logger.error(f"알 수 없는 엔드포인트: {endpoint_key}")
            return pd.DataFrame()

        # 파라미터 구성 (기본값 + 사용자 값)
        merged = dict(ep["default_params"])
        merged.update(params)

        result = self.fetch_json(ep["bld"], **merged)
        if not result:
            return pd.DataFrame()

        # 응답 키에서 데이터 추출
        items = result.get(ep["response_key"], [])

        # 일부 엔드포인트는 response_key가 다를 수 있음 → fallback
        if not items:
            for key in ["output", "OutBlock_1", "block1"]:
                if key in result and isinstance(result[key], list) and result[key]:
                    items = result[key]
                    break

        if not items:
            return pd.DataFrame()

        df = pd.DataFrame(items)

        # 숫자 컬럼 정리 (쉼표 제거, 숫자 변환)
        for col in df.columns:
            if df[col].dtype == object:
                cleaned = df[col].str.replace(",", "", regex=False).str.strip('"')
                try:
                    df[col] = pd.to_numeric(cleaned)
                except (ValueError, TypeError):
                    pass

        logger.info(f"KRX 수집 ({endpoint_key}): {len(df)}행 x {len(df.columns)}열")
        return df

    @property
    def is_logged_in(self) -> bool:
        if not self._logged_in or self._session is None:
            return False
        if time.time() - self._session_created_at > SESSION_MAX_AGE:
            self._logged_in = False
            return False
        return True

    def status(self) -> dict:
        return {
            "logged_in": self.is_logged_in,
            "member_no": self._member_no if self._logged_in else None,
            "session_age_sec": (
                int(time.time() - self._session_created_at)
                if self._logged_in else None
            ),
            "session_max_age_sec": SESSION_MAX_AGE,
            "method": "krx_id_pw_login",
            "available_endpoints": list(KRX_AUTH_ENDPOINTS.keys()),
        }


# 전역 싱글톤
_auth: Optional[KRXAuth] = None


def get_krx_auth() -> KRXAuth:
    """KRX 인증 관리자 싱글톤"""
    global _auth
    if _auth is None:
        _auth = KRXAuth()
    return _auth
