import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def calculate_indicators(df):
    df['close'] = pd.to_numeric(df['C'], errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    diff = df['close'].diff()
    up, down = diff.clip(lower=0), -diff.clip(upper=0)
    ma_up, ma_down = up.rolling(14).mean(), down.rolling(14).mean()
    df['rsi'] = ma_up / (ma_up + ma_down) * 100
    df['bbm'] = df['close'].rolling(20).mean()
    df['std'] = df['close'].rolling(20).std()
    df['bbu'], df['bbl'] = df['bbm'] + df['std']*2, df['bbm'] - df['std']*2
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    df['vol_avg'] = df['volume'].rolling(5).mean()
    return df

def calculate_score(df, name):
    df = calculate_indicators(df)
    if len(df) < 2: return 0, "", 0, ""
    p, c = df.iloc[-2], df.iloc[-1]
    u_s, d_s, u_d, d_d = 0, 0, [], []

    if p['ma5'] < p['ma25'] and c['ma5'] > c['ma25']: u_s += 20; u_d.append("GC(+20)")
    elif p['ma5'] > p['ma25'] and c['ma5'] < c['ma25']: d_s += 20; d_d.append("DC(+20)")
    if c['close'] > c['bbl'] and p['close'] <= p['bbl']: u_s += 15; u_d.append("BB反発(+15)")
    if not np.isnan(c['rsi']):
        if c['rsi'] > p['rsi'] and p['rsi'] < 35: u_s += 15; u_d.append("RSI底(+15)")
    if ((c['close'] - p['close']) / p['close']) * 100 > 3: u_s += 15; u_d.append("急騰(+15)")
    if c['volume'] > c['vol_avg'] * 2: u_s += 20; u_d.append("爆量(+20)")
    if c['ma25'] > p['ma25']: u_s += 10; u_d.append("25線上向(+10)")

    m = f"{name}\n{c['close']}円 【{u_s}点】\n" + "・".join(u_d)
    return u_s, m, d_s, ""

def get_stock_data():
    host = "https://api.jquants.com/v2"
    headers = {"x-api-key": API_KEY}
    
    try:
        r_info = requests.get(f"{host}/equities/info", headers=headers)
        name_map = pd.DataFrame(r_info.json()["info"]).set_index('code')[['company_name']].to_dict('index')

        # 直近1ヶ月分を取得して指標計算を可能にする
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=40)
        params = {
            "from": start_dt.strftime("%Y-%m-%d"),
            "to": end_dt.strftime("%Y-%m-%d")
        }
        
        r_quote = requests.get(f"{host}/equities/bars/daily", headers=headers, params=params)
        quotes = r_quote.json().get("data", [])
        if not quotes: return "データなし", []

        df = pd.DataFrame(quotes).sort_values(['Code', 'Date'])
        u_l = []
        for code, group in df.groupby('Code'):
            if len(group) < 25: continue
            raw_code = str(code)[:4]
            name = name_map.get(raw_code, {}).get("company_name", f"コード:{raw_code}")
            u_s, u_m, _, _ = calculate_score(group.copy(), name)
            if u_s >= 30: u_l.append((u_s, f"{raw_code} {u_m}"))

        top_u = [x[1] for x in sorted(u_l, key=lambda x: x[0], reverse=True)[:10]]
        return None, top_u
    except Exception as e:
        return f"エラー: {str(e)}", []

def notify_line(msg):
    requests.post("https://api.line.me/v2/bot/message/push", 
                  headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}, 
                  json={"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]})

if __name__ == "__main__":
    err, res = get_stock_data()
    if err: notify_line(f"⚠️ {err}")
    elif res: notify_line("【上昇期待TOP10】\n\n" + "\n\n".join(res))
