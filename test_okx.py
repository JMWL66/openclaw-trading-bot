import os
import requests
import base64
import hmac
import datetime
import json

def get_balance():
    api_key = "bfc766c7-9384-4803-9dca-15025fe70daf"
    secret_key = "F6ADC8A4CEC231A24010589B23B010B4"
    passphrase = "F8BR!Nh6!h23!yZ"

    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    path = "/api/v5/account/balance?ccy=USDT"
    msg = ts + "GET" + path
    sign = base64.b64encode(hmac.new(secret_key.encode(), msg.encode(), "sha256").digest()).decode()

    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Accept": "application/json",
    }
    
    # 1. Test live
    res1 = requests.get("https://www.okx.com" + path, headers=headers)
    print("LIVE:", res1.json())
    
    # 2. Test demo
    headers["x-simulated-trading"] = "1"
    res2 = requests.get("https://www.okx.com" + path, headers=headers)
    print("DEMO:", res2.json())

get_balance()
