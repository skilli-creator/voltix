# backend/models/database.py
import mysql.connector
from mysql.connector import Error
import bcrypt
from datetime import datetime, timedelta
import random
from config import Config

class Database:
    def __init__(self):
        self.connection = None
    
    def get_connection(self):
        try:
            self.connection = mysql.connector.connect(
                host=Config.DB_HOST,
                user=Config.DB_USER,
                password=Config.DB_PASSWORD,
                database=Config.DB_NAME,
                consume_results=True,  # Prevents "Unread result found" errors
                autocommit=False
            )
            return self.connection
        except Error as e:
            print(f"Database error: {e}")
            return None
    
    def test_connection(self):
        conn = self.get_connection()
        if conn:
            print("✅ Database connected successfully!")
            # Consume any pending results before closing
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchall()  # Consume all results
                cursor.close()
            except:
                pass
            conn.close()
            return True
        else:
            print("❌ Database connection failed!")
            return False
    
    # ==================== USER FUNCTIONS ====================
    
    def create_user(self, first_name, last_name, phone, email, password):
        conn = self.get_connection()
        if not conn:
            return None
        
        cursor = conn.cursor()
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        try:
            cursor.execute("""
                INSERT INTO users (first_name, last_name, phone, email, password_hash)
                VALUES (%s, %s, %s, %s, %s)
            """, (first_name, last_name, phone, email, password_hash.decode('utf-8')))
            conn.commit()
            return cursor.lastrowid
        except Error as e:
            print(f"Create user error: {e}")
            return None
        finally:
            cursor.close()
            conn.close()
    
    def get_user_by_email(self, email):
        conn = self.get_connection()
        if not conn:
            return None
        
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            # Consume any remaining results
            cursor.fetchall()
            return user
        except Error as e:
            print(f"Get user by email error: {e}")
            return None
        finally:
            cursor.close()
            conn.close()
    
    def get_user_by_phone(self, phone):
        """Get user by phone number"""
        conn = self.get_connection()
        if not conn:
            return None
        
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM users WHERE phone = %s", (phone,))
            user = cursor.fetchone()
            # Consume any remaining results
            cursor.fetchall()
            return user
        except Error as e:
            print(f"Get user by phone error: {e}")
            return None
        finally:
            cursor.close()
            conn.close()
    
    def get_user_by_id(self, user_id):
        conn = self.get_connection()
        if not conn:
            return None
        
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id, email, first_name, last_name, phone, email_verified, is_active FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            # Consume any remaining results
            cursor.fetchall()
            return user
        except Error as e:
            print(f"Get user by ID error: {e}")
            return None
        finally:
            cursor.close()
            conn.close()
    
    def update_last_login(self, user_id):
        conn = self.get_connection()
        if not conn:
            return False
        
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user_id,))
            conn.commit()
            return True
        except Error as e:
            print(f"Update last login error: {e}")
            return False
        finally:
            cursor.close()
            conn.close()
    
    def update_email_verified(self, user_id):
        conn = self.get_connection()
        if not conn:
            return False
        
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE users SET email_verified = 1 WHERE id = %s", (user_id,))
            conn.commit()
            return True
        except Error as e:
            print(f"Update email verified error: {e}")
            return False
        finally:
            cursor.close()
            conn.close()
    
    # ==================== VERIFICATION CODE FUNCTIONS ====================
    
    def generate_code(self):
        return f"{random.randint(100000, 999999)}"
    
    def save_verification_code(self, user_id, email_code):
        conn = self.get_connection()
        if not conn:
            return False
        
        cursor = conn.cursor()
        expires_at = datetime.now() + timedelta(minutes=10)
        
        try:
            cursor.execute("""
                UPDATE users SET verification_code = %s, code_expires_at = %s WHERE id = %s
            """, (email_code, expires_at, user_id))
            conn.commit()
            return True
        except Error as e:
            print(f"Save code error: {e}")
            return False
        finally:
            cursor.close()
            conn.close()
    
    def verify_code(self, user_id, code):
        conn = self.get_connection()
        if not conn:
            return False
        
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT verification_code, code_expires_at FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            # Consume any remaining results
            cursor.fetchall()
            
            if not user:
                return False
            
            if user['verification_code'] == code and datetime.now() < user['code_expires_at']:
                return True
            return False
        except Error as e:
            print(f"Verify code error: {e}")
            return False
        finally:
            cursor.close()
            conn.close()

# Create single instance
db = Database()