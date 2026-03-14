"""
KRX Direct Fetcher — outerLoader 우회를 통한 KRX 직접 데이터 수집
================================================================
핵심 원리 (초등학생 설명):
  KRX 데이터마켓(data.krx.co.kr)은 원래 로그인이 필요해요.
  하지만 "outerLoader"라는 외부 임베딩용 뒷문이 있는데,
  이 문을 먼저 두드리면(세션 생성) → OTP 비밀번호를 받고 →
  그 비밀번호로 CSV 파일을 다운로드할 수 있어요.

  마치 도서관에 회원증 없이도,
  "견학 방문자" 출입구로 들어가면 책을 빌릴 수 있는 것처럼!

흐름:
  1. outerLoader 페이지 방문 → JSESSIONID 쿠키 획득
  2. GenerateOTP로 일회용 비밀번호 생성 (MDC_OUT bld 사용)
  3. download_csv로 CSV 데이터 다운로드
  4. pandas로 파싱하여 DataFrame 반환
"""

import requests
import pandas as pd
import io
import time
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================================
# MDC_OUT bld 매핑 (outerLoader에서 로그인 없이 접근 가능한 데이터)
# ============================================================================
# 각 bld는 KRX 데이터마켓의 특정 화면(screenId)에 대응합니다.
# MDC_OUT = 외부 공개용, _OUT 접미사 = outerLoader 전용 경로

KRX_OUT_ENDPOINTS = {
    # === 전체 종목 시세 ===
    "all_stock_price": {
        "screen": "MDCSTAT015",
        "bld": "dbms/MDC_OUT/STAT/standard/MDCSTAT01501_OUT",
        "desc": "전체 종목 시세 (종가, 등락률, 거래량 등)",
        "default_params": {"mktId": "STK", "share": "1", "money": "1"},
        "date_param": "trdDd",
    },
    # === 개별 종목 월간 시세 ===
    "stock_monthly": {
        "screen": "MDCSTAT018",
        "bld": "dbms/MDC_OUT/STAT/standard/MDCSTAT01802_OUT",
        "desc": "개별 종목 월간 시세 (종가, 변동성, 베타 등)",
        "default_params": {},
        "date_param": None,  # strtDd, endDd 별도 지정
    },
    # === 투자자별 거래 실적 (전체시장) ===
    "investor_trading": {
        "screen": "MDCSTAT022",
        "bld": "dbms/MDC_OUT/STAT/standard/MDCSTAT02201_OUT",
        "desc": "투자자별 매매동향 (기관, 외국인, 개인 등)",
        "default_params": {"inqTpCd": "2", "askBid": "3"},
        "date_param": "trdDd",
    },
    # === 투자자별 일별 추이 (전체시장) ===
    "investor_daily": {
        "screen": "MDCSTAT022",
        "bld": "dbms/MDC_OUT/STAT/standard/MDCSTAT02202_OUT",
        "desc": "투자자별 일별 순매수 추이",
        "default_params": {"inqTpCd": "2", "askBid": "3"},
        "date_param": None,  # strtDd, endDd
    },
    # === 투자자별 세부 분류 (전체시장) ===
    "investor_detail": {
        "screen": "MDCSTAT022",
        "bld": "dbms/MDC_OUT/STAT/standard/MDCSTAT02203_OUT",
        "desc": "투자자별 세부 분류 (금융투자, 보험, 투신 등)",
        "default_params": {"inqTpCd": "2", "askBid": "3"},
        "date_param": None,  # strtDd, endDd
    },
    # === 투자자별 거래 실적 (개별종목) ===
    "investor_by_stock": {
        "screen": "MDCSTAT023",
        "bld": "dbms/MDC_OUT/STAT/standard/MDCSTAT02301_OUT",
        "desc": "개별 종목 투자자별 매매동향",
        "default_params": {"inqTpCd": "2", "askBid": "3"},
        "date_param": None,  # strtDd, endDd
    },
    # === 업종 분류 현황 ===
    "sector": {
        "screen": "MDCSTAT024",
        "bld": "dbms/MDC_OUT/STAT/standard/MDCSTAT02401_OUT",
        "desc": "업종별 종목 분류",
        "default_params": {},
        "date_param": "trdDd",
    },
    # === 발행 증권 현황 (ELS/DLS 등) ===
    "issued_securities": {
        "screen": "MDCSTAT177",
        "bld": "dbms/MDC_OUT/STAT/standard/MDCSTAT17701_OUT",
        "desc": "발행증권 현황 (ELS, DLS, ELB 등)",
        "default_params": {},
        "date_param": "trdDd",
    },
    # === 등락률 랭킹 ===
    "price_ranking": {
        "screen": "MDCEASY016",
        "bld": "dbms/MDC_OUT/EASY/ranking/MDCEASY01601_OUT",
        "desc": "등락률 상위/하위 종목 랭킹",
        "default_params": {},
        "date_param": "trdDd",
    },
}


class KRXDirectFetcher:
    """
    KRX 데이터마켓에서 직접 데이터를 가져오는 클래스
    (outerLoader 세션 + OTP + CSV 다운로드 방식)

    사용법:
      fetcher = KRXDirectFetcher()
      df = fetcher.fetch("investor_trading", trdDd="20260311", mktId="STK")
    """

    BASE_URL = "https://data.krx.co.kr"
    OUTER_LOADER = "/contents/MDC/MDI/outerLoader/index.cmd"
    GENERATE_OTP = "/comm/fileDn/GenerateOTP/generate.cmd"
    DOWNLOAD_CSV = "/comm/fileDn/download_csv/download.cmd"

    def __init__(self):
        self._lock = threading.Lock()
        self._session: Optional[requests.Session] = None
        self._session_created_at: float = 0
        self._session_max_age: float = 300  # 5분마다 세션 갱신

    def _ensure_session(self) -> requests.Session:
        """outerLoader를 통해 유효한 세션을 확보 (필요시 갱신)"""
        now = time.time()
        if (
            self._session is not None
            and (now - self._session_created_at) < self._session_max_age
        ):
            return self._session

        with self._lock:
            # Double-check 패턴 (다른 스레드가 이미 갱신했을 수 있음)
            if (
                self._session is not None
                and (time.time() - self._session_created_at) < self._session_max_age
            ):
                return self._session

            s = requests.Session()
            s.headers.update(
                {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36",
                }
            )

            # outerLoader 방문 → JSESSIONID 쿠키 획득
            try:
                r = s.get(
                    f"{self.BASE_URL}{self.OUTER_LOADER}",
                    params={"screenId": "MDCSTAT015", "locale": "ko_KR"},
                    timeout=15,
                )
                if r.status_code == 200:
                    self._session = s
                    self._session_created_at = time.time()
                    cookies = dict(s.cookies)
                    logger.info(
                        f"KRX outerLoader 세션 생성 완료 "
                        f"(JSESSIONID: {cookies.get('JSESSIONID', 'N/A')[:20]}...)"
                    )
                else:
                    logger.warning(
                        f"outerLoader 접근 실패: status={r.status_code}"
                    )
                    # 세션 없어도 OTP 시도는 가능
                    self._session = s
                    self._session_created_at = time.time()
            except Exception as e:
                logger.error(f"outerLoader 세션 생성 실패: {e}")
                self._session = s
                self._session_created_at = time.time()

            return self._session

    def fetch(self, endpoint_key: str, **params) -> pd.DataFrame:
        """
        KRX 데이터를 직접 가져옵니다.

        Args:
            endpoint_key: KRX_OUT_ENDPOINTS 딕셔너리의 키
                (예: "investor_trading", "sector", "issued_securities")
            **params: 추가 파라미터 (trdDd, mktId, isuCd 등)

        Returns:
            pandas DataFrame (비어있을 수 있음)
        """
        endpoint = KRX_OUT_ENDPOINTS.get(endpoint_key)
        if not endpoint:
            logger.error(f"알 수 없는 KRX 엔드포인트: {endpoint_key}")
            return pd.DataFrame()

        s = self._ensure_session()

        # 파라미터 구성
        data = {
            "locale": "ko_KR",
            "csvxls_isNo": "false",
            "name": "fileDown",
            "url": endpoint["bld"],
        }
        # 기본 파라미터 적용
        data.update(endpoint["default_params"])
        # 사용자 파라미터 적용 (기본값 덮어쓰기)
        data.update(params)

        try:
            # Step 1: OTP 생성
            r_otp = s.post(
                f"{self.BASE_URL}{self.GENERATE_OTP}",
                data=data,
                headers={
                    "Referer": f"{self.BASE_URL}{self.OUTER_LOADER}",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=15,
            )

            if "LOGOUT" in r_otp.text or len(r_otp.text) < 10:
                logger.warning(
                    f"KRX OTP 생성 실패 ({endpoint_key}): "
                    f"LOGOUT 또는 빈 응답 (세션 재생성 시도)"
                )
                # 세션 만료 → 재생성
                self._session_created_at = 0
                s = self._ensure_session()
                r_otp = s.post(
                    f"{self.BASE_URL}{self.GENERATE_OTP}",
                    data=data,
                    headers={
                        "Referer": f"{self.BASE_URL}{self.OUTER_LOADER}",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=15,
                )
                if "LOGOUT" in r_otp.text or len(r_otp.text) < 10:
                    logger.error(f"KRX OTP 재시도도 실패 ({endpoint_key})")
                    return pd.DataFrame()

            otp = r_otp.text.strip()
            logger.debug(f"KRX OTP 생성 성공 ({endpoint_key}): {len(otp)} chars")

            # Step 2: CSV 다운로드
            r_csv = s.post(
                f"{self.BASE_URL}{self.DOWNLOAD_CSV}",
                data={"code": otp},
                headers={
                    "Referer": f"{self.BASE_URL}{self.OUTER_LOADER}",
                },
                timeout=30,
            )

            if r_csv.status_code != 200 or len(r_csv.content) == 0:
                logger.warning(
                    f"KRX CSV 다운로드 실패 ({endpoint_key}): "
                    f"status={r_csv.status_code}, size={len(r_csv.content)}"
                )
                return pd.DataFrame()

            # Step 3: CSV → DataFrame 파싱
            # KRX CSV는 euc-kr 인코딩 사용
            try:
                text = r_csv.content.decode("euc-kr")
            except UnicodeDecodeError:
                text = r_csv.content.decode("cp949", errors="replace")

            df = pd.read_csv(io.StringIO(text))

            # 숫자 컬럼의 쉼표 제거 및 숫자 변환
            for col in df.columns:
                if df[col].dtype == object:
                    # 따옴표로 감싸진 숫자 처리
                    cleaned = df[col].str.strip('"').str.replace(",", "", regex=False)
                    try:
                        df[col] = pd.to_numeric(cleaned)
                    except (ValueError, TypeError):
                        pass

            logger.info(
                f"KRX 직접 수집 성공 ({endpoint_key}): "
                f"{len(df)}행 x {len(df.columns)}열"
            )
            return df

        except Exception as e:
            logger.error(f"KRX 직접 수집 실패 ({endpoint_key}): {e}", exc_info=True)
            return pd.DataFrame()

    def fetch_raw_csv(self, bld: str, **params) -> pd.DataFrame:
        """
        임의의 MDC_OUT bld 경로로 직접 CSV를 다운로드합니다.
        (KRX_OUT_ENDPOINTS에 정의되지 않은 커스텀 bld용)

        Args:
            bld: KRX bld 경로 (예: "dbms/MDC_OUT/STAT/standard/MDCSTAT02401_OUT")
            **params: POST 파라미터
        """
        s = self._ensure_session()

        data = {
            "locale": "ko_KR",
            "csvxls_isNo": "false",
            "name": "fileDown",
            "url": bld,
        }
        data.update(params)

        try:
            r_otp = s.post(
                f"{self.BASE_URL}{self.GENERATE_OTP}",
                data=data,
                headers={
                    "Referer": f"{self.BASE_URL}{self.OUTER_LOADER}",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=15,
            )

            if "LOGOUT" in r_otp.text or len(r_otp.text) < 10:
                return pd.DataFrame()

            r_csv = s.post(
                f"{self.BASE_URL}{self.DOWNLOAD_CSV}",
                data={"code": r_otp.text.strip()},
                headers={"Referer": f"{self.BASE_URL}{self.OUTER_LOADER}"},
                timeout=30,
            )

            if len(r_csv.content) == 0:
                return pd.DataFrame()

            try:
                text = r_csv.content.decode("euc-kr")
            except UnicodeDecodeError:
                text = r_csv.content.decode("cp949", errors="replace")

            df = pd.read_csv(io.StringIO(text))
            for col in df.columns:
                if df[col].dtype == object:
                    cleaned = df[col].str.strip('"').str.replace(",", "", regex=False)
                    try:
                        df[col] = pd.to_numeric(cleaned)
                    except (ValueError, TypeError):
                        pass
            return df

        except Exception as e:
            logger.error(f"KRX raw CSV 수집 실패 ({bld}): {e}")
            return pd.DataFrame()


# ============================================================================
# 전역 싱글톤 (앱 전체에서 하나만 사용)
# ============================================================================

_fetcher: Optional[KRXDirectFetcher] = None


def get_krx_fetcher() -> KRXDirectFetcher:
    """KRX 직접 수집기 싱글톤 반환"""
    global _fetcher
    if _fetcher is None:
        _fetcher = KRXDirectFetcher()
    return _fetcher


def krx_direct_status() -> dict:
    """KRX 직접 접속 상태"""
    f = get_krx_fetcher()
    return {
        "enabled": True,
        "session_active": f._session is not None,
        "session_age_sec": (
            int(time.time() - f._session_created_at) if f._session else None
        ),
        "available_endpoints": list(KRX_OUT_ENDPOINTS.keys()),
        "method": "outerLoader + OTP + CSV",
    }
