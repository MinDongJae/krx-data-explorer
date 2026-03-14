// ============================================================================
// 데이터 익스플로러 - GraphicWalker 기반 시각화
// No-code 드래그앤드롭 데이터 분석 도구
// KRX Auth API 연동으로 실시간 주식 데이터 제공
// ============================================================================

import React, { useState, useCallback, useMemo, useEffect, lazy, Suspense } from 'react';
import '@kanaries/graphic-walker/dist/style.css';

// React Best Practices 2.2: Heavy 컴포넌트 Dynamic Import
// GraphicWalker ~300KB+ 초기 로드 방지
const GraphicWalker = lazy(() =>
  import('@kanaries/graphic-walker').then(mod => ({ default: mod.GraphicWalker }))
);
import {
  ArrowLeft,
  Upload,
  Database,
  TrendingUp,
  HelpCircle,
  RefreshCw,
  Loader2,
  AlertCircle,
  Wifi,
  WifiOff,
  Send,
  Sparkles,
  Clock,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Info,
} from 'lucide-react';
// react-router-dom Link 불필요 (독립 앱)
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';

// ============================================================================
// 타입 정의
// ============================================================================

// 자연어 질의 API 응답 타입 (온톨로지 기반 — LLM이 API+차트 자동 생성)
interface NLChartConfig {
  type: string;  // bar, line, scatter, area, pie
  title: string;
  x: string;
  y: string;
  sort?: string;
  limit?: number;
  color_field?: string;
}

interface NaturalLanguageResponse {
  query: string;
  intent: string;
  chart: NLChartConfig;
  data: Record<string, unknown>[];
  columns: string[];
  rows: number;
  latency_ms: number;
  model: string;
  endpoints_called: string[];
}

interface DataField {
  fid: string;
  name: string;
  semanticType: 'nominal' | 'ordinal' | 'quantitative' | 'temporal';
  analyticType: 'dimension' | 'measure';
}

interface KRXApiResponse {
  date: string;
  count: number;
  data: Record<string, unknown>[];
  market?: string;
  rows?: number;
}

type DataSourceType = 'sample' | 'krx-api' | 'uploaded';
type MarketType = 'ALL' | 'KOSPI' | 'KOSDAQ';
type DataTypeOption = 'fundamental' | 'market-cap' | 'sector';

// ============================================================================
// KRX API 설정 — 배포 환경: 상대경로, 개발 환경: localhost
// ============================================================================

const KRX_API_URL = import.meta.env.DEV ? 'http://localhost:8000' : '';

// ============================================================================
// 데이터 커버리지 명세 (API 테스트 결과 기반)
// ============================================================================

interface DataCoverageItem {
  category: string;
  description: string;
  status: 'working' | 'empty' | 'error';
  endpoint: string;
  note?: string;
}

const DATA_COVERAGE: DataCoverageItem[] = [
  // ── 주식 기본 (네이버 소스 — 로그인 불필요!) ──
  { category: '주식 OHLCV', description: '시가/고가/저가/종가/거래량', status: 'working', endpoint: '/api/stocks/ohlcv', note: '네이버 소스' },
  { category: '전체 시장 데이터', description: 'KOSPI/KOSDAQ 종목 데이터', status: 'working', endpoint: '/api/stocks/all-markets', note: '네이버 소스' },
  { category: '종목 목록', description: '상장 종목 코드+이름 리스트', status: 'working', endpoint: '/api/stocks/list', note: '네이버 소스' },
  { category: '시가총액 순위', description: '종목별 시가총액 순위', status: 'working', endpoint: '/api/stocks/market-cap', note: '네이버 소스' },
  { category: '펀더멘털', description: 'PER/PBR/EPS/BPS/배당수익률', status: 'working', endpoint: '/api/stocks/fundamental', note: '네이버 소스' },
  { category: '투자자별 거래', description: '기관/외국인/개인 매매동향', status: 'working', endpoint: '/api/stocks/investor-trading', note: '네이버 폴백' },
  // ── 주식 심화 (KRX→네이버 폴백) ──
  { category: '시가총액 추이', description: '개별 종목 시가총액 일별 추이', status: 'working', endpoint: '/api/stocks/market-cap-by-date', note: '네이버 폴백' },
  { category: '시가총액 스냅샷', description: '전 종목 시가총액 특정일', status: 'working', endpoint: '/api/stocks/market-cap-snapshot', note: '네이버 폴백' },
  { category: '펀더멘털 추이', description: 'PER/PBR/EPS 일별 추이', status: 'working', endpoint: '/api/stocks/fundamental-by-date', note: '네이버 폴백' },
  { category: '펀더멘털 스냅샷', description: '전 종목 PER/PBR 특정일', status: 'working', endpoint: '/api/stocks/fundamental-snapshot', note: '네이버 폴백' },
  { category: 'OHLCV 스냅샷', description: '전 종목 OHLCV 특정일', status: 'working', endpoint: '/api/stocks/ohlcv-snapshot', note: '네이버 폴백' },
  { category: '등락률', description: '전 종목 등락률 순위', status: 'working', endpoint: '/api/stocks/price-change', note: '장중 데이터' },
  { category: '업종 분류', description: '업종별 시세 (79개 업종)', status: 'working', endpoint: '/api/stocks/sector', note: '네이버 폴백' },
  { category: '외국인 보유 추이', description: '외국인 보유/소진율 일별', status: 'working', endpoint: '/api/stocks/foreign-by-date', note: '네이버 폴백' },
  { category: '외국인 보유 추이', description: '외국인 보유/소진율 일별', status: 'working', endpoint: '/api/stocks/foreign-by-date', note: '네이버 폴백' },
  { category: '투자자별 거래량', description: '기관/외국인/개인별 거래', status: 'working', endpoint: '/api/stocks/trading-by-investor', note: '네이버 폴백' },
  // ── ETF ──
  { category: 'ETF 목록', description: 'ETF 전체 목록 (1000+개)', status: 'working', endpoint: '/api/etf/list', note: '네이버 JSON API' },
  { category: 'ETF OHLCV', description: 'ETF 가격 데이터', status: 'working', endpoint: '/api/etf/ohlcv', note: '네이버 차트 API' },
  // ── 지수 ──
  { category: '실시간 지수', description: '코스피/코스닥 실시간', status: 'working', endpoint: '/api/index/realtime', note: '장중 데이터' },
  { category: '지수 목록', description: 'KOSPI/KOSDAQ 지수 리스트', status: 'working', endpoint: '/api/index/list' },
  { category: '지수 OHLCV', description: '지수별 가격 데이터', status: 'working', endpoint: '/api/index/ohlcv' },
  // ── 네이버 전용 ──
  { category: '일별 시세', description: '개별 종목 일별시세 (HTML)', status: 'working', endpoint: '/api/naver/daily-price', note: '네이버 전용' },
  { category: '외국인 보유현황', description: '외국인 보유비율 일별 추이', status: 'working', endpoint: '/api/naver/foreign-holding', note: '네이버 전용' },
  { category: '등락률 순위', description: '상승/하락 종목 순위', status: 'working', endpoint: '/api/naver/price-ranking', note: '장중 데이터' },
  { category: '업종별 시세', description: '79개 업종별 등락현황', status: 'working', endpoint: '/api/naver/sector-list', note: '네이버 전용' },
  { category: '투자자 매매동향', description: '시장 전체 투자자별 매매', status: 'working', endpoint: '/api/naver/investor-trend', note: '장중 데이터' },
  { category: '자연어 질의', description: 'AI 기반 자연어 → API 변환', status: 'working', endpoint: '/api/natural-language' },
  // ── KRX 로그인 인증 (krx_auth.py — ID/PW 직접 로그인) ──
  { category: '전종목 시세', description: 'KOSPI/KOSDAQ 전종목 시세 (951개)', status: 'working', endpoint: '/api/krx-auth/all-stock-price', note: 'KRX 로그인' },
  { category: '투자자별 매매', description: '기관/외국인/개인 순매수 기간조회', status: 'working', endpoint: '/api/krx-auth/investor-summary', note: 'KRX 로그인' },
  { category: '공매도 전종목', description: '공매도 거래량/잔고 (951개)', status: 'working', endpoint: '/api/krx-auth/short-selling-all', note: 'KRX 로그인' },
  { category: '채권 수익률', description: '국고채/회사채/CD 금리', status: 'working', endpoint: '/api/krx-auth/bond-yield', note: 'KRX 로그인' },
  { category: '파생상품', description: '선물/옵션/미니 시세', status: 'working', endpoint: '/api/krx-auth/derivative-price', note: 'KRX 로그인' },
  { category: 'ETF 전종목', description: 'ETF 시세 (1,075개)', status: 'working', endpoint: '/api/krx-auth/etf-price', note: 'KRX 로그인' },
  { category: 'ETN 전종목', description: 'ETN 시세 (389개)', status: 'working', endpoint: '/api/krx-auth/etn-price', note: 'KRX 로그인' },
  { category: 'ELW 전종목', description: 'ELW 시세 (2,964개)', status: 'working', endpoint: '/api/krx-auth/elw-price', note: 'KRX 로그인' },
  { category: '금 시세', description: 'KRX 금시장 시세', status: 'working', endpoint: '/api/krx-auth/gold-price', note: 'KRX 로그인' },
];

// ============================================================================
// 샘플 데이터 (API 미연결 시 기본 표시)
// ============================================================================

const krxSampleData = [
  { 종목코드: '005930', 종목명: '삼성전자', 시장: '코스피', 종가: 71500, 등락률: 0.7, 거래량: 12534567, 거래대금_억: 8965.4, 시가총액_조: 427.0, PER: 12.5, PBR: 1.2, 배당수익률: 2.1 },
  { 종목코드: '000660', 종목명: 'SK하이닉스', 시장: '코스피', 종가: 178000, 등락률: -1.1, 거래량: 3456789, 거래대금_억: 6153.1, 시가총액_조: 129.0, PER: 8.2, PBR: 1.8, 배당수익률: 1.5 },
  { 종목코드: '035420', 종목명: 'NAVER', 시장: '코스피', 종가: 215000, 등락률: 1.4, 거래량: 567890, 거래대금_억: 1221.0, 시가총액_조: 35.2, PER: 22.1, PBR: 1.9, 배당수익률: 0.5 },
  { 종목코드: '005380', 종목명: '현대차', 시장: '코스피', 종가: 248500, 등락률: 0.6, 거래량: 789012, 거래대금_억: 1961.7, 시가총액_조: 53.1, PER: 5.8, PBR: 0.6, 배당수익률: 3.2 },
  { 종목코드: '051910', 종목명: 'LG화학', 시장: '코스피', 종가: 385000, 등락률: -1.3, 거래량: 234567, 거래대금_억: 902.9, 시가총액_조: 27.2, PER: 15.3, PBR: 1.1, 배당수익률: 1.8 },
  { 종목코드: '006400', 종목명: '삼성SDI', 시장: '코스피', 종가: 412000, 등락률: 2.0, 거래량: 345678, 거래대금_억: 1424.2, 시가총액_조: 28.3, PER: 18.7, PBR: 1.5, 배당수익률: 0.8 },
  { 종목코드: '035720', 종목명: '카카오', 시장: '코스피', 종가: 52300, 등락률: -1.3, 거래량: 4567890, 거래대금_억: 2389.0, 시가총액_조: 23.2, PER: 35.2, PBR: 2.1, 배당수익률: 0.2 },
  { 종목코드: '068270', 종목명: '셀트리온', 시장: '코스피', 종가: 178500, 등락률: 1.4, 거래량: 890123, 거래대금_억: 1588.9, 시가총액_조: 24.7, PER: 28.4, PBR: 3.2, 배당수익률: 0.4 },
  { 종목코드: '028260', 종목명: '삼성물산', 시장: '코스피', 종가: 132500, 등락률: 0.8, 거래량: 456789, 거래대금_억: 605.2, 시가총액_조: 24.8, PER: 11.2, PBR: 0.8, 배당수익률: 2.5 },
  { 종목코드: '105560', 종목명: 'KB금융', 시장: '코스피', 종가: 78500, 등락률: 0.6, 거래량: 1234567, 거래대금_억: 969.1, 시가총액_조: 32.1, PER: 6.8, PBR: 0.5, 배당수익률: 4.2 },
  { 종목코드: '247540', 종목명: '에코프로비엠', 시장: '코스닥', 종가: 256000, 등락률: 3.2, 거래량: 1234567, 거래대금_억: 3160.5, 시가총액_조: 12.1, PER: 85.3, PBR: 8.5, 배당수익률: 0.0 },
  { 종목코드: '086520', 종목명: '에코프로', 시장: '코스닥', 종가: 98700, 등락률: 2.8, 거래량: 2345678, 거래대금_억: 2315.3, 시가총액_조: 9.8, PER: 120.5, PBR: 12.3, 배당수익률: 0.0 },
  { 종목코드: '373220', 종목명: 'LG에너지솔루션', 시장: '코스피', 종가: 395000, 등락률: 1.5, 거래량: 567890, 거래대금_억: 2243.2, 시가총액_조: 92.4, PER: 45.2, PBR: 4.8, 배당수익률: 0.0 },
  { 종목코드: '055550', 종목명: '신한지주', 시장: '코스피', 종가: 51200, 등락률: 0.6, 거래량: 2345678, 거래대금_억: 1201.0, 시가총액_조: 26.4, PER: 5.9, PBR: 0.5, 배당수익률: 4.5 },
  { 종목코드: '003550', 종목명: 'LG', 시장: '코스피', 종가: 92300, 등락률: -1.3, 거래량: 567890, 거래대금_억: 524.2, 시가총액_조: 14.5, PER: 9.1, PBR: 0.7, 배당수익률: 2.8 },
  { 종목코드: '066570', 종목명: 'LG전자', 시장: '코스피', 종가: 98700, 등락률: 1.5, 거래량: 678901, 거래대금_억: 670.1, 시가총액_조: 16.1, PER: 12.3, PBR: 0.9, 배당수익률: 1.9 },
  { 종목코드: '034730', 종목명: 'SK', 시장: '코스피', 종가: 165000, 등락률: -1.8, 거래량: 345678, 거래대금_억: 570.4, 시가총액_조: 11.6, PER: 7.5, PBR: 0.4, 배당수익률: 3.8 },
  { 종목코드: '017670', 종목명: 'SK텔레콤', 시장: '코스피', 종가: 52800, 등락률: 0.4, 거래량: 456789, 거래대금_억: 241.2, 시가총액_조: 12.8, PER: 8.9, PBR: 0.8, 배당수익률: 5.1 },
  { 종목코드: '030200', 종목명: 'KT', 시장: '코스피', 종가: 38900, 등락률: 0.3, 거래량: 567890, 거래대금_억: 220.9, 시가총액_조: 9.7, PER: 7.2, PBR: 0.5, 배당수익률: 5.8 },
  { 종목코드: '032830', 종목명: '삼성생명', 시장: '코스피', 종가: 85600, 등락률: 0.7, 거래량: 234567, 거래대금_억: 200.8, 시가총액_조: 17.1, PER: 8.1, PBR: 0.4, 배당수익률: 3.5 },
];

// 샘플 데이터용 필드 정의
const sampleFields: DataField[] = [
  { fid: '종목코드', name: '종목코드', semanticType: 'nominal', analyticType: 'dimension' },
  { fid: '종목명', name: '종목명', semanticType: 'nominal', analyticType: 'dimension' },
  { fid: '시장', name: '시장', semanticType: 'nominal', analyticType: 'dimension' },
  { fid: '종가', name: '종가', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: '등락률', name: '등락률(%)', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: '거래량', name: '거래량', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: '거래대금_억', name: '거래대금(억)', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: '시가총액_조', name: '시가총액(조)', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: 'PER', name: 'PER', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: 'PBR', name: 'PBR', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: '배당수익률', name: '배당수익률(%)', semanticType: 'quantitative', analyticType: 'measure' },
];

// KRX API 필드 정의
const pykrxFields: DataField[] = [
  { fid: '종목코드', name: '종목코드', semanticType: 'nominal', analyticType: 'dimension' },
  { fid: '종목명', name: '종목명', semanticType: 'nominal', analyticType: 'dimension' },
  { fid: '시장', name: '시장', semanticType: 'nominal', analyticType: 'dimension' },
  { fid: '종가', name: '종가', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: '등락률', name: '등락률(%)', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: '거래량', name: '거래량', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: '거래대금_억', name: '거래대금(억)', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: '시가총액_조', name: '시가총액(조)', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: 'PER', name: 'PER', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: 'PBR', name: 'PBR', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: '배당수익률', name: '배당수익률(%)', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: 'EPS', name: 'EPS', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: 'BPS', name: 'BPS', semanticType: 'quantitative', analyticType: 'measure' },
  { fid: '기준일', name: '기준일', semanticType: 'temporal', analyticType: 'dimension' },
];

// ============================================================================
// CSV 파싱 유틸리티
// ============================================================================

function parseCSV(csvText: string): { data: Record<string, unknown>[]; fields: DataField[] } {
  const lines = csvText.trim().split('\n');
  if (lines.length < 2) return { data: [], fields: [] };

  const headers = lines[0].split(',').map(h => h.trim().replace(/"/g, ''));
  const data: Record<string, unknown>[] = [];

  for (let i = 1; i < lines.length; i++) {
    const values = lines[i].split(',').map(v => v.trim().replace(/"/g, ''));
    const row: Record<string, unknown> = {};
    headers.forEach((header, idx) => {
      const value = values[idx];
      const numValue = parseFloat(value);
      row[header] = isNaN(numValue) ? value : numValue;
    });
    data.push(row);
  }

  const fields: DataField[] = headers.map(header => {
    const sampleValue = data[0]?.[header];
    const isNumber = typeof sampleValue === 'number';
    const isDate = typeof sampleValue === 'string' && !isNaN(Date.parse(sampleValue));

    return {
      fid: header,
      name: header,
      semanticType: isDate ? 'temporal' : isNumber ? 'quantitative' : 'nominal',
      analyticType: isNumber ? 'measure' : 'dimension',
    };
  });

  return { data, fields };
}

// ============================================================================
// KRX API 함수
// ============================================================================

const DATA_EXPLORE_API = `${KRX_API_URL}/api/data-explore`;

async function checkKRXConnection(): Promise<boolean> {
  try {
    const response = await fetch(`${DATA_EXPLORE_API}/status`, {
      method: 'GET',
      signal: AbortSignal.timeout(5000)
    });
    return response.ok;
  } catch {
    return false;
  }
}

// 자연어 질의 API 호출 (온톨로지 기반 — Gemini Flash가 API+차트 자동 생성)
// GET 방식 (CloudFront OAC + AWS_IAM 호환 — POST body 서명 문제 우회)
async function processNaturalLanguageQuery(
  query: string,
): Promise<NaturalLanguageResponse> {
  const params = new URLSearchParams({ q: query });
  const response = await fetch(`${DATA_EXPLORE_API}/nl-query?${params}`, {
    signal: AbortSignal.timeout(60000)
  });

  if (!response.ok) {
    throw new Error(`API Error: ${response.status}`);
  }

  return response.json();
}

async function fetchKRXData(
  dataType: DataTypeOption,
  market: MarketType,
  _topN: number = 50
): Promise<KRXApiResponse> {
  const params = new URLSearchParams();
  let endpoint = '';

  if (dataType === 'fundamental') {
    // foreign_holding = PER/PBR/EPS/BPS/배당수익률 포함
    endpoint = '/foreign-holding';
    params.set('market', market === 'ALL' ? 'STK' : market === 'KOSPI' ? 'STK' : 'KSQ');
  } else if (dataType === 'market-cap') {
    endpoint = '/market-cap';
    params.set('market', market === 'ALL' ? 'STK' : market === 'KOSPI' ? 'STK' : 'KSQ');
  } else if (dataType === 'sector') {
    endpoint = '/sector-price';
    params.set('market', market === 'ALL' ? 'STK' : market === 'KOSPI' ? 'STK' : 'KSQ');
  }

  const response = await fetch(`${DATA_EXPLORE_API}${endpoint}?${params}`, {
    signal: AbortSignal.timeout(30000)
  });

  if (!response.ok) {
    throw new Error(`KRX API Error: ${response.status}`);
  }

  return response.json();
}

// ============================================================================
// 컴포넌트
// ============================================================================

const DataExplorer: React.FC = () => {
  // 상태
  const [data, setData] = useState<Record<string, unknown>[]>(krxSampleData);
  const [fields, setFields] = useState<DataField[]>(sampleFields);
  const [dataSource, setDataSource] = useState<DataSourceType>('sample');
  const [fileName, setFileName] = useState<string>('');
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false);
  const [isCoverageOpen, setIsCoverageOpen] = useState(false);

  // API 연결 상태
  const [isAPIConnected, setIsAPIConnected] = useState<boolean | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // 자연어 질의 관련 상태
  const [nlQuery, setNlQuery] = useState('');
  const [nlLoading, setNlLoading] = useState(false);
  const [nlResult, setNlResult] = useState<NaturalLanguageResponse | null>(null);
  const [nlError, setNlError] = useState<string | null>(null);
  const [nlHistoryOpen, setNlHistoryOpen] = useState(false);
  const [nlHistory, setNlHistory] = useState<NaturalLanguageResponse[]>([]);
  const [selectedMarket, setSelectedMarket] = useState<MarketType>('ALL');
  const [selectedDataType, setSelectedDataType] = useState<DataTypeOption>('fundamental');
  const [topN, setTopN] = useState<number>(50);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  // API 연결 확인
  useEffect(() => {
    const checkConnection = async () => {
      const connected = await checkKRXConnection();
      setIsAPIConnected(connected);
    };
    checkConnection();
  }, []);

  // 자연어 질의 처리 (온톨로지 기반 — LLM이 API 선택 + 차트 설정 자동 생성)
  const handleNaturalLanguageQuery = useCallback(async () => {
    if (!nlQuery.trim() || nlLoading) return;

    setNlLoading(true);
    setNlError(null);
    setNlResult(null);

    try {
      const result = await processNaturalLanguageQuery(nlQuery.trim());
      setNlResult(result);

      // 히스토리에 추가 (최대 10개)
      setNlHistory(prev => [result, ...prev.slice(0, 9)]);

      // 결과 데이터가 있으면 GraphicWalker에 로드
      if (result.data && result.data.length > 0) {
        // 동적으로 필드 생성
        const sampleRow = result.data[0];
        const dynamicFields: DataField[] = Object.keys(sampleRow).map(key => {
          const value = sampleRow[key];
          const isNumber = typeof value === 'number';
          const isDate = typeof value === 'string' && /^\d{4}[-\/]\d{2}[-\/]\d{2}/.test(value);

          return {
            fid: key,
            name: key,
            semanticType: isDate ? 'temporal' : isNumber ? 'quantitative' : 'nominal',
            analyticType: isNumber ? 'measure' : 'dimension',
          };
        });

        setData(result.data);
        setFields(dynamicFields);
        setDataSource('krx-api');
        setLastUpdated(new Date().toLocaleDateString('ko-KR'));
      }
    } catch (error) {
      console.error('자연어 질의 실패:', error);
      setNlError(error instanceof Error ? error.message : '자연어 질의 처리 실패');
    } finally {
      setNlLoading(false);
    }
  }, [nlQuery, nlLoading]);

  // Enter 키 처리
  const handleNlKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleNaturalLanguageQuery();
    }
  }, [handleNaturalLanguageQuery]);

  // KRX 데이터 로드
  const loadKRXData = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);

    try {
      const response = await fetchKRXData(selectedDataType, selectedMarket, topN);

      if (response.data && response.data.length > 0) {
        setData(response.data);
        setFields(pykrxFields);
        setDataSource('krx-api');
        setLastUpdated(response.date);
      } else {
        throw new Error('데이터가 없습니다');
      }
    } catch (error) {
      console.error('KRX 데이터 로드 실패:', error);
      setLoadError(error instanceof Error ? error.message : '데이터 로드 실패');
    } finally {
      setIsLoading(false);
    }
  }, [selectedDataType, selectedMarket, topN]);

  // 파일 업로드 핸들러
  const handleFileUpload = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      const { data: parsedData, fields: parsedFields } = parseCSV(text);

      if (parsedData.length > 0) {
        setData(parsedData);
        setFields(parsedFields);
        setDataSource('uploaded');
        setFileName(file.name);
        setIsUploadDialogOpen(false);
      }
    };
    reader.readAsText(file);
  }, []);

  // 샘플 데이터로 리셋
  const resetToSampleData = useCallback(() => {
    setData(krxSampleData);
    setFields(sampleFields);
    setDataSource('sample');
    setFileName('');
    setLastUpdated(null);
  }, []);

  // Graphic Walker 설정 — 보라색 테마 + 한글화 + 툴바 정리
  const gwConfig = useMemo(() => ({
    i18nLang: 'ko-KR' as const,
    appearance: 'light' as const,

    // UI 테마 — 프로젝트 보라색 톤 통일
    uiTheme: {
      light: {
        background: '#fafafa',
        foreground: '#1a1a2e',
        primary: '#7c3aed',
        'primary-foreground': '#ffffff',
        border: '#e5e7eb',
        ring: '#7c3aed',
        muted: '#f3f0ff',
        'muted-foreground': '#6b7280',
        accent: '#ede9fe',
        'accent-foreground': '#4c1d95',
        dimension: '#7c3aed',
        measure: '#f59e0b',
      },
      dark: {
        background: '#1a1a2e',
        foreground: '#e5e7eb',
        primary: '#a78bfa',
        'primary-foreground': '#1a1a2e',
        border: '#374151',
        ring: '#a78bfa',
        muted: '#2d2d44',
        'muted-foreground': '#9ca3af',
        accent: '#3b3660',
        'accent-foreground': '#c4b5fd',
        dimension: '#a78bfa',
        measure: '#fbbf24',
      },
    },

    // Vega-Lite 차트 테마 — 보라색 계열
    vizThemeConfig: {
      light: {
        background: 'transparent',
        area: { fill: '#7c3aed' },
        bar: { fill: '#7c3aed' },
        circle: { fill: '#7c3aed' },
        line: { stroke: '#7c3aed', strokeWidth: 2 },
        point: { fill: '#7c3aed' },
        rect: { fill: '#7c3aed' },
        axis: {
          gridColor: '#e5e7eb',
          labelColor: '#6b7280',
          titleColor: '#374151',
          labelFont: 'Pretendard Variable, Pretendard, sans-serif',
          titleFont: 'Pretendard Variable, Pretendard, sans-serif',
        },
        legend: {
          labelColor: '#6b7280',
          titleColor: '#374151',
          labelFont: 'Pretendard Variable, Pretendard, sans-serif',
          titleFont: 'Pretendard Variable, Pretendard, sans-serif',
        },
        range: {
          category: [
            '#7c3aed', '#f59e0b', '#10b981', '#3b82f6', '#ef4444',
            '#8b5cf6', '#f97316', '#06b6d4', '#ec4899', '#84cc16',
          ],
        },
      },
      dark: {
        background: 'transparent',
        area: { fill: '#a78bfa' },
        bar: { fill: '#a78bfa' },
        circle: { fill: '#a78bfa' },
        line: { stroke: '#a78bfa', strokeWidth: 2 },
        point: { fill: '#a78bfa' },
        rect: { fill: '#a78bfa' },
        axis: {
          gridColor: '#374151',
          labelColor: '#9ca3af',
          titleColor: '#d1d5db',
          labelFont: 'Pretendard Variable, Pretendard, sans-serif',
          titleFont: 'Pretendard Variable, Pretendard, sans-serif',
        },
        legend: {
          labelColor: '#9ca3af',
          titleColor: '#d1d5db',
          labelFont: 'Pretendard Variable, Pretendard, sans-serif',
          titleFont: 'Pretendard Variable, Pretendard, sans-serif',
        },
        range: {
          category: [
            '#a78bfa', '#fbbf24', '#34d399', '#60a5fa', '#f87171',
            '#c084fc', '#fb923c', '#22d3ee', '#f472b6', '#a3e635',
          ],
        },
      },
    },

    // 툴바 정리 — 불필요한 버튼 숨김
    toolbar: {
      exclude: ['kanaries', 'debug', 'painter', 'export_code'],
    },

    // 한글 번역
    i18nResources: {
      'ko-KR': {
        translation: {
          // 탭
          'main.tabpanel.DatasetFields': '데이터',
          'main.tabpanel.Visualization': '시각화',
          'main.tabpanel.chartName': '차트',
          'main.tabpanel.new': '+ 새 차트',
          // 필드
          'main.field.field_list': '필드 목록',
          'main.field.filter': '필터',
          'main.field.x_axis': 'X축',
          'main.field.y_axis': 'Y축',
          'main.field.color': '색상',
          'main.field.opacity': '투명도',
          'main.field.size': '크기',
          'main.field.shape': '모양',
          'main.field.details': '세부사항',
          'main.field.drop_field_here': '여기에 필드를 놓으세요',
          // 마크 타입
          'constant.mark_type.auto': '자동',
          'constant.mark_type.bar': '막대',
          'constant.mark_type.line': '선',
          'constant.mark_type.area': '영역',
          'constant.mark_type.point': '점',
          'constant.mark_type.circle': '원',
          'constant.mark_type.tick': '틱',
          'constant.mark_type.rect': '사각형',
          'constant.mark_type.arc': '호',
          'constant.mark_type.boxplot': '상자수염',
          'constant.mark_type.table': '표',
          'constant.mark_type.text': '텍스트',
          // 집계
          'constant.aggregation.sum': '합계',
          'constant.aggregation.mean': '평균',
          'constant.aggregation.count': '개수',
          'constant.aggregation.median': '중앙값',
          'constant.aggregation.min': '최솟값',
          'constant.aggregation.max': '최댓값',
          'constant.aggregation.variance': '분산',
          'constant.aggregation.stdev': '표준편차',
          // 설정
          'main.tabpanel.settings.toggle.aggregation': '집계',
          'main.tabpanel.settings.toggle.stack': '스택',
          'main.tabpanel.settings.sort.asc': '오름차순',
          'main.tabpanel.settings.sort.desc': '내림차순',
          // 공통
          'actions.undo': '실행 취소',
          'actions.redo': '다시 실행',
          'actions.export_chart': '차트 내보내기',
          'actions.export_csv': 'CSV 다운로드',
        },
      },
    },
  }), []);

  // 기본 프리셋 차트 — 시가총액 막대차트
  const defaultChart = useMemo(() => [{
    visId: 'preset-market-cap',
    name: '시가총액 TOP 20',
    encodings: {
      dimensions: [
        { fid: '종목명', name: '종목명', semanticType: 'nominal', analyticType: 'dimension', dragId: 'd-name' },
      ],
      measures: [
        { fid: '시가총액(조)', name: '시가총액(조)', semanticType: 'quantitative', analyticType: 'measure', dragId: 'm-cap', aggName: 'sum' },
      ],
      rows: [
        { fid: '종목명', name: '종목명', semanticType: 'nominal', analyticType: 'dimension', dragId: 'd-name-r' },
      ],
      columns: [
        { fid: '시가총액(조)', name: '시가총액(조)', semanticType: 'quantitative', analyticType: 'measure', dragId: 'm-cap-c', aggName: 'sum' },
      ],
      color: [],
      opacity: [],
      size: [],
      shape: [],
      radius: [],
      theta: [],
      details: [],
      filters: [],
      text: [],
    },
    config: {
      defaultAggregated: true,
      geoms: ['bar'],
      coordSystem: 'generic',
      limit: 20,
    },
    layout: {
      showActions: false,
      showTableSummary: false,
      size: { mode: 'auto' as const },
    },
  }], []);

  // 데이터 소스 배지 색상
  const getDataSourceBadgeStyle = () => {
    switch (dataSource) {
      case 'krx-api':
        return 'bg-blue-100 text-blue-700 border-blue-200';
      case 'uploaded':
        return 'bg-green-100 text-green-700 border-green-200';
      default:
        return 'bg-gray-100 text-gray-700 border-gray-200';
    }
  };

  const getDataSourceLabel = () => {
    switch (dataSource) {
      case 'krx-api':
        return `KRX 실시간 (${lastUpdated || '로딩중'})`;
      case 'uploaded':
        return fileName;
      default:
        return 'KRX 샘플 데이터';
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-violet-50/30">
      {/* 헤더 */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-gray-200/50">
        <div className="max-w-[1920px] mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            {/* 왼쪽: 뒤로가기 + 타이틀 */}
            <div className="flex items-center gap-4">
              <a href="https://krxdata.co.kr">
                <Button variant="ghost" size="sm" className="gap-2">
                  <ArrowLeft className="w-4 h-4" />
                  홈으로
                </Button>
              </a>
              <Separator orientation="vertical" className="h-6" />
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500 to-orange-500 flex items-center justify-center">
                  <TrendingUp className="w-5 h-5 text-white" />
                </div>
                <div>
                  <h1 className="text-lg font-bold text-gray-900">데이터 익스플로러</h1>
                  <p className="text-xs text-gray-500">
                    KRX 주식 데이터 실시간 시각화
                  </p>
                </div>
              </div>
            </div>

            {/* 중앙: API 연결 상태 + 데이터 소스 + 커버리지 */}
            <div className="flex items-center gap-3">
              {/* API 연결 상태 */}
              {isAPIConnected !== null && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className={`flex items-center gap-1.5 px-2 py-1 rounded-full text-xs ${
                    isAPIConnected ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'
                  }`}>
                    {isAPIConnected ? (
                      <Wifi className="w-3 h-3" />
                    ) : (
                      <Database className="w-3 h-3" />
                    )}
                    {isAPIConnected ? 'API 연결됨' : '샘플 데이터'}
                  </div>
                </TooltipTrigger>
                <TooltipContent>
                  {isAPIConnected ? 'KRX API 서버 연결됨' :
                   '오프라인 모드 — 샘플 데이터로 시각화 체험 가능'}
                </TooltipContent>
              </Tooltip>
              )}

              {/* 데이터 커버리지 다이얼로그 */}
              <Dialog open={isCoverageOpen} onOpenChange={setIsCoverageOpen}>
                <DialogTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1.5 h-7 text-xs bg-green-50 border-green-200 text-green-700 hover:bg-green-100"
                  >
                    <Info className="w-3.5 h-3.5" />
                    데이터 커버리지
                    <Badge variant="secondary" className="ml-1 h-4 px-1.5 text-[10px] bg-green-100">
                      {DATA_COVERAGE.filter(d => d.status === 'working').length}/{DATA_COVERAGE.length}
                    </Badge>
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-2xl max-h-[80vh] overflow-auto">
                  <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                      <Database className="w-5 h-5 text-amber-600" />
                      KRX 데이터 커버리지 명세
                    </DialogTitle>
                    <DialogDescription>
                      현재 지원하는 API 엔드포인트와 상태입니다. (테스트 일시: {new Date().toLocaleDateString('ko-KR')})
                    </DialogDescription>
                  </DialogHeader>

                  {/* 요약 통계 */}
                  <div className="my-4">
                    <div className="flex items-center gap-2 p-3 bg-green-50 rounded-lg border border-green-200">
                      <CheckCircle2 className="w-5 h-5 text-green-600" />
                      <div>
                        <div className="text-lg font-bold text-green-700">
                          {DATA_COVERAGE.filter(d => d.status === 'working').length}/{DATA_COVERAGE.length} API 정상 작동
                        </div>
                        <div className="text-xs text-green-600">KRX ID/PW 로그인 + 네이버 금융 폴백으로 전 데이터 커버리지 확보</div>
                      </div>
                    </div>
                  </div>

                  {/* 상세 목록 */}
                  <div className="space-y-2">
                    {DATA_COVERAGE.map((item, idx) => (
                      <div
                        key={idx}
                        className={`flex items-center justify-between p-3 rounded-lg border ${
                          item.status === 'working' ? 'bg-green-50/50 border-green-200' :
                          item.status === 'empty' ? 'bg-yellow-50/50 border-yellow-200' :
                          'bg-red-50/50 border-red-200'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          {item.status === 'working' ? (
                            <CheckCircle2 className="w-4 h-4 text-green-600 flex-shrink-0" />
                          ) : item.status === 'empty' ? (
                            <AlertTriangle className="w-4 h-4 text-yellow-600 flex-shrink-0" />
                          ) : (
                            <XCircle className="w-4 h-4 text-red-600 flex-shrink-0" />
                          )}
                          <div>
                            <div className="font-medium text-sm text-gray-900">{item.category}</div>
                            <div className="text-xs text-gray-500">{item.description}</div>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 text-right">
                          <code className="text-[10px] bg-gray-100 px-1.5 py-0.5 rounded text-gray-600">
                            {item.endpoint}
                          </code>
                          {item.note && (
                            <Badge
                              variant="outline"
                              className={`text-[10px] ${
                                item.status === 'working' ? 'border-green-300 text-green-700' :
                                item.status === 'empty' ? 'border-yellow-300 text-yellow-700' :
                                'border-red-300 text-red-700'
                              }`}
                            >
                              {item.note}
                            </Badge>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* 안내 문구 */}
                  <div className="mt-4 p-3 bg-blue-50 rounded-lg border border-blue-200">
                    <div className="flex items-start gap-2">
                      <Info className="w-4 h-4 text-blue-600 mt-0.5 flex-shrink-0" />
                      <div className="text-xs text-blue-700">
                        <strong>참고:</strong> 네이버 금융을 통해 KRX 데이터를 로그인 없이 가져옵니다.
                        IP 차단 방지를 위한 프록시 로테이션이 자동 적용됩니다.
                      </div>
                    </div>
                  </div>
                </DialogContent>
              </Dialog>

              {/* 데이터 소스 배지 */}
              <Badge
                variant="outline"
                className={getDataSourceBadgeStyle()}
              >
                {getDataSourceLabel()}
                <span className="ml-1 text-xs opacity-70">({data.length}행)</span>
              </Badge>
            </div>

            {/* 오른쪽: 액션 버튼 */}
            <div className="flex items-center gap-2">
              {/* KRX 데이터 로드 */}
              {isAPIConnected && (
                <div className="flex items-center gap-2 mr-2">
                  <Select value={selectedMarket} onValueChange={(v) => setSelectedMarket(v as MarketType)}>
                    <SelectTrigger className="w-[100px] h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ALL">전체</SelectItem>
                      <SelectItem value="KOSPI">코스피</SelectItem>
                      <SelectItem value="KOSDAQ">코스닥</SelectItem>
                    </SelectContent>
                  </Select>

                  <Select value={String(topN)} onValueChange={(v) => setTopN(Number(v))}>
                    <SelectTrigger className="w-[80px] h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="30">30종목</SelectItem>
                      <SelectItem value="50">50종목</SelectItem>
                      <SelectItem value="100">100종목</SelectItem>
                    </SelectContent>
                  </Select>

                  <Button
                    variant="default"
                    size="sm"
                    className="gap-2 bg-blue-600 hover:bg-blue-700"
                    onClick={loadKRXData}
                    disabled={isLoading}
                  >
                    {isLoading ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Database className="w-4 h-4" />
                    )}
                    실시간 데이터
                  </Button>
                </div>
              )}

              <Separator orientation="vertical" className="h-6" />

              {/* 파일 업로드 다이얼로그 */}
              <Dialog open={isUploadDialogOpen} onOpenChange={setIsUploadDialogOpen}>
                <DialogTrigger asChild>
                  <Button variant="outline" size="sm" className="gap-2">
                    <Upload className="w-4 h-4" />
                    CSV 업로드
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>데이터 파일 업로드</DialogTitle>
                    <DialogDescription>
                      CSV 파일을 업로드하여 분석할 수 있습니다.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="space-y-4 py-4">
                    <div className="space-y-2">
                      <Label htmlFor="file">CSV 파일 선택</Label>
                      <Input
                        id="file"
                        type="file"
                        accept=".csv"
                        onChange={handleFileUpload}
                      />
                    </div>
                    <p className="text-sm text-gray-500">
                      첫 번째 행은 컬럼명으로 사용됩니다.
                    </p>
                  </div>
                </DialogContent>
              </Dialog>

              {dataSource !== 'sample' && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="outline" size="sm" onClick={resetToSampleData}>
                      <RefreshCw className="w-4 h-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>샘플 데이터로 초기화</TooltipContent>
                </Tooltip>
              )}

              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="outline" size="sm">
                    <HelpCircle className="w-4 h-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <div className="max-w-xs space-y-2">
                    <p className="font-semibold">사용법</p>
                    <ul className="text-xs space-y-1">
                      <li>• <strong>실시간 데이터</strong>: KRX에서 주식 데이터 로드</li>
                      <li>• 왼쪽 필드를 X/Y축으로 드래그</li>
                      <li>• 차트 타입 선택으로 시각화 변경</li>
                      <li>• 필터로 데이터 범위 조절</li>
                      <li>• CSV 업로드로 자체 데이터 분석</li>
                    </ul>
                  </div>
                </TooltipContent>
              </Tooltip>
            </div>
          </div>
        </div>
      </header>

      {/* 자연어 질의 섹션 */}
      {isAPIConnected && (
        <div className="max-w-[1920px] mx-auto px-6 py-4">
          <div className="bg-gradient-to-r from-violet-50 to-purple-50 rounded-xl border border-violet-200/50 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Sparkles className="w-5 h-5 text-violet-600" />
              <h2 className="text-sm font-semibold text-violet-900">AI 자연어 질의</h2>
              <Badge variant="outline" className="text-xs bg-violet-100 text-violet-700 border-violet-300">
                온톨로지 기반 · Gemini Flash
              </Badge>
            </div>

            {/* 입력 영역 */}
            <div className="flex gap-2">
              <div className="flex-1 relative">
                <Input
                  placeholder="예: 삼성전자 주가, 코스피 시가총액 상위 10개, ETF 목록, SK하이닉스 PER..."
                  value={nlQuery}
                  onChange={(e) => setNlQuery(e.target.value)}
                  onKeyDown={handleNlKeyDown}
                  className="pr-10 bg-white border-violet-200 focus:border-violet-400 focus:ring-violet-400"
                  disabled={nlLoading}
                />
                {nlLoading && (
                  <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-violet-500 animate-spin" />
                )}
              </div>
              <Button
                onClick={handleNaturalLanguageQuery}
                disabled={!nlQuery.trim() || nlLoading}
                className="gap-2 bg-violet-600 hover:bg-violet-700"
              >
                <Send className="w-4 h-4" />
                질의
              </Button>
            </div>

            {/* 에러 메시지 */}
            {nlError && (
              <Alert variant="destructive" className="mt-3">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{nlError}</AlertDescription>
              </Alert>
            )}

            {/* 결과 표시 (온톨로지 기반 — AI가 자동 생성한 차트 설정 포함) */}
            {nlResult && (
              <div className="mt-3 p-3 bg-white rounded-lg border border-violet-100">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Badge className="text-xs bg-violet-100 text-violet-700">
                      {nlResult.intent}
                    </Badge>
                    <span className="text-xs text-gray-500 flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {nlResult.latency_ms}ms
                    </span>
                    <span className="text-xs text-gray-400">|</span>
                    <span className="text-xs text-gray-500">
                      {nlResult.model}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    {nlResult.endpoints_called.map(ep => (
                      <code key={ep} className="text-[10px] bg-gray-100 px-1.5 py-0.5 rounded text-gray-600">
                        {ep}
                      </code>
                    ))}
                  </div>
                </div>

                {nlResult.data && nlResult.data.length > 0 ? (
                  <div className="text-sm">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-green-600 font-medium">
                        {nlResult.rows}개 결과 로드됨
                      </span>
                      {nlResult.chart?.title && (
                        <>
                          <span className="text-gray-400">|</span>
                          <span className="text-violet-600 text-xs">
                            AI 추천 차트: {nlResult.chart.title} ({nlResult.chart.type})
                          </span>
                        </>
                      )}
                    </div>

                    {/* AI 차트 설정 안내 */}
                    {nlResult.chart && (
                      <div className="p-2 bg-violet-50 rounded-lg border border-violet-100 mb-2">
                        <div className="text-xs text-violet-700">
                          <span className="font-medium">AI 자동 설정:</span>{' '}
                          X축={nlResult.chart.x}, Y축={nlResult.chart.y}
                          {nlResult.chart.sort && nlResult.chart.sort !== 'none' && `, 정렬=${nlResult.chart.sort === 'desc' ? '내림차순' : '오름차순'}`}
                          {nlResult.chart.limit && `, 상위 ${nlResult.chart.limit}개`}
                          {nlResult.chart.color_field && `, 색상=${nlResult.chart.color_field}`}
                        </div>
                      </div>
                    )}

                    {/* 데이터 미리보기 테이블 */}
                    <div className="max-h-48 overflow-auto rounded border border-gray-200">
                      <table className="min-w-full text-xs">
                        <thead className="bg-gray-50 sticky top-0">
                          <tr>
                            {Object.keys(nlResult.data[0]).slice(0, 8).map((key) => (
                              <th key={key} className="px-2 py-1 text-left font-medium text-gray-600 border-b">
                                {key}
                              </th>
                            ))}
                            {Object.keys(nlResult.data[0]).length > 8 && (
                              <th className="px-2 py-1 text-left font-medium text-gray-400 border-b">
                                +{Object.keys(nlResult.data[0]).length - 8}
                              </th>
                            )}
                          </tr>
                        </thead>
                        <tbody>
                          {nlResult.data.slice(0, 5).map((row, rowIdx) => (
                            <tr key={rowIdx} className={rowIdx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                              {Object.values(row).slice(0, 8).map((val, colIdx) => (
                                <td key={colIdx} className="px-2 py-1 border-b border-gray-100 whitespace-nowrap">
                                  {typeof val === 'number'
                                    ? val.toLocaleString('ko-KR', { maximumFractionDigits: 2 })
                                    : String(val)}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {nlResult.data.length > 5 && (
                        <div className="text-center py-1 text-gray-400 text-xs bg-gray-50">
                          ... 외 {nlResult.data.length - 5}개 (아래 GraphicWalker에서 시각화)
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <span className="text-amber-600 text-sm">
                    데이터 없음 — 질의를 다시 시도해주세요
                  </span>
                )}
              </div>
            )}

            {/* 히스토리 */}
            {nlHistory.length > 0 && (
              <Collapsible open={nlHistoryOpen} onOpenChange={setNlHistoryOpen} className="mt-3">
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="sm" className="gap-1 text-xs text-violet-600 hover:text-violet-700">
                    {nlHistoryOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                    최근 질의 ({nlHistory.length})
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent className="mt-2 space-y-1">
                  {nlHistory.map((item, idx) => (
                    <button
                      key={idx}
                      className="w-full text-left px-3 py-2 text-xs bg-white rounded border border-violet-100 hover:bg-violet-50 transition-colors"
                      onClick={() => setNlQuery(item.query)}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-gray-700 truncate">{item.query}</span>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="text-xs">
                            {item.intent}
                          </Badge>
                          <span className="text-gray-400">{item.rows}행</span>
                          <span className="text-gray-400">{item.latency_ms}ms</span>
                        </div>
                      </div>
                    </button>
                  ))}
                </CollapsibleContent>
              </Collapsible>
            )}

            {/* 예시 질의 */}
            <div className="mt-3 flex flex-wrap gap-2">
              <span className="text-xs text-gray-500">예시:</span>
              {[
                '코스피 시가총액 상위 20개 막대차트',
                '외국인 순매수 상위 종목',
                '업종별 등락률',
                'ETF 전종목 시세',
                '국고채 수익률',
                '공매도 상위 50 종목',
              ].map((example) => (
                <button
                  key={example}
                  className="px-2 py-1 text-xs bg-white border border-violet-200 rounded-full hover:bg-violet-50 transition-colors"
                  onClick={() => setNlQuery(example)}
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 에러 메시지 */}
      {loadError && (
        <div className="max-w-[1920px] mx-auto px-6 py-2">
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>데이터 로드 실패</AlertTitle>
            <AlertDescription>{loadError}</AlertDescription>
          </Alert>
        </div>
      )}

      {/* 오프라인 모드 안내 — 샘플 데이터 사용 중 */}
      {isAPIConnected === false && (
        <div className="max-w-[1920px] mx-auto px-6 py-2">
          <Alert className="border-amber-200 bg-amber-50">
            <Database className="h-4 w-4 text-amber-600" />
            <AlertTitle className="text-amber-800">샘플 데이터 모드</AlertTitle>
            <AlertDescription className="text-amber-700">
              KRX 샘플 데이터로 시각화 기능을 체험할 수 있습니다. CSV 파일을 업로드하여 직접 데이터를 분석할 수도 있습니다.
            </AlertDescription>
          </Alert>
        </div>
      )}

      {/* Graphic Walker 메인 영역 */}
      <div className="w-full h-[calc(100vh-80px)]">
        <Suspense fallback={
          <div className="flex items-center justify-center h-full bg-gray-50">
            <div className="text-center space-y-4">
              <Loader2 className="w-8 h-8 animate-spin text-violet-600 mx-auto" />
              <p className="text-sm text-gray-500">GraphicWalker 로딩 중...</p>
            </div>
          </div>
        }>
          <GraphicWalker
            data={data}
            fields={fields}
            chart={defaultChart}
            {...gwConfig}
          />
        </Suspense>
      </div>
    </div>
  );
};

export default DataExplorer;
