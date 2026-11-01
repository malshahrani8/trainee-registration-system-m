import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'tvtc-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///database.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # إعدادات البريد الإلكتروني (Gmail مثال)
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')  # ضع بريدك هنا
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')  # App Password
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_USERNAME')