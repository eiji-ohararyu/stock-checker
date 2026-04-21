import os
import requests
import json
from datetime import datetime, timedelta

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

DEBUG_CODE = "4768" # 大塚商会

def get_raw_api_data():
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    # 直近10営業日分程度をターゲットにする
    start_date = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    r = requests.get(f"{host}/equities/bars/daily", headers=headers, 
                     params={"code": DEBUG_CODE, "from": start_date, "to": end_date})
    
    if r.status_code != 200:
        return f"APIエラー: {r.status_code}\n{r.text}"
    
    raw_json = r.json()
    data_list = raw_json.get("data", [])
    
    # APIから返ってきたリストを、一切加工せずそのまま文字列化
    # 1件ずつ改行して、読みやすくします
    formatted_raw_data = []
    for entry in data_list:
        formatted_raw_data.append(json.dumps(entry, ensure_ascii=False))
    
    return "\n".join(formatted_raw_data)

if __name__ == "__main__":
    raw_output = get_raw_api_data()
    
    # LINEの文字数制限に配慮しつつ、生のリストをそのまま送信
    msg = f"【大塚商会 API生データリスト】\n\n{raw_output}"
    
    requests.post("https://api.line.me/v2/bot/message/push", 
                  headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                  json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
