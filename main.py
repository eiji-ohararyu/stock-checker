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

# --- 監視対象（主要株） ---
MAJOR_STOCKS = {
    "6723": ("ルネサス", "電気機器"), "6752": ("パナソニック", "電気機器"),
    "4063": ("信越化", "化学"), "8035": ("東エレク", "電気機器"),
    "7011": ("三菱重", "機械"), "9984": ("ソフトバンクG", "情報・通信業")
}

def normalize_code(raw_code):
    s = str(raw_code).strip()
    m = re.search(r'\d{4}', s)
    return m.group(0) if m else s.zfill(4)[:4]

def calculate_indicators(df):
    df['open'] = pd.to_numeric(df['O'], errors='coerce')
    df['high'] = pd.to_numeric(df['H'], errors='coerce')
    df['low'] = pd.to_numeric(df['L'], errors='coerce')
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)
    if len(df) < 50: return None
    
    # 移動平均線
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    df['ma75'] = df['close'].rolling(75).mean()
    
    # RSI (14日)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    
    # ボリンジャーバンド
    df['std'] = df['close'].rolling(20).std()
    df['bbh'] = df['close'].rolling(20).mean() + (df['std'] * 2)
    return df

def run_scan(target_codes, full_df, master_info):
    up_res = []
    for code, group in full_df.groupby('Code'):
        s_code = normalize_code(code)
        if target_codes and s_code not in target_codes: continue
            
        df = calculate_indicators(group.copy())
        if df is None: continue
        
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        score, desc = 0, []
        
        # 1. トレンド判定 (パーフェクトオーダー)
        if curr['ma5'] > curr['ma25'] > curr['ma75']:
            score += 40; desc.append("Pオーダー(+40)")
            
        # 2. ギャップアップ判定 (材料反応の検知)
        if curr['open'] > prev['high']:
            score += 30; desc.append("窓開け上昇(+30)")
        
        # 3. 出来高急増判定 (直近5日平均比)
        if len(df) >= 15:
            base_vol = df['volume'].iloc[-6:-1].mean()
            v_ratio = curr['volume'] / base_vol if base_vol > 0 else 1.0
            if v_ratio >= 2.0:
                score += 30; desc.append(f"出来高急増(x{v_ratio:.1f})(+30)")
        
        # 4. RSI判定 (過熱・売られすぎ)
        if curr['rsi'] > 80:
            score -= 20; desc.append(f"RSI買われすぎ")
        elif curr['rsi'] < 30:
            score += 20; desc.append(f"RSI売られすぎ")

        # 5. ボリンジャーバンド (バンドウォーク/過熱)
        if curr['close'] > curr['bbh']:
            score = int(score * 0.7); desc.append("BB過熱調整")

        if score >= 40:
            name, sector = master_info.get(s_code, ("不明", "不明"))
            up_res.append((score, f"{s_code} {name}\n{curr['close']:.1f}円 【{score}点】\n" + "・".join(desc)))
            
    return [x[1] for x in sorted(up_res, key=lambda x:x[0], reverse=True)[:10]]

if __name__ == "__main__":
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    # 銘柄マスター
    m_r = requests.get(f"{host}/listed/info", headers=headers)
    master = {normalize_code(m["Code"]): (m["CompanyName"], m["Sector17CodeName"]) for m in m_r.json().get("info", [])}
    
    # 過去80日分のデータ取得
    all_prices = []
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(80)]
    for d in reversed(dates):
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d})
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data: all_prices.extend(data)
    
    if all_prices:
        full_df = pd.DataFrame(all_prices).sort_values(['Code', 'Date'])
        today = datetime.now().strftime('%Y.%m.%d')
        
        # レポート実行
        res = run_scan(None, full_df, master)
        if res:
            send_line(f"{today} 株式市場スコアレポート\n\n" + "\n\n".join(res))
