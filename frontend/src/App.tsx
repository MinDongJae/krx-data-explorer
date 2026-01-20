// ============================================================================
// KRX Data Explorer - Standalone Application
// PyGWalker (Graphic Walker) 기반 시각화
// No-code 드래그앤드롭 데이터 분석 도구
// PyKRX API 연동으로 실시간 KRX 주식 데이터 제공
// ============================================================================

import React, { useState, useCallback, useMemo, useEffect } from 'react';
import { GraphicWalker } from '@kanaries/graphic-walker';
import '@kanaries/graphic-walker/dist/style.css';
import {
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
  Github,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
  TooltipProvider,
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

// 자연어 질의 API 응답 타입
interface NaturalLanguageResponse {
  query: string;
  intent: string;
  confidence: number;
  method: string;
  endpoint: string;
  parameters: Record<string, unknown>;
  latency_ms: number;
  executed?: boolean;
  result?: {
    success: boolean;
    data?: Record<string, unknown>[];
    error?: string;
    count?: number;
  };
}

interface DataField {
  fid: string;
  name: string;
  semanticType: 'nominal' | 'ordinal' | 'quantitative' | 'temporal';
  analyticType: 'dimension' | 'measure';
}

interface PyKRXResponse {
  date: string;
  count: number;
  data: Record<string, unknown>[];
  market?: string;
}

type DataSourceType = 'sample' | 'pykrx' | 'uploaded';
type MarketType = 'ALL' | 'KOSPI' | 'KOSDAQ';
type DataTypeOption = 'fundamental' | 'market-cap' | 'sector';

// ============================================================================
// PyKRX API 설정
// ============================================================================

const PYKRX_API_URL = import.meta.env.VITE_PYKRX_API_URL || 'http://localhost:8000';

// ============================================================================
// 샘플 데이터 (PyKRX 연결 실패 시 폴백)
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

// PyKRX API 필드 정의
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
// PyKRX API 함수
// ============================================================================

async function checkPyKRXConnection(): Promise<boolean> {
  try {
    const response = await fetch(`${PYKRX_API_URL}/`, {
      method: 'GET',
      signal: AbortSignal.timeout(3000)
    });
    return response.ok;
  } catch {
    return false;
  }
}

// 자연어 질의 API 호출
async function processNaturalLanguageQuery(
  query: string,
  execute: boolean = true
): Promise<NaturalLanguageResponse> {
  const response = await fetch(`${PYKRX_API_URL}/api/natural-language`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, execute }),
    signal: AbortSignal.timeout(30000)
  });

  if (!response.ok) {
    throw new Error(`Natural Language API Error: ${response.status}`);
  }

  return response.json();
}

async function fetchPyKRXData(
  dataType: DataTypeOption,
  market: MarketType,
  topN: number = 50
): Promise<PyKRXResponse> {
  let endpoint = '';
  const params = new URLSearchParams();

  if (dataType === 'fundamental') {
    if (market === 'ALL') {
      endpoint = '/api/stocks/all-markets';
      params.set('top_n', String(topN));
    } else {
      endpoint = '/api/stocks/fundamental';
      params.set('market', market);
      params.set('top_n', String(topN));
    }
  } else if (dataType === 'market-cap') {
    endpoint = '/api/stocks/market-cap';
    params.set('market', market === 'ALL' ? 'KOSPI' : market);
    params.set('top_n', String(topN));
  } else if (dataType === 'sector') {
    endpoint = '/api/stocks/sector';
    params.set('market', market === 'ALL' ? 'KOSPI' : market);
  }

  const response = await fetch(`${PYKRX_API_URL}${endpoint}?${params}`, {
    signal: AbortSignal.timeout(30000)
  });

  if (!response.ok) {
    throw new Error(`PyKRX API Error: ${response.status}`);
  }

  return response.json();
}

// ============================================================================
// 메인 App 컴포넌트
// ============================================================================

const App: React.FC = () => {
  // 상태
  const [data, setData] = useState<Record<string, unknown>[]>(krxSampleData);
  const [fields, setFields] = useState<DataField[]>(sampleFields);
  const [dataSource, setDataSource] = useState<DataSourceType>('sample');
  const [fileName, setFileName] = useState<string>('');
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false);

  // PyKRX 관련 상태
  const [isPyKRXConnected, setIsPyKRXConnected] = useState<boolean | null>(null);
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
  const [selectedDataType] = useState<DataTypeOption>('fundamental');
  const [topN, setTopN] = useState<number>(50);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  // PyKRX 연결 확인
  useEffect(() => {
    const checkConnection = async () => {
      const connected = await checkPyKRXConnection();
      setIsPyKRXConnected(connected);
    };
    checkConnection();
  }, []);

  // 자연어 질의 처리
  const handleNaturalLanguageQuery = useCallback(async () => {
    if (!nlQuery.trim() || nlLoading) return;

    setNlLoading(true);
    setNlError(null);
    setNlResult(null);

    try {
      const result = await processNaturalLanguageQuery(nlQuery.trim(), true);
      setNlResult(result);

      // 히스토리에 추가 (최대 10개)
      setNlHistory(prev => [result, ...prev.slice(0, 9)]);

      // 실행 결과가 데이터 배열이면 GraphicWalker에 로드
      if (result.executed && result.result?.success && result.result.data && result.result.data.length > 0) {
        const resultData = result.result.data;

        // 동적으로 필드 생성
        const sampleRow = resultData[0];
        const dynamicFields: DataField[] = Object.keys(sampleRow).map(key => {
          const value = sampleRow[key];
          const isNumber = typeof value === 'number';
          const isDate = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}/.test(value);

          return {
            fid: key,
            name: key,
            semanticType: isDate ? 'temporal' : isNumber ? 'quantitative' : 'nominal',
            analyticType: isNumber ? 'measure' : 'dimension',
          };
        });

        setData(resultData);
        setFields(dynamicFields);
        setDataSource('pykrx');
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

  // PyKRX 데이터 로드
  const loadPyKRXData = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);

    try {
      const response = await fetchPyKRXData(selectedDataType, selectedMarket, topN);

      if (response.data && response.data.length > 0) {
        setData(response.data);
        setFields(pykrxFields);
        setDataSource('pykrx');
        setLastUpdated(response.date);
      } else {
        throw new Error('데이터가 없습니다');
      }
    } catch (error) {
      console.error('PyKRX 데이터 로드 실패:', error);
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

  // Graphic Walker 설정
  const gwConfig = useMemo(() => ({
    i18nLang: 'ko-KR' as const,
    themeKey: 'vega' as const,
    dark: 'light' as const,
  }), []);

  // 데이터 소스 배지 색상
  const getDataSourceBadgeStyle = () => {
    switch (dataSource) {
      case 'pykrx':
        return 'bg-blue-100 text-blue-700 border-blue-200';
      case 'uploaded':
        return 'bg-green-100 text-green-700 border-green-200';
      default:
        return 'bg-gray-100 text-gray-700 border-gray-200';
    }
  };

  const getDataSourceLabel = () => {
    switch (dataSource) {
      case 'pykrx':
        return `PyKRX 실시간 (${lastUpdated || '로딩중'})`;
      case 'uploaded':
        return fileName;
      default:
        return 'KRX 샘플 데이터';
    }
  };

  return (
    <TooltipProvider>
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-violet-50/30">
        {/* 헤더 */}
        <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-gray-200/50">
          <div className="max-w-[1920px] mx-auto px-6 py-4">
            <div className="flex items-center justify-between">
              {/* 왼쪽: 타이틀 */}
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500 to-orange-500 flex items-center justify-center">
                    <TrendingUp className="w-5 h-5 text-white" />
                  </div>
                  <div>
                    <h1 className="text-lg font-bold text-gray-900">KRX Data Explorer</h1>
                    <p className="text-xs text-gray-500">
                      PyGWalker + PyKRX 실시간 시각화
                    </p>
                  </div>
                </div>
              </div>

              {/* 중앙: PyKRX 연결 상태 + 데이터 소스 */}
              <div className="flex items-center gap-3">
                {/* PyKRX 연결 상태 */}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className={`flex items-center gap-1.5 px-2 py-1 rounded-full text-xs ${
                      isPyKRXConnected === null ? 'bg-gray-100 text-gray-500' :
                      isPyKRXConnected ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                    }`}>
                      {isPyKRXConnected === null ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : isPyKRXConnected ? (
                        <Wifi className="w-3 h-3" />
                      ) : (
                        <WifiOff className="w-3 h-3" />
                      )}
                      PyKRX
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>
                    {isPyKRXConnected === null ? '연결 확인 중...' :
                     isPyKRXConnected ? 'PyKRX API 연결됨 (localhost:8000)' :
                     'PyKRX API 연결 안됨 - 샘플 데이터 사용'}
                  </TooltipContent>
                </Tooltip>

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
                {/* PyKRX 데이터 로드 */}
                {isPyKRXConnected && (
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
                      onClick={loadPyKRXData}
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
                        <li>• <strong>실시간 데이터</strong>: PyKRX에서 주식 데이터 로드</li>
                        <li>• 왼쪽 필드를 X/Y축으로 드래그</li>
                        <li>• 차트 타입 선택으로 시각화 변경</li>
                        <li>• 필터로 데이터 범위 조절</li>
                        <li>• CSV 업로드로 자체 데이터 분석</li>
                      </ul>
                    </div>
                  </TooltipContent>
                </Tooltip>

                <a
                  href="https://github.com/your-username/krx-data-explorer"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Button variant="outline" size="sm">
                    <Github className="w-4 h-4" />
                  </Button>
                </a>
              </div>
            </div>
          </div>
        </header>

        {/* 자연어 질의 섹션 */}
        {isPyKRXConnected && (
          <div className="max-w-[1920px] mx-auto px-6 py-4">
            <div className="bg-gradient-to-r from-violet-50 to-purple-50 rounded-xl border border-violet-200/50 p-4">
              <div className="flex items-center gap-2 mb-3">
                <Sparkles className="w-5 h-5 text-violet-600" />
                <h2 className="text-sm font-semibold text-violet-900">AI 자연어 질의</h2>
                <Badge variant="outline" className="text-xs bg-violet-100 text-violet-700 border-violet-300">
                  Hybrid Intent Classification
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

              {/* 결과 표시 */}
              {nlResult && (
                <div className="mt-3 p-3 bg-white rounded-lg border border-violet-100">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Badge className={`text-xs ${
                        nlResult.confidence >= 0.8 ? 'bg-green-100 text-green-700' :
                        nlResult.confidence >= 0.5 ? 'bg-yellow-100 text-yellow-700' :
                        'bg-red-100 text-red-700'
                      }`}>
                        {nlResult.intent}
                      </Badge>
                      <span className="text-xs text-gray-500">
                        신뢰도: {(nlResult.confidence * 100).toFixed(1)}%
                      </span>
                      <span className="text-xs text-gray-400">|</span>
                      <span className="text-xs text-gray-500">
                        방법: {nlResult.method}
                      </span>
                      <span className="text-xs text-gray-400">|</span>
                      <span className="text-xs text-gray-500 flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {nlResult.latency_ms.toFixed(0)}ms
                      </span>
                    </div>
                    <code className="text-xs bg-gray-100 px-2 py-1 rounded">
                      {nlResult.endpoint}
                    </code>
                  </div>

                  {nlResult.executed && nlResult.result && (
                    <div className="text-sm">
                      {nlResult.result.success ? (
                        <>
                          <span className="text-green-600">
                            {nlResult.result.count ?? nlResult.result.data?.length ?? 0}개 결과 로드됨
                          </span>
                          {/* 데이터 미리보기 테이블 */}
                          {nlResult.result.data && nlResult.result.data.length > 0 && (
                            <div className="mt-3 max-h-48 overflow-auto rounded border border-gray-200">
                              <table className="min-w-full text-xs">
                                <thead className="bg-gray-50 sticky top-0">
                                  <tr>
                                    {Object.keys(nlResult.result.data[0]).map((key) => (
                                      <th key={key} className="px-2 py-1 text-left font-medium text-gray-600 border-b">
                                        {key}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {nlResult.result.data.slice(0, 10).map((row, rowIdx) => (
                                    <tr key={rowIdx} className={rowIdx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                      {Object.values(row).map((val, colIdx) => (
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
                              {nlResult.result.data.length > 10 && (
                                <div className="text-center py-1 text-gray-400 text-xs bg-gray-50">
                                  ... 외 {nlResult.result.data.length - 10}개 더
                                </div>
                              )}
                            </div>
                          )}
                        </>
                      ) : (
                        <span className="text-red-600">
                          실행 실패: {nlResult.result.error}
                        </span>
                      )}
                    </div>
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
                            <span className="text-gray-400">{item.latency_ms.toFixed(0)}ms</span>
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
                  '삼성전자 주가',
                  '코스피 시가총액 상위 10개',
                  'ETF 목록',
                  'SK하이닉스 외국인 보유율',
                  '코스닥150 지수',
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

        {/* PyKRX 미연결 안내 */}
        {isPyKRXConnected === false && (
          <div className="max-w-[1920px] mx-auto px-6 py-2">
            <Alert>
              <WifiOff className="h-4 w-4" />
              <AlertTitle>PyKRX API 서버 연결 안됨</AlertTitle>
              <AlertDescription>
                실시간 데이터를 사용하려면 PyKRX 서버를 시작하세요:
                <code className="ml-2 px-2 py-1 bg-gray-100 rounded text-sm">
                  cd backend && python main.py
                </code>
              </AlertDescription>
            </Alert>
          </div>
        )}

        {/* Graphic Walker 메인 영역 */}
        <div className="w-full h-[calc(100vh-80px)]">
          <GraphicWalker
            data={data}
            fields={fields}
            {...gwConfig}
          />
        </div>
      </div>
    </TooltipProvider>
  );
};

export default App;
