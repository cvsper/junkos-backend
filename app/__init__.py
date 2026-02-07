from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import os

db = SQLAlchemy()


def create_app(config_name=None):
    """Flask application factory"""
    app = Flask(__name__)
    
    # Load configuration
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'development')
    
    from config import config
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    db.init_app(app)
    CORS(app, origins=app.config['CORS_ORIGINS'], supports_credentials=True)
    
    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.bookings import bookings_bp
    from app.routes.jobs import jobs_bp
    from app.routes.payments import payments_bp
    
    api_prefix = app.config['API_PREFIX']
    app.register_blueprint(auth_bp, url_prefix=f'{api_prefix}/auth')
    app.register_blueprint(bookings_bp, url_prefix=f'{api_prefix}/bookings')
    app.register_blueprint(jobs_bp, url_prefix=f'{api_prefix}/jobs')
    app.register_blueprint(payments_bp, url_prefix=f'{api_prefix}/payments')
    
    # Health check endpoint
    @app.route('/health')
    def health():
        return {'status': 'healthy', 'service': 'junkos-backend'}, 200
    
    return app
