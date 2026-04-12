import os
import requests
import pandas as pd

# Secrets
REFRESH_TOKEN = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def get_stock_data():
    if not REFRESH_TOKEN: return []
    host = "api.jquants.com"
    
    try:
        # ログイン
        auth_url = "https://" + host + "/v1/token/auth_refresh"
        r = requests.post(auth_url, params={"refreshtoken": REFRESH_TOKEN})
        id_token = r.json().get("idToken")
        
        # 株価データ取得
        quote_url = "https://" + host + "/v1/prices/daily_quotes"
        headers = {"Authorization": "Bearer " + id_token}
        r = requests.get(quote_url, headers=headers)
        df = pd.DataFrame(r.json().get("daily_quotes", []))
    except:
        return []

    if df.empty: return []

    # 銘柄ごとにソート
    df = df.sort_values(['Code', 'Date'])
    
    # 移動平均線と出来高平均の計算
    df['ma5'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(window=5).mean())
    df['ma25'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(window=25).mean())
    df['vol_avg'] = df.groupby('Code')['Volume'].transform(lambda x: x.rolling(window=5).mean())

    # 直近2日分をチェック
    latest = df.groupby('Code').tail(2)
    
    picked_stocks = []
    for code, group in latest.groupby('Code'):
        if len(group) < 2: continue
        
        prev = group.iloc[0]
        curr = group.iloc[1]
        
        # 判定：ゴールデンクロス または 出来高急増
        is_gc = (prev['ma5'] < prev['ma25']) and (curr['ma5'] > curr['ma25'])
        is_vol_spike = curr['Volume'] > (curr['vol_avg'] * 2)
        
        if curr['Close'] <= 10000 and (is_gc or is_vol_spike):
            reason = "【GC】" if is_gc else "【出来高増】"
            picked_stocks.append(f"{code}: {curr['Close']}円 {reason}")

    return picked_stocks

def notify_line(message):
    url = "[https://api.line.me/v2/bot/message/push](https://api.line.me/v2/bot/message/push)"
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + LINE_TOKEN}
    body = {"to": USER_ID, "messages": [{"type": "text", "text": message}]}
    requests.post(url, headers=headers, json=body)

if __name__ == "__main__":
    results = get_stock_data()
    # results がリスト形式なので、len(results) > 0 で判定するように修正
    if len(results) > 0:
        msg = "【お宝スキャン】\n本日注目の銘柄が見つかりました：\n\n" + "\n".join(results[:5])
        notify_line(msg)
    else:
        print("条件に合う銘柄はありませんでした。")
