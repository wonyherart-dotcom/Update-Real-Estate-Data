import os
import json
import datetime
import requests
import xmltodict

# 1. 설정값 (강남구 법정동 시군구코드: 11680, 역삼동)
SERVICE_KEY = os.environ.get("DATA_GO_KR_API_KEY")
LAWD_CD = "11680"  # 서울시 강남구
TARGET_DONG = "역삼동"

# 국토교통부 표준 OpenAPI 엔드포인트
URL_TRADE = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
URL_RENT = "http://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

def get_recent_ym_list(months_back=3):
    today = datetime.date.today()
    ym_list = []
    for i in range(months_back):
        # 대략적인 월 계산
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        ym_list.append(f"{year}{month:02d}")
    return ym_list

def fetch_api_data(endpoint, deal_ym):
    params = {
        "serviceKey": SERVICE_KEY,
        "LAWD_CD": LAWD_CD,
        "DEAL_YMD": deal_ym,
        "pageNo": "1",
        "numOfRows": "2000"
    }
    res = requests.get(endpoint, params=params, timeout=15)
    if res.status_code != 200:
        return []
    
    data_dict = xmltodict.parse(res.text)
    header = data_dict.get("response", {}).get("header", {})
    if header.get("resultCode") != "00":
        return []
        
    items = data_dict.get("response", {}).get("body", {}).get("items", {})
    if not items or "item" not in items:
        return []
        
    item_list = items["item"]
    return item_list if isinstance(item_list, list) else [item_list]

def run_pipeline():
    ym_list = get_recent_ym_list(months_back=3)
    trades_filtered = []
    rents_filtered = []

    for ym in ym_list:
        # 매매 수집
        raw_trades = fetch_api_data(URL_TRADE, ym)
        for item in raw_trades:
            if TARGET_DONG in item.get("umdNm", "") or TARGET_DONG in item.get("법정동", ""):
                deal_amount_str = item.get("dealAmount", item.get("거래금액", "0")).replace(",", "").strip()
                trades_filtered.append({
                    "aptName": item.get("aptNm", item.get("아파트", "")),
                    "area": float(item.get("excluUseAr", item.get("전용면적", 0))),
                    "floor": int(item.get("floor", item.get("층", 0))),
                    "dealAmount": int(deal_amount_str),  # 단위: 만원
                    "date": f"{item.get('dealYear', item.get('년'))}-{int(item.get('dealMonth', item.get('월'))):02d}-{int(item.get('dealDay', item.get('일'))):02d}",
                    "type": "매매"
                })

        # 전월세 수집
        raw_rents = fetch_api_data(URL_RENT, ym)
        for item in raw_rents:
            if TARGET_DONG in item.get("umdNm", "") or TARGET_DONG in item.get("법정동", ""):
                deposit_str = item.get("deposit", item.get("보증금액", "0")).replace(",", "").strip()
                monthly_rent_str = item.get("monthlyRent", item.get("월세금액", "0")).replace(",", "").strip()
                deposit = int(deposit_str)
                monthly = int(monthly_rent_str)
                rent_type = "월세" if monthly > 0 else "전세"
                
                rents_filtered.append({
                    "aptName": item.get("aptNm", item.get("아파트", "")),
                    "area": float(item.get("excluUseAr", item.get("전용면적", 0))),
                    "floor": int(item.get("floor", item.get("층", 0))),
                    "deposit": deposit,
                    "monthlyRent": monthly,
                    "date": f"{item.get('dealYear', item.get('년'))}-{int(item.get('dealMonth', item.get('월'))):02d}-{int(item.get('dealDay', item.get('일'))):02d}",
                    "type": rent_type
                })

    os.makedirs("data", exist_ok=True)
    payload = {
        "updatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trades": sorted(trades_filtered, key=lambda x: x["date"], reverse=True),
        "rents": sorted(rents_filtered, key=lambda x: x["date"], reverse=True)
    }
    with open("data/real_estate_data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    run_pipeline()