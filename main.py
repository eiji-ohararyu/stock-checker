import os
import requests
import pandas as pd
from datetime import datetime, timedelta

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

DEBUG_CODE = "4768" # 大塚商会

def check_position():
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    # 75日線を出すために120日分取得
    start_date = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    r = requests.get(f"{host}/equities/bars/daily", headers=headers, 
                     params={"code": DEBUG_CODE, "from": start_date, "to": end_date})
    
    if r.status_code != 200: return "API接続エラー"
    
    data = r.json().get("data", [])
    df = pd.DataFrame(data).sort_values('Date').reset_index(drop=True)
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    
    # 移動平均算出
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    df['ma75'] = df['close'].rolling(75).mean()
    
    # 最新5日間の数値と位置関係をそのまま書き出す
    log_lines = []
    for i in range(len(df)-5, len(df)):
        row = df.iloc[i]
        # 物理的な順序を判定（MA5が一番下か？）
        is_ma5_bottom = (row['ma5'] < row['ma25']) and (row['ma5'] < row['ma75'])
        
        log_lines.append(
            f"{row['Date'][5:]}: 終{row['close']:.1f}\n"
            f"  MA5:{row['ma5']:.1f} / MA25:{row['ma25']:.1f} / MA75:{row['ma75']:.1f}\n"
            f"  短期が一番下か？: {'YES' if is_ma5_bottom else 'NO'}"
        )
    
    return "\n".join(log_lines)

if __name__ == "__main__":
    result = check_position()
    msg = f"【大塚商会 位置関係デバッグ】\n\n{result}"
    requests.post("https://api.line.me/v2/bot/message/push", 
                  headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                  json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
