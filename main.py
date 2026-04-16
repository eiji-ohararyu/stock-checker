import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import io
from scipy.signal import argrelextrema
import re

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def normalize_code(raw_code):
    """銘柄コードを4桁に統一"""
    s = str(raw_code).strip()
    m = re.search(r'\d{4}', s)
    return m.group(0) if m else s.zfill(4)[:4]

def calculate_indicators(df):
    """指標算出（RSI, MA, BB, 出来高）"""
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)
    if len(df) < 25: return df
    
    df['ma5'], df['ma25'] = df['close'].rolling(5).mean(), df['close'].rolling(25).mean()
    df['bbm'] = df['close'].rolling(20).mean()
    df['std'] = df['close'].rolling(20).std()
    df['bbl'] = df['bbm'] - (df['std'] * 2)
    df['vol_avg'] = df['volume'].rolling(5).mean()
    return df

def detect_up_patterns(prices):
    """形状検知（谷の深さと間隔を厳格化）"""
    res = {'score': 0, 'desc': []}
    if len(prices) < 40: return res
    
    t_idx = argrelextrema(prices, np.less_equal, order=5)[0]
    p_idx = argrelextrema(prices, np.greater_equal, order=5)[0]
    
    # 意味のある谷（3%以上の下落）のみ抽出
    valid_troughs = []
    for i in t_idx:
        lookback = prices[max(0, i-10):i]
        if len(lookback) > 0 and (lookback.max() - prices[i]) / lookback.max() > 0.03:
            valid_troughs.append(i)

    # ダブルボトム
    if len(valid_troughs) >= 2:
        idx1, idx2 = valid_troughs[-2], valid_troughs[-1]
        if (idx2 - idx1) >= 7 and abs(prices[idx1] - prices[idx2]) / prices[idx1] < 0.02:
            res['score'] += 40; res['desc'].append("ダブルボトム(+40)")

    # ソーサーボトム
    p_win = prices[-20:]
    c_min_idx = np.argmin(p_win)
    if 5 <= c_min_idx <= 15:
        c_min = p_win[c_min_idx]
        if p_win[0] > c_min * 1.04 and p_win[-1] > c_min * 1.02:
            res['score'] += 35; res['desc'].append("ソーサーボトム(+35)")

    # 三角保合い
    if len(p_idx) >= 2 and len(valid_troughs) >= 2:
        if prices[p_idx[-2]] > prices[p_idx[-1]] and prices[valid_troughs[-2]] < prices[valid_troughs[-1]]:
            res['score'] += 25; res['desc'].append("三角保合い(+25)")

    return res

def get_stock_report():
    """データ収集とスコアリング"""
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    name_map = {}
    try:
        csv_res = requests.get("https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.csv", timeout=10)
        csv_res.encoding = 'shift_jis'
        csv_df = pd.read_csv(io.StringIO(csv_res.text))
        for _, row in csv_df.iterrows():
            code = normalize_code(row['コード'])
            name_map[code] = {"name": str(row['銘柄名']).strip(), "sector": str(row['17業種区分']).strip()}
    except: pass

    all_prices, success_days = [], 0
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(60)]
    for d in reversed(dates):
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d})
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                all_prices.extend(data)
                success_days += 1
    
    if not all_prices: return success_days, []
    
    full_df = pd.DataFrame(all_prices).sort_values(['Code', 'Date'])
    up_res = []
    
    for code, group in full_df.groupby('Code'):
        s_code = normalize_code(code)
        info = name_map.get(s_code, {"name": "不明", "sector": "不明"})
        
        df = calculate_indicators(group.copy())
        if len(df) < 25 or df['vol_avg'].iloc[-1] < 100000: continue
        
        prev, curr = df.iloc[-2], df.iloc[-1]
        raw_s, d_l = 0, []
        
        # 指標加点
        if prev['ma5'] < prev['ma25'] and curr['ma5'] > curr['ma25']: raw_s += 20; d_l.append("GC発生(+20)")
        if curr['close'] > curr['bbl'] and prev['close'] <= prev['bbl']: raw_s += 15; d_l.append("BB下限反発(+15)")
        if curr['ma25'] > prev['ma25']: raw_s += 10; d_l.append("25日線上向き(+10)")
        change = ((curr['close'] - prev['close']) / prev['close']) * 100 if prev['close'] > 0 else 0
        if change > 3: raw_s += 15; d_l.append(f"急騰 {change:.1f}%(+15)")
        
        # 形状加点
        p = detect_up_patterns(df['close'].values)
        raw_s += p['score']
        d_l.extend(p['desc'])
        
        # 出来高倍率（前日までの5日平均比）による乗算
        vol_ratio = curr['volume'] / df['vol_avg'].iloc[-2] if df['vol_avg'].iloc[-2] > 0 else 1.0
        multiplier = 1.0
        if vol_ratio >= 3.0: multiplier = 3.0
        elif vol_ratio >= 2.5: multiplier = 2.5
        elif vol_ratio >= 2.0: multiplier = 2.0
        elif vol_ratio >= 1.5: multiplier = 1.5
        
        final_s = int(raw_s * multiplier)
        if multiplier > 1.0:
            d_l.append(f"出来高倍率 x{multiplier}")
        
        if final_s >= 50:
            msg_part = f"{s_code} {info['name']} ({info['sector']})\n{int(curr['close'])}円 【{final_s}点】\n" + "・".join(d_l)
            up_res.append((final_s, msg_part))
            
    return success_days, [x[1] for x in sorted(up_res, key=lambda x:x[0], reverse=True)[:10]]

if __name__ == "__main__":
    count, up = get_stock_report()
    if up:
        today = datetime.now().strftime('%Y.%m.%d')
        msg = f"{today}　株価評価レポート\n（データ取得日数：{count}）\n\n"
        msg += "【判定：上昇優勢 TOP10】\n\n" + "\n\n".join(up)
        msg += "\n\n───────────────\n詳細確認: https://www.sbisec.co.jp/ETGate/"
        requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {LINE_TOKEN}"}, json={"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]})
