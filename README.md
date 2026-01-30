# Stock Data Pipeline

Private repository for S&P 500 stock data collection, RS/RRS calculation, and R2 upload.

## Overview

This pipeline:
1. Fetches target stocks from Financial Modeling Prep API
2. Downloads 90 days of price data from Yahoo Finance
3. Calculates technical indicators (SMA, EMA, RSI, ATR, VWAP)
4. Calculates RS (Relative Strength) and RRS scores
5. Exports to JSON format
6. Uploads to Cloudflare R2

## Directory Structure
```
stock-data-pipeline/
├── .github/workflows/
│   └── daily-update.yml       # GitHub Actions (daily execution)
├── scripts/
│   ├── daily/                 # Daily execution scripts
│   │   ├── 1_fetch_target_stocks.py
│   │   ├── 2_fetch_price_data.py
│   │   ├── 3_calculate_rs_simple.py
│   │   ├── 4_export_to_json.py
│   │   └── 5_upload_to_r2.py
│   └── maintenance/           # Local execution scripts (for GA, etc.)
├── config/
│   └── settings.json
├── data/                      # Temporary files (gitignored)
├── requirements.txt
└── README.md
```

## Setup

### 1. Environment Variables

Set the following secrets in GitHub repository settings:

- `FMP_API_KEY`: Financial Modeling Prep API key
- `R2_ACCESS_KEY_ID`: Cloudflare R2 Access Key ID
- `R2_SECRET_ACCESS_KEY`: Cloudflare R2 Secret Access Key
- `R2_ENDPOINT`: Cloudflare R2 endpoint URL
- `R2_BUCKET_NAME`: R2 bucket name (e.g., `stock-data`)

### 2. Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
FMP_API_KEY=your_fmp_api_key
R2_ACCESS_KEY_ID=your_r2_access_key
R2_SECRET_ACCESS_KEY=your_r2_secret_key
R2_ENDPOINT=https://your-account-id.r2.cloudflarestorage.com
R2_BUCKET_NAME=stock-data
EOF

# Run pipeline manually
python scripts/daily/1_fetch_target_stocks.py
python scripts/daily/2_fetch_price_data.py
python scripts/daily/3_calculate_rs_simple.py
python scripts/daily/4_export_to_json.py
python scripts/daily/5_upload_to_r2.py

# Cleanup
rm -rf data/*
```

## GitHub Actions

The pipeline runs automatically:
- **Schedule**: Monday-Friday at 21:00 UTC (after US market close)
- **Manual**: Can be triggered via "Actions" tab

## Output Format

### Individual Stock JSON (`stocks/daily/AAPL.json`)
```json
{
  "ticker": "AAPL",
  "name": "Apple Inc.",
  "sector": "Technology",
  "industry": "Consumer Electronics",
  "data": [
    {
      "date": "2025-01-29",
      "open": 184.50,
      "high": 186.20,
      "low": 183.80,
      "close": 185.40,
      "volume": 52341000,
      "sma20": 182.30,
      "sma50": 178.90,
      "sma200": 175.20,
      "ema21": 183.50,
      "vwap": 184.80,
      "rsi14": 65.3,
      "atr14": 3.45
    }
  ],
  "rs": 85.2,
  "rrs": 2.1,
  "lastUpdated": "2025-01-29T22:00:00Z"
}
```

### RS Scores JSON (`scores/individual/latest.json`)
```json
{
  "date": "2025-01-29",
  "scores": [
    {
      "ticker": "AAPL",
      "rs": 85.2,
      "rrs": 2.1,
      "rank": 15,
      "sector": "Technology",
      "industry": "Consumer Electronics"
    }
  ],
  "totalStocks": 4000
}
```

## Technical Indicators

- **SMA**: Simple Moving Average (20, 50, 200 days)
- **EMA**: Exponential Moving Average (21 days)
- **RSI**: Relative Strength Index (14 days)
- **ATR**: Average True Range (14 days)
- **VWAP**: Volume Weighted Average Price
- **RS**: Relative Strength (percentile-based)
- **RRS**: Relative Rank Strength (Pine Script logic)

## Notes

- All temporary files are deleted after each run
- No large pickle files are stored in the repository
- For GA backtesting, download JSONs from R2 and rebuild locally