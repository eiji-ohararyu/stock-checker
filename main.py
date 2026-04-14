import os
import requests
import pandas as pd
import numpy as np

# Secretsの取得
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def calculate_indicators(df):
    diff = df['close'].diff()
    up = diff.clip(lower=0)
    down = -diff.clip(upper=0)
    ma_up = up.rolling(window=14).mean()
    ma_down = down.rolling(window=14).mean()
    df['rsi'] = ma_up / (ma_up + ma_down) * 100
    df['bbm'] = df['close'].rolling(window=20).mean()
    df['std'] = df['close'].rolling(window=20).std()
    df['bbu'] = df['bbm'] + (df['std'] * 2)
    df['bbl'] = df['bbm'] - (df['std'] * 2)
    return df

def calculate_score(df, company_name):
    df = calculate_indicators(df)
    if len(df) < 2: return 0, "", 0, ""
    prev, curr = df.iloc[-2], df.iloc[-1]
    u_s, d_s = 0, 0
    u_d, d_d = [] , []

    if prev['ma5'] < prev['ma25'] and curr['ma5'] > curr['ma25']:
        u_s += 20; u_d.append("GC(+20)")
    elif prev['ma5'] > prev['ma25'] and curr['ma5'] < prev['ma25']:
        d_s += 20; d_d.append("DC(+20)")
    if curr['close'] > curr['bbl'] and prev['close'] <= prev['bbl']:
        u_s += 15; u_d.append("BB反発(+15)")
    elif curr['close'] < curr['bbu'] and prev['close'] >= curr['bbu']:
        d_s += 15; d_d.append("BB反落(+15)")
    if not np.isnan(curr['rsi']):
        if curr['rsi'] > prev['rsi'] and prev['rsi'] < 35:
            u_s += 15; u_d.append("RSI底(+15)")
        elif curr['rsi'] < prev['rsi'] and prev['rsi'] > 65:
            d_s += 15; d_d.append("RSI天(+15)")
    if ((curr['close'] - prev['close']) / prev['close']) * 100 > 3:
        u_s += 15; u_d.append("急騰(+15)")
    elif ((curr['close'] - prev['close']) / prev['close']) * 100 < -3:
        d_s += 15; d_d.append("急落(+15)")
    if curr['volume'] > curr['vol_avg'] * 2:
        u_s += 20; d_s += 20; u_d.append("爆量(+20)")
    if curr['ma25'] > prev['ma25']:
        u_s += 10; u_d.append("25線上向(+10)")
    else:
        d_s += 10; d_d.append("25線下向(+10)")

    u_msg = f"{company_name}\n{curr['close']}円 【{u_s}点】\n" + "・".join(u_d)
    d_msg = f"{company_name}\n{curr['close']}円 【{d_s}点】\n" + "・".join(d_d)
    return u_s, u_msg, d_s, d_msg

def get_stock_data():
    host = "https://api.jquants.com/v2"
    headers = {"x-api-key": API_KEY}
    
    try:
        # 1. 銘柄情報取得 (パスをシンプルに修正)
        r_info = requests.get(f"{host}/listed/info", headers=headers)
        if r_info.status_code != 200:
            # 再度エラーなら equities を挟む旧パスを試す
            r_info = requests.get(f"{host}/equities/info", headers=headers)
            
        if r_info.status_code != 200:
            return f"V2認証失敗({r_info.status_code}): {r_info.text}", []
        
        info_data = r_info.json().get("info") or r_info.json().get("listed_info")
        name_map = pd.DataFrame(info_data).set_index('code')[['company_name']].to_dict('index')

        # 2. 株価データ取得 (画像ファイル名に基づき prices/daily_quotes を使用)
        r_quote = requests.get(f"{host}/prices/daily_quotes", headers=headers)
        if r_quote.status_code != 200:
            # 失敗時は bars/daily を試す
            r_quote = requests.get(f"{host}/equities/bars/daily", headers=headers)
            
        if r_quote.status_code != 200:
            return f"V2取得失敗({r_quote.status_code}): {r_quote.text}", []
            
        data = r_quote.json()
        quotes = data.get("daily_quotes") or data.get("bars")
        if not quotes:
            return "データなし", []

        df = pd.DataFrame(quotes)
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
        df = df.sort_values(['code', 'date'])

        df['ma5'] = df.groupby('code')['close'].transform(lambda x: x.rolling(5).mean())
        df['ma25'] = df.groupby('code')['close'].transform(lambda x: x.rolling(25).mean())
        df['vol_avg'] = df.groupby('code')['volume'].transform(lambda x: x.rolling(5).mean())

        u_l, d_l = [], []
        for code, group in df.groupby('code'):
            if len(group) < 25: continue
            name = name_map.get(code, {}).get("company_name", f"コード:{code}")
            u_s, u_m, d_s, d_m = calculate_score(group.copy(), name)
            if u_s >= 30: u_l.append((u_s, f"{code} {u_m}"))
            if d_s >= 30: d_l.append((d_s, f"{code} {d_m}"))

        top_u = [x[1] for x in sorted(u_l, key=lambda x: x[0], reverse=True)[:10]]
        top_d = [x[1] for x in sorted(d_l, key=lambda x: x[0], reverse=True)[:10]]
        return None, (top_u, top_d)
    except Exception as e:
        return f"システムエラー: {str(e)}", []

def notify_line(msg):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]}
    requests.post(url, headers=headers, json=payload)

if __name__ == "__main__":
    err, results = get_stock_data()
    if err:
        notify_line(f"⚠️ {err}")
    elif results:
        u, d = results
        if u or d:
            msg = "【上昇期待TOP10】\n\n" + "\n\n".join(u) + "\n\n───────────────\n\n【下落警戒TOP10】\n\n" + "\n\n".join(d)
            notify_line(msg)
