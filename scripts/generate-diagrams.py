#!/usr/bin/env python3
"""
KRX Data Explorer - 고품질 다이어그램 생성
Gemini 2.5 Flash Image API 사용 (텍스트 렌더링 최적화)

실제 프로젝트 UI 반영:
- PyGWalker (Graphic Walker) 기반 데이터 시각화
- 바이올렛/오렌지 테마 (violet-50, amber-500)
- AI 자연어 질의 기능
- KRX 주식 데이터 실시간 분석

참고: https://developers.googleblog.com/en/how-to-prompt-gemini-2-5-flash-image-generation-for-the-best-results/
"""

import google.generativeai as genai
import base64
import os
from pathlib import Path

# Gemini API 설정 - 2.5 Flash Image (텍스트 렌더링 향상)
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

model = genai.GenerativeModel(
    model_name='gemini-2.5-flash-image',
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
# 1. 히어로 배너 (프로젝트 소개)
# ============================================================
print("1. Generating hero banner...")
hero_prompt = """
Create a premium, modern hero banner for a Korean stock market data visualization platform.

Scene description: A wide landscape banner with a sophisticated gradient background flowing from soft lavender-violet (#8b5cf6) on the left to warm amber-orange (#f59e0b) on the right. The gradient should be smooth and elegant, reminiscent of a sunset over a financial district.

In the center-left area, display the main title "KRX Data Explorer" in large, bold, crisp white sans-serif typography. The text should be perfectly sharp and readable, styled like Inter or Pretendard font. Below the main title, show the Korean subtitle "한국거래소 주식 데이터 시각화 플랫폼" in smaller light gray text.

On the right side of the banner, show a stylized preview of a data visualization dashboard: a floating glass-morphism card with a simple bar chart showing 5 colorful bars (orange, violet, teal, blue, green) representing different stock metrics. The chart should have clean gridlines and look professional.

Include subtle decorative elements: small floating sparkle icons near the title (representing AI features), and faint hexagonal patterns in the background suggesting technology and data.

Overall aesthetic: Premium SaaS product, modern fintech, clean and professional. High contrast for text readability. No cluttered elements.

Dimensions: 1920x500 pixels, wide landscape format.
"""

try:
    response = model.generate_content(hero_prompt)
    save_image(response, OUTPUT_DIR / 'hero-banner.png')
except Exception as e:
    print(f"  [ERROR] {e}")

# ============================================================
# 2. 시스템 아키텍처 다이어그램
# ============================================================
print("2. Generating architecture diagram...")
arch_prompt = """
Create a clean, professional system architecture diagram showing the data flow of a stock market visualization platform.

Scene description: A diagram on a clean white background with three main sections connected by arrows, arranged vertically.

TOP SECTION - "FRONTEND" (Violet #8b5cf6 rounded rectangle):
- Inside the box, show text "React + TypeScript" in white
- Below it: "PyGWalker Visualization" in smaller text
- Include a small chart icon

MIDDLE SECTION - "BACKEND" (Orange #f59e0b rounded rectangle):
- Inside the box, show text "FastAPI + Python" in white
- Below it: "PyKRX + NLP Engine" in smaller text
- Include a small server icon

BOTTOM SECTION - "DATA SOURCE" (Teal #14b8a6 rounded rectangle):
- Inside the box, show text "KRX API" in white
- Below it: "OHLCV, Market Cap, ETF" in smaller text
- Include a small database icon

ARROWS connecting the sections:
- Arrow from Frontend to Backend labeled "REST API"
- Arrow from Backend to Data Source labeled "Real-time Data"

Each box should have subtle shadows and rounded corners (16px radius). The arrows should be dark gray (#374151) with clean arrowheads.

Style: Technical documentation quality, minimalist design, Inter font, professional enterprise software aesthetic.

Dimensions: 1000x700 pixels.
"""

try:
    response = model.generate_content(arch_prompt)
    save_image(response, OUTPUT_DIR / 'architecture-diagram.png')
except Exception as e:
    print(f"  [ERROR] {e}")

# ============================================================
# 3. 데이터 플로우 다이어그램
# ============================================================
print("3. Generating data flow diagram...")
flow_prompt = """
Create a horizontal data flow diagram showing how a user query becomes a visualization.

Scene description: Five connected elements arranged in a horizontal line on a clean white background, with arrows pointing from left to right.

From left to right:

1. VIOLET CIRCLE (#8b5cf6): Contains a user icon and text "Query" below. This represents the user asking a question like "Show Samsung stock PER".

2. ORANGE RECTANGLE (#f59e0b): Contains a brain/AI icon and text "NLP Engine" below. This parses the natural language query.

3. BLUE RECTANGLE (#3b82f6): Contains a server icon and text "PyKRX API" below. This fetches real-time stock data.

4. TEAL RECTANGLE (#14b8a6): Contains a chart icon and text "Processing" below. This transforms data for visualization.

5. GREEN CIRCLE (#10b981): Contains a checkmark icon and text "Chart" below. This shows the final visualization result.

Each element should be clearly labeled with crisp, readable text. The connecting arrows should be gray (#6b7280) with smooth curves and pointed tips.

Add small descriptive labels above each arrow:
- "Natural Language" (between 1 and 2)
- "Fetch Data" (between 2 and 3)
- "Transform" (between 3 and 4)
- "Render" (between 4 and 5)

Style: Clean flowchart, professional documentation quality, high contrast text, Inter font.

Dimensions: 1400x350 pixels, wide format.
"""

try:
    response = model.generate_content(flow_prompt)
    save_image(response, OUTPUT_DIR / 'data-flow-diagram.png')
except Exception as e:
    print(f"  [ERROR] {e}")

# ============================================================
# 4. UI 목업 (실제 프로젝트 UI 반영)
# ============================================================
print("4. Generating UI mockup...")
ui_prompt = """
Create a realistic UI mockup of a Korean stock market data visualization dashboard.

Scene description: A full-screen dashboard interface with a light theme and subtle violet accents.

HEADER BAR (white with bottom border):
- Left side: Orange icon (trending chart) + text "KRX Data Explorer" in bold black
- Center: Connection status badge showing "PyKRX Connected" in green
- Right side: "CSV Upload" button and settings icon

MAIN CONTENT AREA (light gray #f8fafc background):

TOP SECTION - AI Query Box:
- A rounded input box with violet border
- Placeholder text "Ask in Korean: Show Samsung PER chart"
- Send button with violet background
- Small "AI" badge with sparkle icon

VISUALIZATION AREA (white card with shadow):
- A professional bar chart showing Korean stock data:
  - X-axis: Company names in Korean (Samsung, SK Hynix, NAVER, Hyundai, LG Chem)
  - Y-axis: Values from 0 to 500,000
  - Colorful bars (violet, orange, teal, blue, green)
  - Title: "Stock Price Comparison" in Korean
  - Clean gridlines and axis labels

BOTTOM SECTION - Data Table:
- A clean data table with columns:
  - Stock Code | Company | Price | Change% | Volume
- 5 rows of sample data
- Alternating row colors (white and light gray)

RIGHT PANEL (floating):
- PyGWalker toolbar with chart type icons
- Filter options

Style: Modern SaaS dashboard, clean typography, subtle shadows, professional fintech aesthetic. The UI should look like a real production application, not a mockup sketch.

Dimensions: 1920x1080 pixels.
"""

try:
    response = model.generate_content(ui_prompt)
    save_image(response, OUTPUT_DIR / 'ui-mockup.png')
except Exception as e:
    print(f"  [ERROR] {e}")

# ============================================================
# 5. 기능 그리드 (Features Grid)
# ============================================================
print("5. Generating features grid...")
features_prompt = """
Create a professional feature showcase grid with 6 cards arranged in 2 rows of 3.

Scene description: Six feature cards on a subtle gradient background (white to light violet #faf5ff).

ROW 1:
Card 1 (Violet icon #8b5cf6):
- Icon: Bar chart
- Title: "OHLCV Data"
- Subtitle: "Real-time price & volume"

Card 2 (Orange icon #f59e0b):
- Icon: Pie chart
- Title: "Market Cap"
- Subtitle: "Company valuations"

Card 3 (Teal icon #14b8a6):
- Icon: Users
- Title: "Investor Flow"
- Subtitle: "Institution vs retail"

ROW 2:
Card 4 (Blue icon #3b82f6):
- Icon: Sparkle/AI
- Title: "NL Query"
- Subtitle: "Ask in Korean"

Card 5 (Green icon #10b981):
- Icon: Layers
- Title: "ETF/ETN"
- Subtitle: "Derivative products"

Card 6 (Rose icon #f43f5e):
- Icon: Search
- Title: "Visual Explorer"
- Subtitle: "PyGWalker charts"

Each card should have:
- White background with subtle shadow
- Rounded corners (16px)
- A colored circular icon at the top
- Bold title text below the icon
- Lighter gray subtitle
- Professional, clean typography

Style: SaaS marketing page, modern card design, consistent spacing, Inter font family.

Dimensions: 1200x600 pixels.
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
