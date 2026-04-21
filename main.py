import os
import requests
import pandas as pd
from datetime import datetime, timedelta

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

DEBUG_CODE = "4768" # 大塚商会

if __name__ == "__main__":
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    # 75営業日を確実に含む期間（約120暦日）
    start_date = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    # データ取得
    r = requests.get(f"{host}/equities/bars/daily", headers=headers, 
                     params={"code": DEBUG_CODE, "from": start_date, "to": end_date})
    
    if r.status_code == 200:
        data = r.json().get("data", [])
        # 75日線が計算できる最低件数を確認
        if len(data) >= 75:
            df = pd.DataFrame(data).sort_values('Date').reset_index(drop=True)
            df['close'] = pd.to_numeric(df['C'], errors='coerce')
            
            # 各移動平均線の計算
            df['ma5'] = df['close'].rolling(5).mean()
            df['ma25'] = df['close'].rolling(25).mean()
            df['ma75'] = df['close'].rolling(75).mean()
            
            # 直近の各数値
            c = df.iloc[-1]   # 今日
            p = df.iloc[-2]   # 昨日
            
            # 判定ロジック
            # 1. GC判定（5日線が25日線を下から上に抜いたか）
            is_gc = (p['ma5'] <= p['ma25']) and (c['ma5'] > c['ma25'])
            
            # 2. MA25の向き
            ma25_up = c['ma25'] > p['ma25']
            
            # 3. MA75との位置関係（おまけ判定：長期線より上か）
            above_ma75 = c['close'] > c['ma75']
            
            msg = (f"【大塚商会 120日データ検証】\n"
                   f"日付: {c['Date'][5:]}\n"
                   f"終値: {c['close']:.1f}\n\n"
                   f"MA5:  {c['ma5']:.1f}\n"
                   f"MA25: {c['ma25']:.1f} ({'上昇' if ma25_up else '下降'})\n"
                   f"MA75: {c['ma75']:.1f}\n\n"
                   f"判定:\n"
                   f"・GC状況: {'発生' if is_gc else 'なし'}\n"
                   f"・長期線(75日)比: {'上' if above_ma75 else '下'}")
        else:
            msg = f"データ不足（現在{len(data)}件 / 75件必要）"
            
        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                      json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
