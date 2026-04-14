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
    # 成功ログに基づく大文字キー (C=Close, Vo=Volume)
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
    if len(df) < 2: return 0, ""
    p, c = df.iloc[-2], df.iloc[-1]
    u_s, u_d = 0, []

    if p['ma5'] < p['ma25'] and c['ma5'] > c['ma25']: u_s += 20; u_d.append("GC(+20)")
    if c['close'] > c['bbl'] and p['close'] <= p['bbl']: u_s += 15; u_d.append("BB反発(+15)")
    if not np.isnan(c['rsi']) and c['rsi'] > p['rsi'] and p['rsi'] < 35: u_s += 15; u_d.append("RSI底(+15)")
    if p['close'] > 0 and ((c['close'] - p['close']) / p['close']) * 100 > 3: u_s += 15; u_d.append("急騰(+15)")
    if c['volume'] > c['vol_avg'] * 2: u_s += 20; u_d.append("爆量(+20)")
    if c['ma25'] > p['ma25']: u_s += 10; u_d.append("25線上向(+10)")

    msg = f"{name}\n{c['close']}円 【{u_s}点】\n" + "・".join(u_d)
    return u_s, msg

def get_stock_data():
    host = "https://api.jquants.com/v2"
    headers = {"x-api-key": API_KEY}
    
    # 1. 銘柄情報取得 (パスを /listed/info に変更)
    name_map = {}
    try:
        r_info = requests.get(f"{host}/listed/info", headers=headers)
        if r_info.status_code == 200:
            info_data = r_info.json().get("data", [])
            for item in info_data:
                # キー名の大文字小文字に依存しないよう取得
                code = item.get("Code") or item.get("code")
                name = item.get("CompanyName") or item.get("company_name")
                if code and name:
                    name_map[str(code)[:4]] = name
    except:
        pass # 銘柄名が取れなくても計算は続行

    try:
        # 2. 株価データ取得
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=50)
        params = {"from": start_dt.strftime("%Y-%m-%d"), "to": end_dt.strftime("%Y-%m-%d")}
        
        r_quote = requests.get(f"{host}/equities/bars/daily", headers=headers, params=params)
        if r_quote.status_code != 200:
            return f"株価取得失敗({r_quote.status_code}): {r_quote.text}", []

        quotes = r_quote.json().get("data", [])
        if not quotes: return "株価データ未配信", []

        # 3. 集計
        df = pd.DataFrame(quotes).sort_values(['Code', 'Date'])
        results = []
        for code, group in df.groupby('Code'):
            if len(group) < 25: continue
            short_code = str(code)[:4]
            name = name_map.get(short_code, f"コード:{short_code}")
            score, text = calculate_score(group.copy(), name)
            if score >= 30:
                results.append((score, f"{short_code} {text}"))

        top10 = [x[1] for x in sorted(results, key=lambda x: x[0], reverse=True)[:10]]
        return None, top10

    except Exception as e:
        return f"実行エラー: {str(e)}", []

def notify_line(msg):
    requests.post("https://api.line.me/v2/bot/message/push", 
                  headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}, 
                  json={"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]})

if __name__ == "__main__":
    err, res = get_stock_data()
    if err:
        notify_line(f"⚠️ {err}")
    elif res:
        notify_line("【上昇期待TOP10】\n\n" + "\n\n".join(res))
    else:
        notify_line("条件に合う銘柄は見つかりませんでした")
