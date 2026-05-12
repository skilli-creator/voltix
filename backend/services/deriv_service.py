# backend/services/deriv_service.py
import websocket
import json
import threading
from config import Config

class DerivService:
    
    # CORRECT Deriv WebSocket URL
    DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3"
    DERIV_APP_ID = "1089"  # Demo App ID
    
    @staticmethod
    def _get_ws_url():
        """Get WebSocket URL with App ID"""
        return f"{DerivService.DERIV_WS_URL}?app_id={DerivService.DERIV_APP_ID}"
    
    @staticmethod
    def test_connection(api_token):
        """Test if the API token is valid using WebSocket"""
        result = {"success": False, "data": None, "error": None}
        response_received = threading.Event()
        
        def on_message(ws, message):
            data = json.loads(message)
            print(f"📨 Response: {data}")
            
            if data.get('authorize'):
                result["success"] = True
                result["data"] = data['authorize']
                response_received.set()
                ws.close()
            elif data.get('error'):
                result["error"] = data['error']['message']
                response_received.set()
                ws.close()
        
        def on_error(ws, error):
            print(f"❌ WebSocket error: {error}")
            result["error"] = str(error)
            response_received.set()
        
        def on_open(ws):
            ws_url = DerivService._get_ws_url()
            print(f"🔌 WebSocket connected to {ws_url}")
            print(f"🔑 Authorizing with token: {api_token[:20]}...")
            ws.send(json.dumps({"authorize": api_token}))
        
        def on_close(ws, close_status_code, close_msg):
            print(f"🔌 WebSocket closed: {close_status_code} - {close_msg}")
        
        ws_url = DerivService._get_ws_url()
        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        
        wst = threading.Thread(target=ws.run_forever)
        wst.daemon = True
        wst.start()
        
        response_received.wait(timeout=10)
        
        if result["success"]:
            print(f"✅ Authorization successful!")
            return True, result["data"]
        else:
            print(f"❌ Authorization failed: {result['error']}")
            return False, result["error"] or "Connection failed"
    
    @staticmethod
    def get_account_info(api_token):
        """Get account information using WebSocket"""
        result = {"success": False, "info": None, "error": None}
        response_received = threading.Event()
        
        def on_message(ws, message):
            data = json.loads(message)
            print(f"📨 Account Info Response: {data}")
            
            if data.get('authorize'):
                result["success"] = True
                result["info"] = {
                    'account_id': data['authorize'].get('loginid', ''),
                    'currency': data['authorize'].get('currency', 'USD'),
                    'account_type': 'Demo' if data['authorize'].get('is_virtual') else 'Real',
                    'email': data['authorize'].get('email', ''),
                    'balance': data['authorize'].get('balance', 0),
                    'fullname': data['authorize'].get('fullname', '')
                }
                response_received.set()
                ws.close()
            elif data.get('error'):
                result["error"] = data['error']['message']
                response_received.set()
                ws.close()
        
        def on_error(ws, error):
            result["error"] = str(error)
            response_received.set()
        
        def on_open(ws):
            ws.send(json.dumps({"authorize": api_token}))
        
        ws_url = DerivService._get_ws_url()
        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error
        )
        
        wst = threading.Thread(target=ws.run_forever)
        wst.daemon = True
        wst.start()
        
        response_received.wait(timeout=10)
        
        if result["success"]:
            return True, result["info"]
        else:
            return False, result["error"] or "Failed to get account info"
    
    @staticmethod
    def get_balance(api_token):
        """Get account balance using WebSocket"""
        result = {"success": False, "balance": None, "currency": None, "error": None}
        response_received = threading.Event()
        authorized = False
        
        def on_message(ws, message):
            nonlocal authorized
            data = json.loads(message)
            print(f"📨 Balance Response: {data}")
            
            if data.get('authorize') and not authorized:
                authorized = True
                ws.send(json.dumps({"balance": 1}))
            
            elif data.get('balance'):
                result["success"] = True
                result["balance"] = data['balance']['balance']
                result["currency"] = data['balance']['currency']
                response_received.set()
                ws.close()
            
            elif data.get('error'):
                result["error"] = data['error']['message']
                response_received.set()
                ws.close()
        
        def on_error(ws, error):
            result["error"] = str(error)
            response_received.set()
        
        def on_open(ws):
            ws.send(json.dumps({"authorize": api_token}))
        
        ws_url = DerivService._get_ws_url()
        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error
        )
        
        wst = threading.Thread(target=ws.run_forever)
        wst.daemon = True
        wst.start()
        
        response_received.wait(timeout=10)
        
        if result["success"]:
            return True, result["balance"], result["currency"]
        else:
            return False, result["error"] or "Failed to get balance", None
    
    @staticmethod
    def place_trade(api_token, symbol, trade_type, amount, duration, duration_unit='t'):
        """
        Place a binary option trade on Deriv using WebSocket
        trade_type: 'CALL' for Rise, 'PUT' for Fall
        """
        result = {"success": False, "trade": None, "error": None}
        response_received = threading.Event()
        authorized = False
        proposal_id = None
        
        def on_message(ws, message):
            nonlocal authorized, proposal_id
            data = json.loads(message)
            print(f"📨 Trade Response: {data}")
            
            if data.get('authorize') and not authorized:
                authorized = True
                print(f"✅ Authorized! Sending proposal...")
                ws.send(json.dumps({
                    "proposal": 1,
                    "amount": amount,
                    "basis": "stake",
                    "contract_type": trade_type,
                    "currency": "USD",
                    "duration": duration,
                    "duration_unit": duration_unit,
                    "symbol": symbol
                }))
            
            elif data.get('proposal') and authorized:
                proposal_id = data['proposal']['id']
                print(f"📊 Proposal received! ID: {proposal_id}")
                ws.send(json.dumps({
                    "buy": proposal_id,
                    "price": amount
                }))
            
            elif data.get('buy'):
                result["success"] = True
                result["trade"] = {
                    'contract_id': data['buy']['contract_id'],
                    'buy_price': data['buy']['buy_price'],
                    'longcode': data['buy'].get('longcode', '')
                }
                print(f"✅ Trade placed! Contract ID: {result['trade']['contract_id']}")
                response_received.set()
                ws.close()
            
            elif data.get('error'):
                result["error"] = data['error']['message']
                print(f"❌ Error: {result['error']}")
                response_received.set()
                ws.close()
        
        def on_error(ws, error):
            result["error"] = str(error)
            response_received.set()
        
        def on_open(ws):
            ws.send(json.dumps({"authorize": api_token}))
        
        ws_url = DerivService._get_ws_url()
        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error
        )
        
        wst = threading.Thread(target=ws.run_forever)
        wst.daemon = True
        wst.start()
        
        response_received.wait(timeout=30)
        
        if result["success"]:
            return True, result["trade"]
        else:
            return False, result["error"] or "Failed to place trade"
    
    @staticmethod
    def get_active_contracts(api_token):
        """Get all active contracts for the account"""
        result = {"success": False, "contracts": [], "error": None}
        response_received = threading.Event()
        authorized = False
        
        def on_message(ws, message):
            nonlocal authorized
            data = json.loads(message)
            print(f"📨 Active Contracts Response: {data}")
            
            if data.get('authorize') and not authorized:
                authorized = True
                ws.send(json.dumps({"portfolio": 1}))
            
            elif data.get('portfolio'):
                contracts = []
                for contract in data['portfolio'].get('contracts', []):
                    contracts.append({
                        'contract_id': contract['contract_id'],
                        'symbol': contract.get('symbol', ''),
                        'buy_price': contract.get('buy_price', 0),
                        'payout': contract.get('payout', 0),
                        'expiry_time': contract.get('expiry_time'),
                        'status': contract.get('status', 'open')
                    })
                result["success"] = True
                result["contracts"] = contracts
                response_received.set()
                ws.close()
            
            elif data.get('error'):
                result["error"] = data['error']['message']
                response_received.set()
                ws.close()
        
        def on_error(ws, error):
            result["error"] = str(error)
            response_received.set()
        
        def on_open(ws):
            ws.send(json.dumps({"authorize": api_token}))
        
        ws_url = DerivService._get_ws_url()
        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error
        )
        
        wst = threading.Thread(target=ws.run_forever)
        wst.daemon = True
        wst.start()
        
        response_received.wait(timeout=10)
        
        if result["success"]:
            return True, result["contracts"]
        else:
            return False, result["error"] or "Failed to get active contracts"

    @staticmethod
    def get_trade_history(api_token, limit=50):
        """Get trade history from Deriv API (real-time, no storage)"""
        result = {"success": False, "history": [], "error": None}
        response_received = threading.Event()
        authorized = False
        
        def on_message(ws, message):
            nonlocal authorized
            data = json.loads(message)
            print(f"📨 Trade History Response: {data}")
            
            if data.get('authorize') and not authorized:
                authorized = True
                # Request profit table (trade history)
                ws.send(json.dumps({"profit_table": 1, "limit": limit}))
            
            elif data.get('profit_table'):
                transactions = []
                for transaction in data['profit_table'].get('transactions', []):
                    transactions.append({
                        'contract_id': transaction.get('contract_id'),
                        'transaction_id': transaction.get('transaction_id'),
                        'action': transaction.get('action'),
                        'amount': transaction.get('amount'),
                        'balance_after': transaction.get('balance_after'),
                        'buy_price': transaction.get('buy_price'),
                        'sell_price': transaction.get('sell_price'),
                        'profit': transaction.get('profit_loss', 0),
                        'payout': transaction.get('payout'),
                        'transaction_time': transaction.get('transaction_time'),
                        'status': transaction.get('status'),
                        'symbol': transaction.get('symbol'),
                        'contract_type': transaction.get('contract_type'),
                        'start_time': transaction.get('start_time'),
                        'exit_time': transaction.get('exit_time')
                    })
                result["success"] = True
                result["history"] = transactions
                response_received.set()
                ws.close()
            
            elif data.get('error'):
                result["error"] = data['error']['message']
                response_received.set()
                ws.close()
        
        def on_error(ws, error):
            result["error"] = str(error)
            response_received.set()
        
        def on_open(ws):
            ws.send(json.dumps({"authorize": api_token}))
        
        ws_url = DerivService._get_ws_url()
        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error
        )
        
        wst = threading.Thread(target=ws.run_forever)
        wst.daemon = True
        wst.start()
        
        response_received.wait(timeout=15)
        
        if result["success"]:
            return True, result["history"]
        else:
            return False, result["error"] or "Failed to get trade history"