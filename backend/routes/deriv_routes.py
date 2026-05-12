# backend/routes/deriv_routes.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models.database import db
from services.deriv_service import DerivService

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
    
    # Test the connection
    success, result = DerivService.test_connection(api_token)
    
    if not success:
        return jsonify({'error': result}), 400
    
    # Get account info
    info_success, account_info = DerivService.get_account_info(api_token)
    
    if not info_success:
        return jsonify({'error': 'Failed to get account info'}), 500
    
    # Get balance
    balance_success, balance, currency = DerivService.get_balance(api_token)
    
    if not balance_success:
        balance = 0
        currency = 'USD'
    
    # Save to database
    conn = db.get_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor()
    try:
        # Check if account already exists
        cursor.execute("""
            SELECT id FROM deriv_accounts WHERE user_id = %s AND account_id = %s
        """, (user_id, account_info['account_id']))
        existing = cursor.fetchone()
        
        if existing:
            # Update existing record
            cursor.execute("""
                UPDATE deriv_accounts 
                SET token = %s, balance = %s, currency = %s, account_type = %s, 
                    email = %s, last_sync_at = NOW()
                WHERE user_id = %s AND account_id = %s
            """, (api_token.encode(), balance, currency, account_type, 
                  account_info['email'], user_id, account_info['account_id']))
        else:
            # Insert new record
            cursor.execute("""
                INSERT INTO deriv_accounts (user_id, account_id, email, token, balance, currency, account_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (user_id, account_info['account_id'], account_info['email'], 
                  api_token.encode(), balance, currency, account_type))
        
        conn.commit()
        
    except Exception as e:
        print(f"Database error: {e}")
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
            'account_type': account_type,
            'email': account_info['email']
        }
    }), 200


@deriv_bp.route('/balance', methods=['GET'])
@jwt_required()
def get_balance():
    """Get current balance from Deriv"""
    user_id = get_jwt_identity()
    
    # Get user's API token from database
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
    
    # Decode token from bytes to string
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    # Get balance from Deriv
    success, balance, currency = DerivService.get_balance(api_token)
    
    if not success:
        return jsonify({'error': balance}), 500
    
    # Update balance in database
    conn = db.get_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE deriv_accounts SET balance = %s, last_sync_at = NOW() WHERE user_id = %s
        """, (balance, user_id))
        conn.commit()
        cursor.close()
        conn.close()
    
    return jsonify({
        'balance': balance,
        'currency': currency,
        'account_id': account['account_id'],
        'account_type': account['account_type']
    }), 200


@deriv_bp.route('/place-trade', methods=['POST'])
@jwt_required()
def place_trade():
    """Place a manual trade"""
    user_id = get_jwt_identity()
    data = request.json
    
    symbol = data.get('symbol', '')
    direction = data.get('direction', '')  # 'Rise' or 'Fall'
    amount = data.get('amount', 0)
    duration = data.get('duration', 1)
    duration_unit = data.get('duration_unit', 't')  # 't' for ticks, 'm' for minutes
    
    if not symbol or not direction or not amount:
        return jsonify({'error': 'Symbol, direction, and amount required'}), 400
    
    if amount < 0.35:
        return jsonify({'error': 'Minimum stake is $0.35'}), 400
    
    # Get user's API token
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
    
    # Decode token from bytes to string
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    # Convert direction to Deriv trade type
    trade_type = 'CALL' if direction.lower() == 'rise' else 'PUT'
    
    # Place trade
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
    
    return jsonify({
        'message': 'Trade placed successfully',
        'trade': result
    }), 200


@deriv_bp.route('/active-contracts', methods=['GET'])
@jwt_required()
def get_active_contracts():
    """Get all active contracts (open trades)"""
    user_id = get_jwt_identity()
    
    # Get user's API token
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
    
    # Decode token from bytes to string
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
    """Get trade history from Deriv API (real-time, no storage)"""
    user_id = get_jwt_identity()
    
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
    
    # Decode token from bytes to string
    api_token = account['token'].decode('utf-8') if isinstance(account['token'], bytes) else account['token']
    
    # Get limit from query parameter (default 50)
    limit = request.args.get('limit', 50, type=int)
    
    # Get trade history from Deriv API
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
    """Get profit/loss summary from Deriv API (real-time, no storage)"""
    user_id = get_jwt_identity()
    
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
    
    # Get trade history and calculate profit/loss
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
    """Test Deriv connection without JWT (TEMPORARY - for testing only)"""
    data = request.json
    api_token = data.get('api_token', '').strip()
    account_type = data.get('account_type', 'Demo')
    
    if not api_token:
        return jsonify({'error': 'API token required'}), 400
    
    print(f"DEBUG: Testing Deriv connection with token: {api_token[:20]}...")
    
    # Test the connection
    success, result = DerivService.test_connection(api_token)
    
    if not success:
        print(f"DEBUG: Connection failed: {result}")
        return jsonify({'error': result}), 400
    
    print(f"DEBUG: Connection successful!")
    
    # Get account info
    info_success, account_info = DerivService.get_account_info(api_token)
    
    if not info_success:
        return jsonify({'error': account_info}), 500
    
    # Get balance
    balance_success, balance, currency = DerivService.get_balance(api_token)
    
    if not balance_success:
        balance = 0
        currency = 'USD'
    
    return jsonify({
        'message': 'Deriv account connected successfully',
        'account': {
            'account_id': account_info['account_id'],
            'balance': balance,
            'currency': currency,
            'account_type': account_type,
            'email': account_info['email']
        }
    }), 200