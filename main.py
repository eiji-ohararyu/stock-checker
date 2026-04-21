import os
import requests
import pandas as pd
from datetime import datetime, timedelta

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def get_raw_debug():
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    start_date = (datetime.now() - timedelta(days=150)).strftime("%Y-%m-%d")
    
    # 大塚商会(4768)の生データを取得
    r = requests.get(f"{host}/equities/bars/daily", headers=headers, 
                     params={"code": "4768", "from": start_date})
    
    if r.status_code != 200: return "APIエラー"
    
    data = r.json().get("data", [])
    df = pd.DataFrame(data).sort_values('Date').reset_index(drop=True)
    
    # 判定に使っている「生」の終値（AdjCがあればそれ、なければC）
    df['target_c'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    
    # 判定に使っている「計算式そのまま」の数値
    df['ma5'] = df['target_c'].rolling(5).mean()
    df['ma25'] = df['target_c'].rolling(25).mean()
    df['ma75'] = df['target_c'].rolling(75).mean()
    
    # 最新の状態をすべてさらけ出す
    c = df.iloc[-1]
    
    # 判定ロジックの中身（if文の評価に使っている生フラグ）
    is_5_above_25 = c['ma5'] > c['ma25']
    is_5_above_75 = c['ma5'] > c['ma75']
    
    # 計算に使った直近5日間の「生終値リスト」
    last_5_prices = df['target_c'].tail(5).tolist()
    
    output = (
        f"【4768 大塚商会 内部変数露出】\n\n"
        f"取得日: {c['Date']}\n"
        f"判定用終値: {c['target_c']}\n"
        f"直近5日生データ: {last_5_prices}\n\n"
        f"--- 計算されたMA数値 ---\n"
        f"MA5:  {c['ma5']:.2f}\n"
        f"MA25: {c['ma25']:.2f}\n"
        f"MA75: {c['ma75']:.2f}\n\n"
        f"--- 内部判定フラグ ---\n"
        f"MA5 > MA25か: {is_5_above_25}\n"
        f"MA5 > MA75か: {is_5_above_75}\n"
    )
    return output

if __name__ == "__main__":
    msg = get_raw_debug()
    requests.post("https://api.line.me/v2/bot/message/push", 
                  headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                  json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
