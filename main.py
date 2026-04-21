import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import re
from scipy.signal import argrelextrema

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

# MAJOR_STOCKS リストは以前のものを維持（省略）

def normalize_code(raw_code):
    s = str(raw_code).strip()
    m = re.search(r'\d{4}', s)
    return m.group(0) if m else s.zfill(4)[:4]

def calculate_indicators(df):
    df = df.sort_values('Date').reset_index(drop=True)
    df['open'] = pd.to_numeric(df['O'], errors='coerce')
    df['high'] = pd.to_numeric(df['H'], errors='coerce')
    # 修正株価を優先使用
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)
    
    # 75日線を出すため最低80営業日は必要
    if len(df) < 80: return None
    
    # 移動平均線 (5, 25, 75)
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    df['ma75'] = df['close'].rolling(75).mean()
    
    df['high_10d'] = df['high'].shift(1).rolling(10).max()
    df['std'] = df['close'].rolling(20).std()
    df['bbh'] = df['close'].rolling(20).mean() + (df['std'] * 2)
    return df

def detect_strict_bottom(prices):
    """ダブルボトム判定"""
    res = {'score': 0, 'desc': []}
    t_idx = argrelextrema(prices, np.less_equal, order=10)[0]
    if len(t_idx) >= 2:
        idx1, idx2 = t_idx[-2], t_idx[-1]
        p1, p2 = prices[idx1], prices[idx2]
        peak = prices[idx1:idx2].max()
        if (peak - p1) / p1 > 0.04: 
            if abs(p1 - p2) / p1 < 0.02 or p2 > p1:
                if (idx2 - idx1) >= 12:
                    res['score'] = 40; res['desc'].append("ダブルボトム(+40)")
    return res

def send_line(msg):
    requests.post("https://api.line.me/v2/bot/message/push", 
                  headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                  json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})

def run_scan(target_codes, full_df, master_info):
    up_res = []
    for code, group in full_df.groupby('Code'):
        s_code = normalize_code(code)
        if target_codes and s_code not in target_codes: continue
            
        df = calculate_indicators(group.copy())
        if df is None: continue
        
        curr = df.iloc[-1]
        raw_s, d_l = 0, []
        is_yang = curr['close'] > curr['open']
        
        # 1. 陽線
        if is_yang: raw_s += 15; d_l.append("陽線(+15)")
        
        # 2. GC判定（直近5日間に拡張）
        gc_found = False
        for i in range(len(df)-5, len(df)):
            if i <= 0: continue
            p_row, c_row = df.iloc[i-1], df.iloc[i]
            if p_row['ma5'] <= p_row['ma25'] and c_row['ma5'] > c_row['ma25']:
                gc_found = True; break
        if gc_found: raw_s += 40; d_l.append("GC初動(+40)")
        
        # 3. MA25上昇トレンド (生命線)
        if df['ma25'].diff().iloc[-3:].min() > 0: raw_s += 20; d_l.append("MA25上昇(+20)")
        
        # 4. トレンド初動（順列×収束）
        # 並びが 5 > 25 > 75 かつ、短期と長期の乖離が3%以内
        is_po = (curr['ma5'] > curr['ma25']) and (curr['ma25'] > curr['ma75'])
        is_converged = ((abs(curr['ma5'] - curr['ma75'])) / curr['ma75']) < 0.03
        if is_po and is_converged:
            raw_s += 30; d_l.append("トレンド初動(+30)")
        elif is_po:
            raw_s += 10; d_l.append("上昇トレンド継続(+10)")
            
        # 5. 高値突破・ボトム判定
        if curr['close'] > curr['high_10d']: raw_s += 20; d_l.append("高値突破(+20)")
        p = detect_strict_bottom(df['close'].values)
        raw_s += p['score']; d_l.extend(p['desc'])

        # 6. 出来高加点
        vol_score = 0
        base_vol = df['volume'].iloc[-8:-3].mean()
        vol_ratio = curr['volume'] / base_vol if base_vol > 0 else 1.0
        if is_yang:
            if vol_ratio >= 5.0:   vol_score = 70; d_l.append(f"出来高異常値(x{vol_ratio:.1f})")
            elif vol_ratio >= 3.0: vol_score = 50; d_l.append(f"出来高爆増(x{vol_ratio:.1f})")
            elif vol_ratio >= 2.0: vol_score = 30; d_l.append(f"出来高急増(x{vol_ratio:.1f})")
            elif vol_ratio >= 1.5: vol_score = 15; d_l.append(f"出来高増加(x{vol_ratio:.1f})")
        
        final_score = raw_s + vol_score
        if curr['close'] > curr['bbh']:
            final_score = int(final_score * 0.7); d_l.append("過熱警戒")

        if final_score >= 40:
            name, sector = master_info.get(s_code, ("不明", "不明"))
            suffix = "\n※理想的な並びと収束です" if (is_po and is_converged) else ""
            up_res.append((final_score, f"{s_code} {name} ({sector})\n{curr['close']:.1f}円 【{final_score}点】\n" + "・".join(d_l) + suffix))
            
    return [x[1] for x in sorted(up_res, key=lambda x:x[0], reverse=True)[:10]]

if __name__ == "__main__":
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    m_r = requests.get(f"{host}/listed/info", headers=headers)
    master = {normalize_code(m["Code"]): (m["CompanyName"], m["Sector17CodeName"]) for m in m_r.json().get("info", [])}
    
    # 75日線を出すために120暦日前から取得
    start_date = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
    r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"from": start_date})
    
    if r.status_code == 200:
        full_df = pd.DataFrame(r.json().get("data", []))
        today = datetime.now().strftime('%Y.%m.%d')
        
        m_up = run_scan(set(MAJOR_STOCKS.keys()), full_df, MAJOR_STOCKS)
        if m_up:
            send_line(f"{today} 国内主要株レポート\n" + "\n\n".join(m_up) + "\n\n───────────────\n詳細確認: https://www.sbisec.co.jp/ETGate/")
            
        a_up = run_scan(None, full_df, master)
        if a_up:
            send_line(f"{today} 株式市場レポート\n" + "\n\n".join(a_up) + "\n\n───────────────\n詳細確認: https://www.sbisec.co.jp/ETGate/")
