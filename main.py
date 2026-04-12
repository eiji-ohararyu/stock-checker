import os
import requests
import pandas as pd

# Secrets
REFRESH_TOKEN = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def get_stock_data():
    if not REFRESH_TOKEN: return pd.DataFrame()
    host = "api.jquants.com"
    
    try:
        # ログイン
        auth_url = "https://" + host + "/v1/token/auth_refresh"
        r = requests.post(auth_url, params={"refreshtoken": REFRESH_TOKEN})
        id_token = r.json().get("idToken")
        
        # 株価データ取得（最新30日分くらいを取得）
        quote_url = "https://" + host + "/v1/prices/daily_quotes"
        headers = {"Authorization": "Bearer " + id_token}
        r = requests.get(quote_url, headers=headers)
        df = pd.DataFrame(r.json().get("daily_quotes", []))
    except:
        return pd.DataFrame()

    if df.empty: return df

    # --- お宝探しアルゴリズム（テクニカル分析編） ---
    
    # 銘柄ごとに計算するためにグループ化
    df = df.sort_values(['Code', 'Date'])
    
    # 1. 移動平均線の計算（5日線と25日線）
    df['ma5'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(window=5).mean())
    df['ma25'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(window=25).mean())
    
    # 2. 出来高の平均を計算（過去5日間の平均出来高）
    df['vol_avg'] = df.groupby('Code')['Volume'].transform(lambda x: x.rolling(window=5).mean())

    # 最新日のデータだけを抽出
    latest = df.groupby('Code').tail(2) # 変化を見るために直近2日分
    
    picked_stocks = []
    for code, group in latest.groupby('Code'):
        if len(group) < 2: continue
        
        prev = group.iloc[0] # 前日
        curr = group.iloc[1] # 今日
        
        # 判定A: ゴールデンクロス（昨日 ma5 < ma25 だったのが、今日 ma5 > ma25 になった）
        is_gc = prev['ma5'] < prev['ma25'] and curr['ma5'] > curr['ma25']
        
        # 判定B: 出来高急増（今日の出来高が過去5日平均の2倍以上）
        is_vol_spike = curr['Volume'] > (curr['vol_avg'] * 2)
        
        # 条件：1株1万円以下で、ゴールデンクロスか出来高急増が発生
        if curr['Close'] <= 10000 and (is_gc or is_vol_spike):
            reason = "【GC発生】" if is_gc else "【出来高急増】"
            picked_stocks.append(f"{code}: {curr['Close']}円 {reason}")

    return picked_stocks[:5] # 多すぎるとLINEが見づらいので5つまで

def notify_line(message):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + LINE_TOKEN}
    body = {"to": USER_ID, "messages": [{"type": "text", "text": message}]}
    requests.post(url, headers=headers, json=body)

if __name__ == "__main__":
    results = get_stock_data()
    if results:
        msg = "【お宝スキャン】\n本日注目の銘柄が見つかりました：\n\n" + "\n".join(results)
        notify_line(msg)
    else:
        print("本日、条件に合う銘柄はありませんでした。")
