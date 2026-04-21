import os
import requests
import pandas as pd
import time
from datetime import datetime, timedelta

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def fetch_all_daily_data(headers, days=105):
    """1日ずつ全銘柄のデータを105日分かき集める"""
    all_records = []
    today = datetime.now()
    
    print(f"Starting to fetch data for the last {days} days...")
    
    # 直近から1日ずつ遡る
    for i in range(days):
        target_date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        
        # date指定なら爆速。1リクエストで全銘柄のその日の値が取れる。
        params = {"date": target_date}
        
        try:
            r = requests.get("https://api.jquants.com/v2/equities/bars/daily", 
                             headers=headers, params=params, timeout=30)
            
            if r.status_code == 200:
                data = r.json().get("data", [])
                if data:
                    all_records.extend(data)
                    print(f"Fetched {target_date}: {len(data)} stocks found.")
                else:
                    # 土日祝などはデータがないのでスキップ
                    print(f"Skipped {target_date}: No market data.")
            elif r.status_code == 429: # レート制限対策
                print("Rate limit hit. Waiting 60s...")
                time.sleep(60)
            
        except Exception as e:
            print(f"Error on {target_date}: {e}")
            
        # 無料枠なら秒間リクエスト制限があるので少し待つ（Standard以上なら0.1でOK）
        time.sleep(0.2)
        
    return all_records

if __name__ == "__main__":
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    # 銘柄マスターなどは以前と同じ
    # ...
    
    # 105日分、1日ずつ丁寧に取得（これが一番確実）
    raw_data_list = fetch_all_daily_data(headers, days=105)
    
    if raw_data_list:
        full_df = pd.DataFrame(raw_data_list)
        # 以降の scan 処理（5/25/75MA判定）へ
