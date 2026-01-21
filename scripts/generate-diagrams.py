#!/usr/bin/env python3
"""
KRX Data Explorer - 고품질 다이어그램 생성
Gemini 2.5 Flash API 사용 (텍스트 렌더링 최적화)

참고: https://developers.googleblog.com/en/how-to-prompt-gemini-2-5-flash-image-generation-for-the-best-results/
"""

import google.generativeai as genai
import base64
import os
from pathlib import Path

# Gemini API 설정 - 2.5 Flash로 업그레이드 (텍스트 렌더링 향상)
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

model = genai.GenerativeModel(
    model_name='gemini-2.5-flash-image',  # 이미지 생성 전용 모델
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
            print(f"  [OK] Saved: {output_path} ({len(img_data):,} bytes)")
            return True
    print(f"  [FAIL] No image in response for {output_path}")
    return False

# ============================================================
# 1. 히어로 배너 (프로젝트 소개) - Gemini로 생성
# ============================================================
print("1. Generating hero banner...")
hero_prompt = """
Create a professional, modern hero banner for a fintech data platform.

Scene description: A sleek, dark-themed financial dashboard interface floating in a deep navy blue digital space. The background has a subtle gradient from dark navy (#0a1628) to slightly lighter navy (#1a2744). Abstract geometric patterns of hexagons and circuit-like lines glow softly in electric blue (#3b82f6) in the background.

In the center, display the title "KRX Data Explorer" in large, bold, clean white sans-serif typography (similar to Inter or SF Pro Display font). Below it, show the subtitle "Korea Exchange Stock Data Platform" in smaller, light gray text.

On the left side, include a simplified green candlestick chart icon showing 4 bars going upward. On the right side, show a minimal pie chart icon in teal color.

The overall style should be: minimalist, professional, fintech-inspired, with a Bloomberg Terminal or trading platform aesthetic. High contrast between text and background for maximum readability.

Dimensions: 1920x600 pixels, landscape orientation.
"""

try:
    response = model.generate_content(hero_prompt)
    save_image(response, OUTPUT_DIR / 'hero-banner.png')
except Exception as e:
    print(f"  [ERROR] {e}")

# ============================================================
# 2. 시스템 아키텍처 다이어그램 - Gemini로 생성
# ============================================================
print("2. Generating architecture diagram...")
arch_prompt = """
Create a clean, professional system architecture diagram with three horizontal layers.

Scene description: A vertical stack of three rounded rectangular boxes on a pure white background, connected by downward-pointing arrows.

TOP BOX (Sky Blue #3b82f6):
- Contains bold white text "FRONTEND"
- Below it in smaller white text: "React + TypeScript + Vite"
- The box has subtle rounded corners and a light shadow

MIDDLE BOX (Deep Blue #1e40af):
- Contains bold white text "BACKEND"
- Below it in smaller white text: "FastAPI + PyKRX + NLP"
- Connected from top box with a dark gray arrow labeled "REST API"

BOTTOM BOX (Emerald Green #10b981):
- Contains bold white text "KRX DATA"
- Below it in smaller white text: "OHLCV, Market Cap, ETF, Investor"
- Connected from middle box with a dark gray arrow labeled "Web Scraping"

Style: Clean technical diagram, minimal design, sans-serif fonts only, high contrast text, professional documentation style. All text must be perfectly legible and sharp.

Dimensions: 1200x800 pixels.
"""

try:
    response = model.generate_content(arch_prompt)
    save_image(response, OUTPUT_DIR / 'architecture-diagram.png')
except Exception as e:
    print(f"  [ERROR] {e}")

# ============================================================
# 3. 데이터 플로우 다이어그램 - Gemini로 생성
# ============================================================
print("3. Generating data flow diagram...")
flow_prompt = """
Create a horizontal flowchart showing data flow from left to right.

Scene description: Five connected shapes arranged horizontally on a clean white background, with gray arrows pointing right between each shape.

From left to right:
1. BLUE CIRCLE - Contains text "User Query" in white
2. PURPLE ROUNDED RECTANGLE - Contains text "NLP Classifier" in white
3. ORANGE ROUNDED RECTANGLE - Contains text "API Router" in white
4. GREEN ROUNDED RECTANGLE - Contains text "KRX Data" in white
5. BLUE CIRCLE - Contains text "Response" in white

Each shape has a subtle drop shadow. The arrows between shapes are gray (#6b7280) and have pointed tips.

Style: Professional flowchart, clean lines, bold sans-serif text, high readability, technical documentation aesthetic.

Dimensions: 1400x400 pixels, wide landscape format.
"""

try:
    response = model.generate_content(flow_prompt)
    save_image(response, OUTPUT_DIR / 'data-flow-diagram.png')
except Exception as e:
    print(f"  [ERROR] {e}")

# ============================================================
# 4. UI 목업 - Gemini로 생성 (다크 대시보드)
# ============================================================
print("4. Generating UI mockup...")
ui_prompt = """
Create a dark-themed financial dashboard UI mockup, similar to Bloomberg Terminal or TradingView.

Scene description: A full dashboard interface with dark gray background (#111827).

TOP NAVIGATION BAR (darker gray #0f172a):
- Left: Logo text "KRX Explorer" in white
- Center: A search input field with placeholder text
- Right: A simple user avatar circle

LEFT SIDEBAR (dark gray #1f2937, narrow):
- Menu items in vertical list, white text:
  "Dashboard" (highlighted with blue accent)
  "OHLCV Data"
  "Market Cap"
  "Investors"
  "ETF/ETN"

MAIN CONTENT AREA:
- Header showing "Samsung Electronics" in large white text
- Stock code "005930" in gray
- Large green price "71,200" with up arrow and "+2.3%"
- Below: Four metric cards in a row showing:
  "PER 12.5" | "PBR 1.2" | "Volume 15M" | "MCap 450T"
- Below cards: A simple green line chart on dark background
- Bottom: A data table with 5 rows of stock data

Style: Modern fintech dashboard, dark mode, clean typography, professional trading platform aesthetic. All text must be sharp and perfectly readable.

Dimensions: 1920x1080 pixels.
"""

try:
    response = model.generate_content(ui_prompt)
    save_image(response, OUTPUT_DIR / 'ui-mockup.png')
except Exception as e:
    print(f"  [ERROR] {e}")

# ============================================================
# 5. 기능 그리드 - Gemini로 생성
# ============================================================
print("5. Generating features grid...")
features_prompt = """
Create a feature showcase grid with 6 feature cards arranged in 2 rows of 3.

Scene description: Six white cards with rounded corners arranged in a grid pattern on a light gray (#f1f5f9) background.

ROW 1 (left to right):
- Card 1: Blue circle icon, text "OHLCV Data" below, subtitle "Price & Volume"
- Card 2: Green circle icon, text "Market Cap" below, subtitle "Company Size"
- Card 3: Purple circle icon, text "Investor Flow" below, subtitle "Buy/Sell Trends"

ROW 2 (left to right):
- Card 4: Orange circle icon, text "NL Query" below, subtitle "Ask in Korean"
- Card 5: Teal circle icon, text "ETF/ETN" below, subtitle "Derivatives"
- Card 6: Red circle icon, text "Search" below, subtitle "Find Stocks"

Each card has:
- White background
- Subtle shadow
- Rounded corners (16px)
- Simple geometric icon (filled circle in the specified color)
- Bold feature name
- Lighter gray subtitle text

Style: Clean, modern card grid, minimal icons, professional SaaS marketing style. All text perfectly sharp and readable.

Dimensions: 1200x700 pixels.
"""

try:
    response = model.generate_content(features_prompt)
    save_image(response, OUTPUT_DIR / 'features-grid.png')
except Exception as e:
    print(f"  [ERROR] {e}")

print("\n" + "="*60)
print("All diagrams generated!")
print(f"Output directory: {OUTPUT_DIR}")
print("="*60)
