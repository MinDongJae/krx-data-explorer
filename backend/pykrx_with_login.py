"""
PyKRX + KRX 로그인 통합 모듈

기존 PyKRX 라이브러리에 로그인 세션을 주입하여
로그인이 필요한 모든 API를 사용 가능하게 함

사용법:
    from pykrx_with_login import login_and_patch, stock

    # 로그인 및 PyKRX 패치
    login_and_patch("user_id", "password")

    # 이제 PyKRX 정상 사용 가능
    df = stock.get_market_ohlcv("20250116")
    df = stock.get_market_fundamental("20250116")  # PER, PBR, 배당수익률
"""

from krx_session import KRXSession
from pykrx import stock
from pykrx.website.comm import webio


# 전역 세션 객체
_krx_session = None


def _patched_post_read(self, **params):
    """세션 쿠키가 포함된 requests.post"""
    import requests

    global _krx_session

    if _krx_session and _krx_session.logged_in:
        # 로그인된 세션 사용
        resp = _krx_session.session.post(self.url, headers=self.headers, data=params)
    else:
        # 기본 동작 (로그인 없이)
        resp = requests.post(self.url, headers=self.headers, data=params)

    return resp


def login_and_patch(user_id: str, password: str, force: bool = False) -> bool:
    """
    KRX 로그인 후 PyKRX 라이브러리 패치

    Args:
        user_id: KRX Data Marketplace 아이디
        password: 비밀번호
        force: 강제 재로그인

    Returns:
        로그인 성공 여부
    """
    global _krx_session

    # 세션 생성
    _krx_session = KRXSession(headless=True)

    # 로그인
    if not _krx_session.login(user_id, password, force=force):
        return False

    # PyKRX의 Post 클래스 패치
    webio.Post.read = _patched_post_read

    print("✅ PyKRX 패치 완료! 이제 모든 기능 사용 가능")
    return True


def get_session() -> KRXSession:
    """현재 세션 반환"""
    return _krx_session


def main():
    """테스트"""
    import sys

    if len(sys.argv) < 3:
        print("사용법: python pykrx_with_login.py <user_id> <password>")
        return

    user_id = sys.argv[1]
    password = sys.argv[2]

    # 로그인 및 패치
    if not login_and_patch(user_id, password):
        print("❌ 로그인 실패")
        return

    print("\n" + "="*60)
    print("🧪 PyKRX 기능 테스트")
    print("="*60)

    test_date = "20250116"

    # 1. OHLCV (기존에도 작동)
    print(f"\n1️⃣ get_market_ohlcv({test_date})...")
    try:
        df = stock.get_market_ohlcv(test_date)
        print(f"   ✅ 성공! {len(df)}개 종목")
        print(df.head(3).to_string())
    except Exception as e:
        print(f"   ❌ 실패: {e}")

    # 2. Fundamental (PER, PBR, 배당수익률) - 로그인 필요
    print(f"\n2️⃣ get_market_fundamental({test_date})...")
    try:
        df = stock.get_market_fundamental(test_date)
        print(f"   ✅ 성공! {len(df)}개 종목")
        print(df.head(3).to_string())
    except Exception as e:
        print(f"   ❌ 실패: {e}")

    # 3. 시가총액
    print(f"\n3️⃣ get_market_cap({test_date})...")
    try:
        df = stock.get_market_cap(test_date)
        print(f"   ✅ 성공! {len(df)}개 종목")
        print(df.head(3).to_string())
    except Exception as e:
        print(f"   ❌ 실패: {e}")

    # 4. 외국인/기관 순매수
    print(f"\n4️⃣ get_market_net_purchases_of_equities({test_date})...")
    try:
        df = stock.get_market_net_purchases_of_equities(test_date, test_date, "KOSPI")
        print(f"   ✅ 성공! {len(df)}개 종목")
        print(df.head(3).to_string())
    except Exception as e:
        print(f"   ❌ 실패: {e}")

    # 5. 종목별 투자자 매매동향
    print(f"\n5️⃣ get_market_trading_value_by_investor({test_date})...")
    try:
        df = stock.get_market_trading_value_by_investor(test_date, test_date, "005930")
        print(f"   ✅ 성공!")
        print(df.to_string())
    except Exception as e:
        print(f"   ❌ 실패: {e}")

    print("\n" + "="*60)
    print("✅ 테스트 완료!")


if __name__ == "__main__":
    main()
