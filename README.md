# KRX Data Explorer

<div align="center">

**한국거래소(KRX) 시장 데이터 — REST API + MCP 서버**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![MCP](https://img.shields.io/badge/MCP-FastMCP_2.0-8b5cf6?style=for-the-badge)](https://gofastmcp.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://reactjs.org)

</div>

---

## 개요

KRX(data.krx.co.kr)에 ID/PW로 직접 로그인하여 **31개 데이터 엔드포인트**를 제공합니다.

- **REST API**: FastAPI 기반 119개 라우트
- **MCP 서버**: AI가 직접 호출 가능한 35개 도구 (Claude Desktop, Cursor 등)
- **프론트엔드**: React + TypeScript 데이터 시각화

### 데이터 범위

| 카테고리 | 엔드포인트 | 데이터 |
|----------|-----------|--------|
| 주식 시세 | all_stock_price, stock_daily, market_cap, market_trading | KOSPI/KOSDAQ 전종목 |
| 외국인/PER | foreign_holding, foreign_exhaustion | PER/PBR/EPS/배당수익률 |
| 업종/지수 | sector_price, index_price, index_trend | KOSPI/KOSDAQ 51개 지수 |
| 투자자 | investor_summary, investor_trend, investor_daily, investor_by_stock, investor_top_net_buying | 13개 투자자 유형별 |
| 프로그램 | program_trading, program_daily | 차익/비차익 매매 |
| ETF/ETN/ELW | etf_price, etn_price, elw_price | 1,075 / 389 / 2,964개 |
| 공매도 | short_selling_all, short_selling_stock, short_selling_stock_daily, short_selling_investor, short_selling_top50, short_selling_balance | 전종목 + 상위50 + 잔고 |
| 파생상품 | derivative_price | 선물/옵션/미니/달러 |
| 채권 | bond_price, bond_yield, bond_yield_trend | 국채/회사채/CD |
| 기타 | dividend, issued_securities, gold_price | 배당/발행증권/금 |

---

## 빠른 시작

### 백엔드 (REST API)

```bash
cd backend
pip install -r requirements.txt

# 환경변수 (선택 — 기본값 있음)
export KRX_ID=your_id
export KRX_PW=your_password

# 서버 실행
uvicorn main:app --reload --port 8000
```

API 문서: http://localhost:8000/docs

### MCP 서버 (AI 도구)

```bash
cd backend

# stdio 모드 (Claude Desktop)
python krx_mcp.py

# SSE 모드 (웹 클라이언트)
python krx_mcp.py --transport sse
```

**Claude Desktop 설정** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "krx-data": {
      "command": "python",
      "args": ["path/to/backend/krx_mcp.py"]
    }
  }
}
```

### 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

http://localhost:5173

---

## 아키텍처

```
krx-data-explorer/
├── backend/
│   ├── krx_auth.py          # KRX ID/PW 로그인 + 세션 관리 (핵심)
│   ├── krx_mcp.py           # MCP 서버 (35개 도구)
│   ├── krx_direct.py        # outerLoader 우회 방식 (폴백)
│   ├── main.py              # FastAPI 앱 (119 라우트)
│   ├── naver_finance.py     # 네이버 금융 데이터 (폴백)
│   ├── proxy_rotator.py     # 프록시 로테이션
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── DataExplorer.tsx  # 메인 데이터 탐색 UI
│   │   └── components/ui/   # shadcn/ui
│   └── package.json
│
└── docs/                    # 다이어그램
```

### 데이터 수집 우선순위

```
KRX ID/PW 로그인 (krx_auth.py)
    ↓ 실패시
outerLoader 우회 (krx_direct.py)
    ↓ 실패시
네이버 금융 (naver_finance.py)
```

---

## 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | FastAPI, requests, pandas |
| MCP | FastMCP 2.x |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui |
| Data | KRX data.krx.co.kr (ID/PW 로그인) |

---

## 라이선스

MIT License
