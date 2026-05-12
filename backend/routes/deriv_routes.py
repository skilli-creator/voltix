# backend/routes/deriv_routes.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models.database import db
from services.deriv_service import DerivService
import logging
import threading
import json
import websocket

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

deriv_bp = Blueprint('deriv', __name__)


@deriv_bp.route('/connect', methods=['POST'])
@jwt_required()
def connect_deriv():
    """Connect Deriv account using API token"""
    user_id = get_jwt_identity()
    data = request.json
    
    api_token = data.get('api_token', '').strip()
    account_type = data.get('account_type', 'Demo')
    
    if not api_token:
        return jsonify({'error': 'API token required'}), 400
    
    # Get account info directly
    info_success, account_info = DerivService.get_account_info(api_token)
    
    if not info_success:
        return jsonify({'error': 'Failed to get account info. Invalid API token?'}), 400
    
    # Get balance - uses authorized account directly
    balance_success, balance, currency, loginid = DerivService.get_balance(api_token)
    
    if not balance_success:
        balance = 0
        currency = 'USD'
    
    # Determine account type from loginid
    if loginid and loginid.startswith('VRTC'):
        detected_account_type = 'Demo'
    elif loginid and loginid.startswith('CR'):
        detected_account_type = 'Real'
    else:
        detected_account_type = account_type
    
    # Save to database
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id FROM deriv_accounts WHERE user_id = %s AND account_id = %s
        """, (user_id, account_info['account_id']))
        existing = cursor.fetchone()
        
        if existing:
            cursor.execute("""
                UPDATE deriv_accounts 
                SET token = %s, balance = %s, currency = %s, account_type = %s, 
                    email = %s, last_sync_at = NOW()
                WHERE user_id = %s AND account_id = %s
            """, (api_token.encode(), balance, currency, detected_account_type, 
                  account_info['email'], user_id, account_info['account_id']))
        else:
            cursor.execute("""
                INSERT INTO deriv_accounts (user_id, account_id, email, token, balance, currency, account_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (user_id, account_info['account_id'], account_info['email'], 
                  api_token.encode(), balance, currency, detected_account_type))
        
        conn.commit()
        
    except Exception as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
        return jsonify({'error': f'Database error: {str(e)}'}), 500
    finally:
        cursor.close()
        conn.close()
    
    return jsonify({
        'message': 'Deriv account connected successfully',
        'account': {
            'account_id': account_info['account_id'],
            'balance': balance,
            'currency': currency,
            'account_type': detected_account_type,
            'email': account_info['email']
        }
    }), 200


@deriv_bp.route('/balance', methods=['GET'])
@jwt_required()
def get_balance():
    """Get current balance from Deriv - uses authorized account directly"""
    user_id = get_jwt_identity()
    
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT token, account_id, account_type FROM deriv_accounts 
        WHERE user_id = %s AND is_active = 1
    """, (user_id,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not account:
        return jsonify({'error': 'No Deriv account connected'}), 404
    
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    success, balance, currency, loginid = DerivService.get_balance(api_token)
    
    if not success:
        return jsonify({'error': balance}), 500
    
    account_type = 'Demo' if loginid and loginid.startswith('VRTC') else 'Real'
    
    # Update balance in database
    conn2 = db.get_connection()
    if conn2:
        cursor2 = conn2.cursor()
        cursor2.execute("""
            UPDATE deriv_accounts SET balance = %s, last_sync_at = NOW() WHERE user_id = %s
        """, (balance, user_id))
        conn2.commit()
        cursor2.close()
        conn2.close()
    
    return jsonify({
        'balance': balance,
        'currency': currency,
        'account_id': loginid or account['account_id'],
        'account_type': account_type,
        'email': account.get('email', '')
    }), 200


@deriv_bp.route('/accounts', methods=['GET'])
@jwt_required()
def get_accounts():
    """Get all accounts (Real and Demo) for the user"""
    user_id = get_jwt_identity()
    
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT token FROM deriv_accounts 
        WHERE user_id = %s AND is_active = 1
    """, (user_id,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not account:
        return jsonify({'error': 'No Deriv account connected'}), 404
    
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    # Get account list from Deriv API
    result = {"success": False, "accounts": [], "error": None}
    response_received = threading.Event()
    
    def on_message(ws, message):
        data = json.loads(message)
        print(f"📨 Accounts Response: {data}")
        
        if data.get('authorize'):
            account_list = data['authorize'].get('account_list', [])
            accounts = []
            for acc in account_list:
                if acc.get('account_category') == 'trading':
                    accounts.append({
                        'account_id': acc.get('loginid'),
                        'account_type': 'Demo' if acc.get('is_virtual') else 'Real',
                        'balance': acc.get('balance', 0),
                        'currency': acc.get('currency', 'USD'),
                        'is_virtual': acc.get('is_virtual', 1)
                    })
            result["success"] = True
            result["accounts"] = accounts
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
    
    ws_url = f"wss://ws.derivws.com/websockets/v3?app_id=1089"
    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message, on_error=on_error)
    
    wst = threading.Thread(target=ws.run_forever)
    wst.daemon = True
    wst.start()
    
    response_received.wait(timeout=10)
    
    try:
        ws.close()
    except:
        pass
    
    if result["success"]:
        return jsonify({
            'accounts': result['accounts'],
            'current_account': None
        }), 200
    else:
        return jsonify({'error': result['error'] or 'Failed to get accounts'}), 500


@deriv_bp.route('/switch-account', methods=['POST'])
@jwt_required()
def switch_account():
    """Switch to a different Deriv account by re-authorizing with that account"""
    user_id = get_jwt_identity()
    data = request.json
    
    new_account_id = data.get('loginid')
    account_type = data.get('account_type', 'Demo')
    
    if not new_account_id:
        return jsonify({'error': 'Account loginid required'}), 400
    
    # Get user's API token from database
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT token FROM deriv_accounts 
        WHERE user_id = %s AND is_active = 1
    """, (user_id,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not account:
        return jsonify({'error': 'No Deriv account connected'}), 404
    
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    # Re-authorize with the selected account
    result = {"success": False, "balance": None, "currency": None, "loginid": None, "error": None}
    response_received = threading.Event()
    
    def on_message(ws, message):
        data = json.loads(message)
        print(f"📨 Switch Response: {data}")
        
        if data.get('authorize'):
            # After successful authorization, get balance
            ws.send(json.dumps({"balance": 1}))
        
        elif data.get('balance'):
            result["success"] = True
            result["balance"] = data['balance']['balance']
            result["currency"] = data['balance']['currency']
            result["loginid"] = data['balance']['loginid']
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
        # Re-authorize with the selected account
        ws.send(json.dumps({
            "authorize": api_token,
            "account": new_account_id
        }))
    
    ws_url = f"wss://ws.derivws.com/websockets/v3?app_id=1089"
    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message, on_error=on_error)
    
    wst = threading.Thread(target=ws.run_forever)
    wst.daemon = True
    wst.start()
    
    response_received.wait(timeout=15)
    
    try:
        ws.close()
    except:
        pass
    
    if result["success"]:
        # Update database with new account info
        conn2 = db.get_connection()
        if conn2:
            cursor2 = conn2.cursor()
            cursor2.execute("""
                UPDATE deriv_accounts 
                SET account_id = %s, account_type = %s, balance = %s, last_sync_at = NOW()
                WHERE user_id = %s
            """, (new_account_id, account_type, result['balance'], user_id))
            conn2.commit()
            cursor2.close()
            conn2.close()
        
        return jsonify({
            'message': f'Switched to account: {new_account_id}',
            'account_id': new_account_id,
            'account_type': account_type,
            'balance': result['balance'],
            'currency': result['currency']
        }), 200
    else:
        return jsonify({'error': result['error'] or 'Failed to switch account'}), 500


@deriv_bp.route('/place-trade', methods=['POST'])
@jwt_required()
def place_trade():
    """Place a manual trade - uses authorized account directly"""
    user_id = get_jwt_identity()
    data = request.json
    
    symbol = data.get('symbol', '')
    direction = data.get('direction', '')
    amount = data.get('amount', 0)
    duration = data.get('duration', 1)
    duration_unit = data.get('duration_unit', 't')
    
    if not symbol or not direction or not amount:
        return jsonify({'error': 'Symbol, direction, and amount required'}), 400
    
    if amount < 1.50:
        return jsonify({'error': 'Minimum stake is $1.50'}), 400
    
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT token, account_id FROM deriv_accounts 
        WHERE user_id = %s AND is_active = 1
    """, (user_id,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not account:
        return jsonify({'error': 'No Deriv account connected'}), 404
    
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    trade_type = 'CALL' if direction.lower() == 'rise' else 'PUT'
    
    success, result = DerivService.place_trade(
        api_token=api_token,
        symbol=symbol,
        trade_type=trade_type,
        amount=amount,
        duration=duration,
        duration_unit=duration_unit
    )
    
    if not success:
        return jsonify({'error': result}), 500
    
    logger.info(f"Trade placed: {direction} on {symbol} for ${amount}")
    
    return jsonify({
        'message': 'Trade placed successfully',
        'trade': result
    }), 200


@deriv_bp.route('/active-contracts', methods=['GET'])
@jwt_required()
def get_active_contracts():
    """Get all active contracts (open trades)"""
    user_id = get_jwt_identity()
    
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT token FROM deriv_accounts WHERE user_id = %s AND is_active = 1
    """, (user_id,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not account:
        return jsonify({'error': 'No Deriv account connected'}), 404
    
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    success, contracts = DerivService.get_active_contracts(api_token)
    
    if not success:
        return jsonify({'error': contracts}), 500
    
    return jsonify({
        'contracts': contracts,
        'count': len(contracts)
    }), 200


@deriv_bp.route('/trade-history', methods=['GET'])
@jwt_required()
def get_trade_history():
    """Get trade history from Deriv API (real-time)"""
    user_id = get_jwt_identity()
    
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT token FROM deriv_accounts 
        WHERE user_id = %s AND is_active = 1
    """, (user_id,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not account:
        return jsonify({'error': 'No Deriv account connected'}), 404
    
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    limit = request.args.get('limit', 50, type=int)
    
    success, history = DerivService.get_trade_history(api_token, limit)
    
    if not success:
        return jsonify({'error': history}), 500
    
    return jsonify({
        'history': history,
        'count': len(history)
    }), 200


@deriv_bp.route('/profit-loss', methods=['GET'])
@jwt_required()
def get_profit_loss():
    """Get profit/loss summary from Deriv API"""
    user_id = get_jwt_identity()
    
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT token FROM deriv_accounts 
        WHERE user_id = %s AND is_active = 1
    """, (user_id,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not account:
        return jsonify({'error': 'No Deriv account connected'}), 404
    
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    success, history = DerivService.get_trade_history(api_token, 200)
    
    if not success:
        return jsonify({'error': history}), 500
    
    wins = [t for t in history if t.get('profit', 0) > 0]
    losses = [t for t in history if t.get('profit', 0) < 0]
    total_profit = sum(t.get('profit', 0) for t in wins)
    total_loss = abs(sum(t.get('profit', 0) for t in losses))
    
    return jsonify({
        'total_trades': len(history),
        'wins': len(wins),
        'losses': len(losses),
        'total_profit': total_profit,
        'total_loss': total_loss,
        'net_profit': total_profit - total_loss
    }), 200


@deriv_bp.route('/disconnect', methods=['POST'])
@jwt_required()
def disconnect_deriv():
    """Disconnect Deriv account"""
    user_id = get_jwt_identity()
    
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE deriv_accounts SET is_active = 0 WHERE user_id = %s
    """, (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'message': 'Deriv account disconnected'}), 200


@deriv_bp.route('/test-connect', methods=['POST'])
def test_connect():
    """Test Deriv connection without JWT (for testing only)"""
    data = request.json
    api_token = data.get('api_token', '').strip()
    account_type = data.get('account_type', 'Demo')
    
    if not api_token:
        return jsonify({'error': 'API token required'}), 400
    
    logger.info(f"Testing Deriv connection with token: {api_token[:20]}...")
    
    info_success, account_info = DerivService.get_account_info(api_token)
    
    if not info_success:
        return jsonify({'error': 'Failed to get account info'}), 500
    
    balance_success, balance, currency, loginid = DerivService.get_balance(api_token)
    
    if not balance_success:
        balance = 0
        currency = 'USD'
    
    if loginid and loginid.startswith('VRTC'):
        acc_type = 'Demo'
    elif loginid and loginid.startswith('CR'):
        acc_type = 'Real'
    else:
        acc_type = account_type
    
    return jsonify({
        'message': 'Deriv account connected successfully',
        'account': {
            'account_id': account_info['account_id'],
            'balance': balance,
            'currency': currency,
            'account_type': acc_type,
            'email': account_info['email'],
            'trading_account_id': loginid
        }
    }), 200