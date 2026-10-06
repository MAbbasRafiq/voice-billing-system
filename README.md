# Voice Billing System

Local voice-driven billing app for a motorcycle spare-parts shop. Speak a full order, resolve ambiguous part variants manually, apply FOC rules, preview the bill, then save and download a PDF.

**Stack:** Python 3.11+ · FastAPI · SQLite · HTML + Tailwind CDN + vanilla JS · local Parakeet TDT (default) · optional browser voice

---

## Features

- Voice or typed order → AI parse (Groq → Gemini → offline RapidFuzz)
- **Local Parakeet** (default mic mode, fast CPU STT for English part names) or browser Web Speech as fallback
- **Never auto-selects** a model variant when multiple matches exist
- Disambiguation UI with multi-select and per-variant quantities
- FOC (free-of-cost) lines on bill preview and PDF
- Catalog browse/search, bill history, settings (API keys + Excel re-import)
- Runs fully offline when no API keys are set

---



## Requirements

- Windows / macOS / Linux
- Python **3.11+** (3.12 recommended)
- A modern browser with microphone access (Chrome or Edge recommended)
- Optional free API keys:
  - [Groq](https://console.groq.com) — primary
  - [Google AI Studio](https://aistudio.google.com) — fallback

---



## Setup

```bash
# 1. Clone
git clone https://github.com/MAbbasRafiq/voice-billing-system.git
cd voice-billing-system

# 2. Virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. Dependencies
pip install -r requirements.txt
```

Edit `.env` (keys are optional — omit them to use offline fuzzy mode):

```env
GROQ_API_KEY=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash-lite
GROQ_MODEL=openai/gpt-oss-20b
STT_MODEL=nemo-parakeet-tdt-0.6b-v3
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

1. Choose **Local Parakeet** (default) or browser voice, then click **Start Listening** (or type the order).
   Prefer **English part names** (quantity can be adjusted in the cart)
   (e.g. `air filter`, `chain kit`, `back light complete`).
2. Click **Stop Listening** — the order is matched automatically (no need to click Parse Text).
3. Resolve ambiguous items (select variants + qty). Use **Remove** to skip a wrong line.
4. Adjust cart quantities; FOC hints appear when thresholds are met
5. **Preview Bill** (required before save)
6. **Save & Download PDF** → stored under `data/bills/` and listed in History

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


Local Parakeet uploads one microphone recording to `POST /api/transcribe` (runs on the server, no API key);
the returned text then uses the same `/api/parse-order` flow as browser speech and typed input.

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

