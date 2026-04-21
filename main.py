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

# STOCKS_DATA (主要株150) は以前のものを維持

def normalize_code(raw_code):
    s = str(raw_code).strip()
    return re.search(r'\d{4}', s).group(0) if re.search(r'\d{4}', s) else s.zfill(4)[:4]

def calculate_indicators(df, use_75=True):
    df = df.sort_values('Date').reset_index(drop=True)
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['open'] = pd.to_numeric(df['O'], errors='coerce')
    df['high'] = pd.to_numeric(df['H'], errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)
    
    min_days = 80 if use_75 else 30
    if len(df) < min_days: return None
    
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    if use_75:
        df['ma75'] = df['close'].rolling(75).mean()
    
    df['high_10d'] = df['high'].shift(1).rolling(10).max()
    df['std'] = df['close'].rolling(20).std()
    df['bbh'] = df['close'].rolling(20).mean() + (df['std'] * 2)
    return df

def run_scan(target_codes, full_df, master_info, use_75=True):
    up_res = []
    for code, group in full_df.groupby('Code'):
        s_code = normalize_code(code)
        if target_codes and s_code not in target_codes: continue
        
        df = calculate_indicators(group.copy(), use_75=use_75)
        if df is None: continue
        
        curr = df.iloc[-1]
        raw_s, d_l = 0, []
        is_yang = curr['close'] > curr['open']
        if is_yang: raw_s += 15; d_l.append("陽線(+15)")
        
        # GC判定 (直近5日)
        gc_found = any(df['ma5'].iloc[i-1] <= df['ma25'].iloc[i-1] and df['ma5'].iloc[i] > df['ma25'].iloc[i] 
                       for i in range(len(df)-4, len(df)) if i > 0)
        if gc_found: raw_s += 40; d_l.append("GC初動(+40)")
        
        if df['ma25'].diff().iloc[-3:].min() > 0: raw_s += 20; d_l.append("MA25上昇(+20)")
        
        # 75日線が計算できる場合のみ「トレンド初動」を判定
        is_po, is_conv = False, False
        if use_75:
            is_po = (curr['ma5'] > curr['ma25'] > curr['ma75'])
            is_conv = (abs(curr['ma5'] - curr['ma75']) / curr['ma75']) < 0.03
            if is_po and is_conv: raw_s += 30; d_l.append("トレンド初動(+30)")
            elif is_po: raw_s += 10; d_l.append("上昇トレンド継続(+10)")

        if curr['close'] > curr['high_10d']: raw_s += 20; d_l.append("高値突破(+20)")
        
        # 出来高
        base_vol = df['volume'].iloc[-8:-3].mean()
        vol_ratio = curr['volume'] / base_vol if base_vol > 0 else 1.0
        if is_yang and vol_ratio >= 1.5:
            v_pts = 50 if vol_ratio >= 3.0 else 30
            raw_s += v_pts; d_l.append(f"出来高x{vol_ratio:.1f}(+{v_pts})")
            
        final_score = int(raw_s * 0.7) if curr['close'] > curr['bbh'] else raw_s
        if curr['close'] > curr['bbh']: d_l.append("過熱警戒")

        if final_score >= 40:
            name, sector = master_info.get(s_code, ("不明", "不明"))
            up_res.append((final_score, f"{s_code} {name} ({sector})\n{curr['close']:.1f}円 【{final_score}点】\n" + "・".join(d_l)))
            
    return [x[1] for x in sorted(up_res, key=lambda x:x[0], reverse=True)[:10]]

if __name__ == "__main__":
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    m_r = requests.get(f"{host}/listed/info", headers=headers)
    master = {normalize_code(m["Code"]): (m["CompanyName"], m["Sector17CodeName"]) for m in m_r.json().get("info", [])}
    today_dt = datetime.now()

    # --- 1. 主要株: 105日分取得して75日線を計算 ---
    start_m = (today_dt - timedelta(days=105)).strftime("%Y-%m-%d")
    m_data = []
    for code in STOCKS_DATA.keys():
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"code": code, "from": start_m})
        if r.status_code == 200: m_data.extend(r.json().get("data", []))
    
    if m_data:
        m_up = run_scan(set(STOCKS_DATA.keys()), pd.DataFrame(m_data), STOCKS_DATA, use_75=True)
        send_line(f"{today_dt.strftime('%Y.%m.%d')} 国内主要株(75日線対応)\n" + "\n\n".join(m_up))

    # --- 2. 全銘柄: 40日分だけ取得して25日線まででスキャン (激軽) ---
    start_a = (today_dt - timedelta(days=40)).strftime("%Y-%m-%d")
    r_all = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"from": start_a})
    if r_all.status_code == 200:
        a_up = run_scan(None, pd.DataFrame(r_all.json().get("data", [])), master, use_75=False)
        send_line(f"{today_dt.strftime('%Y.%m.%d')} 株式市場(40日スキャン)\n" + "\n\n".join(a_up))
