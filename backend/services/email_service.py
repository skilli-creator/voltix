# backend/services/email_service.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import Config

class EmailService:
    
    @staticmethod
    def send_verification_email(to_email, code):
        """Send email verification code to new user"""
        try:
            msg = MIMEMultipart()
            msg['From'] = Config.EMAIL_USER
            msg['To'] = to_email
            msg['Subject'] = 'Verify Your Voltix Account'
            
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{ font-family: Arial, sans-serif; background-color: #0a1428; padding: 20px; }}
                    .container {{ max-width: 600px; margin: 0 auto; background: #0f1730; border-radius: 20px; padding: 40px; }}
                    h2 {{ color: #22c55e; }}
                    .code {{ font-size: 36px; letter-spacing: 8px; background: #1e293b; padding: 20px; border-radius: 12px; text-align: center; color: #22c55e; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h2>⚡ Voltix</h2>
                    <h3>Verify Your Email Address</h3>
                    <p>Thank you for registering with Voltix. Use the verification code below to complete your registration:</p>
                    <div class="code"><strong>{code}</strong></div>
                    <p>This code expires in <strong>10 minutes</strong>.</p>
                    <hr>
                    <p style="color: #666; font-size: 12px;">© 2026 Voltix — AI Trading Platform</p>
                </div>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(html, 'html'))
            
            with smtplib.SMTP(Config.EMAIL_HOST, Config.EMAIL_PORT) as server:
                server.starttls()
                server.login(Config.EMAIL_USER, Config.EMAIL_PASS)
                server.send_message(msg)
            
            print(f"✅ Verification email sent to {to_email}")
            return True
        except Exception as e:
            print(f"Verification email error: {e}")
            return False
    
    @staticmethod
    def send_password_reset_email(to_email, code):
        """Send password reset code to user"""
        try:
            msg = MIMEMultipart()
            msg['From'] = Config.EMAIL_USER
            msg['To'] = to_email
            msg['Subject'] = 'Voltix - Password Reset Code'
            
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{ font-family: Arial, sans-serif; background-color: #0a1428; padding: 20px; }}
                    .container {{ max-width: 600px; margin: 0 auto; background: #0f1730; border-radius: 20px; padding: 40px; }}
                    h2 {{ color: #22c55e; }}
                    .code {{ font-size: 36px; letter-spacing: 8px; background: #1e293b; padding: 20px; border-radius: 12px; text-align: center; color: #22c55e; }}
                    .warning {{ color: #f59e0b; font-size: 12px; margin-top: 20px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h2>⚡ Voltix</h2>
                    <h3>Password Reset Request</h3>
                    <p>You requested to reset your password. Use the code below to proceed:</p>
                    <div class="code"><strong>{code}</strong></div>
                    <p>This code expires in <strong>10 minutes</strong>.</p>
                    <p class="warning">⚠️ If you did not request this, please ignore this email or contact support.</p>
                    <hr>
                    <p style="color: #666; font-size: 12px;">© 2026 Voltix — AI Trading Platform</p>
                </div>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(html, 'html'))
            
            with smtplib.SMTP(Config.EMAIL_HOST, Config.EMAIL_PORT) as server:
                server.starttls()
                server.login(Config.EMAIL_USER, Config.EMAIL_PASS)
                server.send_message(msg)
            
            print(f"✅ Password reset email sent to {to_email}")
            return True
        except Exception as e:
            print(f"Password reset email error: {e}")
            return False
    
    @staticmethod
    def send_admin_notification(subject, body):
        """Send notification to admin email"""
        try:
            msg = MIMEMultipart()
            msg['From'] = Config.EMAIL_USER
            msg['To'] = Config.ADMIN_EMAIL
            msg['Subject'] = f"[Voltix Admin] {subject}"
            
            html = f"""
            <div style="font-family: Arial, sans-serif;">
                <h2>⚡ Voltix Admin Notification</h2>
                <hr>
                <pre style="background: #f0f0f0; padding: 15px; border-radius: 8px;">{body}</pre>
                <hr>
                <p style="color: #666; font-size: 12px;">Sent at: {__import__('datetime').datetime.now()}</p>
            </div>
            """
            
            msg.attach(MIMEText(html, 'html'))
            
            with smtplib.SMTP(Config.EMAIL_HOST, Config.EMAIL_PORT) as server:
                server.starttls()
                server.login(Config.EMAIL_USER, Config.EMAIL_PASS)
                server.send_message(msg)
            
            print(f"✅ Admin notification sent to {Config.ADMIN_EMAIL}")
            return True
        except Exception as e:
            print(f"Admin notification error: {e}")
            return False