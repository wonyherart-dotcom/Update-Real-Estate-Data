Python
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
③ .github/workflows/update_data.yml
YAML
name: Update Real Estate Data

on:
  schedule:
    - cron: '0 21 * * *'  # 매일 한국 시간 06:00
  workflow_dispatch:      # 수동 실행 트리거

jobs:
  build-and-update:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Dependencies
        run: pip install -r requirements.txt

      - name: Execute Fetcher
        env:
          DATA_GO_KR_API_KEY: ${{ secrets.DATA_GO_KR_API_KEY }}
        run: python scripts/fetch_transactions.py

      - name: Commit and Push if Changed
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          git add data/real_estate_data.json
          git diff --quiet && git diff --staged --quiet || (git commit -m "Auto-update: $(date +'%Y-%m-%d')" && git push)
④ index.html (대시보드 프론트엔드)
HTML
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>역삼동 아파트 실거래가 모니터링</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body class="bg-slate-50 text-slate-800 p-6">
  <div class="max-w-6xl mx-auto space-y-6">
    <header class="flex justify-between items-center border-b pb-4">
      <div>
        <h1 class="text-2xl font-bold">강남구 역삼2동 주변 실거래가 대시보드</h1>
        <p class="text-sm text-slate-500">출처: 국토교통부 실거래가 공개시스템 API</p>
      </div>
      <div id="updatedAt" class="text-xs text-slate-400">업데이트 확인 중...</div>
    </header>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
        <span class="text-sm text-slate-500">최근 3개월 매매 건수</span>
        <div id="tradeCount" class="text-2xl font-bold mt-1 text-blue-600">-</div>
      </div>
      <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
        <span class="text-sm text-slate-500">최근 3개월 전세 건수</span>
        <div id="jeonseCount" class="text-2xl font-bold mt-1 text-emerald-600">-</div>
      </div>
      <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
        <span class="text-sm text-slate-500">최근 3개월 월세 건수</span>
        <div id="monthlyCount" class="text-2xl font-bold mt-1 text-purple-600">-</div>
      </div>
    </div>

    <div class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
      <h2 class="text-lg font-semibold mb-4">최근 매매가 추이 (만원)</h2>
      <canvas id="tradeChart" height="90"></canvas>
    </div>

    <div class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
      <div class="flex justify-between items-center mb-4">
        <h2 class="text-lg font-semibold">최근 실거래 목록</h2>
        <input type="text" id="filterInput" placeholder="단지명 검색 (예: 래미안, 개나리)" class="border rounded px-3 py-1 text-sm outline-none">
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm">
          <thead class="bg-slate-100 text-slate-600 border-b">
            <tr>
              <th class="p-3">계약일</th>
              <th class="p-3">단지명</th>
              <th class="p-3">구분</th>
              <th class="p-3">전용면적</th>
              <th class="p-3">층</th>
              <th class="p-3">거래금액 / 보증금</th>
              <th class="p-3">월세</th>
            </tr>
          </thead>
          <tbody id="tableBody" class="divide-y"></tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    let rawTrades = [];
    let rawRents = [];

    async function loadData() {
      const res = await fetch('data/real_estate_data.json');
      const data = await res.json();
      
      document.getElementById('updatedAt').innerText = `최종 갱신: ${data.updatedAt}`;
      rawTrades = data.trades;
      rawRents = data.rents;

      const jeonses = rawRents.filter(r => r.type === '전세');
      const monthlies = rawRents.filter(r => r.type === '월세');

      document.getElementById('tradeCount').innerText = `${rawTrades.length}건`;
      document.getElementById('jeonseCount').innerText = `${jeonses.length}건`;
      document.getElementById('monthlyCount').innerText = `${monthlies.length}건`;

      renderChart(rawTrades);
      renderTable([...rawTrades, ...rawRents]);
    }

    function renderChart(trades) {
      const sorted = [...trades].sort((a,b) => new Date(a.date) - new Date(b.date));
      new Chart(document.getElementById('tradeChart'), {
        type: 'line',
        data: {
          labels: sorted.map(t => `${t.date} (${t.aptName})`),
          datasets: [{
            label: '매매금액 (만원)',
            data: sorted.map(t => t.dealAmount),
            borderColor: '#2563eb',
            backgroundColor: 'rgba(37, 99, 235, 0.1)',
            fill: true,
            tension: 0.2
          }]
        },
        options: { responsive: true, scales: { y: { beginAtZero: false } } }
      });
    }

    function renderTable(list) {
      const tbody = document.getElementById('tableBody');
      tbody.innerHTML = '';
      const filter = document.getElementById('filterInput').value.trim();

      const filtered = list.filter(item => item.aptName.includes(filter))
                           .sort((a,b) => new Date(b.date) - new Date(a.date));

      filtered.slice(0, 50).forEach(item => {
        const tr = document.createElement('tr');
        const price = item.type === '매매' ? `${item.dealAmount.toLocaleString()}만원` : `${item.deposit.toLocaleString()}만원`;
        const monthly = item.monthlyRent ? `${item.monthlyRent.toLocaleString()}만원` : '-';
        tr.innerHTML = `
          <td class="p-3">${item.date}</td>
          <td class="p-3 font-medium">${item.aptName}</td>
          <td class="p-3"><span class="px-2 py-0.5 rounded text-xs ${item.type === '매매' ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'}">${item.type}</span></td>
          <td class="p-3">${item.area}㎡</td>
          <td class="p-3">${item.floor}층</td>
          <td class="p-3 font-semibold">${price}</td>
          <td class="p-3">${monthly}</td>
        `;
        tbody.appendChild(tr);
      });
    }

    document.getElementById('filterInput').addEventListener('input', () => {
      renderTable([...rawTrades, ...rawRents]);
    });

    loadData();
  </script>
</body>
</html>
