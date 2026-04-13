import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Secrets
REFRESH_TOKEN = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def calculate_indicators(df):
    diff = df['Close'].diff()
    up = diff.clip(lower=0)
    down = -diff.clip(upper=0)
    ma_up = up.rolling(window=14).mean()
    ma_down = down.rolling(window=14).mean()
    df['RSI'] = ma_up / (ma_up + ma_down) * 100
    df['BBM'] = df['Close'].rolling(window=20).mean()
    df['std'] = df['Close'].rolling(window=20).std()
    df['BBU'] = df['BBM'] + (df['std'] * 2)
    df['BBL'] = df['BBM'] - (df['std'] * 2)
    return df

def calculate_score(df, info):
    df = calculate_indicators(df)
    if len(df) < 2: return -1, "", -1, ""
    
    prev, curr = df.iloc[-2], df.iloc[-1]
    u_score, d_score = 0, 0
    u_det, d_det = [], []

    # スコア計算（条件を大幅に緩和）
    if curr['ma5'] > curr['ma25']: u_score += 10; u_det.append("5日線>25日線")
    if curr['Close'] > curr['ma5']: u_score += 10; u_det.append("価格>5日線")
    if curr['Volume'] > curr['vol_avg']: u_score += 10; u_det.append("出来高増")
    
    # 逆も計算
    if curr['ma5'] < curr['ma25']: d_score += 10; d_det.append("5日線<25日線")
    if curr['Close'] < curr['ma5']: d_score += 10; d_det.append("価格<5日線")

    u_m = f"{info['CompanyName']}\n{curr['Close']}円 【{u_score}点】\n" + "・".join(u_det)
    d_m = f"{info['CompanyName']}\n{curr['Close']}円 【{d_score}点】\n" + "・".join(d_det)
    return u_score, u_m, d_score, d_m

def get_stock_data():
    host = "api.jquants.com"
    try:
        # トークン取得
        r = requests.post(f"https://{host}/v1/token/auth_refresh", params={"refreshtoken": REFRESH_TOKEN})
        token = r.json().get('idToken')
        headers = {"Authorization": f"Bearer {token}"}
        
        # 銘柄情報
        info_res = requests.get(f"https://{host}/v1/listed/info", headers=headers)
        name_map = pd.DataFrame(info_res.json().get("info", [])).set_index('Code')[['CompanyName']].to_dict('index')
        
        # 株価データ（直近数日分を確実に取る）
        quote_res = requests.get(f"https://{host}/v1/prices/daily_quotes", headers=headers)
        df = pd.DataFrame(quote_res.json().get("daily_quotes", []))
    except Exception as e:
        print(f"APIエラー: {e}")
        return [], []

    if df.empty: return [], []
    
    df = df.sort_values(['Code', 'Date'])
    df['ma5'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(5).mean())
    df['ma25'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(25).mean())
    df['vol_avg'] = df.groupby('Code')['Volume'].transform(lambda x: x.rolling(5).mean())

    u_l, d_l = [], []
    for code, group in df.groupby('Code'):
        if len(group) < 25: continue
        u_s, u_m, d_s, d_m = calculate_score(group.copy(), name_map.get(code, {"CompanyName": "不明"}))
        u_l.append((u_s, f"{code} {u_m}"))
        d_l.append((d_s, f"{code} {d_m}"))

    top_u = [x[1] for x in sorted(u_l, key=lambda x: x[0], reverse=True)[:10]]
    top_d = [x[1] for x in sorted(d_l, key=lambda x: x[0], reverse=True)[:10]]
    return top_u, top_d

def notify_line(msg):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]}
    r = requests.post(url, headers=headers, json=payload)
    print(f"LINE送信結果: {r.status_code}")

if __name__ == "__main__":
    u, d = get_stock_data()
    m = ""
    if u: m += "【本日の上昇期待】\n\n" + "\n\n".join(u)
    if d: m += "\n\n───────────────\n\n【本日の下落警戒】\n\n" + "\n\n".join(d)
    
    if m:
        notify_line(m)
    else:
        print("最終判定でデータが残りませんでした")
