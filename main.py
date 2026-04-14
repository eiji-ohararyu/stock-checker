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
    # V2のキー (C:終値, Vo:出来高) を使用
    df['close'] = pd.to_numeric(df['C'], errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    
    # RSI (14日)
    diff = df['close'].diff()
    up, down = diff.clip(lower=0), -diff.clip(upper=0)
    ma_up = up.rolling(14).mean()
    ma_down = down.rolling(14).mean()
    df['rsi'] = ma_up / (ma_up + ma_down) * 100
    
    # ボリンジャーバンド (20日)
    df['bbm'] = df['close'].rolling(20).mean()
    df['std'] = df['close'].rolling(20).std()
    df['bbu'] = df['bbm'] + (df['std'] * 2)
    df['bbl'] = df['bbm'] - (df['std'] * 2)
    
    # 移動平均と出来高平均
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    df['vol_avg'] = df['volume'].rolling(5).mean()
    return df

def calculate_score(df, info):
    df = calculate_indicators(df)
    if len(df) < 2: return 0, "", 0, ""
    
    prev, curr = df.iloc[-2], df.iloc[-1]
    u_s, d_s = 0, 0
    u_d, d_d = [], []

    # ① GC/DC (20)
    if prev['ma5'] < prev['ma25'] and curr['ma5'] > curr['ma25']:
        u_s += 20; u_d.append("GC発生(+20)")
    elif prev['ma5'] > prev['ma25'] and curr['ma5'] < prev['ma25']:
        d_s += 20; d_d.append("DC発生(+20)")

    # ② ボリンジャーバンド (15)
    if curr['close'] > curr['bbl'] and prev['close'] <= prev['bbl']:
        u_s += 15; u_d.append("BB下限反発(+15)")
    elif curr['close'] < curr['bbu'] and prev['close'] >= curr['bbu']:
        d_s += 15; d_d.append("BB上限反落(+15)")

    # ③ RSI (15)
    if not np.isnan(curr['rsi']):
        if curr['rsi'] > prev['rsi'] and prev['rsi'] < 35:
            u_s += 15; u_d.append("RSI底打ち(+15)")
        elif curr['rsi'] < prev['rsi'] and prev['rsi'] > 65:
            d_s += 15; d_d.append("RSI天井打ち(+15)")

    # ④ 騰落率 (15)
    change = ((curr['close'] - prev['close']) / prev['close']) * 100 if prev['close'] > 0 else 0
    if change > 3:
        u_s += 15; u_d.append(f"急騰 {change:.1f}%(+15)")
    elif change < -3:
        d_s += 15; d_d.append(f"急落 {change:.1f}%(+15)")

    # ⑤ 出来高増加 (20)
    if curr['vol_avg'] > 0 and (curr['volume'] / curr['vol_avg']) > 2:
        u_s += 20; d_s += 20
        u_d.append("出来高2倍超(+20)"); d_d.append("出来高2倍超(+20)")

    # ⑥ 出来高維持 (5)
    if curr['volume'] > prev['volume']:
        u_s += 5; d_s += 5

    # ⑦ 25日線の傾き (10)
    if curr['ma25'] > prev['ma25']:
        u_s += 10; u_d.append("25日線上向き(+10)")
    else:
        d_s += 10; d_d.append("25日線下向き(+10)")

    header = f"{info['name']} ({info['sector']})\n{curr['close']}円"
    u_msg = f"{header} 【{u_s}点】\n" + "・".join(u_d)
    d_msg = f"{header} 【{d_s}点】\n" + "・".join(d_d)
    
    return u_s, u_msg, d_s, d_msg

def get_stock_data():
    host = "https://api.jquants.com/v2"
    headers = {"x-api-key": API_KEY}
    
    # 1. 銘柄情報
    name_map = {}
    r_info = requests.get(f"{host}/listed/info", headers=headers)
    if r_info.status_code == 200:
        for item in r_info.json().get("data", []):
            name_map[str(item.get("Code"))[:4]] = {
                "name": item.get("CompanyName", "不明"),
                "sector": item.get("Sector17CodeName", "-")
            }

    # 2. 過去35日分のデータを収集
    all_data = []
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(35)]
    for d in reversed(dates):
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d})
        if r.status_code == 200:
            all_data.extend(r.json().get("data", []))
    
    if not all_data: return [], []

    # 3. 集計と判定
    df = pd.DataFrame(all_data).sort_values(['Code', 'Date'])
    up_list, down_list = [], []
    
    for code, group in df.groupby('Code'):
        if len(group) < 2: continue
        short_code = str(code)[:4]
        info = name_map.get(short_code, {"name": "不明", "sector": "-"})
        u_s, u_m, d_s, d_m = calculate_score(group.copy(), info)
        
        if u_s >= 40: up_list.append((u_s, f"{short_code} {u_m}"))
        if d_s >= 40: down_list.append((d_s, f"{short_code} {d_m}"))

    top_u = [x[1] for x in sorted(up_list, key=lambda x: x[0], reverse=True)[:10]]
    top_d = [x[1] for x in sorted(down_list, key=lambda x: x[0], reverse=True)[:10]]
    return top_u, top_d

def notify_line(msg):
    requests.post("https://api.line.me/v2/bot/message/push", 
                  headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}, 
                  json={"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]})

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
