"""
Request ID middleware for request tracing and logging
"""
from werkzeug.wrappers import Request
import uuid


class RequestIdMiddleware:
    """
    WSGI middleware to add unique request ID to each request
    Useful for logging and tracing requests across services
    """
    
    def __init__(self, app):
        self.app = app
    
    def __call__(self, environ, start_response):
        # Generate or extract request ID
        request_id = environ.get('HTTP_X_REQUEST_ID') or str(uuid.uuid4())
        
        # Store in environ
        environ['request_id'] = request_id
        
        # Add to response headers
        def custom_start_response(status, headers, exc_info=None):
            headers.append(('X-Request-ID', request_id))
            return start_response(status, headers, exc_info)
        
        return self.app(environ, custom_start_response)
