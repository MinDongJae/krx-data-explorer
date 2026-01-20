"""
KRX Data Marketplace 로그인 세션 관리
Selenium 기반 E2E 암호화 우회 로그인 + 세션 쿠키 추출

역공학 분석 결과:
- KRX는 NPPFS (Non-Plugin Free Solution) 키보드 보안 사용
- 비밀번호가 E2E 암호화되어 전송됨 (__E2E_RESULT__ 필드)
- 직접 requests로 로그인 불가 → Selenium으로 실제 브라우저 로그인 필요
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import os
import time
import json
import pickle
import requests
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("⚠️ Selenium not installed. Run: pip install selenium")

# 쿠키 저장 경로
COOKIE_FILE = Path(__file__).parent / ".krx_cookies.pkl"
SESSION_FILE = Path(__file__).parent / ".krx_session.json"


class KRXSession:
    """
    KRX Data Marketplace 세션 관리 클래스

    사용법:
        session = KRXSession()
        session.login("user_id", "password")
        data = session.get_market_data("MDCSTAT01501", {"mktId": "STK", "trdDd": "20250117"})
    """

    BASE_URL = "https://data.krx.co.kr"
    LOGIN_URL = f"{BASE_URL}/contents/MDC/COMS/client/MDCCOMS001.cmd"
    DATA_URL = f"{BASE_URL}/comm/bldAttendant/getJsonData.cmd"

    # BLD 엔드포인트 매핑 (150%+ Coverage - 40+ endpoints)
    BLD_ENDPOINTS = {
        # ============================================================
        # 1. 종목 검색 (로그인 불필요)
        # ============================================================
        "상장종목검색": "dbms/comm/finder/finder_stkisu",
        "ETF종목검색": "dbms/comm/finder/finder_etfisu",
        "ETN종목검색": "dbms/comm/finder/finder_etnisu",
        "ELW종목검색": "dbms/comm/finder/finder_elwisu",

        # ============================================================
        # 2. 주식 시세 (화면번호: 10XXX)
        # ============================================================
        "전종목시세": "dbms/MDC/STAT/standard/MDCSTAT01501",           # 10501
        "개별종목시세": "dbms/MDC/STAT/standard/MDCSTAT01701",         # 10701
        "개별종목시세_일별": "dbms/MDC/STAT/standard/MDCSTAT01601",    # 10601
        "기간별시세": "dbms/MDC/STAT/standard/MDCSTAT01801",           # 10801
        "호가잔량": "dbms/MDC/STAT/standard/MDCSTAT01901",             # 10901
        "시간별체결": "dbms/MDC/STAT/standard/MDCSTAT02001",           # 20001
        "프로그램매매_종목별": "dbms/MDC/STAT/standard/MDCSTAT02101",  # 20101

        # ============================================================
        # 3. 기업 정보/펀더멘털 (화면번호: 35XXX)
        # ============================================================
        "PER_PBR_배당수익률": "dbms/MDC/STAT/standard/MDCSTAT03501",   # 35001
        "배당정보": "dbms/MDC/STAT/standard/MDCSTAT03502",             # 35002
        "상장법인_재무정보": "dbms/MDC/STAT/standard/MDCSTAT03901",    # 39001
        "시가총액_상위": "dbms/MDC/STAT/standard/MDCSTAT03401",        # 34001

        # ============================================================
        # 4. 투자자별 거래 (화면번호: 22XXX)
        # ============================================================
        "투자자별_거래실적": "dbms/MDC/STAT/standard/MDCSTAT02201",    # 22001
        "투자자별_거래실적_일별": "dbms/MDC/STAT/standard/MDCSTAT02202", # 22002
        "투자자별_순매수_상위": "dbms/MDC/STAT/standard/MDCSTAT02203", # 22003
        "외국인_순매수_상위": "dbms/MDC/STAT/standard/MDCSTAT02204",   # 22004

        # ============================================================
        # 5. 외국인 보유/거래 (화면번호: 37XXX)
        # ============================================================
        "외국인보유량": "dbms/MDC/STAT/standard/MDCSTAT03701",         # 37001
        "외국인보유량_추이": "dbms/MDC/STAT/standard/MDCSTAT03702",    # 37002
        "외국인한도소진율": "dbms/MDC/STAT/standard/MDCSTAT03703",     # 37003

        # ============================================================
        # 6. 공매도 (화면번호: 30XXX)
        # ============================================================
        "공매도_종합정보": "dbms/MDC/STAT/srt/MDCSTAT30001",           # 30001
        "공매도_거래_종목별": "dbms/MDC/STAT/srt/MDCSTAT30101",        # 30101
        "공매도_잔고_종목별": "dbms/MDC/STAT/srt/MDCSTAT30201",        # 30201
        "대차거래_종목별": "dbms/MDC/STAT/srt/MDCSTAT30301",           # 30301

        # ============================================================
        # 7. 지수 (화면번호: 00XXX)
        # ============================================================
        "지수_전체": "dbms/MDC/STAT/standard/MDCSTAT00101",            # 00101
        "지수_개별": "dbms/MDC/STAT/standard/MDCSTAT00301",            # 00301
        "지수_구성종목": "dbms/MDC/STAT/standard/MDCSTAT00601",        # 00601
        "지수_시계열": "dbms/MDC/STAT/standard/MDCSTAT00401",          # 00401

        # ============================================================
        # 8. ETF/ETN (화면번호: 80XXX)
        # ============================================================
        "ETF_전종목시세": "dbms/MDC/STAT/standard/MDCSTAT04301",       # 43001
        "ETF_추적오차율": "dbms/MDC/STAT/standard/MDCSTAT04302",       # 43002
        "ETF_괴리율_추이": "dbms/MDC/STAT/standard/MDCSTAT04303",      # 43003
        "ETN_전종목시세": "dbms/MDC/STAT/standard/MDCSTAT04401",       # 44001
        "ETN_투자지표": "dbms/MDC/STAT/standard/MDCSTAT04402",         # 44002

        # ============================================================
        # 9. 파생상품 (화면번호: 50XXX)
        # ============================================================
        "선물_전종목시세": "dbms/MDC/STAT/standard/MDCSTAT12101",      # 12101
        "선물_일별거래": "dbms/MDC/STAT/standard/MDCSTAT12201",        # 12201
        "옵션_전종목시세": "dbms/MDC/STAT/standard/MDCSTAT12301",      # 12301
        "옵션_일별거래": "dbms/MDC/STAT/standard/MDCSTAT12401",        # 12401

        # ============================================================
        # 10. 업종 (화면번호: 02XXX)
        # ============================================================
        "업종_전체시세": "dbms/MDC/STAT/standard/MDCSTAT02301",        # 02301
        "업종_투자자별": "dbms/MDC/STAT/standard/MDCSTAT02401",        # 02401
        "업종_시계열": "dbms/MDC/STAT/standard/MDCSTAT02501",          # 02501

        # ============================================================
        # 11. 신용거래/대용 (화면번호: 31XXX)
        # ============================================================
        "신용거래_종목별": "dbms/MDC/STAT/standard/MDCSTAT03101",      # 31001
        "신용거래_일별추이": "dbms/MDC/STAT/standard/MDCSTAT03102",    # 31002

        # ============================================================
        # 12. 거래정지/관리종목
        # ============================================================
        "거래정지종목": "dbms/MDC/STAT/standard/MDCSTAT01901",         # 19001
        "관리종목": "dbms/MDC/STAT/standard/MDCSTAT03601",             # 36001
    }

    def __init__(self, headless: bool = True):
        """
        Args:
            headless: 브라우저 창 숨김 여부 (기본: True)
        """
        self.headless = headless
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": self.BASE_URL
        })
        self.logged_in = False
        self.login_time: Optional[datetime] = None
        self.mbr_no: Optional[str] = None

        # 저장된 세션 복원 시도
        self._load_session()

    def _load_session(self) -> bool:
        """저장된 세션 쿠키 로드"""
        if COOKIE_FILE.exists() and SESSION_FILE.exists():
            try:
                # 세션 정보 확인
                with open(SESSION_FILE, 'r') as f:
                    session_info = json.load(f)

                login_time = datetime.fromisoformat(session_info.get('login_time', ''))
                # 세션 유효 시간: 1시간 (KRX mdc.client_session 쿠키 기준 ~50분)
                if datetime.now() - login_time < timedelta(hours=1):
                    # 쿠키 로드
                    with open(COOKIE_FILE, 'rb') as f:
                        cookies = pickle.load(f)

                    for cookie in cookies:
                        self.session.cookies.set(cookie['name'], cookie['value'])

                    self.logged_in = True
                    self.login_time = login_time
                    self.mbr_no = session_info.get('mbr_no')
                    print(f"✅ 저장된 세션 복원 완료 (로그인: {login_time.strftime('%H:%M:%S')})")
                    return True
            except Exception as e:
                print(f"⚠️ 세션 복원 실패: {e}")

        return False

    def _save_session(self, cookies: list):
        """세션 쿠키 저장"""
        try:
            with open(COOKIE_FILE, 'wb') as f:
                pickle.dump(cookies, f)

            with open(SESSION_FILE, 'w') as f:
                json.dump({
                    'login_time': self.login_time.isoformat(),
                    'mbr_no': self.mbr_no
                }, f)

            print(f"✅ 세션 저장 완료: {COOKIE_FILE}")
        except Exception as e:
            print(f"⚠️ 세션 저장 실패: {e}")

    def login(self, user_id: str, password: str, force: bool = False) -> bool:
        """
        KRX 로그인 (Selenium 사용)

        Args:
            user_id: KRX Data Marketplace 아이디
            password: 비밀번호
            force: 강제 재로그인 여부

        Returns:
            로그인 성공 여부
        """
        if not SELENIUM_AVAILABLE:
            raise RuntimeError("Selenium이 설치되지 않았습니다. pip install selenium")

        # 이미 로그인된 경우
        if self.logged_in and not force:
            print("✅ 이미 로그인된 상태입니다.")
            return True

        print(f"🔐 KRX 로그인 시도: {user_id}")

        # Chrome 옵션 설정
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

        driver = None
        try:
            driver = webdriver.Chrome(options=options)
            wait = WebDriverWait(driver, 20)

            # 1. 로그인 페이지 접속
            print("   → 로그인 페이지 접속...")
            driver.get(self.LOGIN_URL)
            time.sleep(2)

            # 2. iframe 내부로 전환
            print("   → 로그인 폼 대기...")
            iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
            driver.switch_to.frame(iframe)

            # 3. 로그인 폼 입력
            print("   → 자격 증명 입력...")

            # ID 입력
            id_input = wait.until(EC.presence_of_element_located((By.NAME, "mbrId")))
            id_input.clear()
            id_input.send_keys(user_id)
            time.sleep(0.5)

            # 비밀번호 입력 (E2E 암호화를 위해 직접 입력)
            pw_input = driver.find_element(By.NAME, "pw")
            pw_input.clear()
            # 한 글자씩 입력 (키보드 보안 우회)
            for char in password:
                pw_input.send_keys(char)
                time.sleep(0.05)

            time.sleep(1)

            # 4. 로그인 버튼 클릭
            print("   → 로그인 버튼 클릭...")
            login_btn = driver.find_element(By.CSS_SELECTOR, ".jsLoginBtn")
            login_btn.click()

            # 5. 로그인 결과 확인 (최대 10초 대기)
            time.sleep(3)

            # iframe에서 나와서 메인 페이지 확인
            driver.switch_to.default_content()

            # 쿠키 확인
            cookies = driver.get_cookies()
            jsessionid = None
            for cookie in cookies:
                if cookie['name'] == 'JSESSIONID':
                    jsessionid = cookie['value']
                    break

            if jsessionid:
                # 로그인 성공
                print(f"✅ 로그인 성공! JSESSIONID: {jsessionid[:20]}...")

                # requests 세션에 쿠키 적용
                self.session.cookies.clear()
                for cookie in cookies:
                    self.session.cookies.set(cookie['name'], cookie['value'])

                self.logged_in = True
                self.login_time = datetime.now()

                # 세션 저장
                self._save_session(cookies)

                return True
            else:
                # 로그인 실패 - 에러 메시지 확인
                try:
                    driver.switch_to.frame(iframe)
                    error_elem = driver.find_element(By.CSS_SELECTOR, ".error-msg, .alert")
                    print(f"❌ 로그인 실패: {error_elem.text}")
                except:
                    print("❌ 로그인 실패: 알 수 없는 오류")

                return False

        except TimeoutException:
            print("❌ 로그인 타임아웃: 페이지 로딩 실패")
            return False
        except Exception as e:
            print(f"❌ 로그인 오류: {e}")
            return False
        finally:
            if driver:
                driver.quit()

    def get_market_data(self, bld: str, params: Dict[str, Any]) -> Optional[Dict]:
        """
        KRX API 데이터 조회

        Args:
            bld: BLD 엔드포인트 (예: "dbms/MDC/STAT/standard/MDCSTAT01501")
            params: API 파라미터

        Returns:
            API 응답 데이터 (dict) 또는 None
        """
        if not self.logged_in:
            print("⚠️ 로그인이 필요합니다.")
            return None

        data = {
            "bld": bld,
            **params
        }

        try:
            response = self.session.post(self.DATA_URL, data=data)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"❌ API 호출 실패: {e}")
            return None

    def get_all_stocks(self, date: str, market: str = "STK") -> Optional[Dict]:
        """
        전종목 시세 조회

        Args:
            date: 조회일 (YYYYMMDD)
            market: 시장 구분 (STK: 유가증권, KSQ: 코스닥, KNX: 코넥스)
        """
        return self.get_market_data(
            self.BLD_ENDPOINTS["전종목시세"],
            {
                "mktId": market,
                "trdDd": date,
                "share": "1",
                "money": "1"
            }
        )

    def get_per_pbr_div(self, date: str, market: str = "STK") -> Optional[Dict]:
        """
        PER/PBR/배당수익률 조회

        Args:
            date: 조회일 (YYYYMMDD)
            market: 시장 구분 (STK: 유가증권, KSQ: 코스닥)
        """
        return self.get_market_data(
            self.BLD_ENDPOINTS["PER_PBR_배당수익률"],
            {
                "mktId": market,
                "trdDd": date,
                "searchType": "1"  # 전체 조회
            }
        )

    def get_investor_trading(self, date: str, market: str = "STK") -> Optional[Dict]:
        """
        투자자별 거래실적 조회

        Args:
            date: 조회일 (YYYYMMDD)
            market: 시장 구분
        """
        return self.get_market_data(
            self.BLD_ENDPOINTS["투자자별_거래실적"],
            {
                "mktId": market,
                "trdDd": date,
                "inqTpCd": "1",
                "trdVolVal": "1",
                "askBid": "3",
                "share": "1"
            }
        )

    def get_foreign_holding(self, date: str, market: str = "STK") -> Optional[Dict]:
        """
        외국인 보유량 조회

        Args:
            date: 조회일 (YYYYMMDD)
            market: 시장 구분 (STK: 유가증권, KSQ: 코스닥)
        """
        return self.get_market_data(
            self.BLD_ENDPOINTS["외국인보유량"],
            {
                "mktId": market,
                "trdDd": date,
                "inqTpCd": "1",  # 조회 유형
                "share": "1"
            }
        )

    def get_short_selling(self, date: str, market: str = "STK") -> Optional[Dict]:
        """
        공매도 종합정보 조회

        Args:
            date: 조회일 (YYYYMMDD)
            market: 시장 구분
        """
        return self.get_market_data(
            self.BLD_ENDPOINTS["공매도_종합정보"],
            {
                "mktTpCd": "0" if market == "STK" else "1",
                "trdDd": date,
                "inqCondTpCd": "1"
            }
        )

    # ============================================================
    # 추가 API 메서드들 (150%+ Coverage)
    # ============================================================

    def get_etf_data(self, date: str) -> Optional[Dict]:
        """ETF 전종목 시세 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["ETF_전종목시세"],
            {"trdDd": date}
        )

    def get_etn_data(self, date: str) -> Optional[Dict]:
        """ETN 전종목 시세 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["ETN_전종목시세"],
            {"trdDd": date}
        )

    def get_futures_data(self, date: str) -> Optional[Dict]:
        """선물 전종목 시세 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["선물_전종목시세"],
            {"trdDd": date, "prodId": "KRDRVFUK2I"}  # KOSPI200 선물
        )

    def get_options_data(self, date: str) -> Optional[Dict]:
        """옵션 전종목 시세 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["옵션_전종목시세"],
            {"trdDd": date, "prodId": "KRDRVOPK2I"}  # KOSPI200 옵션
        )

    def get_sector_data(self, date: str, market: str = "STK") -> Optional[Dict]:
        """업종별 시세 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["업종_전체시세"],
            {"mktId": market, "trdDd": date}
        )

    def get_index_list(self, date: str, market: str = "STK") -> Optional[Dict]:
        """지수 목록 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["지수_전체"],
            {"idxIndMidclssCd": "01" if market == "STK" else "03", "trdDd": date}
        )

    def get_index_ohlcv(self, date: str, idx_code: str) -> Optional[Dict]:
        """개별 지수 시세 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["지수_개별"],
            {"trdDd": date, "indIdx": idx_code}
        )

    def get_index_components(self, date: str, idx_code: str) -> Optional[Dict]:
        """지수 구성종목 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["지수_구성종목"],
            {"trdDd": date, "indIdx": idx_code}
        )

    def get_short_selling_by_stock(self, date: str, market: str = "STK") -> Optional[Dict]:
        """공매도 거래 종목별 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["공매도_거래_종목별"],
            {"mktTpCd": "0" if market == "STK" else "1", "trdDd": date}
        )

    def get_short_selling_balance(self, date: str, market: str = "STK") -> Optional[Dict]:
        """공매도 잔고 종목별 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["공매도_잔고_종목별"],
            {"mktTpCd": "0" if market == "STK" else "1", "trdDd": date}
        )

    def get_lending_data(self, date: str, market: str = "STK") -> Optional[Dict]:
        """대차거래 종목별 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["대차거래_종목별"],
            {"mktTpCd": "0" if market == "STK" else "1", "trdDd": date}
        )

    def get_credit_trading(self, date: str, market: str = "STK") -> Optional[Dict]:
        """신용거래 종목별 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["신용거래_종목별"],
            {"mktId": market, "trdDd": date}
        )

    def get_program_trading(self, date: str, market: str = "STK") -> Optional[Dict]:
        """프로그램매매 종목별 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["프로그램매매_종목별"],
            {"mktId": market, "trdDd": date}
        )

    def get_orderbook(self, ticker: str) -> Optional[Dict]:
        """호가잔량 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["호가잔량"],
            {"isuCd": ticker}
        )

    def get_dividend_info(self, date: str, market: str = "STK") -> Optional[Dict]:
        """배당정보 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["배당정보"],
            {"mktId": market, "trdDd": date}
        )

    def get_market_cap_ranking(self, date: str, market: str = "STK") -> Optional[Dict]:
        """시가총액 상위 종목 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["시가총액_상위"],
            {"mktId": market, "trdDd": date}
        )

    def get_trading_halt(self, date: str) -> Optional[Dict]:
        """거래정지 종목 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["거래정지종목"],
            {"trdDd": date}
        )

    def get_admin_issue(self, date: str) -> Optional[Dict]:
        """관리종목 조회"""
        return self.get_market_data(
            self.BLD_ENDPOINTS["관리종목"],
            {"trdDd": date}
        )

    def get_stock_by_bld(self, bld_name: str, params: Dict[str, Any]) -> Optional[Dict]:
        """
        BLD 엔드포인트 이름으로 직접 조회 (화면번호 기반)

        Args:
            bld_name: BLD 엔드포인트 이름 (예: "전종목시세", "PER_PBR_배당수익률")
            params: API 파라미터

        Returns:
            API 응답 데이터
        """
        if bld_name not in self.BLD_ENDPOINTS:
            available = ', '.join(self.BLD_ENDPOINTS.keys())
            print(f"❌ 알 수 없는 BLD: {bld_name}")
            print(f"   사용 가능: {available}")
            return None

        return self.get_market_data(self.BLD_ENDPOINTS[bld_name], params)


def main():
    """테스트 실행"""
    import sys

    if len(sys.argv) < 3:
        print("사용법: python krx_session.py <user_id> <password>")
        print("예: python krx_session.py goguma 비밀번호123")
        return

    user_id = sys.argv[1]
    password = sys.argv[2]

    # 세션 생성 및 로그인
    krx = KRXSession(headless=False)  # 디버깅용으로 브라우저 표시

    if krx.login(user_id, password):
        print("\n" + "="*50)
        print("🧪 API 테스트 시작")
        print("="*50)

        # 테스트 날짜
        test_date = "20250116"

        # 1. 전종목 시세
        print(f"\n1️⃣ 전종목 시세 ({test_date})...")
        data = krx.get_all_stocks(test_date)
        if data:
            print(f"   ✅ 성공! {len(data.get('OutBlock_1', []))}개 종목")
        else:
            print("   ❌ 실패")

        # 2. PER/PBR/배당수익률
        print(f"\n2️⃣ PER/PBR/배당수익률 ({test_date})...")
        data = krx.get_per_pbr_div(test_date)
        if data:
            # 응답 키: 'output' 또는 'OutBlock_1'
            items = data.get('output', data.get('OutBlock_1', []))
            print(f"   ✅ 성공! {len(items)}개 종목")
            if items:
                sample = items[0]
                print(f"   샘플: {sample.get('ISU_ABBRV', '')} PER={sample.get('PER', 'N/A')} PBR={sample.get('PBR', 'N/A')}")
        else:
            print("   ❌ 실패")

        # 3. 투자자별 거래실적
        print(f"\n3️⃣ 투자자별 거래실적 ({test_date})...")
        data = krx.get_investor_trading(test_date)
        if data:
            print(f"   ✅ 성공!")
            print(f"   데이터: {json.dumps(data, ensure_ascii=False)[:200]}...")
        else:
            print("   ❌ 실패")

        # 4. 외국인 보유량
        print(f"\n4️⃣ 외국인 보유량 ({test_date})...")
        data = krx.get_foreign_holding(test_date)
        if data:
            items = data.get('output', data.get('OutBlock_1', []))
            print(f"   ✅ 성공! {len(items)}개 종목")
            if items:
                sample = items[0]
                print(f"   샘플: {sample.get('ISU_ABBRV', '')} 보유량={sample.get('FORN_HD_QTY', 'N/A')}")
        else:
            print("   ❌ 실패")

        print("\n" + "="*50)
        print("✅ 테스트 완료!")
    else:
        print("❌ 로그인 실패. 자격 증명을 확인해주세요.")


if __name__ == "__main__":
    main()
