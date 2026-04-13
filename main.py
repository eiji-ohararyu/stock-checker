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

def calculate_score(df, company_name):
    df = calculate_indicators(df)
    if len(df) < 2: return 0, "", 0, ""
    prev, curr = df.iloc[-2], df.iloc[-1]
    
    u_s, d_s = 0, 0
    u_d, d_d = [], []

    # ① GC/DC (20点)
    if prev['ma5'] < prev['ma25'] and curr['ma5'] > curr['ma25']:
        u_s += 20; u_d.append("GC(+20)")
    elif prev['ma5'] > prev['ma25'] and curr['ma5'] < prev['ma25']:
        d_s += 20; d_d.append("DC(+20)")

    # ② ボリンジャーバンド (15点)
    if curr['Close'] > curr['BBL'] and prev['Close'] <= prev['BBL']:
        u_s += 15; u_d.append("BB反発(+15)")
    elif curr['Close'] < curr['BBU'] and prev['Close'] >= curr['BBU']:
        d_s += 15; d_d.append("BB反落(+15)")

    # ③ RSI (15点)
    if not np.isnan(curr['RSI']):
        if curr['RSI'] > prev['RSI'] and prev['RSI'] < 35:
            u_s += 15; u_d.append("RSI反転(+15)")
        elif curr['RSI'] < prev['RSI'] and prev['RSI'] > 65:
            d_s += 15; d_d.append("RSI反落(+15)")

    # ④ 騰落率 (15点)
    chg = ((curr['Close'] - prev['Close']) / prev['Close']) * 100
    if chg > 3: u_s += 15; u_d.append(f"急騰(+15)")
    elif chg < -3: d_s += 15; d_d.append(f"急落(+15)")

    # ⑤ 出来高増加 (20点)
    if curr['Volume'] > curr['vol_avg'] * 2:
        u_s += 20; d_s += 20; u_d.append("爆量(+20)"); d_d.append("爆量(+20)")

    # ⑥ 出来高維持 (5点)
    if curr['Volume'] > prev['Volume']:
        u_s += 5; d_s += 5

    # ⑦ 25日線傾き (10点)
    if curr['ma25'] > prev['ma25']:
        u_s += 10; u_d.append("25線上向(+10)")
    else:
        d_s += 10; d_d.append("25線下向(+10)")

    u_m = f"{company_name}\n{curr['Close']}円 【{u_s}点】\n" + "・".join(u_d)
    d_m = f"{company_name}\n{curr['Close']}円 【{d_s}点】\n" + "・".join(d_d)
    return u_s, u_m, d_s, d_m

def get_stock_data():
    host = "api.jquants.com"
    try:
        r_auth = requests.post(f"https://{host}/v1/token/auth_refresh", params={"refreshtoken": REFRESH_TOKEN})
        token = r_auth.json().get('idToken')
        if not token: return "認証トークンが取得できませんでした", []
        headers = {"Authorization": f"Bearer {token}"}
        
        # 銘柄情報の取得
        r_info = requests.get(f"https://{host}/v1/listed/info", headers=headers)
        info_json = r_info.json()
        name_map = {}
        if "info" in info_json:
            name_map = pd.DataFrame(info_json["info"]).set_index('Code')[['CompanyName']].to_dict('index')

        # 株価データの取得
        r_quote = requests.get(f"https://{host}/v1/prices/daily_quotes", headers=headers)
        quote_json = r_quote.json()
        if "daily_quotes" not in quote_json:
            return f"株価データが見つかりません(API応答: {r_quote.status_code})", []
        
        quotes = quote_json["daily_quotes"]
        if not quotes:
            return "取得した株価データが空です", []

        df = pd.DataFrame(quotes)
        df = df.sort_values(['Code', 'Date'])
        df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
        df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
        df['ma5'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(5).mean())
        df['ma25'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(25).mean())
        df['vol_avg'] = df.groupby('Code')['Volume'].transform(lambda x: x.rolling(5).mean())

        u_l, d_l = [], []
        for code, group in df.groupby('Code'):
            if len(group) < 25: continue
            name = name_map.get(code, {}).get("CompanyName", f"コード:{code}")
            u_s, u_m, d_s, d_m = calculate_score(group.copy(), name)
            u_l.append((u_s, f"{code} {u_m}"))
            d_l.append((d_s, f"{code} {d_m}"))

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
        msg = "【上昇期待TOP10】\n\n" + "\n\n".join(u) + "\n\n───────────────\n\n【下落警戒TOP10】\n\n" + "\n\n".join(d)
        notify_line(msg)
