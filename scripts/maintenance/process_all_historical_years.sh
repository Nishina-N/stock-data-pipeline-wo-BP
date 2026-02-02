#!/bin/bash
# process_all_historical_years.sh

for year in {1927..2024}; do
  echo "Processing year $year..."
  
  # Export
  python3 scripts/maintenance/4_4_export_historical_by_year.py --year $year
  
  # Upload with workers=10
  python3 scripts/maintenance/5_4_upload_historical_by_year.py --year $year --workers 10
  
  # 中間ファイル削除（容量節約）
  rm -rf data/maintenance/r2/stocks/daily/core/$year
  rm -rf data/maintenance/r2/stocks/daily/indicators/standard/$year
  
  echo "Year $year completed!"
  echo ""
done

echo "All years processed!"