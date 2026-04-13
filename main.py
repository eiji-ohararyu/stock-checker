import os
import requests
import pandas as pd
import numpy as np

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
    prev, curr = df.iloc[-2], df.iloc[-1]
    u_score, d_score = 0, 0
    u_det, d_det = [], []

    if prev['ma5'] < prev['ma25'] and curr['ma5'] > curr['ma25']:
        u_score += 20; u_det.append("GC(+20)")
    elif prev['ma5'] > prev['ma25'] and curr['ma5'] < prev['ma25']:
        d_score += 20; d_det.append("DC(+20)")

    if curr['Close'] > curr['BBL'] and prev['Close'] <= prev['BBL']:
        u_score += 15; u_det.append("BB反発(+15)")
    elif curr['Close'] < curr['BBU'] and prev['Close'] >= curr['BBU']:
        d_score += 15; d_det.append("BB反落(+15)")

    if not np.isnan(curr['RSI']):
        if curr['RSI'] > prev['RSI'] and prev['RSI'] < 35:
            u_score += 15; u_det.append("RSI底打(+15)")
        elif curr['RSI'] < prev['RSI'] and prev['RSI'] > 65:
            d_score += 15; d_det.append("RSI天打(+15)")

    chg = ((curr['Close'] - prev['Close']) / prev['Close']) * 100
    if chg > 3:
        u_score += 15; u_det.append(f"急騰(+15)")
    elif chg < -3:
        d_score += 15; d_det.append(f"急落(+15)")

    if curr['Volume'] > curr['vol_avg'] * 2:
        u_score += 20; d_score += 20; u_det.append("爆量(+20)"); d_det.append("爆量(+20)")

    if curr['ma25'] > prev['ma25']:
        u_score += 10; u_det.append("25線上向(+10)")
    else:
        d_score += 10; d_det.append("25線下向(+10)")

    u_m = f"{info['CompanyName']}\n{curr['Close']}円 【{u_score}点】\n" + "・".join(u_det)
    d_m = f"{info['CompanyName']}\n{curr['Close']}円 【{d_score}点】\n" + "・".join(d_det)
    return u_score, u_m, d_score, d_m

def get_stock_data():
    host = "api.jquants.com"
    try:
        r = requests.post(f"https://{host}/v1/token/auth_refresh", params={"refreshtoken": REFRESH_TOKEN})
        headers = {"Authorization": f"Bearer {r.json().get('idToken')}"}
        info_res = requests.get(f"https://{host}/v1/listed/info", headers=headers)
        name_map = pd.DataFrame(info_res.json().get("info", [])).set_index('Code')[['CompanyName', 'Sector17CodeName']].fillna("不明").to_dict('index')
        quote_res = requests.get(f"https://{host}/v1/prices/daily_quotes", headers=headers)
        df = pd.DataFrame(quote_res.json().get("daily_quotes", []))
    except: return [], []

    if df.empty: return [], []
    df = df.sort_values(['Code', 'Date'])
    df['ma5'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(5).mean())
    df['ma25'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(25).mean())
    df['vol_avg'] = df.groupby('Code')['Volume'].transform(lambda x: x.rolling(5).mean())

    u_l, d_l = [], []
    for code, group in df.groupby('Code'):
        if len(group) < 25: continue
        u_s, u_m, d_s, d_m = calculate_score(group.copy(), name_map.get(code, {"CompanyName": "不明"}))
        if u_s >= 0: u_l.append((u_s, f"{code} {u_m}"))
        if d_s >= 0: d_l.append((d_s, f"{code} {d_m}"))

    return [x[1] for x in sorted(u_l, key=lambda x: x[0], reverse=True)[:10]], [x[1] for x in sorted(d_l, key=lambda x: x[0], reverse=True)[:10]]

def notify_line(msg):
    requests.post("https://api.line.me/v2/bot/message/push", headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}, json={"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]})

if __name__ == "__main__":
    u, d = get_stock_data()
    m = ""
    if u: m += "【上昇期待順】\n\n" + "\n\n".join(u)
    if d: m += "\n\n───────────────\n\n【下落警戒順】\n\n" + "\n\n".join(d)
    if m: notify_line(m)
    else: print("データなし")
