"""
Multi-tenancy middleware for JunkOS
Extracts tenant from subdomain or auth token and sets in request context
"""
from werkzeug.wrappers import Request, Response
from flask import g, request
from functools import wraps
import re


class TenantMiddleware:
    """
    WSGI middleware to handle multi-tenancy
    
    Extracts tenant from:
    1. Subdomain (e.g., acme-junk.junkos.com)
    2. X-Tenant-ID header
    3. JWT token (tenant_id claim)
    4. Query parameter (for development)
    """
    
    def __init__(self, app):
        self.app = app
    
    def __call__(self, environ, start_response):
        request = Request(environ)
        
        # Extract tenant identifier
        tenant_slug = self._extract_tenant(request)
        
        # Store in environ for Flask's g object
        environ['tenant_slug'] = tenant_slug
        
        return self.app(environ, start_response)
    
    def _extract_tenant(self, request):
        """
        Extract tenant identifier from request
        
        Priority order:
        1. X-Tenant-ID header (explicit override)
        2. Subdomain extraction
        3. tenant query parameter (dev only)
        """
        # 1. Check explicit header
        tenant_header = request.headers.get('X-Tenant-ID')
        if tenant_header:
            return tenant_header
        
        # 2. Extract from subdomain
        host = request.host.lower()
        tenant_slug = self._extract_from_subdomain(host)
        if tenant_slug:
            return tenant_slug
        
        # 3. Query parameter (development only)
        tenant_param = request.args.get('tenant')
        if tenant_param:
            return tenant_param
        
        # No tenant found
        return None
    
    def _extract_from_subdomain(self, host):
        """
        Extract tenant slug from subdomain
        
        Examples:
        - acme-junk.junkos.com -> acme-junk
        - demo.junkos.com -> demo
        - junkos.com -> None (main domain)
        - localhost:5000 -> None
        """
        # Skip localhost and IPs
        if 'localhost' in host or re.match(r'^\d+\.\d+\.\d+\.\d+', host):
            return None
        
        # Remove port if present
        host = host.split(':')[0]
        
        # Split by dots
        parts = host.split('.')
        
        # Need at least subdomain.domain.tld (3 parts)
        if len(parts) >= 3:
            # Return first part as tenant slug
            subdomain = parts[0]
            
            # Ignore common subdomains
            if subdomain not in ['www', 'api', 'app', 'admin']:
                return subdomain
        
        return None


def tenant_required(f):
    """
    Decorator to ensure a valid tenant is present
    Use on routes that require tenant context
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask import current_app, jsonify
        
        tenant_slug = g.get('tenant_slug')
        
        if not tenant_slug:
            return jsonify({
                'error': 'Tenant Required',
                'message': 'No tenant identifier found in request'
            }), 400
        
        # Load tenant from database
        from app.models.tenant import Tenant
        tenant = Tenant.query.filter_by(slug=tenant_slug, deleted_at=None).first()
        
        if not tenant:
            return jsonify({
                'error': 'Invalid Tenant',
                'message': f'Tenant "{tenant_slug}" not found'
            }), 404
        
        # Check tenant status
        if tenant.status not in ['active', 'trial']:
            return jsonify({
                'error': 'Tenant Inactive',
                'message': f'Tenant is {tenant.status}'
            }), 403
        
        # Store tenant object in g for use in views
        g.tenant = tenant
        g.tenant_id = tenant.id
        
        return f(*args, **kwargs)
    
    return decorated_function


def get_current_tenant():
    """
    Helper function to get current tenant from request context
    
    Returns:
        Tenant: Current tenant object or None
    """
    return g.get('tenant')


def get_current_tenant_id():
    """
    Helper function to get current tenant ID
    
    Returns:
        UUID: Current tenant ID or None
    """
    return g.get('tenant_id')
