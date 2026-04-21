import os
import requests
import pandas as pd
from datetime import datetime, timedelta

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

DEBUG_CODE = "4768" # 大塚商会

def get_full_debug_log():
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    # 75営業日分をカバーするため120暦日前から取得
    start_date = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    r = requests.get(f"{host}/equities/bars/daily", headers=headers, 
                     params={"code": DEBUG_CODE, "from": start_date, "to": end_date})
    
    if r.status_code != 200: return "API接続エラー"
    
    data = r.json().get("data", [])
    df = pd.DataFrame(data).sort_values('Date').reset_index(drop=True)
    
    # 計算に使う値を定義（修正株価を優先）
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    
    # 移動平均を算術的に算出（ごまかしなし）
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    df['ma75'] = df['close'].rolling(75).mean()
    
    # 過去5日間の詳細をすべて文字列化
    log_lines = []
    for i in range(len(df)-5, len(df)):
        row = df.iloc[i]
        
        # 計算根拠を可視化
        s5 = df['close'].iloc[i-4:i+1].sum()   # 短期5日の合計
        s25 = df['close'].iloc[i-24:i+1].sum() # 中期25日の合計
        s75 = df['close'].iloc[i-74:i+1].sum() # 長期75日の合計
        
        log_lines.append(
            f"■{row['Date']}\n"
            f" 終値: {row['close']}\n"
            f" [MA5]  合計:{s5:.1f} / 5 = {row['ma5']:.2f}\n"
            f" [MA25] 合計:{s25:.1f} / 25 = {row['ma25']:.2f}\n"
            f" [MA75] 合計:{s75:.1f} / 75 = {row['ma75']:.2f}\n"
            f" [位置] MA5 > MA25: {row['ma5'] > row['ma25']}\n"
            f" [位置] MA5 > MA75: {row['ma5'] > row['ma75']}"
        )
    
    return "\n\n".join(log_lines)

if __name__ == "__main__":
    debug_result = get_full_debug_log()
    msg = f"【大塚商会 全数値デバッグ】\n\n{debug_result}"
    
    requests.post("https://api.line.me/v2/bot/message/push", 
                  headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                  json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
