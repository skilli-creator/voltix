# backend/app.py
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from config import Config
from routes.auth_routes import auth_bp
from routes.deriv_routes import deriv_bp

# Create Flask app FIRST
app = Flask(__name__)

# Load configuration
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['JWT_SECRET_KEY'] = Config.JWT_SECRET_KEY

# Initialize extensions
CORS(app)
jwt = JWTManager(app)

# Register blueprints (AFTER app is created)
app.register_blueprint(auth_bp, url_prefix='/api/auth')
app.register_blueprint(deriv_bp, url_prefix='/api/deriv')

# Health check routes
@app.route('/')
def home():
    return jsonify({'message': 'Voltix API Running 🚀', 'status': 'online'})

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'})

# Run the app
if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )