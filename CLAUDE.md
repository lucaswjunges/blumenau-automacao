# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Static website for **Blumenau Automação** (www.blumenauautomacao.com.br) - an Industrial and Residential Automation company based in Blumenau, SC, Brazil. Founded by UFSC-trained Control and Automation Engineers with CREA registration.

The site mirrors the structure and visual style of the reference site www.blumenauti.com.br but adapted for the automation industry.

## Technology Stack

- **HTML5** - Semantic markup
- **TailwindCSS** - Utility-first CSS framework
- **Vanilla JavaScript** - No frameworks, performance-focused

## Architecture

### Page Structure

Single-page design with these sections:
1. **Hero** - Strong headline about modernization/efficiency, CTA for quotes or free MVP consultation
2. **Services** - 4 pillars: Retrofit/Modernization, Industrial Automation/Industry 4.0, Electrical Projects, Residential Automation
3. **MVP Offering** - Free initial analysis/POC for new clients
4. **Products** - Vitrine-style product display (no cart, WhatsApp-based purchases)
5. **About** - UFSC engineering background, CREA registration, technical authority
6. **Contact** - Form and WhatsApp integration

### Product Catalog System

Products are loaded from an external JSON file (populated by a separate scraping script from Proesi and Loja Vale suppliers).

**JSON Structure Expected:**
```json
{
  "products": [
    {
      "name": "Product Name",
      "price": 99.90,
      "in_stock": true,
      "whatsapp_link": "https://wa.me/..."
    }
  ]
}
```

**Display Logic:**
- If `in_stock: true` → Show price and WhatsApp purchase button
- If `in_stock: false` → Show "Sob Consulta" (Upon Request)

### Visual Design

Following www.blumenauti.com.br patterns:
- Dark navy primary colors (#1a1a2e, #16213e)
- Teal/coral accent gradients
- Rounded corners, box shadows
- Inter font family
- Smooth 0.3s transitions
- Floating WhatsApp button

## Services Focus (Local Market Strategy)

1. **Retrofit e Modernização** - Machine updates, panel replacement, NR12 compliance, PLC/HMI modernization
2. **Automação Industrial & Indústria 4.0** - Telemetry, SCADA, industrial networks, computer vision, robotics (textile and brewery expertise)
3. **Projetos Elétricos e Montagem** - Command panels, CCMs, inverters, soft-starters, industrial electrical infrastructure
4. **Automação Residencial** - Smart homes, access control, sensors, IoT

## Key Regulatory References

- **NR10** - Safety in electrical installations
- **NR12** - Safety in machinery and equipment

## Development Commands

```bash
# Start local server (Python)
python3 -m http.server 8000

# Start local server (Node)
npx serve .

# Watch TailwindCSS (if using CLI)
npx tailwindcss -i ./src/input.css -o ./dist/output.css --watch
```

## Deployment

Static files - deploy to any static hosting (Vercel, Netlify, GitHub Pages, traditional hosting).
