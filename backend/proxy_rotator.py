"""
PyKRX 프록시 로테이션 + 네이버 소스 활용 모듈
==============================================
- IP 차단 방지를 위해 프록시를 자동으로 돌려가며 사용
- 네이버 소스(adjusted=True)로 로그인 없이 OHLCV 데이터 수집
- KRX 소스에도 프록시 적용하여 IP 차단 회피
"""

import requests
import itertools
import threading
import time
import logging
from typing import Optional
from fp.fp import FreeProxy

logger = logging.getLogger(__name__)


class ProxyPool:
    """
    프록시 풀 관리자
    (수영장처럼 여러 프록시를 모아두고 돌려가며 쓰는 것)
    """

    def __init__(self, min_proxies: int = 5, max_proxies: int = 15):
        self.min_proxies = min_proxies
        self.max_proxies = max_proxies
        self.proxies: list[str] = []
        self.failed: set[str] = set()  # 실패한 프록시 블랙리스트
        self._cycle: Optional[itertools.cycle] = None

    def collect(self, count: Optional[int] = None) -> list[str]:
        """무료 프록시를 자동 수집 (인터넷에서 사용 가능한 프록시 찾기)"""
        target = count or self.max_proxies
        collected = []

        logger.info(f"프록시 수집 시작 (목표: {target}개)...")

        for _ in range(target * 4):  # 실패 감안해서 4배 시도
            try:
                proxy = FreeProxy(timeout=1, rand=True).get()
                if proxy and proxy not in collected and proxy not in self.failed:
                    # 프록시가 실제로 작동하는지 빠르게 테스트
                    if self._test_proxy(proxy):
                        collected.append(proxy)
                        logger.info(f"  프록시 확보: {proxy} ({len(collected)}/{target})")
                    if len(collected) >= target:
                        break
            except Exception:
                continue

        self.proxies = collected
        self._cycle = itertools.cycle(self.proxies) if self.proxies else None
        logger.info(f"프록시 수집 완료: {len(self.proxies)}개")
        return self.proxies

    def _test_proxy(self, proxy: str, timeout: float = 3) -> bool:
        """프록시가 실제로 작동하는지 테스트"""
        try:
            resp = requests.get(
                "http://httpbin.org/ip",
                proxies={"http": proxy, "https": proxy},
                timeout=timeout,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def next(self) -> dict:
        """다음 프록시를 가져옴 (돌려가며 사용)"""
        if not self._cycle:
            return {}  # 프록시 없으면 직접 연결
        proxy = next(self._cycle)
        return {"http": proxy, "https": proxy}

    def mark_failed(self, proxy_dict: dict):
        """실패한 프록시를 블랙리스트에 추가"""
        proxy = proxy_dict.get("http", "")
        if proxy:
            self.failed.add(proxy)
            if proxy in self.proxies:
                self.proxies.remove(proxy)
            # 프록시가 부족하면 자동 보충
            if len(self.proxies) < self.min_proxies:
                logger.warning(f"프록시 부족 ({len(self.proxies)}개). 자동 보충 중...")
                self.collect(self.min_proxies)
            self._cycle = itertools.cycle(self.proxies) if self.proxies else None

    @property
    def count(self) -> int:
        return len(self.proxies)

    @property
    def is_ready(self) -> bool:
        return len(self.proxies) >= self.min_proxies


class PyKRXProxyPatcher:
    """
    PyKRX 라이브러리에 프록시를 끼워넣는 패처
    (PyKRX가 인터넷 요청할 때 우리가 지정한 프록시를 사용하도록 변경)
    """

    def __init__(self, proxy_pool: ProxyPool):
        self.pool = proxy_pool
        self._patched = False
        self._original_get_read = None
        self._original_post_read = None

    # pykrx 1.0.51은 http://data.krx.co.kr/ 를 사용하지만,
    # KRX가 HTTPS + outerLoader Referer를 요구하도록 변경됨 (1.2.4 기준)
    # → URL과 Referer를 강제로 최신 방식으로 패치
    KRX_HTTPS_REFERER = "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd"

    def _fix_url(self, url: str) -> str:
        """http://data.krx.co.kr → https://data.krx.co.kr 변환"""
        if url and url.startswith("http://data.krx.co.kr"):
            return url.replace("http://data.krx.co.kr", "https://data.krx.co.kr", 1)
        return url

    def _fix_headers(self, headers: dict) -> dict:
        """Referer를 최신 outerLoader URL로 교체"""
        headers = dict(headers) if headers else {}
        headers["Referer"] = self.KRX_HTTPS_REFERER
        return headers

    def patch(self):
        """PyKRX의 HTTP 요청에 HTTPS 패치 + 프록시를 주입"""
        if self._patched:
            return

        from pykrx.website.comm import webio
        from pykrx.website.krx import krxio

        # 원본 메서드 백업 (나중에 복원할 수 있도록)
        self._original_get_read = webio.Get.read
        self._original_post_read = webio.Post.read

        pool = self.pool  # 클로저에서 참조
        patcher = self  # HTTPS 패치 메서드 참조

        # KrxWebIo.url과 KrxFutureIo.url도 HTTPS로 패치
        krxio.KrxWebIo.url = property(
            lambda self: "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
        )
        krxio.KrxFutureIo.url = property(
            lambda self: "https://data.krx.co.kr/comm/bldAttendant/executeForResourceBundle.cmd"
        )

        def proxied_get_read(wio_self, **params):
            """GET 요청에 HTTPS + 프록시를 끼워넣음"""
            url = patcher._fix_url(wio_self.url)
            headers = patcher._fix_headers(wio_self.headers)
            max_retries = 3
            for attempt in range(max_retries):
                proxy_dict = pool.next()
                try:
                    resp = requests.get(
                        url,
                        headers=headers,
                        params=params,
                        proxies=proxy_dict if proxy_dict else None,
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        return resp
                    if resp.status_code in (403, 429, 503):
                        logger.warning(f"IP 차단 감지 (GET {resp.status_code}), 프록시 교체...")
                        pool.mark_failed(proxy_dict)
                        time.sleep(1)
                        continue
                    return resp
                except (requests.exceptions.ProxyError,
                        requests.exceptions.ConnectTimeout,
                        requests.exceptions.ConnectionError) as e:
                    logger.warning(f"프록시 실패: {e}")
                    pool.mark_failed(proxy_dict)
                    continue
            logger.warning("모든 프록시 실패, 직접 연결 시도...")
            return requests.get(url, headers=headers, params=params, timeout=30)

        def proxied_post_read(wio_self, **params):
            """POST 요청에 HTTPS + 프록시를 끼워넣음"""
            url = patcher._fix_url(wio_self.url)
            headers = patcher._fix_headers(wio_self.headers)
            logger.debug(f"KRX POST → {url} (params keys: {list(params.keys())[:5]})")
            max_retries = 3
            for attempt in range(max_retries):
                proxy_dict = pool.next()
                try:
                    resp = requests.post(
                        url,
                        headers=headers,
                        data=params,
                        proxies=proxy_dict if proxy_dict else None,
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        return resp
                    if resp.status_code in (403, 429, 503):
                        logger.warning(f"IP 차단 감지 (POST {resp.status_code}), 프록시 교체...")
                        pool.mark_failed(proxy_dict)
                        time.sleep(1)
                        continue
                    return resp
                except (requests.exceptions.ProxyError,
                        requests.exceptions.ConnectTimeout,
                        requests.exceptions.ConnectionError) as e:
                    logger.warning(f"프록시 실패: {e}")
                    pool.mark_failed(proxy_dict)
                    continue
            logger.warning("모든 프록시 실패, 직접 연결 시도...")
            return requests.post(url, headers=headers, data=params, timeout=30)

        webio.Get.read = proxied_get_read
        webio.Post.read = proxied_post_read
        self._patched = True
        logger.info("PyKRX HTTPS + 프록시 패치 완료 (outerLoader Referer 적용)")

    def unpatch(self):
        """원래대로 복원"""
        if not self._patched:
            return
        from pykrx.website.comm import webio
        webio.Get.read = self._original_get_read
        webio.Post.read = self._original_post_read
        self._patched = False
        logger.info("PyKRX 프록시 패치 해제")


# ============================================================================
# 전역 싱글톤 (앱 전체에서 하나만 사용)
# ============================================================================

_proxy_pool: Optional[ProxyPool] = None
_patcher: Optional[PyKRXProxyPatcher] = None


def init_proxy_rotation(min_proxies: int = 3, max_proxies: int = 10) -> ProxyPool:
    """
    프록시 로테이션 초기화
    - 프록시 패치는 즉시 적용 (프록시 없으면 직접 연결)
    - 프록시 수집은 백그라운드에서 진행 (서버 시작을 막지 않음)
    """
    global _proxy_pool, _patcher

    _proxy_pool = ProxyPool(min_proxies=min_proxies, max_proxies=max_proxies)

    # 패치 먼저 적용 (프록시 없어도 직접 연결로 동작)
    _patcher = PyKRXProxyPatcher(_proxy_pool)
    _patcher.patch()

    # 프록시 수집은 백그라운드에서 (서버 즉시 시작)
    def _bg_collect():
        _proxy_pool.collect()
        logger.info(f"백그라운드 프록시 수집 완료: {_proxy_pool.count}개")

    thread = threading.Thread(target=_bg_collect, daemon=True)
    thread.start()

    return _proxy_pool


def get_proxy_pool() -> Optional[ProxyPool]:
    return _proxy_pool


def get_proxy_status() -> dict:
    """현재 프록시 상태 정보"""
    if not _proxy_pool:
        return {"enabled": False, "count": 0, "ready": False}
    return {
        "enabled": True,
        "count": _proxy_pool.count,
        "ready": _proxy_pool.is_ready,
        "failed_count": len(_proxy_pool.failed),
        "proxies": _proxy_pool.proxies[:3],  # 처음 3개만 노출
    }
