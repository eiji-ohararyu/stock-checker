import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import re

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

# 主要株リスト (STOCKS_DATAは以前のものを維持)
STOCKS_DATA = {
    "4768": ("大塚商会", "情報・通信業"), "8035": ("東エレク", "電気機器"),
    # ... 他の銘柄 ...
}

def normalize_code(raw_code):
    s = str(raw_code).strip()
    m = re.search(r'\d{4}', s)
    return m.group(0) if m else s.zfill(4)[:4]

def calculate_indicators(df):
    df = df.sort_values('Date').reset_index(drop=True)
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['open'] = pd.to_numeric(df['O'], errors='coerce')
    df['high'] = pd.to_numeric(df['H'], errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)
    
    # 50日線を出すため、最低55営業日程度を確保
    if len(df) < 55: return None
    
    # 移動平均線 (5, 25, 50)
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    df['ma50'] = df['close'].rolling(50).mean()
    
    df['high_10d'] = df['high'].shift(1).rolling(10).max()
    df['bbh'] = df['close'].rolling(20).mean() + (df['close'].rolling(20).std() * 2)
    return df

def run_scan(target_codes, full_df, master_info):
    up_res = []
    for code, group in full_df.groupby('Code'):
        s_code = normalize_code(code)
        if target_codes and s_code not in target_codes: continue
        # ETF除外
        if target_codes is None and (s_code.startswith("1") and int(s_code) < 1600): continue
            
        df = calculate_indicators(group.copy())
        if df is None: continue
        
        c = df.iloc[-1]
        raw_s, d_l = 0, []
        is_yang = c['close'] > c['open']
        
        # 1. 陽線
        if is_yang: raw_s += 15; d_l.append("陽線(+15)")
        
        # 2. GC判定 (直近5日間で5日が25日を抜いたか)
        gc_found = False
        for i in range(len(df)-5, len(df)):
            if i <= 0: continue
            if df['ma5'].iloc[i-1] <= df['ma25'].iloc[i-1] and df['ma5'].iloc[i] > df['ma25'].iloc[i]:
                gc_found = True; break
        if gc_found: raw_s += 40; d_l.append("GC初動(+40)")
        
        # 3. MA25上昇トレンド
        if df['ma25'].diff().iloc[-3:].min() > 0: raw_s += 20; d_l.append("MA25上昇(+20)")
        
        # 4. トレンド初動判定 (5 > 25 > 50 且つ 5と50の乖離が3%以内)
        is_po = (c['ma5'] > c['ma25'] > c['ma50'])
        is_conv = (abs(c['ma5'] - c['ma50']) / c['ma50']) < 0.03
        if is_po and is_conv:
            raw_s += 30; d_l.append("トレンド初動(+30)")
        elif is_po:
            raw_s += 10; d_l.append("上昇トレンド継続(+10)")
            
        # 5. 高値突破
        if c['close'] > c['high_10d']: raw_s += 20; d_l.append("高値突破(+20)")

        # 6. 出来高加点
        base_vol = df['volume'].iloc[-8:-3].mean()
        vol_ratio = c['volume'] / base_vol if base_vol > 0 else 1.0
        if is_yang and vol_ratio >= 1.5:
            v_pts = 50 if vol_ratio >= 3.0 else 30
            raw_s += v_pts; d_l.append(f"出来高x{vol_ratio:.1f}(+{v_pts})")
        
        final_score = int(raw_s * 0.7) if c['close'] > c['bbh'] else raw_s
        if c['close'] > c['bbh']: d_l.append("過熱警戒")

        if final_score >= 40:
            name, sector = master_info.get(s_code, ("不明", "不明"))
            suffix = "\n※理想的な並びと収束です" if (is_po and is_conv) else ""
            up_res.append((final_score, f"{s_code} {name} ({sector})\n{c['close']:.1f}円 【{final_score}点】\n" + "・".join(d_l) + suffix))
            
    return [x[1] for x in sorted(up_res, key=lambda x:x[0], reverse=True)[:10]]

if __name__ == "__main__":
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    m_r = requests.get(f"{host}/listed/info", headers=headers)
    master = {normalize_code(m["Code"]): (m["CompanyName"], m["Sector17CodeName"]) for m in m_r.json().get("info", [])}
    
    # 80暦日分取得 (一括リクエストで安定する限界)
    start_date = (datetime.now() - timedelta(days=80)).strftime("%Y-%m-%d")
    r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"from": start_date})
    
    if r.status_code == 200:
        full_df = pd.DataFrame(r.json().get("data", []))
        today = datetime.now().strftime('%Y.%m.%d')
        
        # 1. 国内主要株レポート
        m_up = run_scan(set(STOCKS_DATA.keys()), full_df, STOCKS_DATA)
        if m_up:
            requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                          json={"to": USER_ID, "messages": [{"type": "text", "text": f"{today} 国内主要株レポート\n\n" + "\n\n".join(m_up) + "\n\n───────────────\n詳細確認: https://www.sbisec.co.jp/ETGate/"}]})
            
        # 2. 株式市場レポート（全体）
        a_up = run_scan(None, full_df, master)
        if a_up:
            requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                          json={"to": USER_ID, "messages": [{"type": "text", "text": f"{today} 株式市場レポート\n\n" + "\n\n".join(a_up) + "\n\n───────────────\n詳細確認: https://www.sbisec.co.jp/ETGate/"}]})
