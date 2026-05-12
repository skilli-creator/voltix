# backend/routes/bot_routes.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models.database import db
from services.deriv_service import DerivService
import threading
import time
import json
import websocket

bot_bp = Blueprint('bot', __name__)

# Store active bot sessions
active_bots = {}


def tick_over_under_strategy(ticks):
    """
    Over/Under trading strategy based on last 5 ticks
    Returns: "OVER", "UNDER", or "NO TRADE"
    """
    if len(ticks) < 5:
        return "NO TRADE"

    last = ticks[-5:]

    changes = [last[i] - last[i-1] for i in range(1, len(last))]

    momentum = sum(changes)

    up_moves = sum(1 for c in changes if c > 0)
    down_moves = sum(1 for c in changes if c < 0)

    volatility = max(last) - min(last)

    # OVER condition
    if momentum > 0 and up_moves >= 3 and volatility < 1.0:
        return "OVER"

    # UNDER condition
    elif momentum < 0 and down_moves >= 3 and volatility < 1.0:
        return "UNDER"

    return "NO TRADE"


def fetch_real_ticks(api_token, symbol, count=10):
    """Fetch real ticks from Deriv WebSocket"""
    result = {"success": False, "ticks": [], "error": None}
    response_received = threading.Event()
    
    def on_message(ws, message):
        data = json.loads(message)
        if data.get('history'):
            result["ticks"] = data['history']['prices']
            result["success"] = True
            response_received.set()
            ws.close()
        elif data.get('error'):
            result["error"] = data['error']['message']
            response_received.set()
            ws.close()
    
    def on_open(ws):
        ws.send(json.dumps({
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "style": "ticks"
        }))
    
    ws_url = f"wss://ws.derivws.com/websockets/v3?app_id=1089"
    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message)
    wst = threading.Thread(target=ws.run_forever)
    wst.daemon = True
    wst.start()
    
    response_received.wait(timeout=10)
    return result


def fetch_current_price(api_token, symbol):
    """Fetch current price from Deriv WebSocket"""
    result = {"success": False, "price": None, "error": None}
    response_received = threading.Event()
    
    def on_message(ws, message):
        data = json.loads(message)
        if data.get('tick'):
            result["price"] = data['tick']['quote']
            result["success"] = True
            response_received.set()
            ws.close()
        elif data.get('error'):
            result["error"] = data['error']['message']
            response_received.set()
            ws.close()
    
    def on_open(ws):
        ws.send(json.dumps({
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": 1,
            "end": "latest",
            "style": "ticks"
        }))
    
    ws_url = f"wss://ws.derivws.com/websockets/v3?app_id=1089"
    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message)
    wst = threading.Thread(target=ws.run_forever)
    wst.daemon = True
    wst.start()
    
    response_received.wait(timeout=10)
    return result


class TradingBot:
    def __init__(self, user_id, config, api_token):
        self.user_id = user_id
        self.config = config
        self.api_token = api_token
        self.is_running = False
        self.thread = None
        self.trades_executed = 0
        self.current_profit = 0
        self.current_loss = 0
        
    def start(self):
        self.is_running = True
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()
        
    def stop(self):
        self.is_running = False
        
    def _get_over_under_signal(self):
        """Get OVER/UNDER signal based on real tick data"""
        symbol = self.config.get('market')
        
        # Fetch real ticks
        result = fetch_real_ticks(self.api_token, symbol, count=10)
        
        if not result["success"] or not result["ticks"]:
            return "NO TRADE"
        
        ticks = result["ticks"]
        return tick_over_under_strategy(ticks)
    
    def _get_rise_fall_signal(self):
        """Get RISE/FALL signal based on price momentum"""
        symbol = self.config.get('market')
        
        # Fetch current price and previous price
        price_result = fetch_current_price(self.api_token, symbol)
        
        if not price_result["success"] or price_result["price"] is None:
            return "RISE"  # Default
        
        # For simplicity, compare with stored previous price
        if not hasattr(self, '_last_price'):
            self._last_price = price_result["price"]
            return "RISE"
        
        current_price = price_result["price"]
        if current_price > self._last_price:
            signal = "RISE"
        elif current_price < self._last_price:
            signal = "FALL"
        else:
            signal = "RISE"
        
        self._last_price = current_price
        return signal
    
    def _get_higher_lower_signal(self):
        """Get HIGHER/LOWER signal based on barrier comparison"""
        symbol = self.config.get('market')
        
        price_result = fetch_current_price(self.api_token, symbol)
        
        if not price_result["success"] or price_result["price"] is None:
            return "HIGHER"
        
        current_price = price_result["price"]
        barrier = self.config.get('barrier', current_price)
        
        return "HIGHER" if current_price > barrier else "LOWER"
    
    def _determine_trade_direction(self):
        """Determine trade direction based on trade type"""
        trade_type = self.config.get('trade_type')
        
        if trade_type == 'Over/Under':
            signal = self._get_over_under_signal()
            # Map signal to Deriv trade type
            if signal == "OVER":
                return "CALL"
            elif signal == "UNDER":
                return "PUT"
            else:
                return None  # No trade
        elif trade_type == 'Rise/Fall':
            signal = self._get_rise_fall_signal()
            return "CALL" if signal == "RISE" else "PUT"
        elif trade_type == 'Higher/Lower':
            signal = self._get_higher_lower_signal()
            return "CALL" if signal == "HIGHER" else "PUT"
        elif trade_type == 'Even/Odd':
            # For Even/Odd, return direction based on digit analysis
            return "CALL"  # Will be implemented later
        elif trade_type == 'Matches/Differs':
            return "CALL"  # Will be implemented later
        
        return "CALL"
    
    def _run(self):
        market = self.config.get('market')
        trade_type = self.config.get('trade_type')
        stake = float(self.config.get('stake', 1.5))
        duration = self.config.get('duration')
        loops = int(self.config.get('loops', 999))
        tp = float(self.config.get('tp')) if self.config.get('tp') else None
        sl = float(self.config.get('sl')) if self.config.get('sl') else None
        martingale = self.config.get('martingale', False)
        
        for i in range(loops):
            if not self.is_running:
                break
            
            try:
                # Get trade direction based on strategy
                direction = self._determine_trade_direction()
                
                # Skip if no trade signal (for Over/Under)
                if direction is None:
                    time.sleep(5)
                    continue
                
                # Map direction to Deriv trade type (CALL/PUT)
                trade_type_deriv = direction if direction in ['CALL', 'PUT'] else ('CALL' if direction in ['RISE', 'HIGHER'] else 'PUT')
                
                # Execute real trade
                success, result = DerivService.place_trade(
                    api_token=self.api_token,
                    symbol=market,
                    trade_type=trade_type_deriv,
                    amount=stake,
                    duration=int(duration[:-1]),
                    duration_unit=duration[-1]
                )
                
                if success:
                    self.trades_executed += 1
                    
                    # Get real contract result
                    contract_id = result.get('contract_id')
                    if contract_id:
                        # Wait for contract to complete
                        time.sleep(int(duration[:-1]) + 2)
                        # Get contract result
                        success_info, contract_info = DerivService.get_contract_info(self.api_token, contract_id)
                        if success_info:
                            profit = contract_info.get('profit', 0)
                            self.current_profit += profit
                            
                            if martingale and profit < 0:
                                stake = min(stake * 2, 100)
                            else:
                                stake = float(self.config.get('stake', 1.5))
                    
                    if tp and self.current_profit >= tp:
                        self.stop()
                        break
                    if sl and self.current_profit <= -sl:
                        self.stop()
                        break
                else:
                    print(f"Trade failed: {result}")
                
                time.sleep(5)  # Wait between trades
                
            except Exception as e:
                print(f"Error in bot loop: {e}")
                time.sleep(5)


@bot_bp.route('/start', methods=['POST'])
@jwt_required()
def start_bot():
    """Start the automated trading bot"""
    user_id = get_jwt_identity()
    data = request.json
    
    market = data.get('market')
    trade_type = data.get('trade_type')
    stake = data.get('stake')
    duration = data.get('duration')
    tp = data.get('tp')
    sl = data.get('sl')
    loops = data.get('loops')
    martingale = data.get('martingale', False)
    over_under_choice = data.get('over_under_choice')
    
    # Validation
    if not market or not trade_type or not stake or not duration:
        return jsonify({'error': 'Market, Trade Type, Stake, and Duration are required'}), 400
    
    if float(stake) < 1.5:
        return jsonify({'error': 'Minimum stake is $1.50'}), 400
    
    # Check if bot is already running
    if user_id in active_bots and active_bots[user_id].is_running:
        return jsonify({'error': 'Bot is already running. Stop it first.'}), 400
    
    # Get user's Deriv token
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT token, balance FROM deriv_accounts WHERE user_id = %s AND is_active = 1", (user_id,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not account:
        return jsonify({'error': 'No Deriv account connected. Please connect your account first.'}), 400
    
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    # Verify sufficient balance
    balance_success, balance, currency = DerivService.get_balance(api_token)
    if balance_success and balance < float(stake):
        return jsonify({'error': f'Insufficient balance. Your balance is ${balance:.2f}'}), 400
    
    config = {
        'market': market,
        'trade_type': trade_type,
        'stake': stake,
        'duration': duration,
        'tp': tp,
        'sl': sl,
        'loops': loops,
        'martingale': martingale,
        'over_under_choice': over_under_choice
    }
    
    bot = TradingBot(user_id, config, api_token)
    active_bots[user_id] = bot
    bot.start()
    
    return jsonify({
        'message': 'Bot started successfully',
        'config': config
    }), 200


@bot_bp.route('/stop', methods=['POST'])
@jwt_required()
def stop_bot():
    """Stop the automated trading bot"""
    user_id = get_jwt_identity()
    
    if user_id not in active_bots or not active_bots[user_id].is_running:
        return jsonify({'error': 'No active bot running'}), 400
    
    active_bots[user_id].stop()
    del active_bots[user_id]
    
    return jsonify({'message': 'Bot stopped successfully'}), 200


@bot_bp.route('/status', methods=['GET'])
@jwt_required()
def bot_status():
    """Get the status of the bot"""
    user_id = get_jwt_identity()
    
    if user_id in active_bots and active_bots[user_id].is_running:
        bot = active_bots[user_id]
        return jsonify({
            'is_running': True,
            'trades_executed': bot.trades_executed,
            'current_profit': bot.current_profit,
            'current_loss': bot.current_loss
        }), 200
    else:
        return jsonify({'is_running': False}), 200


@bot_bp.route('/market-analysis/over-under', methods=['GET'])
@jwt_required()
def get_over_under_analysis():
    """Get Over/Under strategy analysis from real tick data"""
    user_id = get_jwt_identity()
    symbol = request.args.get('symbol', 'R_75')
    
    # Get user's Deriv token
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT token FROM deriv_accounts WHERE user_id = %s AND is_active = 1", (user_id,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not account:
        return jsonify({'error': 'No Deriv account connected'}), 400
    
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    # Fetch real ticks
    result = fetch_real_ticks(api_token, symbol, count=10)
    
    if not result["success"] or not result["ticks"]:
        return jsonify({'error': 'Failed to fetch tick data'}), 500
    
    ticks = result["ticks"]
    signal = tick_over_under_strategy(ticks)
    
    # Calculate additional analysis data
    if len(ticks) >= 5:
        last = ticks[-5:]
        changes = [last[i] - last[i-1] for i in range(1, len(last))]
        momentum = sum(changes)
        up_moves = sum(1 for c in changes if c > 0)
        down_moves = sum(1 for c in changes if c < 0)
        volatility = max(last) - min(last)
    else:
        momentum = 0
        up_moves = 0
        down_moves = 0
        volatility = 0
    
    return jsonify({
        'signal': signal,
        'analysis': {
            'momentum': round(momentum, 4),
            'up_moves': up_moves,
            'down_moves': down_moves,
            'volatility': round(volatility, 4),
            'last_ticks': ticks[-5:] if len(ticks) >= 5 else ticks
        }
    }), 200


@bot_bp.route('/market-analysis/digits', methods=['GET'])
@jwt_required()
def get_digit_analysis():
    """Get digit frequency analysis for digit-based trading"""
    symbol = request.args.get('symbol', 'R_75')
    
    # Get user's Deriv token
    user_id = get_jwt_identity()
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT token FROM deriv_accounts WHERE user_id = %s AND is_active = 1", (user_id,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not account:
        return jsonify({'error': 'No Deriv account connected'}), 400
    
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    # Fetch real ticks from Deriv
    result = fetch_real_ticks(api_token, symbol, count=100)
    
    if not result["success"] or not result["ticks"]:
        return jsonify({'error': 'Failed to fetch tick data'}), 500
    
    ticks = result["ticks"]
    
    # Calculate digit frequencies
    digit_counts = {i: 0 for i in range(10)}
    for tick in ticks:
        price_str = str(tick)
        if '.' in price_str:
            digit = int(price_str.split('.')[-1][-1])
        else:
            digit = int(str(tick)[-1])
        digit_counts[digit] += 1
    
    total = len(ticks)
    digits_data = []
    for d in range(10):
        percentage = round((digit_counts[d] / total) * 100, 1) if total > 0 else 0
        digits_data.append({'digit': d, 'percentage': percentage})
    
    return jsonify({'digits': digits_data}), 200


@bot_bp.route('/market-analysis/price', methods=['GET'])
@jwt_required()
def get_price_analysis():
    """Get real-time price analysis for price-based trading"""
    symbol = request.args.get('symbol', 'R_75')
    
    # Get user's Deriv token
    user_id = get_jwt_identity()
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT token FROM deriv_accounts WHERE user_id = %s AND is_active = 1", (user_id,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not account:
        return jsonify({'error': 'No Deriv account connected'}), 400
    
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    result = fetch_current_price(api_token, symbol)
    
    if not result["success"] or result["price"] is None:
        return jsonify({'error': 'Failed to fetch price data'}), 500
    
    return jsonify({
        'symbol': symbol,
        'current_price': result['price'],
        'timestamp': time.time()
    }), 200