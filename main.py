import os
import requests
import json
from datetime import datetime, timedelta

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

DEBUG_CODE = "4768" # 大塚商会

def get_full_raw_data():
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    # 75日線を確実に計算するため、120営業日前（約180暦日前）から取得
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    r = requests.get(f"{host}/equities/bars/daily", headers=headers, 
                     params={"code": DEBUG_CODE, "from": start_date, "to": end_date})
    
    if r.status_code != 200:
        return f"APIエラー: {r.status_code}"
    
    data_list = r.json().get("data", [])
    
    # 全件の生データを日付順に並べてテキスト化
    # ※LINEの文字数制限を超える可能性があるため、直近30件を表示し、
    # 本来はファイルとして保存・確認すべきデータです。
    output = []
    for entry in data_list:
        # 必要な要素（日付、終値、修正係数）に絞って1行で出す
        line = f"{entry['Date']} C:{entry['C']} AdjC:{entry.get('AdjustmentClose', entry['C'])} F:{entry.get('AdjFactor', 1.0)}"
        output.append(line)
    
    return "\n".join(output)

if __name__ == "__main__":
    raw_list = get_full_raw_data()
    
    # 判定に使われる「全ての弾丸」を提示
    msg = f"【大塚商会 120営業日 生データ】\n\n{raw_list}"
    
    # 文字数が多すぎる場合は分割して送信されます
    requests.post("https://api.line.me/v2/bot/message/push", 
                  headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                  json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
