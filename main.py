import os
import requests
import pandas as pd
import numpy as np

# Secrets
REFRESH_TOKEN = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def notify_line(msg):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]}
    requests.post(url, headers=headers, json=payload)

def get_stock_data():
    host = "api.jquants.com"
    try:
        # 1. IDトークンの取得
        r_auth = requests.post(f"https://{host}/v1/token/auth_refresh", params={"refreshtoken": REFRESH_TOKEN})
        token = r_auth.json().get('idToken')
        if not token:
            return f"認証失敗: {r_auth.text}", []
        headers = {"Authorization": f"Bearer {token}"}
        
        # 2. 銘柄情報の取得
        r_info = requests.get(f"https://{host}/v1/listed/info", headers=headers)
        info_data = r_info.json().get("info", [])
        if not info_data:
            return "銘柄情報が取得できません", []
        name_map = pd.DataFrame(info_data).set_index('Code')[['CompanyName']].to_dict('index')
        
        # 3. 株価データの取得（日付指定なしで直近分を取得）
        r_quote = requests.get(f"https://{host}/v1/prices/daily_quotes", headers=headers)
        quotes = r_quote.json().get("daily_quotes", [])
        if not quotes:
            return f"株価データが空です (API応答: {r_quote.status_code})", []
        
        df = pd.DataFrame(quotes)
        if 'Code' not in df.columns:
            return "取得データにCode列がありません", []

        # 計算処理
        df = df.sort_values(['Code', 'Date'])
        df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
        df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
        df = df.dropna(subset=['Close'])

        df['ma5'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(5).mean())
        df['ma25'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(25).mean())
        df['vol_avg'] = df.groupby('Code')['Volume'].transform(lambda x: x.rolling(5).mean())

        u_l, d_l = [], []
        for code, group in df.groupby('Code'):
            if len(group) < 2: continue
            curr = group.iloc[-1]
            prev = group.iloc[-2]
            
            u_score = 0
            details = []
            if curr['ma5'] > curr['ma25']: u_score += 10; details.append("5日線>25日線")
            if curr['Close'] > curr['ma5']: u_score += 10; details.append("価格>5日線")
            if curr['Volume'] > curr['vol_avg']: u_score += 10; details.append("出来高増")
            
            name = name_map.get(code, {"CompanyName": "不明"})["CompanyName"]
            msg = f"{code} {name}\n{curr['Close']}円 【{u_score}点】\n" + "・".join(details)
            u_l.append((u_score, msg))

        top_u = [x[1] for x in sorted(u_l, key=lambda x: x[0], reverse=True)[:10]]
        return None, top_u

    except Exception as e:
        return f"実行エラー: {str(e)}", []

if __name__ == "__main__":
    err, up = get_stock_data()
    if err:
        notify_line(f"❌ システムエラー報告:\n{err}")
    elif up:
        notify_line("【本日の期待銘柄】\n\n" + "\n\n".join(up))
    else:
        notify_line("⚠️ 判定対象の銘柄が見つかりませんでした")
