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
Generate a 1920x1080 pixel professional banner image.

CRITICAL TEXT REQUIREMENTS:
- Main title: "KRX Data Explorer" in 72pt bold Arial/Helvetica white font
- Subtitle: "Korea Exchange Data Platform" in 36pt white font
- ALL TEXT MUST BE PERFECTLY SHARP AND READABLE - no blur, no distortion
- Use simple sans-serif fonts only

DESIGN:
- Background: solid dark blue (#0f172a) gradient to navy (#1e3a5a)
- Left side: simple green candlestick chart icon (3-4 bars)
- Right side: simple pie chart icon
- Center: the text
- Minimalist, clean, professional fintech style
- NO Korean text (to avoid font rendering issues)
- NO complex graphics, keep it simple and sharp
"""

response = model.generate_content(hero_prompt)
save_image(response, OUTPUT_DIR / 'hero-banner.png')

# 2. 시스템 아키텍처 다이어그램
print("2. Generating architecture diagram...")
arch_prompt = """
Generate a 1200x800 pixel system architecture diagram.

CRITICAL: ALL TEXT MUST BE PERFECTLY SHARP AND READABLE.

LAYOUT (3 horizontal layers, top to bottom):

TOP LAYER - Blue box (#3b82f6):
- Text: "FRONTEND" in bold 24pt white
- Below: "React + TypeScript + Vite" in 16pt white

MIDDLE LAYER - Dark blue box (#1e40af):
- Text: "BACKEND" in bold 24pt white
- Below: "FastAPI + PyKRX + NLP" in 16pt white

BOTTOM LAYER - Green box (#10b981):
- Text: "KRX DATA" in bold 24pt white
- Below: "OHLCV, Market Cap, ETF" in 16pt white

ARROWS:
- Down arrow between each layer
- Labels: "REST API" and "Web Scraping"

STYLE:
- Pure white background
- Simple rounded rectangles with slight shadow
- Use only Arial/Helvetica fonts
- NO icons, text only
- Clean, minimal, professional
"""

response = model.generate_content(arch_prompt)
save_image(response, OUTPUT_DIR / 'architecture-diagram.png')

# 3. 데이터 플로우 다이어그램
print("3. Generating data flow diagram...")
flow_prompt = """
Generate a 1400x500 pixel horizontal flowchart.

CRITICAL: ALL TEXT MUST BE PERFECTLY SHARP AND READABLE.

FLOW (left to right, 5 steps connected by arrows):

STEP 1 - Blue circle:
- Text: "USER QUERY" in 16pt bold

STEP 2 - Purple rounded rectangle:
- Text: "NLP CLASSIFIER" in 16pt bold

STEP 3 - Orange rounded rectangle:
- Text: "API ROUTER" in 16pt bold

STEP 4 - Green rounded rectangle:
- Text: "KRX DATA" in 16pt bold

STEP 5 - Blue circle:
- Text: "RESPONSE" in 16pt bold

ARROWS:
- Simple right-pointing arrows between each step
- Arrow color: gray (#6b7280)

STYLE:
- Pure white background
- Each shape has subtle drop shadow
- Use only Arial/Helvetica fonts
- NO icons, just colored shapes with text
- Clean, professional diagram style
"""

response = model.generate_content(flow_prompt)
save_image(response, OUTPUT_DIR / 'data-flow-diagram.png')

# 4. UI 목업 / 대시보드 프리뷰
print("4. Generating UI mockup...")
ui_prompt = """
Generate a 1920x1080 pixel dashboard UI mockup screenshot.

CRITICAL: ALL TEXT MUST BE PERFECTLY SHARP AND READABLE.

LAYOUT:

TOP BAR (dark gray #1f2937, 60px height):
- Left: "KRX Explorer" logo text in white 20pt
- Center: Search input box
- Right: User icon

LEFT SIDEBAR (dark gray #111827, 200px width):
- Menu items in white 14pt text:
  - "Dashboard"
  - "OHLCV Data"
  - "Market Cap"
  - "Investor Flow"
  - "NL Query"

MAIN CONTENT (gray #374151 background):
- Header: "Samsung Electronics (005930)" in white 28pt
- Large price: "71,200 KRW" in green (#10b981) 48pt
- Below: "+2.3%" in green 24pt
- 4 stat cards in a row (dark boxes with white text):
  - "PER: 12.5"
  - "PBR: 1.2"
  - "Volume: 15M"
  - "MCap: 450T"
- Below: Simple line chart (green line on dark background)
- Bottom: Data table with 5 rows

STYLE:
- Dark mode fintech dashboard
- Use only Arial/Helvetica fonts
- English text only (no Korean)
- Clean, modern Bloomberg-style
"""

response = model.generate_content(ui_prompt)
save_image(response, OUTPUT_DIR / 'ui-mockup.png')

# 5. 기능 아이콘 그리드
print("5. Generating features grid...")
features_prompt = """
Generate a 1200x800 pixel feature grid image.

CRITICAL: ALL TEXT MUST BE PERFECTLY SHARP AND READABLE.

LAYOUT: 2 rows x 3 columns grid of feature cards

ROW 1:
- Card 1: Blue icon, text "OHLCV Data" in 18pt bold
- Card 2: Green icon, text "Market Cap" in 18pt bold
- Card 3: Purple icon, text "Investor Flow" in 18pt bold

ROW 2:
- Card 4: Orange icon, text "NL Query" in 18pt bold
- Card 5: Teal icon, text "ETF/ETN" in 18pt bold
- Card 6: Red icon, text "Search" in 18pt bold

EACH CARD:
- White background with subtle shadow
- Rounded corners (16px)
- Simple geometric icon (circle, square, or triangle)
- Text centered below icon

STYLE:
- Light gray background (#f1f5f9)
- Equal spacing between cards
- Use only Arial/Helvetica fonts
- English text only
- Minimal, modern design
"""

response = model.generate_content(features_prompt)
save_image(response, OUTPUT_DIR / 'features-grid.png')

print("All diagrams generated!")
print(f"Output: {OUTPUT_DIR}")
