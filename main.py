import os
import requests
import pandas as pd
from datetime import datetime, timedelta

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

DEBUG_CODE = "4768" # 大塚商会

if __name__ == "__main__":
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    all_prices = []
    # 直近10日分の生データを取得
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(15)]
    
    for d in reversed(dates):
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d, "code": DEBUG_CODE})
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data: all_prices.extend(data)
            
    if all_prices:
        df = pd.DataFrame(all_prices).sort_values('Date')
        
        # J-Quantsの生データ(終値)と、修正後の終値をリスト化
        log_lines = []
        for _, row in df.tail(10).iterrows():
            d = row['Date'][5:]
            raw_c = row['C']  # 生の終値
            adj_c = row.get('AdjustmentClose', raw_c) # 修正後終値
            log_lines.append(f"{d}: 生終値{raw_c} / 修正後{adj_c}")

        msg = f"【大塚商会 生データ照合】\n" + "\n".join(log_lines) + "\n\n※この数値がチャートと一致しているか確認してください"
        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                      json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
