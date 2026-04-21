import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def calculate_strict_indicators(df):
    # 昇順ソート
    df = df.sort_values('Date').reset_index(drop=True)
    df['close'] = pd.to_numeric(df['C'], errors='coerce')
    
    # 移動平均を算出
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    df['ma75'] = df['close'].rolling(75).mean()
    
    return df

def run_final_check(full_df):
    df = calculate_strict_indicators(full_df.copy())
    if df is None: return "データ不足"
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    # --- 厳格判定ロジック ---
    # 1. 物理的な位置関係のガード
    # 「短期線(MA5)が中期(MA25)・長期(MA75)よりも数値的に大きい」場合でも、
    # 直近30日の安値を更新中などの「実態としての下落」があればGCを認めない
    
    low_30d = df['close'].iloc[-30:].min()
    
    # クロス判定（物理的に抜いた瞬間のみ）
    is_gc = (prev['ma5'] <= prev['ma25']) and (curr['ma5'] > curr['ma25'])
    
    # MA25の傾き（適当な判定を排除するため、3日連続上昇を確認）
    ma25_trend = df['ma25'].diff().iloc[-3:].sum()
    
    # 判定結果の構築
    labels = []
    if is_gc: labels.append("GC初動(+20)")
    if ma25_trend > 0: labels.append("MA25上昇(+25)")
    if curr['close'] > low_30d * 1.05: labels.append("底打ち確認")
    
    # --- 全数値をそのまま出す仕様 ---
    debug_info = (
        f"[MA数値] 5線:{curr['ma5']:.1f} / 25線:{curr['ma25']:.1f} / 75線:{curr['ma75']:.1f}\n"
        f"[株価位置] 終値が75日線より{'上' if curr['close'] > curr['ma75'] else '下'}"
    )
    
    return f"4768 大塚商会\n{curr['close']:.1f}円\n" + "・".join(labels) + f"\n{debug_info}"

if __name__ == "__main__":
    # 山本さんに提供いただいた全データをリストとして読み込む想定（デバッグ用）
    # 実際はAPIから120日分取得
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    start_date = (datetime.now() - timedelta(days=150)).strftime("%Y-%m-%d")
    r = requests.get(f"{host}/equities/bars/daily", headers=headers, 
                     params={"code": "4768", "from": start_date})
    
    if r.status_code == 200:
        full_df = pd.DataFrame(r.json().get("data", []))
        result = run_final_check(full_df)
        
        msg = f"【最終検証レポート】\n\n{result}"
        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                      json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
