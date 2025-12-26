import requests
import json
from datetime import date, timedelta

BASE_URL = "http://127.0.0.1:8000"

def test_backtest():
    print("Testing backtest API...")
    
    # 1. Run backtest
    payload = {
        "strategy_name": "Test Strategy",
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "initial_capital": 100000.0,
        "regime_filter": ["TREND_RISK"],
        "stop_loss_pct": 0.5,
        "take_profit_pct": 1.0
    }
    
    try:
        response = requests.post(f"{BASE_URL}/backtest/run", json=payload)
        if response.status_code != 200:
            print(f"Failed to start backtest: {response.text}")
            return
            
        data = response.json()
        run_id = data["run_id"]
        print(f"Backtest started with ID: {run_id}")
        
        # 2. Get results
        response = requests.get(f"{BASE_URL}/backtest/{run_id}")
        if response.status_code == 200:
            results = response.json()
            print("Results:")
            print(json.dumps(results["metrics"], indent=2))
        else:
            print(f"Failed to get results: {response.text}")
            
        # 3. Get trades
        response = requests.get(f"{BASE_URL}/backtest/{run_id}/trades")
        if response.status_code == 200:
            trades = response.json()
            print(f"Total trades: {len(trades)}")
            if trades:
                print("First trade:", trades[0])
        else:
            print(f"Failed to get trades: {response.text}")
            
        # 4. Get equity curve
        response = requests.get(f"{BASE_URL}/backtest/{run_id}/equity")
        if response.status_code == 200:
            curve = response.json()
            print(f"Equity curve points: {len(curve)}")
        else:
            print(f"Failed to get equity curve: {response.text}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_backtest()
