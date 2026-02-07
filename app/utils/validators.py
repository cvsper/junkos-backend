"""
Validation utilities
"""
import re


def validate_email(email):
    """
    Validate email format
    
    Args:
        email (str): Email address to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not email:
        return False
    
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_phone(phone):
    """
    Validate phone number format (US/Canada)
    
    Args:
        phone (str): Phone number to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not phone:
        return False
    
    # Remove common separators
    cleaned = re.sub(r'[\s\-\(\)\.]', '', phone)
    
    # Check for valid US/Canada format: 10 or 11 digits (with optional +1)
    pattern = r'^(\+?1)?[2-9]\d{9}$'
    return bool(re.match(pattern, cleaned))


def validate_postal_code(postal_code, country='US'):
    """
    Validate postal code format
    
    Args:
        postal_code (str): Postal code to validate
        country (str): Country code (US or CA)
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not postal_code:
        return False
    
    if country == 'US':
        # US ZIP: 12345 or 12345-6789
        pattern = r'^\d{5}(-\d{4})?$'
    elif country == 'CA':
        # Canadian postal code: A1A 1A1 or A1A1A1
        pattern = r'^[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d$'
    else:
        return True  # Skip validation for other countries
    
    return bool(re.match(pattern, postal_code))


def validate_uuid(uuid_string):
    """
    Validate UUID format
    
    Args:
        uuid_string (str): UUID string to validate
        
    Returns:
        bool: True if valid UUID, False otherwise
    """
    import uuid
    
    try:
        uuid.UUID(uuid_string)
        return True
    except (ValueError, AttributeError, TypeError):
        return False
