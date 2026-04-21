import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import re
import time

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

# MAJOR_STOCKS リストは以前のものを維持（省略）

def normalize_code(raw_code):
    s = str(raw_code).strip()
    m = re.search(r'\d{4}', s)
    return m.group(0) if m else s.zfill(4)[:4]

def fetch_data_chunked(headers, total_days=105, chunk_days=35):
    """指定された日数を分割して取得する"""
    all_data = []
    end_date = datetime.now()
    
    # 35日ずつ遡って取得
    for i in range(0, total_days, chunk_days):
        from_date = (end_date - timedelta(days=i + chunk_days - 1)).strftime("%Y-%m-%d")
        to_date = (end_date - timedelta(days=i)).strftime("%Y-%m-%d")
        
        params = {"from": from_date, "to": to_date}
        try:
            # タイムアウト対策でtimeoutを設定
            r = requests.get("https://api.jquants.com/v2/equities/bars/daily", 
                             headers=headers, params=params, timeout=60)
            if r.status_code == 200:
                data = r.json().get("data", [])
                all_data.extend(data)
                print(f"Success: {from_date} to {to_date} ({len(data)} records)")
            else:
                print(f"Error {r.status_code}: {from_date} to {to_date}")
        except Exception as e:
            print(f"Request failed: {e}")
        
        # 連続リクエストによる負荷を避けるため少し待機
        time.sleep(1)
        
    return all_data

def calculate_indicators(df):
    df = df.sort_values(['Code', 'Date']).reset_index(drop=True)
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['open'] = pd.to_numeric(df['O'], errors='coerce')
    df['high'] = pd.to_numeric(df['H'], errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)
    
    # 75日線を出すために必要な日数をチェック
    if len(df) < 76: return None
    
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    df['ma75'] = df['close'].rolling(75).mean()
    
    df['high_10d'] = df['high'].shift(1).rolling(10).max()
    df['bbh'] = df['close'].rolling(20).mean() + (df['close'].rolling(20).std() * 2)
    return df

def run_scan(target_codes, full_df, master_info):
    up_res = []
    # 銘柄ごとにグループ化して処理
    for code, group in full_df.groupby('Code'):
        s_code = normalize_code(code)
        if target_codes and s_code not in target_codes: continue
        if target_codes is None and (s_code.startswith("1") and int(s_code) < 1600): continue
        
        df = calculate_indicators(group.copy())
        if df is None: continue
        
        c = df.iloc[-1]
        raw_s, labels = 0, []
        
        is_yang = c['close'] > c['open']
        if is_yang: raw_s += 15; labels.append("陽線(+15)")
        
        # GC初動 (直近5日)
        gc_found = any(df['ma5'].iloc[i-1] <= df['ma25'].iloc[i-1] and df['ma5'].iloc[i] > df['ma25'].iloc[i] 
                       for i in range(len(df)-4, len(df)) if i > 0)
        if gc_found: raw_s += 40; labels.append("GC初動(+40)")
        
        if df['ma25'].diff().iloc[-3:].min() > 0: raw_s += 20; labels.append("MA25上昇(+20)")
        
        # トレンド初動 (5 > 25 > 75 かつ 収束)
        is_po = (c['ma5'] > c['ma25'] > c['ma75'])
        is_conv = (abs(c['ma5'] - c['ma75']) / c['ma75']) < 0.03
        if is_po and is_conv:
            raw_s += 30; labels.append("トレンド初動(+30)")
        elif is_po:
            raw_s += 10; labels.append("上昇トレンド継続(+10)")

        if c['close'] > c['high_10d']: raw_s += 20; labels.append("高値突破(+20)")
        
        # 出来高
        base_vol = df['volume'].iloc[-8:-3].mean()
        vol_ratio = c['volume'] / base_vol if base_vol > 0 else 1.0
        if is_yang and vol_ratio >= 1.5:
            v_pts = 50 if vol_ratio >= 3.0 else 30
            raw_s += v_pts; labels.append(f"出来高x{vol_ratio:.1f}(+{v_pts})")
            
        if c['close'] > c['bbh']: raw_s -= 15; labels.append("過熱警戒(-15)")
        
        if raw_s >= 40:
            name, sector = master_info.get(s_code, ("不明", "不明"))
            up_res.append((raw_s, f"{s_code} {name} ({sector})\n{c['close']:.1f}円 【{raw_s}点】\n" + "・".join(labels)))
            
    return [x[1] for x in sorted(up_res, key=lambda x:x[0], reverse=True)[:10]]

if __name__ == "__main__":
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    # 銘柄マスター
    m_r = requests.get(f"{host}/listed/info", headers=headers, timeout=30)
    master = {normalize_code(m["Code"]): (m["CompanyName"], m["Sector17CodeName"]) for m in m_r.json().get("info", [])}
    
    # 【変更点】35日×3回の分割取得
    all_raw_data = fetch_data_chunked(headers, total_days=105, chunk_days=35)
    
    if all_raw_data:
        full_df = pd.DataFrame(all_raw_data)
        today = datetime.now().strftime('%Y.%m.%d')
        
        # 主要株レポート
        m_res = run_scan(set(MAJOR_STOCKS.keys()), full_df, MAJOR_STOCKS)
        if m_res:
            requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                          json={"to": USER_ID, "messages": [{"type": "text", "text": f"{today} 国内主要株レポート(105日分割取得)\n\n" + "\n\n".join(m_res)}]})
            
        # 全銘柄レポート
        a_res = run_scan(None, full_df, master)
        if a_res:
            requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                          json={"to": USER_ID, "messages": [{"type": "text", "text": f"{today} 株式市場レポート(105日分割取得)\n\n" + "\n\n".join(a_res)}]})
