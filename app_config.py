import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration"""
    
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.environ.get('FLASK_ENV', 'development') == 'development'
    
    # API Security
    API_KEY = os.environ.get('API_KEY', 'junkos-api-key-12345')
    
    # Database
    DATABASE_PATH = os.environ.get('DATABASE_PATH', 'junkos.db')
    
    # CORS - Allow iOS app origin
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '*')
    
    # Pricing
    BASE_PRICE = float(os.environ.get('BASE_PRICE', '50.0'))
    
    # Server
    PORT = int(os.environ.get('PORT', '8080'))
