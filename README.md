# Voice Billing System

Local voice-driven billing app for a motorcycle spare-parts shop. Speak a full order, resolve ambiguous part variants manually, apply FOC rules, preview the bill, then save and download a PDF.

**Stack:** Python 3.11+ · FastAPI · SQLite · HTML + Tailwind CDN + vanilla JS · Web Speech API

---

## Features

- Voice or typed order → AI parse (Groq → Gemini → offline RapidFuzz)
- **Never auto-selects** a model variant when multiple matches exist
- Disambiguation UI with multi-select and per-variant quantities
- FOC (free-of-cost) lines on bill preview and PDF
- Catalog browse/search, bill history, settings (API keys + Excel re-import)
- Runs fully offline when no API keys are set

---



## Requirements

- Windows / macOS / Linux
- Python **3.11+** (3.12 recommended)
- Chrome or Edge for microphone input (Web Speech API)
- Optional free API keys:
  - [Groq](https://console.groq.com) — primary
  - [Google AI Studio](https://aistudio.google.com) — fallback

---



## Setup

```bash
# 1. Clone
git clone https://github.com/<your-username>/voice-billing-system.git
cd voice-billing-system

# 2. Virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. Dependencies
pip install -r requirements.txt

# 4. Environment
copy .env.example .env          # Windows
# cp .env.example .env         # macOS / Linux
```

Edit `.env` (keys are optional — omit them to use offline fuzzy mode):

```env
GROQ_API_KEY=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash-lite
GROQ_MODEL=openai/gpt-oss-20b
SHOP_NAME=Spare Parts Shop
```



### Price list

Place your Excel file at:

```text
data/C_P_LIST.xlsx
```

Expected sheets: `70cc. 125cc`, `OTHER MODELS`, `CNG RICKSHAW`, `ELECTRIC VEHICLES`, `FIT 150`.

On first startup the app imports all sheets into SQLite (`database.db`). It re-imports automatically when the file’s last-modified time changes.

---



## Run

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)**


| Page                   | URL         |
| ---------------------- | ----------- |
| Billing (voice + cart) | `/`         |
| Catalog                | `/catalog`  |
| History                | `/history`  |
| Settings               | `/settings` |




### Smoke test (no browser)

```bash
python scripts/smoke_phase1.py
```

Prints per-sheet import counts and a sample parse result.

---



## Typical workflow

1. Hold **Hold to Speak** (or type the order) → **Parse Text**
2. Resolve ambiguous items in the disambiguation panel (select all needed variants + qty)
3. Adjust cart quantities; FOC hints appear when thresholds are met
4. **Preview Bill** (required before save)
5. **Save & Download PDF** → stored under `data/bills/` and listed in History

---



## API overview


| Method | Path                 | Purpose                                   |
| ------ | -------------------- | ----------------------------------------- |
| `POST` | `/api/parse-order`   | Parse spoken/typed text + catalog matches |
| `GET`  | `/api/catalog`       | List/filter items                         |
| `GET`  | `/api/search?q=`     | Fuzzy catalog search                      |
| `POST` | `/api/bill/preview`  | FOC + totals without saving               |
| `POST` | `/api/bill`          | Save bill + generate PDF                  |
| `GET`  | `/api/bill/{id}/pdf` | Download PDF                              |
| `GET`  | `/api/history`       | Past bills                                |
| `POST` | `/api/import`        | Force Excel re-import                     |
| `GET`  | `/api/status`        | Active AI mode + import status            |


AI mode chain: **Groq** (`openai/gpt-oss-20b`) → **Gemini** (`gemini-2.5-flash-lite`) → **RapidFuzz** offline.

---



## Project layout

```text
billing-system/
├── main.py                 # FastAPI entry
├── requirements.txt
├── .env.example
├── data/
│   ├── C_P_LIST.xlsx       # price list (you provide)
│   └── bills/              # generated PDFs
├── app/
│   ├── routes/             # API routers
│   ├── services/           # AI, Excel, FOC, PDF, fuzzy
│   ├── database/           # SQLite schema + queries
│   └── templates/          # Jinja2 HTML
├── static/js/              # mic, cart, bill preview
└── scripts/smoke_phase1.py
```

