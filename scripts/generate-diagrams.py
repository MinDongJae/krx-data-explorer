#!/usr/bin/env python3
"""
KRX Data Explorer - 고품질 다이어그램 생성
Gemini 2.0 Flash Exp API 직접 호출
"""

import google.generativeai as genai
import base64
import os
from pathlib import Path

# Gemini API 설정
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

model = genai.GenerativeModel(
    model_name='gemini-2.0-flash-exp',
    generation_config={
        'response_modalities': ['TEXT', 'IMAGE']
    }
)

OUTPUT_DIR = Path(__file__).parent.parent / 'docs'
OUTPUT_DIR.mkdir(exist_ok=True)

def save_image(response, output_path):
    """Gemini 응답에서 이미지 추출 및 저장"""
    for part in response.candidates[0].content.parts:
        if hasattr(part, 'inline_data') and part.inline_data:
            img_data = part.inline_data.data
            if isinstance(img_data, str):
                img_data = base64.b64decode(img_data)
            with open(output_path, 'wb') as f:
                f.write(img_data)
            print(f"  Saved: {output_path} ({len(img_data):,} bytes)")
            return True
    return False

# 1. 히어로 배너 (프로젝트 소개)
print("1. Generating hero banner...")
hero_prompt = """
Create a modern, professional hero banner image for "KRX Data Explorer" project.

Design requirements:
- Clean, minimalist tech aesthetic with dark blue (#1a1a2e) to purple (#4a0080) gradient background
- Centered title "KRX Data Explorer" in bold white sans-serif font (clearly readable)
- Subtitle below: "한국거래소 데이터 탐색기" in smaller white text
- Left side: Abstract stock chart visualization with glowing green/red candlesticks
- Right side: Circular data visualization with interconnected nodes
- Bottom: Subtle wave pattern representing data flow
- Overall mood: Professional fintech, modern Korean tech aesthetic
- Aspect ratio: 16:9 (1920x1080 style)
- NO photographs of people, pure graphic design
- Text must be CRISP and READABLE
"""

response = model.generate_content(hero_prompt)
save_image(response, OUTPUT_DIR / 'hero-banner.png')

# 2. 시스템 아키텍처 다이어그램
print("2. Generating architecture diagram...")
arch_prompt = """
Create a clean, modern system architecture diagram for a stock data application.

Layout (top to bottom, 3 layers):
LAYER 1 - FRONTEND (light blue box):
- Icons for: React, TypeScript, Vite, Tailwind CSS, GraphicWalker
- Label: "Frontend - React + TypeScript"

LAYER 2 - BACKEND (dark blue box):
- Icons for: FastAPI (Python), NLP Intent Classifier, Session Manager
- Label: "Backend - FastAPI + PyKRX"

LAYER 3 - DATA SOURCE (green box):
- KRX Data Marketplace logo/icon
- Data types: OHLCV, Market Cap, Investor Trading, ETF/ETN

Connections:
- Arrow from Frontend to Backend labeled "REST API"
- Arrow from Backend to KRX labeled "Web Scraping + API"

Style:
- White background with subtle grid pattern
- Rounded rectangle boxes with shadows
- Modern flat design icons
- Clear Korean/English labels
- Professional color scheme (blues, greens)
- Size: 1200x800 pixels style
"""

response = model.generate_content(arch_prompt)
save_image(response, OUTPUT_DIR / 'architecture-diagram.png')

# 3. 데이터 플로우 다이어그램
print("3. Generating data flow diagram...")
flow_prompt = """
Create a horizontal data flow diagram showing natural language query processing.

Flow (left to right):
1. USER INPUT (blue circle):
   - Korean text bubble: "삼성전자 PER 알려줘"
   - Icon: person or chat bubble

2. NLP CLASSIFIER (purple hexagon):
   - Label: "Intent Classifier"
   - Sub-label: "의도 분류"
   - Arrow showing transformation

3. API ROUTER (orange rectangle):
   - Label: "API Router"
   - Shows endpoint: "/api/fundamental"
   - Parameters extracted

4. DATA FETCH (green box):
   - Label: "KRX Data"
   - Shows data table icon

5. RESPONSE (blue circle):
   - Label: "JSON Response"
   - Shows chart visualization

Style:
- Clean white background
- Colorful flat icons for each step
- Curved arrows connecting each step
- Korean labels with English subtitles
- Modern, friendly design
- Size: 1400x500 pixels style
"""

response = model.generate_content(flow_prompt)
save_image(response, OUTPUT_DIR / 'data-flow-diagram.png')

# 4. UI 목업 / 대시보드 프리뷰
print("4. Generating UI mockup...")
ui_prompt = """
Create a UI mockup of a stock data dashboard application.

Dashboard layout:
TOP BAR:
- Logo "KRX Explorer" on left
- Search bar in center with Korean placeholder "종목 검색..."
- User menu on right

LEFT SIDEBAR:
- Navigation menu items with icons:
  - 대시보드 (Dashboard)
  - OHLCV 조회
  - 시가총액
  - 투자자 동향
  - 자연어 질의

MAIN CONTENT:
- Header: "삼성전자 (005930)"
- Price display: "71,200원" in large green text with "+2.3%"
- Row of 4 stat cards: PER, PBR, 시가총액, 거래량
- Below: Line chart showing stock price over time
- Bottom: Data table with columns (날짜, 시가, 고가, 저가, 종가, 거래량)

Style:
- Dark mode theme (dark gray #1f2937 background)
- Accent colors: green for positive, red for negative
- Clean modern UI like Bloomberg Terminal meets modern web
- Korean labels throughout
- Crisp typography
- Size: 1920x1080 desktop style
"""

response = model.generate_content(ui_prompt)
save_image(response, OUTPUT_DIR / 'ui-mockup.png')

# 5. 기능 아이콘 그리드
print("5. Generating features grid...")
features_prompt = """
Create a 2x3 grid of feature icons for a stock data application.

Grid items (each with icon + Korean label):
1. 📊 OHLCV 데이터 - candlestick chart icon
2. 💰 시가총액 - pie chart with coins
3. 📈 투자자 동향 - bar chart with arrows
4. 💬 자연어 질의 - chat bubble with Korean text
5. 📋 ETF/ETN/ELW - stacked documents icon
6. 🔍 실시간 검색 - magnifying glass with graph

Style:
- Each item in a rounded card with subtle shadow
- Consistent icon style (flat, colorful)
- Light background (#f8fafc)
- Blue accent color (#3b82f6)
- Korean labels centered below each icon
- Modern, clean aesthetic
- Size: 1200x800 pixels
"""

response = model.generate_content(features_prompt)
save_image(response, OUTPUT_DIR / 'features-grid.png')

print("\n✅ All diagrams generated successfully!")
print(f"   Output directory: {OUTPUT_DIR}")
