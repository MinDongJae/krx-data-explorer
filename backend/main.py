"""
PyKRX API Server - KRX 주식 데이터 제공
FastAPI 기반 REST API + KRX 로그인 세션 통합

역공학 기반 로그인으로 PER/PBR/배당수익률, 투자자별 거래, 외국인 보유량 등
로그인이 필요한 모든 API 사용 가능
"""

import sys
import os

# Windows 인코딩 설정
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import pandas as pd
from typing import Optional, Dict, List
import uvicorn
import os
import requests
import pickle

# ============================================================================
# [중요] pykrx import 전에 쿠키 주입 먼저 수행!
# pykrx가 import되면 webio.Post 클래스가 이미 로드되므로,
# import 전에 패치해야 함
# ============================================================================

def _inject_cookies_before_pykrx_import():
    """
    pykrx import 전에 webio.Post.read를 패치
    이 함수는 pykrx import 전에 호출되어야 함!
    """
    cookie_file = os.path.join(os.path.dirname(__file__), '.krx_cookies.pkl')

    if not os.path.exists(cookie_file):
        print("[WARN] KRX 쿠키 파일 없음 - ETF/ETN/ELW API 제한됨")
        return False

    try:
        with open(cookie_file, 'rb') as f:
            cookies_list = pickle.load(f)

        cookies_dict = {}
        for c in cookies_list:
            name = c.get('name')
            value = c.get('value')
            if name and value:
                cookies_dict[name] = value

        if not cookies_dict:
            print("[WARN] 유효한 쿠키 없음")
            return False

        print(f"[OK] KRX 쿠키 로드: {len(cookies_dict)}개 - {list(cookies_dict.keys())}")

        # 쿠키를 사용하는 requests 세션 생성
        session = requests.Session()
        session.cookies.update(cookies_dict)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "http://data.krx.co.kr/"
        })

        # pykrx webio 모듈 import (아직 pykrx 전체를 import하지 않음)
        from pykrx.website.comm import webio

        # 원본 Post.read 메서드 저장
        original_post_read = webio.Post.read

        def patched_post_read(self, **params):
            """쿠키가 포함된 세션으로 POST 요청"""
            try:
                resp = session.post(self.url, headers=self.headers, data=params)
                return resp
            except Exception as e:
                print(f"[WARN] pykrx POST 요청 실패: {e}")
                return original_post_read(self, **params)

        # Post 클래스의 read 메서드 패치
        webio.Post.read = patched_post_read

        print("[OK] pykrx webio.Post.read 패치 완료 (import 전)")
        return True

    except Exception as e:
        print(f"[ERROR] 쿠키 주입 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


# === pykrx import 전에 쿠키 주입 실행! ===
print("[STARTUP] pykrx import 전 쿠키 주입 시작...")
_cookie_injected = _inject_cookies_before_pykrx_import()
print(f"[STARTUP] 쿠키 주입 결과: {_cookie_injected}")

# 이제 pykrx를 import (패치된 webio.Post가 사용됨)
print("[STARTUP] pykrx 모듈 import 시작...")
from pykrx_with_login import login_and_patch, get_session
from pykrx import stock
from krx_session import KRXSession
print("[STARTUP] pykrx 모듈 import 완료!")

# ============================================================================
# pykrx requests 세션에 KRX 쿠키 주입 (레거시 - 이제 위에서 처리됨)
# ============================================================================

def inject_krx_cookies_to_pykrx():
    """
    pykrx의 requests 호출에 KRX 로그인 쿠키를 주입

    문제: pykrx는 requests.post()를 직접 호출하여 쿠키 없이 요청
    해결: pykrx의 webio.Post 클래스를 패치하여 쿠키 포함 세션 사용
    """
    import pickle
    from pykrx.website.comm import webio

    cookie_file = os.path.join(os.path.dirname(__file__), '.krx_cookies.pkl')

    try:
        # 저장된 쿠키 로드
        if not os.path.exists(cookie_file):
            print("⚠️ KRX 쿠키 파일 없음 - ETF/ETN/ELW API 제한")
            return False

        with open(cookie_file, 'rb') as f:
            cookies_list = pickle.load(f)

        # 쿠키를 dict로 변환
        cookies_dict = {}
        for c in cookies_list:
            name = c.get('name')
            value = c.get('value')
            if name and value:
                cookies_dict[name] = value

        print(f"🍪 KRX 쿠키 로드: {len(cookies_dict)}개")

        # 쿠키를 사용하는 requests 세션 생성
        session = requests.Session()
        session.cookies.update(cookies_dict)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "http://data.krx.co.kr/"
        })

        # 원본 Post.read 메서드 저장
        original_post_read = webio.Post.read

        def patched_post_read(self, **params):
            """쿠키가 포함된 세션으로 POST 요청"""
            try:
                resp = session.post(self.url, headers=self.headers, data=params)
                return resp
            except Exception as e:
                print(f"⚠️ pykrx POST 요청 실패: {e}")
                # 폴백: 원본 메서드 사용
                return original_post_read(self, **params)

        # Post 클래스의 read 메서드 패치
        webio.Post.read = patched_post_read

        print("✅ pykrx requests 세션에 쿠키 주입 완료")
        return True

    except Exception as e:
        print(f"⚠️ pykrx 쿠키 주입 실패: {e}")
        return False


# ============================================================================
# pykrx ETX (ETF/ETN/ELW) 인코딩 패치
# ============================================================================

def patch_pykrx_etx_ticker():
    """
    pykrx의 EtxTicker 클래스를 패치하여 Windows 인코딩 문제 해결

    문제: pykrx/website/krx/etx/ticker.py의 한글 컬럼명('시장', '종목명', '상장일')이
          Windows에서 깨진 문자로 인식됨
    해결: DataFrame 컬럼을 영문으로 변경하고 검색 조건도 수정
    """
    try:
        from pykrx.website.krx.etx import ticker as etx_ticker
        from pykrx.website.krx.etx.core import (
            ETF_전종목기본종목, ETN_전종목기본종목, ELW_전종목기본종목
        )
        import pandas as pd

        # 기존 싱글톤 인스턴스 초기화 (있다면)
        if hasattr(etx_ticker, 'EtxTicker'):
            # 싱글톤 데코레이터 우회하여 새로 생성

            class PatchedEtxTicker:
                """인코딩 문제가 해결된 EtxTicker"""

                _instance = None
                _df = None

                def __new__(cls):
                    if cls._instance is None:
                        cls._instance = super().__new__(cls)
                        cls._df = cls._get_tickers_safe()
                    return cls._instance

                @classmethod
                def _get_tickers_safe(cls):
                    """인코딩 문제 없이 티커 목록 로드"""
                    try:
                        # ETF
                        df_etf = ETF_전종목기본종목().fetch()
                        if df_etf is not None and not df_etf.empty:
                            df_etf = df_etf[["ISU_CD", "ISU_SRT_CD", "ISU_ABBRV", "LIST_DD"]].copy()
                            df_etf['CATEGORY'] = "ETF"
                        else:
                            df_etf = pd.DataFrame(columns=["ISU_CD", "ISU_SRT_CD", "ISU_ABBRV", "LIST_DD", "CATEGORY"])

                        # ETN
                        df_etn = ETN_전종목기본종목().fetch()
                        if df_etn is not None and not df_etn.empty:
                            df_etn = df_etn[["ISU_CD", "ISU_SRT_CD", "ISU_ABBRV", "LIST_DD"]].copy()
                            df_etn['CATEGORY'] = "ETN"
                        else:
                            df_etn = pd.DataFrame(columns=["ISU_CD", "ISU_SRT_CD", "ISU_ABBRV", "LIST_DD", "CATEGORY"])

                        # ELW
                        df_elw = ELW_전종목기본종목().fetch()
                        if df_elw is not None and not df_elw.empty:
                            df_elw = df_elw[["ISU_CD", "ISU_SRT_CD", "ISU_ABBRV", "LIST_DD"]].copy()
                            df_elw['CATEGORY'] = "ELW"
                        else:
                            df_elw = pd.DataFrame(columns=["ISU_CD", "ISU_SRT_CD", "ISU_ABBRV", "LIST_DD", "CATEGORY"])

                        df = pd.concat([df_etf, df_etn, df_elw], ignore_index=True)

                        # 영문 컬럼명 사용 (인코딩 문제 해결)
                        df.columns = ["isin", "ticker", "name", "list_date", "market"]
                        df = df.replace('/', '', regex=True)

                        if not df.empty:
                            return df.set_index('ticker')
                        return pd.DataFrame()

                    except Exception as e:
                        print(f"⚠️ PatchedEtxTicker 초기화 에러: {e}")
                        return pd.DataFrame()

                @property
                def df(self):
                    if self._df is None:
                        self._df = self._get_tickers_safe()
                    return self._df

                def get_ticker(self, market, date) -> list:
                    if self._df is None or self._df.empty:
                        return []
                    if market == "ALL":
                        return self._df.index.to_list()
                    # 영문 컬럼명 사용
                    cond1 = self._df['market'] == market
                    cond2 = self._df['list_date'] <= date
                    return self._df[cond1 & cond2].index.to_list()

                def get_name(self, ticker) -> str:
                    if self._df is None or self._df.empty:
                        return ticker
                    try:
                        return self._df.loc[ticker, 'name']
                    except:
                        return ticker

                def get_market(self, ticker) -> str:
                    if self._df is None or self._df.empty:
                        return "UNKNOWN"
                    try:
                        return self._df.loc[ticker, 'market']
                    except:
                        return "UNKNOWN"

            # 모듈의 EtxTicker를 패치된 버전으로 교체
            etx_ticker.EtxTicker = PatchedEtxTicker

            # 싱글톤 캐시 클리어 (데코레이터 관련)
            if hasattr(etx_ticker, '_singleton_instances'):
                etx_ticker._singleton_instances = {}

            print("✅ pykrx EtxTicker 인코딩 패치 완료")
            return True

    except Exception as e:
        print(f"⚠️ pykrx EtxTicker 패치 실패: {e}")
        return False


# ============================================================================
# KRX API 직접 호출 (pykrx 인코딩 문제 완전 우회)
# ============================================================================

def get_krx_etf_list_direct(date: str = None) -> List[Dict]:
    """
    KRX API를 직접 호출하여 ETF 목록 조회
    pykrx의 get_etf_ticker_list() 인코딩 문제 완전 우회
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020101"
    }

    # ETF 전종목 기본정보
    params = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT04301",
        "locale": "ko_KR",
        "trdDd": date,
        "share": "1",
        "money": "1",
        "csvxls_is498": "false"
    }

    try:
        response = requests.post(url, data=params, headers=headers, timeout=30)
        response.encoding = 'utf-8'
        data = response.json()

        if "OutBlock_1" in data:
            items = data["OutBlock_1"]
            results = []
            for item in items:
                results.append({
                    "티커": item.get("ISU_SRT_CD", ""),
                    "종목명": item.get("ISU_ABBRV", ""),
                    "종가": int(item.get("TDD_CLSPRC", "0").replace(",", "") or 0),
                    "전일대비": int(item.get("CMPPREVDD_PRC", "0").replace(",", "") or 0),
                    "등락률": float(item.get("FLUC_RT", "0").replace(",", "") or 0),
                    "NAV": float(item.get("NAV", "0").replace(",", "") or 0),
                    "거래량": int(item.get("ACC_TRDVOL", "0").replace(",", "") or 0),
                    "거래대금": int(item.get("ACC_TRDVAL", "0").replace(",", "") or 0),
                    "시가총액": int(item.get("MKTCAP", "0").replace(",", "") or 0),
                })
            return results
        return []
    except Exception as e:
        print(f"⚠️ KRX ETF API 에러: {e}")
        return []


def get_krx_etn_list_direct(date: str = None) -> List[Dict]:
    """
    KRX API를 직접 호출하여 ETN 목록 조회
    pykrx의 get_etn_ticker_list() 인코딩 문제 완전 우회
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020201"
    }

    # ETN 전종목 기본정보
    params = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT04401",
        "locale": "ko_KR",
        "trdDd": date,
        "share": "1",
        "money": "1",
        "csvxls_isNo": "false"
    }

    try:
        response = requests.post(url, data=params, headers=headers, timeout=30)
        response.encoding = 'utf-8'
        data = response.json()

        if "OutBlock_1" in data:
            items = data["OutBlock_1"]
            results = []
            for item in items:
                results.append({
                    "티커": item.get("ISU_SRT_CD", ""),
                    "종목명": item.get("ISU_ABBRV", ""),
                    "종가": int(item.get("TDD_CLSPRC", "0").replace(",", "") or 0),
                    "전일대비": int(item.get("CMPPREVDD_PRC", "0").replace(",", "") or 0),
                    "등락률": float(item.get("FLUC_RT", "0").replace(",", "") or 0),
                    "거래량": int(item.get("ACC_TRDVOL", "0").replace(",", "") or 0),
                    "거래대금": int(item.get("ACC_TRDVAL", "0").replace(",", "") or 0),
                })
            return results
        return []
    except Exception as e:
        print(f"⚠️ KRX ETN API 에러: {e}")
        return []


def get_krx_elw_list_direct(date: str = None) -> List[Dict]:
    """
    KRX API를 직접 호출하여 ELW 목록 조회
    pykrx의 get_elw_ticker_list() 인코딩 문제 완전 우회
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020301"
    }

    # ELW 전종목 기본정보
    params = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT04501",
        "locale": "ko_KR",
        "trdDd": date,
        "share": "1",
        "money": "1",
        "csvxls_isNo": "false"
    }

    try:
        response = requests.post(url, data=params, headers=headers, timeout=30)
        response.encoding = 'utf-8'
        data = response.json()

        if "OutBlock_1" in data:
            items = data["OutBlock_1"]
            results = []
            for item in items:
                results.append({
                    "티커": item.get("ISU_SRT_CD", ""),
                    "종목명": item.get("ISU_ABBRV", ""),
                    "종가": int(item.get("TDD_CLSPRC", "0").replace(",", "") or 0),
                    "전일대비": int(item.get("CMPPREVDD_PRC", "0").replace(",", "") or 0),
                    "등락률": float(item.get("FLUC_RT", "0").replace(",", "") or 0),
                    "거래량": int(item.get("ACC_TRDVOL", "0").replace(",", "") or 0),
                    "거래대금": int(item.get("ACC_TRDVAL", "0").replace(",", "") or 0),
                    "기초자산": item.get("ULY_NM", ""),
                })
            return results
        return []
    except Exception as e:
        print(f"⚠️ KRX ELW API 에러: {e}")
        return []


# ============================================================================
# pykrx 한글 인코딩 래퍼 (Windows 호환)
# ============================================================================

# pykrx 함수별 예상 한글 컬럼명 매핑
PYKRX_COLUMN_MAP = {
    # OHLCV 함수들
    "ohlcv": {
        "시가": "시가", "고가": "고가", "저가": "저가", "종가": "종가",
        "거래량": "거래량", "거래대금": "거래대금", "등락률": "등락률"
    },
    # 시가총액 함수
    "market_cap": {
        "시가총액": "시가총액", "거래량": "거래량", "거래대금": "거래대금",
        "상장주식수": "상장주식수"
    },
    # 펀더멘털 함수
    "fundamental": {
        "BPS": "BPS", "PER": "PER", "PBR": "PBR", "EPS": "EPS",
        "DIV": "DIV", "DPS": "DPS"
    }
}

def safe_pykrx_call(func, *args, fallback_columns=None, **kwargs):
    """
    pykrx 함수를 안전하게 호출하고 인코딩 문제 해결

    Windows에서 pykrx가 반환하는 DataFrame의 컬럼명이 깨지는 문제를 해결합니다.
    깨진 컬럼명을 영문 또는 표준 한글로 자동 변환합니다.

    Args:
        func: 호출할 pykrx 함수
        *args: 함수 인자
        fallback_columns: 컬럼명이 깨졌을 때 사용할 대체 컬럼명 리스트
        **kwargs: 함수 키워드 인자

    Returns:
        pandas.DataFrame: 정상화된 DataFrame
    """
    try:
        df = func(*args, **kwargs)

        if df is None or df.empty:
            return pd.DataFrame()

        # 컬럼명 디코딩 시도
        new_columns = []
        columns_fixed = False

        for col in df.columns:
            if isinstance(col, bytes):
                # bytes 타입이면 UTF-8로 디코딩
                try:
                    new_col = col.decode('utf-8')
                except:
                    try:
                        new_col = col.decode('cp949')
                    except:
                        new_col = str(col)
                new_columns.append(new_col)
                columns_fixed = True
            elif isinstance(col, str):
                # 깨진 문자열 체크 (예: '\ufffd' 포함 시)
                if '\ufffd' in col or not col.isprintable():
                    columns_fixed = True
                    # fallback_columns 사용
                    if fallback_columns and len(new_columns) < len(fallback_columns):
                        new_columns.append(fallback_columns[len(new_columns)])
                    else:
                        new_columns.append(f"col_{len(new_columns)}")
                else:
                    new_columns.append(col)
            else:
                new_columns.append(str(col))

        if columns_fixed or (fallback_columns and len(df.columns) == len(fallback_columns)):
            # 컬럼이 모두 깨져있거나 fallback이 있으면 대체
            if fallback_columns and len(df.columns) == len(fallback_columns):
                df.columns = fallback_columns
            else:
                df.columns = new_columns

        return df

    except Exception as e:
        error_msg = str(e)
        # 컬럼 인덱스 에러 처리
        if "are in the [columns]" in error_msg or "KeyError" in error_msg:
            # 컬럼명 문제 - 빈 DataFrame 대신 에러 메시지 포함
            print(f"⚠️ pykrx 컬럼 인코딩 에러: {error_msg}")
            return pd.DataFrame()
        raise


def get_market_ohlcv_safe(date: str, market: str = "KOSPI", limit: int = 20):
    """
    시장 전체 OHLCV 데이터를 안전하게 조회
    pykrx의 get_market_ohlcv_by_ticker 인코딩 문제 우회
    """
    try:
        # 방법 1: get_market_ticker_list로 종목 목록 가져와서 개별 조회
        tickers = stock.get_market_ticker_list(date, market=market)

        if not tickers:
            return pd.DataFrame()

        # 상위 N개만 조회 (성능)
        tickers = tickers[:limit]

        results = []
        for ticker in tickers:
            try:
                df = stock.get_market_ohlcv(date, date, ticker)
                if not df.empty:
                    row = df.iloc[0].to_dict()
                    row["티커"] = ticker
                    # 종목명 추가
                    try:
                        name = stock.get_market_ticker_name(ticker)
                        row["종목명"] = name
                    except:
                        row["종목명"] = ticker
                    results.append(row)
            except Exception as e:
                continue

        if results:
            result_df = pd.DataFrame(results)
            # 컬럼 순서 정리
            cols = ["티커", "종목명"] + [c for c in result_df.columns if c not in ["티커", "종목명"]]
            return result_df[cols]

        return pd.DataFrame()

    except Exception as e:
        print(f"⚠️ get_market_ohlcv_safe 에러: {e}")
        return pd.DataFrame()


def get_etf_list_safe(date: str, limit: int = 30):
    """
    ETF 목록을 안전하게 조회
    pykrx core 함수를 직접 호출하여 인코딩 문제 완전 우회
    """
    try:
        from pykrx.website.krx.etx.core import ETF_전종목기본종목

        # 직접 fetch 호출 (쿠키가 주입된 세션 사용)
        df = ETF_전종목기본종목().fetch()

        if df is None or df.empty:
            print("⚠️ ETF_전종목기본종목 fetch 결과 없음")
            return pd.DataFrame()

        # 필요한 컬럼만 추출
        result_df = df[["ISU_SRT_CD", "ISU_ABBRV"]].copy()
        result_df.columns = ["티커", "종목명"]

        # 상위 N개만 반환
        return result_df.head(limit)

    except Exception as e:
        print(f"⚠️ get_etf_list_safe 에러: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def get_market_cap_safe(date: str, market: str = "KOSPI", limit: int = 20):
    """
    시가총액 데이터를 안전하게 조회
    pykrx core 함수를 직접 호출하여 한글 인코딩 문제 완전 우회

    영문 컬럼명 사용: ISU_SRT_CD, TDD_CLSPRC, MKTCAP, ACC_TRDVOL, ACC_TRDVAL, LIST_SHRS
    """
    try:
        from pykrx.website.krx.market.core import 전종목시세
        import numpy as np

        # 시장 코드 매핑
        market2mktid = {
            "ALL": "ALL",
            "KOSPI": "STK",
            "KOSDAQ": "KSQ",
            "KONEX": "KNX"
        }

        mktid = market2mktid.get(market, "STK")

        # pykrx core에서 직접 fetch (영문 컬럼명 반환)
        df = 전종목시세().fetch(date, mktid)
        print(f"[get_market_cap_safe] fetch 결과: {type(df)}, empty={df is None or (hasattr(df, 'empty') and df.empty)}")

        if df is None or df.empty:
            print(f"⚠️ 전종목시세 fetch 결과 없음: date={date}, market={market}")
            return pd.DataFrame()

        print(f"[get_market_cap_safe] 컬럼: {list(df.columns)}")
        print(f"[get_market_cap_safe] MKTCAP 샘플: {df['MKTCAP'].head(3).tolist()}")

        # 시가총액이 '-'인 경우 (장 시작 전) 빈 DataFrame 반환 → fallback 트리거
        if len(df) > 0 and df['MKTCAP'].iloc[0] == '-':
            print(f"[get_market_cap_safe] MKTCAP이 '-' (장 시작 전) → fallback 필요")
            return pd.DataFrame()

        # 영문 컬럼명만 사용하여 한글 인코딩 문제 완전 회피
        required_cols = ['ISU_SRT_CD', 'TDD_CLSPRC', 'MKTCAP', 'ACC_TRDVOL', 'ACC_TRDVAL', 'LIST_SHRS']

        # 필요한 컬럼만 추출
        df = df[required_cols].copy()

        # 한글 컬럼명으로 변환 (Python 코드 내에서 직접 설정)
        df.columns = ['티커', '종가', '시가총액', '거래량', '거래대금', '상장주식수']

        # 데이터 정제
        df = df.replace(r'\W', '', regex=True)
        df = df.replace('', 0)

        # 숫자 컬럼 변환
        for col in ['종가', '시가총액', '거래량', '거래대금', '상장주식수']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(np.int64)

        # 시가총액 기준 내림차순 정렬
        df = df.sort_values('시가총액', ascending=False)

        # 상위 N개만 선택
        df = df.head(limit)

        # 종목명 추가
        results = []
        for _, row in df.iterrows():
            ticker = row['티커']
            try:
                name = stock.get_market_ticker_name(ticker)
            except:
                name = ticker

            results.append({
                "티커": ticker,
                "종목명": name,
                "종가": int(row['종가']),
                "시가총액": int(row['시가총액']),
                "거래량": int(row['거래량']),
                "거래대금": int(row['거래대금']),
                "상장주식수": int(row['상장주식수'])
            })

        return pd.DataFrame(results)

    except Exception as e:
        print(f"⚠️ get_market_cap_safe 에러: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def get_etn_list_safe(date: str, limit: int = 30):
    """
    ETN 목록을 안전하게 조회
    pykrx core 함수를 직접 호출하여 인코딩 문제 완전 우회
    """
    try:
        from pykrx.website.krx.etx.core import ETN_전종목기본종목

        # 직접 fetch 호출 (쿠키가 주입된 세션 사용)
        df = ETN_전종목기본종목().fetch()

        if df is None or df.empty:
            print("⚠️ ETN_전종목기본종목 fetch 결과 없음")
            return pd.DataFrame()

        # 필요한 컬럼만 추출
        result_df = df[["ISU_SRT_CD", "ISU_ABBRV"]].copy()
        result_df.columns = ["티커", "종목명"]

        # 상위 N개만 반환
        return result_df.head(limit)

    except Exception as e:
        print(f"⚠️ get_etn_list_safe 에러: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def get_elw_list_safe(date: str, limit: int = 30):
    """
    ELW 목록을 안전하게 조회
    pykrx core 함수를 직접 호출하여 인코딩 문제 완전 우회
    """
    try:
        from pykrx.website.krx.etx.core import ELW_전종목기본종목

        # 직접 fetch 호출 (쿠키가 주입된 세션 사용)
        df = ELW_전종목기본종목().fetch()

        if df is None or df.empty:
            print("⚠️ ELW_전종목기본종목 fetch 결과 없음")
            return pd.DataFrame()

        # 필요한 컬럼만 추출
        result_df = df[["ISU_SRT_CD", "ISU_ABBRV"]].copy()
        result_df.columns = ["티커", "종목명"]

        # 상위 N개만 반환
        return result_df.head(limit)

    except Exception as e:
        print(f"⚠️ get_elw_list_safe 에러: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def get_fundamental_safe(date: str, market: str = "KOSPI", limit: int = 20):
    """
    펀더멘털 데이터(PER/PBR 등)를 안전하게 조회
    """
    try:
        tickers = stock.get_market_ticker_list(date, market=market)

        if not tickers:
            return pd.DataFrame()

        tickers = tickers[:limit * 2]

        results = []
        for ticker in tickers:
            try:
                df = stock.get_market_fundamental(date, date, ticker)
                if not df.empty:
                    row = df.iloc[0].to_dict()
                    row["티커"] = ticker
                    try:
                        name = stock.get_market_ticker_name(ticker)
                        row["종목명"] = name
                    except:
                        row["종목명"] = ticker
                    results.append(row)

                    if len(results) >= limit:
                        break
            except:
                continue

        if results:
            result_df = pd.DataFrame(results)
            cols = ["티커", "종목명"] + [c for c in result_df.columns if c not in ["티커", "종목명"]]
            return result_df[cols]

        return pd.DataFrame()

    except Exception as e:
        print(f"⚠️ get_fundamental_safe 에러: {e}")
        return pd.DataFrame()


# ============================================================================
# 전역 상태
# ============================================================================

_is_logged_in = False
_login_error: Optional[str] = None
_krx_session: Optional[KRXSession] = None

# ============================================================================
# 서버 시작/종료 라이프사이클
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작 시 KRX 로그인 및 pykrx 패치"""
    global _is_logged_in, _login_error, _krx_session

    # 환경변수 또는 기본값에서 자격증명 로드
    user_id = os.getenv("KRX_USER_ID", "goguma")
    password = os.getenv("KRX_PASSWORD", "wjdqh12!@")

    print("=" * 60)
    print("🚀 PyKRX API Server 시작")
    print("=" * 60)

    try:
        print(f"🔐 KRX 로그인 시도: {user_id}")
        success = login_and_patch(user_id, password)

        if success:
            _is_logged_in = True
            _krx_session = get_session()
            print("✅ KRX 로그인 성공! 모든 API 사용 가능")
        else:
            _login_error = "로그인 실패"
            print("⚠️ KRX 로그인 실패 - 일부 API 제한됨")
    except Exception as e:
        _login_error = str(e)
        print(f"⚠️ KRX 로그인 오류: {e}")

    # 쿠키 주입은 이미 파일 로드 시 _inject_cookies_before_pykrx_import()에서 완료됨
    # (pykrx import 전에 패치해야 하므로)

    # pykrx ETX 인코딩 패치 (ETF/ETN/ELW)
    patch_pykrx_etx_ticker()

    print("=" * 60)

    yield  # 서버 실행

    # 서버 종료 시 정리
    print("🛑 PyKRX API Server 종료")


# 한글 지원을 위한 커스텀 JSON 응답 클래스
class UnicodeJSONResponse(JSONResponse):
    """ensure_ascii=False로 한글을 올바르게 인코딩하는 JSON 응답"""
    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            default=str  # datetime 등 직렬화 불가 객체 처리
        ).encode("utf-8")


app = FastAPI(
    title="PyKRX Data API",
    description="KRX 주식 데이터 API + 로그인 세션 통합",
    version="2.0.0",
    lifespan=lifespan,
    default_response_class=UnicodeJSONResponse  # 한글 인코딩 지원
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5180", "http://localhost:5181", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# 주요 종목 목록
# ============================================================================

KOSPI_TOP_STOCKS: Dict[str, str] = {
    "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스", "005935": "삼성전자우", "005380": "현대차",
    "000270": "기아", "006400": "삼성SDI", "051910": "LG화학",
    "035420": "NAVER", "035720": "카카오", "105560": "KB금융",
    "055550": "신한지주", "003670": "포스코퓨처엠", "012330": "현대모비스",
    "028260": "삼성물산", "066570": "LG전자", "086790": "하나금융지주",
    "034730": "SK", "096770": "SK이노베이션", "010130": "고려아연",
    "032830": "삼성생명", "003550": "LG", "015760": "한국전력",
    "011200": "HMM", "018260": "삼성에스디에스", "033780": "KT&G",
    "009150": "삼성전기", "034020": "두산에너빌리티", "030200": "KT",
    "000810": "삼성화재", "017670": "SK텔레콤", "010950": "S-Oil",
    "003490": "대한항공", "010140": "삼성중공업", "047050": "포스코인터내셔널",
    "090430": "아모레퍼시픽", "247540": "에코프로비엠", "316140": "우리금융지주",
    "259960": "크래프톤", "352820": "하이브", "068270": "셀트리온",
    "004020": "현대제철", "138040": "메리츠금융지주", "051900": "LG생활건강",
    "161390": "한국타이어앤테크놀로지", "377300": "카카오페이", "011170": "롯데케미칼",
    "009540": "한국조선해양", "078930": "GS"
}

KOSDAQ_TOP_STOCKS: Dict[str, str] = {
    "247540": "에코프로비엠", "086520": "에코프로", "403870": "HPSP",
    "041510": "에스엠", "293490": "카카오게임즈", "145020": "휴젤",
    "357780": "솔브레인", "196170": "알테오젠", "112040": "위메이드",
    "035900": "JYP Ent.", "091990": "셀트리온헬스케어", "263750": "펄어비스",
    "039030": "이오테크닉스", "095340": "ISC", "257720": "실리콘투",
    "036930": "주성엔지니어링", "328130": "루닛", "277810": "레인보우로보틱스",
    "005290": "동진쎄미켐", "067160": "아프리카TV", "214150": "클래시스",
    "039200": "오스코텍", "140860": "파크시스템스", "377480": "씨앤씨인터내셔널",
    "060280": "큐렉소", "086900": "메디톡스", "065680": "우주일렉트로",
    "141080": "레고켐바이오", "950140": "잉글우드랩", "035760": "CJ ENM"
}

# ============================================================================
# 유틸리티 함수
# ============================================================================

def get_market_name(market: str) -> str:
    """마켓 코드를 한글 이름으로 변환"""
    return {"KOSPI": "코스피", "KOSDAQ": "코스닥", "KONEX": "코넥스"}.get(market, market)


def _safe_float(value) -> Optional[float]:
    """안전한 float 변환 (None, 빈 문자열, 잘못된 값 처리)"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value != 0 else None
    if isinstance(value, str):
        value = value.strip().replace(',', '')
        if not value or value == '-':
            return None
        try:
            result = float(value)
            return result if result != 0 else None
        except ValueError:
            return None
    return None


def find_valid_trading_date(ticker: str = "005930", max_days: int = 14) -> Optional[str]:
    """유효한 거래일 찾기"""
    today = datetime.now()
    end_date = today.strftime("%Y%m%d")
    start_date = (today - timedelta(days=max_days)).strftime("%Y%m%d")

    try:
        df = stock.get_market_ohlcv(start_date, end_date, ticker)
        if df is not None and not df.empty:
            return df.index[-1].strftime("%Y%m%d")
    except:
        pass
    return None


# ============================================================================
# API 엔드포인트
# ============================================================================

@app.get("/")
def root():
    """서버 상태 확인"""
    return {
        "status": "ok",
        "message": "PyKRX API Server Running",
        "version": "2.0.0",
        "krx_login": _is_logged_in,
        "login_error": _login_error,
        "features": {
            "ohlcv": True,
            "market_cap": True,
            "fundamental": _is_logged_in,  # 로그인 필요
            "investor_trading": _is_logged_in,  # 로그인 필요
            "foreign_holding": _is_logged_in,  # 로그인 필요
        }
    }


@app.get("/api/status")
def get_status():
    """상세 상태 확인"""
    return {
        "server": "running",
        "krx_login": {
            "logged_in": _is_logged_in,
            "error": _login_error,
            "session_valid": _krx_session.logged_in if _krx_session else False
        },
        "available_endpoints": [
            "/api/stocks/list",
            "/api/stocks/ohlcv",
            "/api/stocks/market-cap",
            "/api/stocks/fundamental" + (" ✅" if _is_logged_in else " ⚠️ 로그인 필요"),
            "/api/stocks/all-markets",
            "/api/stocks/sector",
            "/api/stocks/investor-trading" + (" ✅" if _is_logged_in else " ⚠️ 로그인 필요"),
            "/api/stocks/foreign-holding" + (" ✅" if _is_logged_in else " ⚠️ 로그인 필요"),
        ]
    }


@app.post("/api/login")
def manual_login(
    user_id: str = Query(..., description="KRX 아이디"),
    password: str = Query(..., description="KRX 비밀번호")
):
    """수동 로그인 (재로그인)"""
    global _is_logged_in, _login_error, _krx_session

    try:
        success = login_and_patch(user_id, password, force=True)
        if success:
            _is_logged_in = True
            _krx_session = get_session()
            _login_error = None
            return {"status": "ok", "message": "로그인 성공"}
        else:
            _login_error = "로그인 실패"
            return {"status": "error", "message": "로그인 실패"}
    except Exception as e:
        _login_error = str(e)
        return {"status": "error", "message": str(e)}


@app.get("/api/stocks/list")
def get_stock_list(
    market: str = Query("KOSPI", description="시장 구분: KOSPI, KOSDAQ, KONEX"),
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD), 미입력시 최근 거래일")
):
    """종목 목록 조회"""
    try:
        if date is None:
            today = datetime.now()
            for i in range(7):
                test_date = (today - timedelta(days=i)).strftime("%Y%m%d")
                tickers = stock.get_market_ticker_list(test_date, market=market)
                if len(tickers) > 0:
                    date = test_date
                    break

        tickers = stock.get_market_ticker_list(date, market=market)
        result = []
        for ticker in tickers[:500]:
            name = stock.get_market_ticker_name(ticker)
            result.append({
                "ticker": ticker,
                "name": name,
                "market": get_market_name(market)
            })

        return {"date": date, "market": market, "count": len(result), "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stocks/ohlcv")
def get_ohlcv(
    ticker: str = Query(..., description="종목코드 (예: 005930)"),
    start: Optional[str] = Query(None, description="시작일 (YYYYMMDD)"),
    end: Optional[str] = Query(None, description="종료일 (YYYYMMDD)"),
    period: int = Query(30, description="기간 (일), start/end 미입력시 사용")
):
    """OHLCV (시가/고가/저가/종가/거래량) 조회"""
    try:
        if end is None:
            end = datetime.now().strftime("%Y%m%d")
        if start is None:
            start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=period)).strftime("%Y%m%d")

        df = stock.get_market_ohlcv(start, end, ticker)
        if df.empty:
            return {"ticker": ticker, "data": []}

        df = df.reset_index()
        df['날짜'] = df['날짜'].dt.strftime('%Y-%m-%d')

        return {
            "ticker": ticker,
            "name": stock.get_market_ticker_name(ticker),
            "start": start,
            "end": end,
            "count": len(df),
            "data": df.to_dict('records')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stocks/market-cap")
def get_market_cap_endpoint(
    market: str = Query("KOSPI", description="시장 구분"),
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    top_n: int = Query(50, description="상위 N개 종목")
):
    """
    시가총액 상위 종목 조회
    pykrx 한글 인코딩 문제 해결된 safe 래퍼 사용
    """
    try:
        # 날짜 없으면 최근 거래일 찾기
        if date is None:
            today = datetime.now()
            for i in range(7):
                test_date = (today - timedelta(days=i)).strftime("%Y%m%d")
                # safe 래퍼로 테스트
                df = get_market_cap_safe(test_date, market=market, limit=1)
                if not df.empty:
                    date = test_date
                    break

        if date is None:
            return {"date": None, "market": market, "data": [], "error": "최근 거래일 없음"}

        # 안전한 래퍼 함수 사용 (pykrx 인코딩 문제 해결)
        df = get_market_cap_safe(date, market=market, limit=top_n)

        if df.empty:
            return {"date": date, "market": market, "data": []}

        result = []
        for _, row in df.iterrows():
            result.append({
                "종목코드": row['티커'],
                "종목명": row['종목명'],
                "시장": get_market_name(market),
                "종가": int(row['종가']),
                "시가총액": int(row['시가총액']),
                "시가총액_조": round(row['시가총액'] / 1000000000000, 2),
                "거래량": int(row['거래량']),
                "거래대금": int(row['거래대금']),
                "상장주식수": int(row['상장주식수'])
            })

        return {"date": date, "market": market, "count": len(result), "data": result}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stocks/fundamental")
def get_fundamental(
    market: str = Query("KOSPI", description="시장 구분"),
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    top_n: int = Query(100, description="상위 N개 종목")
):
    """
    펀더멘털 지표 (PER, PBR, 배당수익률) 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in:
        raise HTTPException(
            status_code=401,
            detail="KRX 로그인이 필요합니다. /api/login 또는 서버 재시작 시 로그인하세요."
        )

    try:
        if date is None:
            today = datetime.now()
            for i in range(7):
                test_date = (today - timedelta(days=i)).strftime("%Y%m%d")
                try:
                    df = stock.get_market_fundamental(test_date, market=market)
                    if not df.empty:
                        date = test_date
                        break
                except:
                    continue

        # 시가총액과 펀더멘털 데이터 병합
        df_cap = stock.get_market_cap(date, market=market)
        df_fund = stock.get_market_fundamental(date, market=market)

        if df_cap.empty or df_fund.empty:
            return {"date": date, "market": market, "data": []}

        df = df_cap.join(df_fund, how='inner')
        df = df.reset_index()
        df = df.sort_values('시가총액', ascending=False).head(top_n)

        result = []
        for _, row in df.iterrows():
            ticker = row['티커']
            result.append({
                "종목코드": ticker,
                "종목명": stock.get_market_ticker_name(ticker),
                "시장": get_market_name(market),
                "종가": int(row['종가']),
                "등락률": round(row.get('등락률', 0), 2),
                "거래량": int(row['거래량']),
                "거래대금_억": round(row['거래대금'] / 100000000, 1),
                "시가총액_조": round(row['시가총액'] / 1000000000000, 2),
                "PER": round(row['PER'], 2) if pd.notna(row['PER']) else None,
                "PBR": round(row['PBR'], 2) if pd.notna(row['PBR']) else None,
                "배당수익률": round(row['DIV'], 2) if pd.notna(row['DIV']) else None,
                "EPS": int(row['EPS']) if pd.notna(row['EPS']) else None,
                "BPS": int(row['BPS']) if pd.notna(row['BPS']) else None,
                "기준일": date
            })

        return {"date": date, "market": market, "count": len(result), "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stocks/all-markets")
def get_all_markets_data(
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    top_n: int = Query(50, description="시장별 상위 N개 종목")
):
    """
    코스피 + 코스닥 통합 데이터 조회 (GraphicWalker용)
    로그인 상태에 따라 PER/PBR 포함 여부 결정
    """
    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)
            if date is None:
                return {"date": None, "count": 0, "data": [], "error": "유효한 거래일을 찾을 수 없습니다"}

        print(f"Using date: {date}")
        all_data = []

        start_date = (datetime.strptime(date, "%Y%m%d") - timedelta(days=10)).strftime("%Y%m%d")
        end_date = date

        # 펀더멘털 데이터 로드 시도 (KRX Session API 직접 사용)
        fund_kospi = {}
        fund_kosdaq = {}
        if _is_logged_in and _krx_session:
            try:
                # KRX Session API 직접 호출 (PyKRX 대신)
                kospi_data = _krx_session.get_per_pbr_div(date, market="STK")
                if kospi_data:
                    items = kospi_data.get('output', kospi_data.get('OutBlock_1', []))
                    for item in items:
                        ticker = item.get('ISU_SRT_CD', '')
                        if ticker:
                            fund_kospi[ticker] = {
                                'PER': _safe_float(item.get('PER')),
                                'PBR': _safe_float(item.get('PBR')),
                                'DIV': _safe_float(item.get('DVD_YLD')),
                                'EPS': _safe_float(item.get('EPS')),
                                'BPS': _safe_float(item.get('BPS'))
                            }
                    print(f"KOSPI fundamental 로드 성공: {len(fund_kospi)}개 종목")
            except Exception as e:
                print(f"KOSPI fundamental 로드 실패: {e}")

            try:
                kosdaq_data = _krx_session.get_per_pbr_div(date, market="KSQ")
                if kosdaq_data:
                    items = kosdaq_data.get('output', kosdaq_data.get('OutBlock_1', []))
                    for item in items:
                        ticker = item.get('ISU_SRT_CD', '')
                        if ticker:
                            fund_kosdaq[ticker] = {
                                'PER': _safe_float(item.get('PER')),
                                'PBR': _safe_float(item.get('PBR')),
                                'DIV': _safe_float(item.get('DVD_YLD')),
                                'EPS': _safe_float(item.get('EPS')),
                                'BPS': _safe_float(item.get('BPS'))
                            }
                    print(f"KOSDAQ fundamental 로드 성공: {len(fund_kosdaq)}개 종목")
            except Exception as e:
                print(f"KOSDAQ fundamental 로드 실패: {e}")

        # KOSPI 종목 처리
        kospi_tickers = list(KOSPI_TOP_STOCKS.items())[:top_n]
        for ticker, name in kospi_tickers:
            try:
                df = stock.get_market_ohlcv(start_date, end_date, ticker)
                if df is not None and not df.empty:
                    row = df.iloc[-1]
                    prev_close = df.iloc[-2]['종가'] if len(df) > 1 else row['종가']
                    change_rate = ((row['종가'] - prev_close) / prev_close * 100) if prev_close else 0

                    item = {
                        "종목코드": ticker,
                        "종목명": name,
                        "시장": "코스피",
                        "시가": int(row['시가']),
                        "고가": int(row['고가']),
                        "저가": int(row['저가']),
                        "종가": int(row['종가']),
                        "등락률": round(change_rate, 2),
                        "거래량": int(row['거래량']),
                        "거래대금_억": round(row['거래대금'] / 100000000, 1) if pd.notna(row.get('거래대금')) else 0,
                        "기준일": df.index[-1].strftime("%Y-%m-%d")
                    }

                    # 펀더멘털 데이터 추가 (로그인 상태)
                    if ticker in fund_kospi:
                        f = fund_kospi[ticker]
                        item["PER"] = round(f['PER'], 2) if pd.notna(f.get('PER')) else None
                        item["PBR"] = round(f['PBR'], 2) if pd.notna(f.get('PBR')) else None
                        item["배당수익률"] = round(f['DIV'], 2) if pd.notna(f.get('DIV')) else None
                        item["EPS"] = int(f['EPS']) if pd.notna(f.get('EPS')) else None
                        item["BPS"] = int(f['BPS']) if pd.notna(f.get('BPS')) else None

                    all_data.append(item)
            except Exception as e:
                print(f"Error fetching {ticker} ({name}): {e}")
                continue

        # KOSDAQ 종목 처리
        kosdaq_tickers = list(KOSDAQ_TOP_STOCKS.items())[:top_n]
        for ticker, name in kosdaq_tickers:
            try:
                df = stock.get_market_ohlcv(start_date, end_date, ticker)
                if df is not None and not df.empty:
                    row = df.iloc[-1]
                    prev_close = df.iloc[-2]['종가'] if len(df) > 1 else row['종가']
                    change_rate = ((row['종가'] - prev_close) / prev_close * 100) if prev_close else 0

                    item = {
                        "종목코드": ticker,
                        "종목명": name,
                        "시장": "코스닥",
                        "시가": int(row['시가']),
                        "고가": int(row['고가']),
                        "저가": int(row['저가']),
                        "종가": int(row['종가']),
                        "등락률": round(change_rate, 2),
                        "거래량": int(row['거래량']),
                        "거래대금_억": round(row['거래대금'] / 100000000, 1) if pd.notna(row.get('거래대금')) else 0,
                        "기준일": df.index[-1].strftime("%Y-%m-%d")
                    }

                    # 펀더멘털 데이터 추가 (로그인 상태)
                    if ticker in fund_kosdaq:
                        f = fund_kosdaq[ticker]
                        item["PER"] = round(f['PER'], 2) if pd.notna(f.get('PER')) else None
                        item["PBR"] = round(f['PBR'], 2) if pd.notna(f.get('PBR')) else None
                        item["배당수익률"] = round(f['DIV'], 2) if pd.notna(f.get('DIV')) else None
                        item["EPS"] = int(f['EPS']) if pd.notna(f.get('EPS')) else None
                        item["BPS"] = int(f['BPS']) if pd.notna(f.get('BPS')) else None

                    all_data.append(item)
            except Exception as e:
                print(f"Error fetching {ticker} ({name}): {e}")
                continue

        print(f"Total fetched: {len(all_data)} stocks")

        return {
            "date": date,
            "count": len(all_data),
            "data": all_data,
            "includes_fundamental": _is_logged_in
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stocks/investor-trading")
def get_investor_trading(
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    market: str = Query("KOSPI", description="시장 구분")
):
    """
    투자자별 거래실적 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in:
        raise HTTPException(
            status_code=401,
            detail="KRX 로그인이 필요합니다."
        )

    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        # 직접 세션 API 사용
        data = _krx_session.get_investor_trading(date, market="STK" if market == "KOSPI" else "KSQ")

        if not data:
            return {"date": date, "market": market, "data": []}

        return {
            "date": date,
            "market": market,
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stocks/foreign-holding")
def get_foreign_holding(
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    market: str = Query("KOSPI", description="시장 구분"),
    top_n: int = Query(50, description="상위 N개 종목")
):
    """
    외국인 보유량 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in:
        raise HTTPException(
            status_code=401,
            detail="KRX 로그인이 필요합니다."
        )

    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        # 직접 세션 API 사용
        data = _krx_session.get_foreign_holding(date, market="STK" if market == "KOSPI" else "KSQ")

        if not data:
            return {"date": date, "market": market, "data": []}

        items = data.get('output', data.get('OutBlock_1', []))[:top_n]

        return {
            "date": date,
            "market": market,
            "count": len(items),
            "data": items
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stocks/sector")
def get_sector_data(
    market: str = Query("KOSPI", description="시장 구분"),
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)")
):
    """업종별 데이터 조회"""
    try:
        if date is None:
            today = datetime.now()
            for i in range(7):
                test_date = (today - timedelta(days=i)).strftime("%Y%m%d")
                try:
                    df = stock.get_index_ticker_list(test_date, market=market)
                    if len(df) > 0:
                        date = test_date
                        break
                except:
                    continue

        sectors = stock.get_index_ticker_list(date, market=market)

        result = []
        for sector_code in sectors[:30]:
            try:
                name = stock.get_index_ticker_name(sector_code)
                ohlcv = stock.get_index_ohlcv(date, date, sector_code)
                if not ohlcv.empty:
                    row = ohlcv.iloc[-1]
                    result.append({
                        "업종코드": sector_code,
                        "업종명": name,
                        "시장": get_market_name(market),
                        "종가": float(row['종가']),
                        "등락률": float(row.get('등락률', 0)),
                        "거래량": int(row['거래량']),
                        "거래대금_억": round(row['거래대금'] / 100000000, 1)
                    })
            except:
                continue

        return {"date": date, "market": market, "count": len(result), "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 150% 커버리지 확장 API 엔드포인트
# ============================================================================

@app.get("/api/etf/all")
def get_etf_all(
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    top_n: int = Query(100, description="상위 N개")
):
    """
    ETF 전종목 데이터 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in or not _krx_session:
        raise HTTPException(status_code=401, detail="KRX 로그인이 필요합니다.")

    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        data = _krx_session.get_etf_data(date)
        if not data:
            return {"date": date, "count": 0, "data": []}

        items = data.get('output', data.get('OutBlock_1', []))[:top_n]
        return {"date": date, "count": len(items), "data": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/etn/all")
def get_etn_all(
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    top_n: int = Query(100, description="상위 N개")
):
    """
    ETN 전종목 데이터 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in or not _krx_session:
        raise HTTPException(status_code=401, detail="KRX 로그인이 필요합니다.")

    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        data = _krx_session.get_etn_data(date)
        if not data:
            return {"date": date, "count": 0, "data": []}

        items = data.get('output', data.get('OutBlock_1', []))[:top_n]
        return {"date": date, "count": len(items), "data": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/short-selling/trading")
def get_short_selling_trading(
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    market: str = Query("KOSPI", description="시장 구분"),
    top_n: int = Query(100, description="상위 N개")
):
    """
    공매도 거래현황 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in or not _krx_session:
        raise HTTPException(status_code=401, detail="KRX 로그인이 필요합니다.")

    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        mkt_code = "STK" if market.upper() == "KOSPI" else "KSQ"
        data = _krx_session.get_short_selling_by_stock(date, market=mkt_code)
        if not data:
            return {"date": date, "market": market, "count": 0, "data": []}

        items = data.get('output', data.get('OutBlock_1', []))[:top_n]
        return {"date": date, "market": market, "count": len(items), "data": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/short-selling/balance")
def get_short_selling_balance(
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    market: str = Query("KOSPI", description="시장 구분"),
    top_n: int = Query(100, description="상위 N개")
):
    """
    공매도 잔고현황 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in or not _krx_session:
        raise HTTPException(status_code=401, detail="KRX 로그인이 필요합니다.")

    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        mkt_code = "STK" if market.upper() == "KOSPI" else "KSQ"
        data = _krx_session.get_short_selling_balance(date, market=mkt_code)
        if not data:
            return {"date": date, "market": market, "count": 0, "data": []}

        items = data.get('output', data.get('OutBlock_1', []))[:top_n]
        return {"date": date, "market": market, "count": len(items), "data": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/credit/trading")
def get_credit_trading(
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    market: str = Query("KOSPI", description="시장 구분"),
    top_n: int = Query(100, description="상위 N개")
):
    """
    신용거래 현황 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in or not _krx_session:
        raise HTTPException(status_code=401, detail="KRX 로그인이 필요합니다.")

    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        mkt_code = "STK" if market.upper() == "KOSPI" else "KSQ"
        data = _krx_session.get_credit_trading(date, market=mkt_code)
        if not data:
            return {"date": date, "market": market, "count": 0, "data": []}

        items = data.get('output', data.get('OutBlock_1', []))[:top_n]
        return {"date": date, "market": market, "count": len(items), "data": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/program/trading")
def get_program_trading(
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    market: str = Query("KOSPI", description="시장 구분"),
    top_n: int = Query(100, description="상위 N개")
):
    """
    프로그램 매매 현황 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in or not _krx_session:
        raise HTTPException(status_code=401, detail="KRX 로그인이 필요합니다.")

    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        mkt_code = "STK" if market.upper() == "KOSPI" else "KSQ"
        data = _krx_session.get_program_trading(date, market=mkt_code)
        if not data:
            return {"date": date, "market": market, "count": 0, "data": []}

        items = data.get('output', data.get('OutBlock_1', []))[:top_n]
        return {"date": date, "market": market, "count": len(items), "data": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/index/list")
def get_index_list(
    market: str = Query("KOSPI", description="시장 구분: KOSPI, KOSDAQ"),
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)")
):
    """지수 목록 조회"""
    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        # PyKRX 사용
        sectors = stock.get_index_ticker_list(date, market=market)
        result = []
        for code in sectors:
            name = stock.get_index_ticker_name(code)
            result.append({"code": code, "name": name, "market": market})

        return {"date": date, "market": market, "count": len(result), "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/index/ohlcv")
def get_index_ohlcv(
    index_code: str = Query(..., description="지수 코드 (예: 1001)"),
    start: Optional[str] = Query(None, description="시작일 (YYYYMMDD)"),
    end: Optional[str] = Query(None, description="종료일 (YYYYMMDD)"),
    period: int = Query(30, description="기간 (일)")
):
    """지수 OHLCV 조회"""
    try:
        if end is None:
            end = datetime.now().strftime("%Y%m%d")
        if start is None:
            start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=period)).strftime("%Y%m%d")

        df = stock.get_index_ohlcv(start, end, index_code)
        if df.empty:
            return {"index_code": index_code, "data": []}

        df = df.reset_index()
        df['날짜'] = df['날짜'].dt.strftime('%Y-%m-%d')

        return {
            "index_code": index_code,
            "name": stock.get_index_ticker_name(index_code),
            "start": start,
            "end": end,
            "count": len(df),
            "data": df.to_dict('records')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/index/components")
def get_index_components(
    index_code: str = Query(..., description="지수 코드 (예: 1001)"),
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)")
):
    """지수 구성종목 조회"""
    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        df = stock.get_index_portfolio_deposit_file(index_code, date)
        if df is None or (hasattr(df, 'empty') and df.empty):
            return {"index_code": index_code, "date": date, "data": []}

        result = []
        if isinstance(df, pd.DataFrame):
            for ticker in df.index:
                result.append({
                    "ticker": ticker,
                    "name": stock.get_market_ticker_name(ticker)
                })
        else:
            for ticker in df:
                result.append({
                    "ticker": ticker,
                    "name": stock.get_market_ticker_name(ticker)
                })

        return {
            "index_code": index_code,
            "name": stock.get_index_ticker_name(index_code),
            "date": date,
            "count": len(result),
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/derivatives/futures")
def get_futures_data(
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    top_n: int = Query(50, description="상위 N개")
):
    """
    선물 시세 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in or not _krx_session:
        raise HTTPException(status_code=401, detail="KRX 로그인이 필요합니다.")

    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        data = _krx_session.get_futures_data(date)
        if not data:
            return {"date": date, "count": 0, "data": []}

        items = data.get('output', data.get('OutBlock_1', []))[:top_n]
        return {"date": date, "count": len(items), "data": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/derivatives/options")
def get_options_data(
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    top_n: int = Query(50, description="상위 N개")
):
    """
    옵션 시세 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in or not _krx_session:
        raise HTTPException(status_code=401, detail="KRX 로그인이 필요합니다.")

    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        data = _krx_session.get_options_data(date)
        if not data:
            return {"date": date, "count": 0, "data": []}

        items = data.get('output', data.get('OutBlock_1', []))[:top_n]
        return {"date": date, "count": len(items), "data": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dividend/info")
def get_dividend_info(
    ticker: str = Query(..., description="종목코드"),
    year: Optional[int] = Query(None, description="연도")
):
    """
    배당 정보 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in or not _krx_session:
        raise HTTPException(status_code=401, detail="KRX 로그인이 필요합니다.")

    try:
        if year is None:
            year = datetime.now().year

        data = _krx_session.get_dividend_info(ticker, year)
        if not data:
            return {"ticker": ticker, "year": year, "data": None}

        return {"ticker": ticker, "year": year, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/special/trading-halt")
def get_trading_halt(
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    market: str = Query("ALL", description="시장 구분")
):
    """
    거래정지 종목 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in or not _krx_session:
        raise HTTPException(status_code=401, detail="KRX 로그인이 필요합니다.")

    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        data = _krx_session.get_trading_halt(date)
        if not data:
            return {"date": date, "count": 0, "data": []}

        items = data.get('output', data.get('OutBlock_1', []))
        return {"date": date, "count": len(items), "data": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/special/admin-issue")
def get_admin_issue(
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    market: str = Query("ALL", description="시장 구분")
):
    """
    관리종목 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in or not _krx_session:
        raise HTTPException(status_code=401, detail="KRX 로그인이 필요합니다.")

    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        data = _krx_session.get_admin_issue(date)
        if not data:
            return {"date": date, "count": 0, "data": []}

        items = data.get('output', data.get('OutBlock_1', []))
        return {"date": date, "count": len(items), "data": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/krx/by-screen")
def get_krx_by_screen(
    screen: str = Query(..., description="화면번호 (예: 12005)"),
    date: Optional[str] = Query(None, description="기준일 (YYYYMMDD)"),
    market: str = Query("STK", description="시장코드 (STK/KSQ/KNX)")
):
    """
    화면번호 기반 KRX 데이터 조회
    ⚠️ KRX 로그인 필요
    """
    if not _is_logged_in or not _krx_session:
        raise HTTPException(status_code=401, detail="KRX 로그인이 필요합니다.")

    try:
        if date is None:
            date = find_valid_trading_date("005930", 14)

        data = _krx_session.get_stock_by_bld(screen, date, market=market)
        if not data:
            return {"screen": screen, "date": date, "market": market, "data": None}

        return {"screen": screen, "date": date, "market": market, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/krx/bld-list")
def get_bld_list():
    """
    사용 가능한 BLD 엔드포인트 목록 조회

    BLD_ENDPOINTS 구조: {"이름": "dbms/MDC/STAT/.../MDCSTATXXXXX"}
    """
    if not _krx_session:
        return {"count": 0, "data": []}

    # 카테고리 매핑 (BLD 경로 기반)
    def get_category(bld_path: str) -> str:
        if "finder" in bld_path:
            return "종목검색"
        elif "srt" in bld_path:
            return "공매도"
        elif "MDCSTAT00" in bld_path:
            return "지수"
        elif "MDCSTAT01" in bld_path or "MDCSTAT02" in bld_path:
            return "주식시세"
        elif "MDCSTAT03" in bld_path:
            return "기업정보"
        elif "MDCSTAT04" in bld_path:
            return "ETF/ETN"
        elif "MDCSTAT12" in bld_path:
            return "파생상품"
        else:
            return "기타"

    result = []
    for name, bld_path in _krx_session.BLD_ENDPOINTS.items():
        result.append({
            "name": name,
            "bld": bld_path,
            "description": name,  # 이름 자체가 설명
            "category": get_category(bld_path)
        })

    return {"count": len(result), "data": result}


# ============================================================================
# 자연어 인텐트 분류 API
# ============================================================================

# 인텐트 분류기 초기화 (지연 로딩)
_intent_classifier = None

def get_intent_classifier():
    """인텐트 분류기 싱글톤"""
    global _intent_classifier
    if _intent_classifier is None:
        from intent_classifier import HybridIntentClassifier
        _intent_classifier = HybridIntentClassifier(
            keyword_threshold=0.7,
            embedding_threshold=0.6,
            enable_embedding=True,
            enable_llm=True
        )
    return _intent_classifier


@app.post("/api/natural-language")
async def process_natural_language(request: dict):
    """
    자연어 쿼리를 분석하여 적절한 API 호출

    Request Body:
        {"query": "삼성전자 오늘 주가 알려줘"}

    Response:
        {
            "intent": "stock_price",
            "confidence": 0.95,
            "method": "keyword",
            "endpoint": "/api/stocks/ohlcv",
            "parameters": {"ticker": "005930", "date": "20260120"},
            "latency_ms": 1.2,
            "data": {...}  // API 실행 결과 (선택)
        }
    """
    query = request.get("query", "")
    execute = request.get("execute", False)  # API 바로 실행 여부

    if not query:
        raise HTTPException(status_code=400, detail="query 파라미터 필요")

    classifier = get_intent_classifier()
    result = await classifier.classify(query)

    response = {
        "query": query,
        "intent": result.intent,
        "confidence": result.confidence,
        "method": result.method,
        "endpoint": result.endpoint,
        "parameters": result.parameters,
        "requires_login": result.requires_login,
        "latency_ms": result.latency_ms
    }

    # API 실행 요청 시
    if execute and result.intent != "unknown":
        try:
            exec_result = await execute_intent(result)
            response["executed"] = True
            response["result"] = exec_result
        except Exception as e:
            response["executed"] = True
            response["result"] = {"success": False, "error": str(e)}
    else:
        response["executed"] = False

    return response


async def execute_intent(result):
    """인텐트에 따라 API 실행하고 결과를 표준화된 형식으로 반환"""
    print(f"[execute_intent] ======= 함수 호출됨! intent={result.intent} =======")
    intent = result.intent
    params = result.parameters
    today = datetime.now().strftime("%Y%m%d")
    print(f"[execute_intent] params={params}, today={today}")

    try:
        # 주가 조회 (특정 종목)
        if intent == "stock_price":
            ticker = params.get("ticker")
            date = params.get("date", today)
            if ticker:
                df = stock.get_market_ohlcv(date, date, ticker)
                # 오늘 데이터가 없으면 (장 시작 전) 최근 30일에서 마지막 데이터 조회
                if df.empty:
                    from_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
                    df = stock.get_market_ohlcv(from_date, today, ticker)
                    if not df.empty:
                        df = df.tail(1)  # 가장 최근 1개
                if not df.empty:
                    df = df.reset_index()
                    # 종목명 추가
                    ticker_name = params.get("ticker_name", ticker)
                    df["종목명"] = ticker_name
                    return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            return {"success": False, "error": "티커 또는 데이터 없음"}

        # 시가총액 (특정 종목 또는 시장 전체)
        elif intent == "market_cap":
            ticker = params.get("ticker")
            market = params.get("market", "KOSPI")
            date = params.get("date", today)
            limit = params.get("limit", 20)

            # 지수 코드는 ticker로 처리하지 않음 (시장 전체 조회로 전환)
            INDEX_CODES = {'1001', '2001', '1028', '2203', '1150', '2150', '3003'}
            if ticker in INDEX_CODES:
                print(f"[market_cap] 지수 코드 {ticker} 감지 → 시장 전체 조회로 전환")
                ticker = None  # 시장 전체 조회로 전환

            if ticker:
                # 특정 종목 → OHLCV + 시가총액 데이터 조회
                df = stock.get_market_ohlcv(date, date, ticker)
                # 오늘 데이터가 없으면 최근 30일에서 마지막 데이터 조회
                if df.empty:
                    from_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
                    df = stock.get_market_ohlcv(from_date, today, ticker)
                    if not df.empty:
                        df = df.tail(1)
                        date = df.index[0].strftime("%Y%m%d") if hasattr(df.index[0], 'strftime') else date
                if not df.empty:
                    df = df.reset_index()
                    ticker_name = params.get("ticker_name", ticker)
                    df["종목명"] = ticker_name
                    df["티커"] = ticker
                    # 시가총액 추가 시도
                    try:
                        cap_df = stock.get_market_cap(date, date, ticker)
                        if not cap_df.empty:
                            df["시가총액"] = cap_df.iloc[0].get("시가총액", None)
                    except:
                        pass
                    return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            else:
                # 시장 전체 → safe 래퍼 사용 (인코딩 문제 해결)
                print(f"[market_cap] 조회 시도: date={date}, market={market}, limit={limit}")
                df = get_market_cap_safe(date, market=market, limit=limit)
                # 오늘 데이터가 없으면 최근 5일만 확인 (성능 최적화)
                if df.empty:
                    print(f"[market_cap] 오늘 데이터 없음, 5일 fallback 시작")
                    for i in range(1, 6):  # 1~5일 전까지만 확인
                        check_date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
                        print(f"[market_cap] fallback 시도: {check_date}")
                        df = get_market_cap_safe(check_date, market=market, limit=limit)
                        if not df.empty:
                            print(f"[market_cap] ✅ {check_date} 데이터 발견! ({len(df)}개)")
                            break
                if not df.empty:
                    return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            return {"success": False, "error": "데이터 없음"}

        # ETF 목록
        elif intent == "etf_list":
            date = params.get("date", today)
            limit = params.get("limit", 30)
            # 패치된 pykrx 사용 (인코딩 문제 해결됨)
            df = get_etf_list_safe(date, limit=limit)
            if not df.empty:
                return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            # 폴백: KRX API 직접 호출
            results = get_krx_etf_list_direct(date)
            if results:
                results = results[:limit]
                return {"success": True, "data": results, "count": len(results)}
            return {"success": False, "error": "데이터 없음"}

        # 지수 조회
        elif intent == "index_price":
            ticker = params.get("ticker", "1001")  # 기본: 코스피
            date = params.get("date", today)
            df = stock.get_index_ohlcv(date, date, ticker)
            # 오늘 데이터가 없으면 (장 시작 전) 최근 30일에서 마지막 데이터 조회
            if df.empty:
                from_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
                df = stock.get_index_ohlcv(from_date, today, ticker)
                if not df.empty:
                    df = df.tail(1)  # 가장 최근 1개
            if not df.empty:
                df = df.reset_index()
                # 지수명 추가
                index_name = params.get("index_name", ticker)
                df["지수명"] = index_name
                return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            return {"success": False, "error": "데이터 없음"}

        # 외국인/기관 보유
        elif intent == "foreign_holding":
            ticker = params.get("ticker")
            date = params.get("date", today)
            ticker_name = params.get("ticker_name", ticker)
            if ticker:
                try:
                    df = stock.get_exhaustion_rates_of_foreign_investment(date, date, ticker)
                    # 오늘 데이터가 없으면 최근 30일에서 마지막 데이터 조회
                    if df.empty:
                        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
                        df = stock.get_exhaustion_rates_of_foreign_investment(from_date, today, ticker)
                        if not df.empty:
                            df = df.tail(1)
                    if not df.empty:
                        df = df.reset_index()
                        df["종목명"] = ticker_name
                        return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
                except Exception as e:
                    # pykrx 오류 발생 시 OHLCV 데이터로 대체 (시가총액 기준)
                    print(f"⚠️ 외국인 보유율 API 오류: {e}")
                    try:
                        # 대안: 시가총액 데이터에서 외국인 보유 정보 추출
                        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
                        cap_df = stock.get_market_cap(from_date, today, ticker)
                        if not cap_df.empty:
                            cap_df = cap_df.tail(1).reset_index()
                            cap_df["종목명"] = ticker_name
                            # 외국인 소진율 정보가 없으므로 시가총액 정보만 반환
                            return {"success": True, "data": cap_df.to_dict(orient="records"), "count": len(cap_df),
                                    "note": "외국인 보유율 API 오류로 시가총액 정보만 제공됩니다"}
                    except:
                        pass
            return {"success": False, "error": "데이터 없음"}

        # PER/PBR 등 펀더멘털
        elif intent == "fundamental":
            ticker = params.get("ticker")
            market = params.get("market", "KOSPI")
            date = params.get("date", today)
            limit = params.get("limit", 20)
            if ticker:
                df = stock.get_market_fundamental(date, date, ticker)
                if not df.empty:
                    df = df.reset_index()
                    ticker_name = params.get("ticker_name", ticker)
                    df["종목명"] = ticker_name
                    return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            else:
                # safe 래퍼 사용 (인코딩 문제 해결)
                df = get_fundamental_safe(date, market=market, limit=limit)
                if not df.empty:
                    return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            return {"success": False, "error": "데이터 없음"}

        # 투자자별 매매동향
        elif intent == "investor_trading":
            ticker = params.get("ticker")
            date = params.get("date", today)
            if ticker:
                df = stock.get_market_trading_value_by_investor(date, date, ticker)
                if not df.empty:
                    df = df.reset_index()
                    ticker_name = params.get("ticker_name", ticker)
                    df["종목명"] = ticker_name
                    return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            return {"success": False, "error": "데이터 없음"}

        # 티커 검색 (종목명 → 티커 조회)
        elif intent == "ticker_search":
            # 이미 파라미터에 티커가 있으면 해당 종목 OHLCV 조회
            ticker = params.get("ticker")
            if ticker:
                df = stock.get_market_ohlcv(today, today, ticker)
                if not df.empty:
                    df = df.reset_index()
                    ticker_name = params.get("ticker_name", ticker)
                    df["종목명"] = ticker_name
                    return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            return {"success": False, "error": "티커 정보 없음. 종목명을 확인해주세요."}

        # ETF 가격
        elif intent == "etf_price":
            ticker = params.get("ticker")
            date = params.get("date", today)
            if ticker:
                df = stock.get_etf_ohlcv(date, date, ticker)
                if not df.empty:
                    df = df.reset_index()
                    ticker_name = params.get("ticker_name", ticker)
                    df["종목명"] = ticker_name
                    return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            return {"success": False, "error": "데이터 없음"}

        # ETN 목록
        elif intent == "etn_list":
            date = params.get("date", today)
            limit = params.get("limit", 30)
            # 패치된 pykrx 사용 (인코딩 문제 해결됨)
            df = get_etn_list_safe(date, limit=limit)
            if not df.empty:
                return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            # 폴백: KRX API 직접 호출
            results = get_krx_etn_list_direct(date)
            if results:
                results = results[:limit]
                return {"success": True, "data": results, "count": len(results)}
            return {"success": False, "error": "데이터 없음"}

        # ELW 목록
        elif intent == "elw_list":
            date = params.get("date", today)
            limit = params.get("limit", 30)
            # 패치된 pykrx 사용 (인코딩 문제 해결됨)
            df = get_elw_list_safe(date, limit=limit)
            if not df.empty:
                return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            # 폴백: KRX API 직접 호출
            results = get_krx_elw_list_direct(date)
            if results:
                results = results[:limit]
                return {"success": True, "data": results, "count": len(results)}
            return {"success": False, "error": "데이터 없음"}

        # 공매도
        elif intent == "short_selling":
            ticker = params.get("ticker")
            date = params.get("date", today)
            market = params.get("market", "KOSPI")
            if ticker:
                df = stock.get_shorting_volume_by_date(date, date, ticker)
                if not df.empty:
                    df = df.reset_index()
                    ticker_name = params.get("ticker_name", ticker)
                    df["종목명"] = ticker_name
                    return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            else:
                # 시장 전체 공매도
                df = stock.get_shorting_volume_top50(date, market)
                if not df.empty:
                    df = df.head(20).reset_index()
                    df.columns = ["티커"] + list(df.columns[1:])
                    return {"success": True, "data": df.to_dict(orient="records"), "count": len(df)}
            return {"success": False, "error": "데이터 없음"}

        # 기타: 엔드포인트 정보만 반환
        return {"success": False, "error": f"'{intent}' 인텐트 직접 실행 미지원. API: {result.endpoint}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/natural-language/intents")
def get_available_intents():
    """사용 가능한 인텐트 목록"""
    from intent_classifier import IntentConfig
    return {
        "count": len(IntentConfig.INTENTS),
        "intents": [
            {
                "id": intent_id,
                "keywords": config["keywords"][:5],
                "endpoint": config["endpoint"],
                "requires_login": config["requires_login"],
                "description": config.get("description", "")
            }
            for intent_id, config in IntentConfig.INTENTS.items()
        ]
    }


@app.get("/api/natural-language/tickers")
def get_ticker_dictionary():
    """티커 사전 조회"""
    from intent_classifier import IntentConfig
    return {
        "count": len(IntentConfig.TICKER_DICT),
        "tickers": IntentConfig.TICKER_DICT
    }


# ============================================================================
# 메인
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
