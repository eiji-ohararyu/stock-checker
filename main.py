import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Secrets
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def calculate_indicators(df):
    df['close'] = pd.to_numeric(df['C'], errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    
    # 指標計算
    diff = df['close'].diff()
    up, down = diff.clip(lower=0), -diff.clip(upper=0)
    ma_up, ma_down = up.rolling(14).mean(), down.rolling(14).mean()
    df['rsi'] = ma_up / (ma_up + ma_down) * 100
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    df['vol_avg'] = df['volume'].rolling(5).mean()
    df['bbm'] = df['close'].rolling(20).mean()
    df['std'] = df['close'].rolling(20).std()
    df['bbl'] = df['bbm'] - (df['std'] * 2)
    return df

def calculate_score(df, name):
    df = calculate_indicators(df)
    if len(df) < 25: return 0, ""
    p, c = df.iloc[-2], df.iloc[-1]
    u_s, u_d = 0, []

    # ゴールデンクロス
    if p['ma5'] < p['ma25'] and c['ma5'] > c['ma25']: u_s += 20; u_d.append("GC(+20)")
    # ボリバン反発
    if c['close'] > c['bbl'] and p['close'] <= p['bbl']: u_s += 15; u_d.append("BB反発(+15)")
    # RSI底打ち
    if not np.isnan(c['rsi']) and c['rsi'] > p['rsi'] and p['rsi'] < 35: u_s += 15; u_d.append("RSI底(+15)")
    # 急騰・出来高
    if p['close'] > 0 and ((c['close'] - p['close']) / p['close']) * 100 > 3: u_s += 15; u_d.append("急騰(+15)")
    if c['volume'] > c['vol_avg'] * 2: u_s += 20; u_d.append("爆量(+20)")
    # 25日線トレンド
    if c['ma25'] > p['ma25']: u_s += 10; u_d.append("25線上向(+10)")

    msg = f"{name}\n{c['close']}円 【{u_s}点】\n" + "・".join(u_d)
    return u_s, msg

def get_stock_data():
    host = "https://api.jquants.com/v2"
    headers = {"x-api-key": API_KEY}
    
    all_quotes = []
    # 過去35日分の日付を生成（土日含む多めに設定）
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(35)]
    
    # 1. 銘柄ごとに履歴を作るため、1日分ずつ取得して蓄積
    for d in reversed(dates): # 古い順に取得
        try:
            r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d})
            if r.status_code == 200:
                data = r.json().get("data", [])
                all_quotes.extend(data)
        except:
            continue

    if not all_quotes:
        return "データが取得できませんでした", []

    full_df = pd.DataFrame(all_quotes).sort_values(['Code', 'Date'])
    
    # 2. 銘柄名マップの作成（簡易版）
    name_map = {}
    try:
        r_info = requests.get(f"{host}/listed/info", headers=headers)
        if r_info.status_code == 200:
            for item in r_info.json().get("data", []):
                name_map[str(item.get("Code"))[:4]] = item.get("CompanyName")
    except:
        pass

    # 3. 銘柄ごとにスコア計算
    results = []
    for code, group in full_df.groupby('Code'):
        if len(group) < 25: continue
        short_code = str(code)[:4]
        name = name_map.get(short_code, f"コード:{short_code}")
        score, text = calculate_score(group.copy(), name)
        if score >= 30:
            results.append((score, f"{short_code} {text}"))

    top10 = [x[1] for x in sorted(results, key=lambda x: x[0], reverse=True)[:10]]
    return None, top10

def notify_line(msg):
    requests.post("https://api.line.me/v2/bot/message/push", 
                  headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}, 
                  json={"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]})

if __name__ == "__main__":
    err, res = get_stock_data()
    if err:
        notify_line(f"⚠️ {err}")
    elif res:
        notify_line("【上昇期待銘柄TOP10】\n\n" + "\n\n".join(res))
    else:
        notify_line("現在、強い上昇サインの出ている銘柄はありません。")
