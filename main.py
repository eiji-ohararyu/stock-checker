import os
import requests
import pandas as pd
import pandas_ta as ta

# Secrets
REFRESH_TOKEN = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def calculate_score(df, info):
    # 指標計算
    df['RSI'] = ta.rsi(df['Close'], length=14)
    bb = ta.bbands(df['Close'], length=20, std=2)
    df['BBM'] = bb['BBM_20_2.0'] # 中央線
    df['BBL'] = bb['BBL_20_2.0'] # -2sigma
    df['BBU'] = bb['BBU_20_2.0'] # +2sigma
    
    prev, curr = df.iloc[-2], df.iloc[-1]
    up_score, down_score = 0, 0
    up_details, down_details = [], []

    # ① GC/DC (20点)
    if prev['ma5'] < prev['ma25'] and curr['ma5'] > curr['ma25']:
        up_score += 20
        up_details.append("GC発生(+20)")
    elif prev['ma5'] > prev['ma25'] and curr['ma5'] < prev['ma25']:
        down_score += 20
        down_details.append("DC発生(+20)")

    # ② ボリンジャーバンド (15点)
    if curr['Close'] > curr['BBL'] and prev['Close'] <= prev['BBL']:
        up_score += 15
        up_details.append("BB下限反発(+15)")
    elif curr['Close'] < curr['BBU'] and prev['Close'] >= curr['BBU']:
        down_score += 15
        down_details.append("BB上限反落(+15)")

    # ③ RSI (15点)
    if curr['RSI'] > prev['RSI'] and prev['RSI'] < 35:
        up_score += 15
        up_details.append("RSI底打ち(+15)")
    elif curr['RSI'] < prev['RSI'] and prev['RSI'] > 65:
        down_score += 15
        down_details.append("RSI天井打ち(+15)")

    # ④ 騰落率 (15点)
    change = ((curr['Close'] - prev['Close']) / prev['Close']) * 100
    if change > 3:
        up_score += 15
        up_details.append(f"急騰 {change:.1f}%(+15)")
    elif change < -3:
        down_score += 15
        down_details.append(f"急落 {change:.1f}%(+15)")

    # ⑤ 出来高増加 (20点)
    vol_ratio = curr['Volume'] / curr['vol_avg']
    if vol_ratio > 2:
        up_score += 20; down_score += 20
        up_details.append("出来高2倍超(+20)"); down_details.append("出来高2倍超(+20)")

    # ⑥ 出来高維持 (5点)
    if curr['Volume'] > prev['Volume']:
        up_score += 5; down_score += 5

    # ⑦ 25日線の傾き (10点)
    if curr['ma25'] > prev['ma25']:
        up_score += 10; up_details.append("25日線上向き(+10)")
    else:
        down_score += 10; down_details.append("25日線下向き(+10)")

    up_msg = f"{info['CompanyName']} ({info['Sector17CodeName']})\n{curr['Close']}円 【{up_score}点】\n" + "・".join(up_details)
    down_msg = f"{info['CompanyName']} ({info['Sector17CodeName']})\n{curr['Close']}円 【{down_score}点】\n" + "・".join(down_details)
    
    return up_score, up_msg, down_score, down_msg

def get_stock_data():
    host = "api.jquants.com"
    try:
        auth_url = f"https://{host}/v1/token/auth_refresh"
        r = requests.post(auth_url, params={"refreshtoken": REFRESH_TOKEN})
        id_token = r.json().get("idToken")
        headers = {"Authorization": f"Bearer {id_token}"}
        
        info_res = requests.get(f"https://{host}/v1/listed/info", headers=headers)
        info_df = pd.DataFrame(info_res.json().get("info", []))
        name_map = info_df.set_index('Code')[['CompanyName', 'Sector17CodeName']].fillna("不明").to_dict('index')
        
        quote_res = requests.get(f"https://{host}/v1/prices/daily_quotes", headers=headers)
        df = pd.DataFrame(quote_res.json().get("daily_quotes", []))
    except: return [], []

    if df.empty: return [], []
    df = df.sort_values(['Code', 'Date'])
    df['ma5'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(window=5).mean())
    df['ma25'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(window=25).mean())
    df['vol_avg'] = df.groupby('Code')['Volume'].transform(lambda x: x.rolling(window=5).mean())

    up_list, down_list = [], []
    for code, group in df.groupby('Code'):
        if len(group) < 25: continue
        info = name_map.get(code, {"CompanyName": "不明", "Sector17CodeName": "-"})
        u_score, u_msg, d_score, d_msg = calculate_score(group, info)
        
        if u_score >= 40: up_list.append((u_score, f"{code} {u_msg}"))
        if d_score >= 40: down_list.append((d_score, f"{code} {d_msg}"))

    top_up = sorted(up_list, key=lambda x: x[0], reverse=True)[:10]
    top_down = sorted(down_list, key=lambda x: x[0], reverse=True)[:10]
    return [x[1] for x in top_up], [x[1] for x in top_down]

def notify_line(message):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    body = {"to": USER_ID, "messages": [{"type": "text", "text": message}]}
    requests.post(url, headers=headers, json=body)

if __name__ == "__main__":
    up, down = get_stock_data()
    msg = ""
    if up:
        msg += "【総合評価：上昇期待TOP10】\n\n" + "\n\n".join(up)
    if down:
        if msg: msg += "\n\n" + "───────────────" + "\n\n"
        msg += "【総合評価：下落警戒TOP10】\n\n" + "\n\n".join(down)
    
    if msg:
        msg += "\n\n───────────────\n詳細確認（SBI証券）:\nhttps://www.sbisec.co.jp/ETGate"
        notify_line(msg)
    else:
        print("シグナルなし")
