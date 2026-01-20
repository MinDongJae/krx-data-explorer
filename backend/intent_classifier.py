"""
하이브리드 인텐트 분류기 (Hybrid Intent Classifier)
=====================================

3단계 폴백 시스템:
1. 키워드 매칭 (0ms) - 90% 쿼리 처리
2. 임베딩 유사도 (~100ms) - 애매한 표현
3. LLM 분류 (~1s) - 복잡한 쿼리

사용법:
    classifier = HybridIntentClassifier()
    result = await classifier.classify("삼성전자 오늘 주가 알려줘")
    # {'intent': 'stock_price', 'confidence': 0.95, 'method': 'keyword', ...}
"""

import json
import re
import os
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio

# 임베딩용 (선택적)
try:
    import numpy as np
    from sentence_transformers import SentenceTransformer
    EMBEDDING_AVAILABLE = True
except ImportError:
    EMBEDDING_AVAILABLE = False
    print("⚠️ sentence-transformers 미설치 - 임베딩 기반 분류 비활성화")

# LLM용 (선택적)
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("⚠️ google-generativeai 미설치 - LLM 분류 비활성화")


@dataclass
class ClassificationResult:
    """분류 결과"""
    intent: str
    confidence: float
    method: str  # 'keyword', 'embedding', 'llm'
    parameters: Dict[str, Any] = field(default_factory=dict)
    endpoint: str = ""
    requires_login: bool = False
    latency_ms: float = 0.0


class IntentConfig:
    """인텐트 설정 - api_schema.json 기반"""

    INTENTS = {
        # 주식 기본
        "stock_price": {
            "keywords": ["주가", "종가", "시세", "ohlcv", "가격", "얼마", "시가", "고가", "저가", "거래량"],
            "endpoint": "/api/stocks/ohlcv",
            "requires_login": False,
            "parameters": ["ticker", "start_date", "end_date"],
            "description": "주식 가격 조회 (OHLCV)"
        },
        "market_cap": {
            "keywords": ["시가총액", "시총", "총액", "마켓캡"],
            "endpoint": "/api/stocks/market-cap",
            "requires_login": False,
            "parameters": ["market", "date"],
            "description": "시가총액 조회"
        },
        "fundamental": {
            "keywords": ["per", "pbr", "배당", "수익률", "eps", "bps", "dps", "기본적"],
            "endpoint": "/api/stocks/fundamental",
            "requires_login": True,
            "parameters": ["market", "date"],
            "description": "기본 지표 (PER/PBR/배당)"
        },
        "investor_trading": {
            "keywords": ["투자자", "매매동향", "외국인", "기관", "개인", "순매수", "순매도"],
            "endpoint": "/api/stocks/investor-trading",
            "requires_login": False,
            "parameters": ["ticker", "start_date", "end_date"],
            "description": "투자자별 매매동향"
        },
        "foreign_holding": {
            "keywords": ["외국인보유", "외국인지분", "외인보유", "외인지분", "외국인 보유율", "외국인 보유", "외인 보유율"],
            "endpoint": "/api/stocks/foreign-holding",
            "requires_login": True,
            "parameters": ["date", "market"],
            "description": "외국인 보유 현황"
        },

        # ETF
        "etf_list": {
            "keywords": ["etf", "상장지수펀드", "etf목록", "etf리스트"],
            "endpoint": "/api/etf/all",
            "requires_login": False,
            "parameters": ["date"],
            "description": "ETF 전종목 조회"
        },
        "etf_price": {
            "keywords": ["etf가격", "etf시세", "etf종가"],
            "endpoint": "/api/etf/ohlcv",
            "requires_login": False,
            "parameters": ["ticker", "start_date", "end_date"],
            "description": "ETF 가격 조회"
        },
        "etf_pdf": {
            "keywords": ["etf구성", "pdf", "포트폴리오", "etf종목"],
            "endpoint": "/api/etf/pdf",
            "requires_login": False,
            "parameters": ["ticker", "date"],
            "description": "ETF PDF(구성종목)"
        },

        # ETN
        "etn_list": {
            "keywords": ["etn", "상장지수증권", "etn목록"],
            "endpoint": "/api/etn/all",
            "requires_login": False,
            "parameters": ["date"],
            "description": "ETN 전종목 조회"
        },

        # ELW
        "elw_list": {
            "keywords": ["elw", "주식워런트증권", "워런트"],
            "endpoint": "/api/elw/all",
            "requires_login": False,
            "parameters": ["date"],
            "description": "ELW 전종목 조회"
        },

        # 공매도
        "short_selling": {
            "keywords": ["공매도", "숏", "대차", "차입", "대주"],
            "endpoint": "/api/short-selling/trading",
            "requires_login": False,
            "parameters": ["ticker", "start_date", "end_date"],
            "description": "공매도 거래 현황"
        },
        "short_balance": {
            "keywords": ["공매도잔고", "숏잔고", "대차잔고"],
            "endpoint": "/api/short-selling/balance",
            "requires_login": False,
            "parameters": ["ticker", "start_date", "end_date"],
            "description": "공매도 잔고 현황"
        },

        # 지수
        "index_price": {
            "keywords": ["지수", "코스피", "코스닥", "인덱스", "kospi", "kosdaq", "코스피200", "코스닥150", "krx100", "krx300"],
            "endpoint": "/api/index/ohlcv",
            "requires_login": False,
            "parameters": ["ticker", "start_date", "end_date"],
            "description": "지수 시세 조회"
        },
        "index_fundamental": {
            "keywords": ["지수per", "지수pbr", "지수배당"],
            "endpoint": "/api/index/fundamental",
            "requires_login": False,
            "parameters": ["ticker", "start_date", "end_date"],
            "description": "지수 기본 지표"
        },

        # 선물/옵션
        "futures_price": {
            "keywords": ["선물", "futures", "코스피200선물"],
            "endpoint": "/api/futures/ohlcv",
            "requires_login": False,
            "parameters": ["ticker", "start_date", "end_date"],
            "description": "선물 가격 조회"
        },
        "options_price": {
            "keywords": ["옵션", "options", "콜옵션", "풋옵션"],
            "endpoint": "/api/options/ohlcv",
            "requires_login": False,
            "parameters": ["ticker", "start_date", "end_date"],
            "description": "옵션 가격 조회"
        },

        # 채권
        "bond_price": {
            "keywords": ["채권", "국채", "회사채", "bond"],
            "endpoint": "/api/bond/ohlcv",
            "requires_login": False,
            "parameters": ["ticker", "start_date", "end_date"],
            "description": "채권 가격 조회"
        },

        # KRX BLD
        "krx_bld": {
            "keywords": ["bld", "krx데이터", "krx조회", "상세데이터"],
            "endpoint": "/api/krx/bld",
            "requires_login": True,
            "parameters": ["bld_id", "params"],
            "description": "KRX BLD 데이터 조회"
        },

        # 상태
        "server_status": {
            "keywords": ["상태", "status", "서버", "로그인상태"],
            "endpoint": "/api/status",
            "requires_login": False,
            "parameters": [],
            "description": "서버 상태 확인"
        },

        # 티커 검색
        "ticker_search": {
            "keywords": ["티커", "종목코드", "코드검색", "ticker"],
            "endpoint": "/api/ticker/search",
            "requires_login": False,
            "parameters": ["query", "market"],
            "description": "티커 검색"
        },

        # 종합 분석
        "comprehensive_analysis": {
            "keywords": ["분석", "종합", "전체", "리포트", "요약"],
            "endpoint": "MULTI",  # 여러 API 조합
            "requires_login": True,
            "parameters": ["ticker"],
            "description": "종합 분석 (여러 API 조합)"
        },
    }

    # 티커 사전
    TICKER_DICT = {
        # 삼성그룹
        "삼성전자": "005930", "삼성sdi": "006400", "삼성물산": "028260",
        "삼성생명": "032830", "삼성화재": "000810", "삼성에스디에스": "018260",
        # SK그룹
        "sk하이닉스": "000660", "sk텔레콤": "017670", "sk이노베이션": "096770",
        "sk": "034730", "sk스퀘어": "402340",
        # 현대차그룹
        "현대차": "005380", "기아": "000270", "현대모비스": "012330",
        "현대글로비스": "086280",
        # LG그룹
        "lg전자": "066570", "lg화학": "051910", "lg에너지솔루션": "373220",
        "lg디스플레이": "034220",
        # 기타 대형주
        "네이버": "035420", "카카오": "035720", "셀트리온": "068270",
        "포스코홀딩스": "005490", "kb금융": "105560", "신한지주": "055550",
        "하나금융지주": "086790", "삼성바이오로직스": "207940",
        "현대중공업": "329180", "크래프톤": "259960", "두산에너빌리티": "034020",
        # 중소형주 예시
        "에코프로": "086520", "에코프로비엠": "247540", "포스코퓨처엠": "003670",
    }

    # 지수 사전
    INDEX_DICT = {
        "코스피": "1001", "코스피200": "1028", "코스피100": "1034",
        "코스피50": "1035", "코스닥": "2001", "코스닥150": "2203",
        "krx100": "5042", "krx300": "5300",
    }

    # 시장 사전
    MARKET_DICT = {
        "코스피": "KOSPI", "kospi": "KOSPI",
        "코스닥": "KOSDAQ", "kosdaq": "KOSDAQ",
        "전체": "ALL", "all": "ALL",
    }


class KeywordMatcher:
    """1단계: 키워드 기반 매칭 (가장 빠름)"""

    def __init__(self):
        self.intents = IntentConfig.INTENTS
        self.ticker_dict = IntentConfig.TICKER_DICT
        self.index_dict = IntentConfig.INDEX_DICT
        self.market_dict = IntentConfig.MARKET_DICT

    def match(self, query: str) -> Optional[ClassificationResult]:
        """
        키워드 매칭으로 인텐트 분류

        Args:
            query: 사용자 쿼리

        Returns:
            ClassificationResult or None (매칭 실패 시)
        """
        import time
        start = time.perf_counter()

        query_lower = query.lower().replace(" ", "")

        # 각 인텐트별 매칭 점수 계산
        scores: List[Tuple[str, float, int]] = []  # (intent, score, match_count)

        for intent_id, config in self.intents.items():
            keywords = config["keywords"]
            match_count = 0

            for kw in keywords:
                if kw.lower() in query_lower:
                    match_count += 1

            if match_count > 0:
                # 매칭된 키워드 수 / 전체 키워드 수 * 가중치
                score = (match_count / len(keywords)) * (1 + match_count * 0.1)
                scores.append((intent_id, score, match_count))

        if not scores:
            return None

        # 가장 높은 점수 선택
        scores.sort(key=lambda x: (-x[1], -x[2]))
        best_intent, best_score, match_count = scores[0]

        # 신뢰도 계산 (최소 0.5, 최대 0.99)
        confidence = min(0.99, max(0.5, best_score))

        # 파라미터 추출
        parameters = self._extract_parameters(query, best_intent)

        config = self.intents[best_intent]
        latency = (time.perf_counter() - start) * 1000

        return ClassificationResult(
            intent=best_intent,
            confidence=confidence,
            method="keyword",
            parameters=parameters,
            endpoint=config["endpoint"],
            requires_login=config["requires_login"],
            latency_ms=latency
        )

    def _extract_parameters(self, query: str, intent: str) -> Dict[str, Any]:
        """쿼리에서 파라미터 추출"""
        params = {}
        query_lower = query.lower().replace(" ", "")  # 공백 제거

        # 티커 추출
        for name, code in self.ticker_dict.items():
            if name.replace(" ", "") in query_lower:
                params["ticker"] = code
                params["ticker_name"] = name
                break

        # 지수 추출 (index 인텐트이거나 지수 관련 키워드 포함 시)
        if "index" in intent or "지수" in query_lower or "코스피" in query_lower or "코스닥" in query_lower:
            for name, code in self.index_dict.items():
                if name.replace(" ", "") in query_lower:
                    params["ticker"] = code
                    params["index_name"] = name
                    break

        # 시장 추출
        for name, code in self.market_dict.items():
            if name in query_lower:
                params["market"] = code
                break

        # 날짜 추출 (간단한 패턴)
        date_patterns = [
            (r"오늘", datetime.now().strftime("%Y%m%d")),
            (r"어제", (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")),
            (r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", None),  # YYYY-MM-DD
        ]

        for pattern, default_date in date_patterns:
            if default_date:
                if re.search(pattern, query):
                    params["date"] = default_date
                    break
            else:
                match = re.search(pattern, query)
                if match:
                    params["date"] = "".join(match.groups())
                    break

        return params


class EmbeddingClassifier:
    """2단계: 임베딩 기반 유사도 분류"""

    def __init__(self, model_name: str = "jhgan/ko-sroberta-multitask"):
        if not EMBEDDING_AVAILABLE:
            self.model = None
            self.intent_embeddings = None
            return

        print(f"🔄 임베딩 모델 로딩: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.intents = IntentConfig.INTENTS

        # 인텐트별 대표 문장 임베딩 미리 계산
        self.intent_examples = self._build_intent_examples()
        self.intent_embeddings = self._compute_intent_embeddings()
        print(f"✅ 임베딩 모델 로딩 완료 ({len(self.intent_embeddings)}개 인텐트)")

    def _build_intent_examples(self) -> Dict[str, List[str]]:
        """인텐트별 대표 쿼리 예시"""
        return {
            "stock_price": [
                "삼성전자 주가 알려줘",
                "오늘 SK하이닉스 종가가 얼마야",
                "네이버 시세 조회",
                "삼성전자 주가",  # 티커 + 주가 패턴
                "현대차 가격",
                "카카오 얼마야",
                "LG전자 오늘 시세",
            ],
            "market_cap": [
                "코스피 시가총액 순위",
                "시총 상위 종목",
                "시가총액 상위 10개",  # 순위/상위 패턴
                "코스닥 시총 순위",
            ],
            "fundamental": [
                "삼성전자 PER이 얼마야",
                "코스피 PBR 평균",
                "배당수익률 높은 종목",
            ],
            "investor_trading": [
                "외국인 순매수 종목",
                "기관 매매동향",
                "개인 투자자 순매도",
            ],
            "etf_list": [
                "ETF 전체 목록",
                "상장지수펀드 리스트",
            ],
            "short_selling": [
                "공매도 현황",
                "대차거래 조회",
            ],
            "index_price": [
                "코스피 지수",
                "코스닥 시세",
            ],
            "futures_price": [
                "코스피200 선물 가격",
                "선물 시세",
            ],
            "comprehensive_analysis": [
                "삼성전자 종합 분석해줘",
                "현대차 전체 리포트",
            ],
        }

    def _compute_intent_embeddings(self) -> Dict[str, np.ndarray]:
        """인텐트별 임베딩 계산"""
        if not self.model:
            return {}

        embeddings = {}
        for intent, examples in self.intent_examples.items():
            # 예시 문장들의 평균 임베딩
            example_embeddings = self.model.encode(examples)
            embeddings[intent] = np.mean(example_embeddings, axis=0)
        return embeddings

    def classify(self, query: str, threshold: float = 0.6) -> Optional[ClassificationResult]:
        """
        임베딩 유사도로 인텐트 분류

        Args:
            query: 사용자 쿼리
            threshold: 최소 유사도 임계값

        Returns:
            ClassificationResult or None
        """
        if not EMBEDDING_AVAILABLE or not self.model:
            return None

        import time
        start = time.perf_counter()

        # 쿼리 임베딩
        query_embedding = self.model.encode([query])[0]

        # 각 인텐트와 유사도 계산
        similarities = {}
        for intent, intent_emb in self.intent_embeddings.items():
            sim = np.dot(query_embedding, intent_emb) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(intent_emb)
            )
            similarities[intent] = float(sim)

        # 최고 유사도 인텐트
        best_intent = max(similarities, key=similarities.get)
        best_sim = similarities[best_intent]

        if best_sim < threshold:
            return None

        config = self.intents.get(best_intent, {})
        latency = (time.perf_counter() - start) * 1000

        # 파라미터 추출 (키워드 매처 재사용)
        keyword_matcher = KeywordMatcher()
        params = keyword_matcher._extract_parameters(query, best_intent)

        return ClassificationResult(
            intent=best_intent,
            confidence=best_sim,
            method="embedding",
            parameters=params,
            endpoint=config.get("endpoint", ""),
            requires_login=config.get("requires_login", False),
            latency_ms=latency
        )


class LLMClassifier:
    """3단계: LLM 기반 분류 (가장 정확하지만 느림)"""

    def __init__(self):
        if not GEMINI_AVAILABLE:
            self.model = None
            return

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("⚠️ GEMINI_API_KEY 미설정 - LLM 분류 비활성화")
            self.model = None
            return

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.0-flash-exp")
        self.intents = IntentConfig.INTENTS
        print("✅ Gemini LLM 분류기 초기화 완료")

    async def classify(self, query: str) -> Optional[ClassificationResult]:
        """
        LLM으로 인텐트 분류

        Args:
            query: 사용자 쿼리

        Returns:
            ClassificationResult or None
        """
        if not self.model:
            return None

        import time
        start = time.perf_counter()

        # 프롬프트 구성
        intent_descriptions = "\n".join([
            f"- {intent_id}: {config['description']} (키워드: {', '.join(config['keywords'][:3])})"
            for intent_id, config in self.intents.items()
        ])

        prompt = f"""당신은 주식 API 인텐트 분류기입니다.
사용자 쿼리를 분석하여 가장 적합한 인텐트를 선택하세요.

가능한 인텐트:
{intent_descriptions}

사용자 쿼리: "{query}"

JSON 형식으로 응답하세요:
{{"intent": "인텐트_id", "confidence": 0.0~1.0, "reasoning": "이유"}}
"""

        try:
            response = self.model.generate_content(prompt)
            response_text = response.text

            # JSON 파싱
            json_match = re.search(r'\{[^}]+\}', response_text)
            if not json_match:
                return None

            result = json.loads(json_match.group())
            intent = result.get("intent")
            confidence = result.get("confidence", 0.7)

            if intent not in self.intents:
                return None

            config = self.intents[intent]
            latency = (time.perf_counter() - start) * 1000

            # 파라미터 추출
            keyword_matcher = KeywordMatcher()
            params = keyword_matcher._extract_parameters(query, intent)

            return ClassificationResult(
                intent=intent,
                confidence=confidence,
                method="llm",
                parameters=params,
                endpoint=config.get("endpoint", ""),
                requires_login=config.get("requires_login", False),
                latency_ms=latency
            )

        except Exception as e:
            print(f"❌ LLM 분류 오류: {e}")
            return None


class HybridIntentClassifier:
    """
    하이브리드 인텐트 분류기

    3단계 폴백:
    1. 키워드 매칭 (신뢰도 > 0.7)
    2. 임베딩 유사도 (신뢰도 > 0.6)
    3. LLM 분류 (최종)
    """

    def __init__(self,
                 keyword_threshold: float = 0.7,
                 embedding_threshold: float = 0.6,
                 enable_embedding: bool = True,
                 enable_llm: bool = True):
        """
        Args:
            keyword_threshold: 키워드 매칭 신뢰도 임계값
            embedding_threshold: 임베딩 유사도 임계값
            enable_embedding: 임베딩 분류 활성화
            enable_llm: LLM 분류 활성화
        """
        self.keyword_matcher = KeywordMatcher()
        self.keyword_threshold = keyword_threshold
        self.embedding_threshold = embedding_threshold

        # 선택적 초기화
        self.embedding_classifier = None
        self.llm_classifier = None

        if enable_embedding and EMBEDDING_AVAILABLE:
            self.embedding_classifier = EmbeddingClassifier()

        if enable_llm and GEMINI_AVAILABLE:
            self.llm_classifier = LLMClassifier()

    async def classify(self, query: str) -> ClassificationResult:
        """
        3단계 폴백으로 인텐트 분류

        Args:
            query: 사용자 쿼리

        Returns:
            ClassificationResult (항상 반환, 실패 시 unknown 인텐트)
        """
        import time
        total_start = time.perf_counter()

        # 1단계: 키워드 매칭 (가장 빠름)
        keyword_result = self.keyword_matcher.match(query)
        if keyword_result and keyword_result.confidence >= self.keyword_threshold:
            print(f"[OK][Keyword] {keyword_result.intent} (conf: {keyword_result.confidence:.2f}, {keyword_result.latency_ms:.1f}ms)")
            return keyword_result

        # 2단계: 임베딩 유사도
        if self.embedding_classifier:
            embedding_result = self.embedding_classifier.classify(query, self.embedding_threshold)
            if embedding_result:
                print(f"[OK][Embedding] {embedding_result.intent} (conf: {embedding_result.confidence:.2f}, {embedding_result.latency_ms:.1f}ms)")
                return embedding_result

        # 3단계: LLM 분류
        if self.llm_classifier:
            llm_result = await self.llm_classifier.classify(query)
            if llm_result:
                print(f"[OK][LLM] {llm_result.intent} (conf: {llm_result.confidence:.2f}, {llm_result.latency_ms:.1f}ms)")
                return llm_result

        # 4단계: 폴백 - 키워드 매칭 결과 반환 (낮은 신뢰도라도)
        if keyword_result:
            print(f"[WARN][Fallback-Keyword] {keyword_result.intent} (conf: {keyword_result.confidence:.2f})")
            return keyword_result

        # 5단계: 완전 실패
        total_latency = (time.perf_counter() - total_start) * 1000
        return ClassificationResult(
            intent="unknown",
            confidence=0.0,
            method="none",
            parameters={},
            endpoint="",
            requires_login=False,
            latency_ms=total_latency
        )

    def classify_sync(self, query: str) -> ClassificationResult:
        """동기 버전 (asyncio 없이 사용)"""
        return asyncio.run(self.classify(query))


# ==============================================================================
# 테스트 및 데모
# ==============================================================================

async def demo():
    """데모 실행"""
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("=" * 60)
    print("[TEST] Hybrid Intent Classifier Test")
    print("=" * 60)

    # 분류기 초기화 (임베딩, LLM 선택적)
    classifier = HybridIntentClassifier(
        enable_embedding=EMBEDDING_AVAILABLE,
        enable_llm=GEMINI_AVAILABLE
    )

    test_queries = [
        # 명확한 키워드 (1단계에서 처리)
        "삼성전자 오늘 주가 알려줘",
        "코스피 시가총액 순위",
        "SK하이닉스 PER 얼마야",
        "외국인 순매수 현황",
        "ETF 전체 목록 보여줘",

        # 애매한 표현 (2-3단계 필요)
        "삼성전자 분석해줘",
        "요즘 주식 어때",
        "현대차 투자해도 될까",
    ]

    print("\n[RESULTS] Test Query Classification:\n")

    for query in test_queries:
        print(f"Q: {query}")
        result = await classifier.classify(query)
        print(f"   → 인텐트: {result.intent}")
        print(f"   → 신뢰도: {result.confidence:.2f}")
        print(f"   → 방식: {result.method}")
        print(f"   → 엔드포인트: {result.endpoint}")
        print(f"   → 파라미터: {result.parameters}")
        print(f"   → 소요시간: {result.latency_ms:.1f}ms")
        print()

    print("=" * 60)
    print("[DONE] Test Complete")


if __name__ == "__main__":
    asyncio.run(demo())
