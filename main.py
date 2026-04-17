import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import io
import re
from scipy.signal import argrelextrema

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def normalize_code(raw_code):
    s = str(raw_code).strip()
    m = re.search(r'\d{4}', s)
    return m.group(0) if m else s.zfill(4)[:4]

def get_latest_topix100():
    """JPX公式サイトから最新のTOPIX100銘柄リストを取得（接続設定を強化）"""
    url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        # タイムアウトを30秒に延長
        r = requests.get(url, headers=headers, timeout=30)
        r.encoding = 'shift_jis'
        if r.status_code == 200:
            df = pd.read_csv(io.StringIO(r.text))
            topix100 = df[df['規模区分'] == 'TOPIX100']
            codes = [normalize_code(c) for c in topix100['コード']]
            names = {normalize_code(row['コード']): row['銘柄名'] for _, row in topix100.iterrows()}
            return codes, names
        else:
            return [], {}
    except Exception:
        return [], {}

def calculate_indicators(df):
    df['open'] = pd.to_numeric(df['O'], errors='coerce')
    df['high'] = pd.to_numeric(df['H'], errors='coerce')
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)
    if len(df) < 40: return None
    
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    df['vol_avg_short'] = df['volume'].rolling(2).mean() 
    df['vol_avg_mid'] = df['volume'].rolling(10).mean()
    df['high_10d'] = df['high'].shift(1).rolling(10).max()
    
    df['std'] = df['close'].rolling(20).std()
    df['bbh'] = df['close'].rolling(20).mean() + (df['std'] * 2)
    
    return df

def detect_bottom_pattern(prices):
    res = {'score': 0, 'desc': []}
    t_idx = argrelextrema(prices, np.less_equal, order=5)[0]
    valid_troughs = []
    for i in t_idx:
        lookback = prices[max(0, i-10):i]
        if len(lookback) > 0 and (lookback.max() - prices[i]) / lookback.max() > 0.03:
            valid_troughs.append(i)
    if len(valid_troughs) >= 2:
        idx1, idx2 = valid_troughs[-2], valid_troughs[-1]
        if (idx2 - idx1) >= 7 and abs(prices[idx1] - prices[idx2]) / prices[idx1] < 0.02:
            res['score'] += 20; res['desc'].append("ダブルボトム(+20)")
    return res

def get_stock_report():
    target_codes, name_map = get_latest_topix100()
    if not target_codes: return 0, ["リスト取得失敗"]

    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    all_prices = []
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(60)]
    
    for d in reversed(dates):
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d})
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data: all_prices.extend(data)
    
    if not all_prices: return 0, []
    full_df = pd.DataFrame(all_prices).sort_values(['Code', 'Date'])
    up_res = []
    
    for code, group in full_df.groupby('Code'):
        s_code = normalize_code(code)
        if s_code not in target_codes: continue
            
        df = calculate_indicators(group.copy())
        if df is None: continue
        
        curr = df.iloc[-1]
        raw_s, d_l = 0, []
        
        # 1. 陽線
        is_yang = curr['close'] > curr['open']
        if is_yang: raw_s += 15; d_l.append("陽線(+15)")
        
        # 2. GC判定
        gc_detected = False
        for i in range(len(df)-3, len(df)):
            if i <= 0: continue
            if df['ma5'].iloc[i-1] <= df['ma25'].iloc[i-1] and df['ma5'].iloc[i] > df['ma25'].iloc[i]:
                if df['ma25'].iloc[i] >= df['ma25'].iloc[i-1]:
                    gc_detected = True; break
        if gc_detected: raw_s += 20; d_l.append("GC初動(+20)")

        # 3. トレンド/高値突破
        if df['ma25'].diff().iloc[-3:].min() > 0:
            raw_s += 25; d_l.append("MA25上昇(+25)")
        if curr['close'] > curr['high_10d']:
            raw_s += 20; d_l.append("高値突破(+20)")

        # 4. ダブルボトム
        p = detect_bottom_pattern(df['close'].values)
        raw_s += p['score']; d_l.extend(p['desc'])

        # 5. 出来高倍率（直近2日平均 / マイルド設定）
        multiplier = 1.0
        if len(df) >= 13:
            base_vol = df['vol_avg_mid'].iloc[-3]
            vol_ratio = curr['vol_avg_short'] / base_vol if base_vol > 0 else 1.0
            if is_yang:
                if vol_ratio >= 2.0: multiplier = 2.0
                elif vol_ratio >= 1.5: multiplier = 1.5
        
        if curr['close'] > curr['bbh']:
            multiplier *= 0.7; d_l.append("過熱警戒")

        final_s = int(raw_s * multiplier)
        if final_s >= 40:
            if multiplier > 1.0: d_l.append(f"出来高x{multiplier}")
            name = name_map.get(s_code, "不明")
            up_res.append((final_s, f"{s_code} {name}\n{int(curr['close'])}円 【{final_s}点】\n" + "・".join(d_l)))
            
    return len(up_res), [x[1] for x in sorted(up_res, key=lambda x:x[0], reverse=True)[:10]]

if __name__ == "__main__":
    count, up = get_stock_report()
    if up:
        msg = f"{datetime.now().strftime('%Y.%m.%d')} TOPIX100厳選\n\n" + "\n\n".join(up)
        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                      json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
