# JunkOS Backend API

Flask-based REST API for JunkOS junk removal booking service.

## Quick Start

**Option 1: Use the run script (easiest)**
```bash
./run.sh
```

**Option 2: Manual setup**
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment config
cp .env.example .env

# Run the server
python app.py
```

Server runs on `http://localhost:8080`

## Authentication

All API endpoints (except `/api/health`) require an API key in the request header:

```
X-API-Key: junkos-api-key-12345
```

Change this in `.env` for production!

## API Endpoints

### 1. Health Check
```
GET /api/health
```

**Response:**
```json
{
  "status": "healthy",
  "service": "JunkOS API"
}
```

---

### 2. Get Services
```
GET /api/services
```

**Headers:**
```
X-API-Key: your-api-key
```

**Response:**
```json
{
  "success": true,
  "services": [
    {
      "id": 1,
      "name": "Single Item Removal",
      "description": "Remove one large item",
      "base_price": 89.00,
      "unit": "item"
    }
  ]
}
```

---

### 3. Get Quote
```
POST /api/quote
```

**Headers:**
```
X-API-Key: your-api-key
Content-Type: application/json
```

**Request Body:**
```json
{
  "services": [1, 2],
  "zip_code": "10001"
}
```

**Response:**
```json
{
  "success": true,
  "estimated_price": 239.00,
  "services": [...],
  "available_time_slots": [
    "2026-02-08 09:00",
    "2026-02-08 13:00"
  ],
  "currency": "USD"
}
```

---

### 4. Create Booking
```
POST /api/bookings
```

**Headers:**
```
X-API-Key: your-api-key
Content-Type: application/json
```

**Request Body:**
```json
{
  "address": "123 Main St, New York, NY 10001",
  "zip_code": "10001",
  "services": [1, 2],
  "photos": [
    "https://example.com/photo1.jpg",
    "https://example.com/photo2.jpg"
  ],
  "scheduled_datetime": "2026-02-08 09:00",
  "customer": {
    "name": "John Doe",
    "email": "john@example.com",
    "phone": "+1-555-123-4567"
  },
  "notes": "Large couch and mattress removal"
}
```

**Response:**
```json
{
  "success": true,
  "booking_id": 1,
  "estimated_price": 239.00,
  "confirmation": "Booking #1 confirmed",
  "scheduled_datetime": "2026-02-08 09:00",
  "services": [...]
}
```

---

### 5. Get Booking Details
```
GET /api/bookings/:id
```

**Headers:**
```
X-API-Key: your-api-key
```

**Response:**
```json
{
  "success": true,
  "booking": {
    "id": 1,
    "customer_id": 1,
    "customer_name": "John Doe",
    "customer_email": "john@example.com",
    "customer_phone": "+1-555-123-4567",
    "address": "123 Main St, New York, NY 10001",
    "zip_code": "10001",
    "services": [1, 2],
    "photos": ["https://..."],
    "scheduled_datetime": "2026-02-08 09:00",
    "estimated_price": 239.00,
    "status": "pending",
    "notes": "Large couch and mattress removal",
    "created_at": "2026-02-07 10:30:00"
  }
}
```

---

## Database Schema

### customers
- `id` (INTEGER, PRIMARY KEY)
- `name` (TEXT)
- `email` (TEXT)
- `phone` (TEXT)
- `created_at` (TIMESTAMP)

### services
- `id` (INTEGER, PRIMARY KEY)
- `name` (TEXT)
- `description` (TEXT)
- `base_price` (REAL)
- `unit` (TEXT)
- `created_at` (TIMESTAMP)

### bookings
- `id` (INTEGER, PRIMARY KEY)
- `customer_id` (INTEGER, FOREIGN KEY)
- `address` (TEXT)
- `zip_code` (TEXT)
- `services` (TEXT, JSON array)
- `photos` (TEXT, JSON array)
- `scheduled_datetime` (TEXT)
- `estimated_price` (REAL)
- `status` (TEXT, default: 'pending')
- `notes` (TEXT)
- `created_at` (TIMESTAMP)

---

## Testing with curl

### Get services:
```bash
curl -H "X-API-Key: junkos-api-key-12345" \
  http://localhost:8080/api/services
```

### Get quote:
```bash
curl -X POST \
  -H "X-API-Key: junkos-api-key-12345" \
  -H "Content-Type: application/json" \
  -d '{"services": [1, 2], "zip_code": "10001"}' \
  http://localhost:8080/api/quote
```

### Create booking:
```bash
curl -X POST \
  -H "X-API-Key: junkos-api-key-12345" \
  -H "Content-Type: application/json" \
  -d '{
    "address": "123 Main St, New York, NY 10001",
    "zip_code": "10001",
    "services": [1],
    "scheduled_datetime": "2026-02-08 09:00",
    "customer": {
      "name": "John Doe",
      "email": "john@example.com",
      "phone": "+1-555-123-4567"
    }
  }' \
  http://localhost:8080/api/bookings
```

### Get booking:
```bash
curl -H "X-API-Key: junkos-api-key-12345" \
  http://localhost:8080/api/bookings/1
```

---

## CORS

CORS is enabled for all origins to support iOS app development. Restrict this in production:

```python
CORS(app, resources={r"/api/*": {"origins": "https://your-ios-app.com"}})
```

---

## Next Steps

- [ ] Add Stripe payment integration
- [ ] Implement user authentication (JWT)
- [ ] Add photo upload endpoint
- [ ] Email confirmations
- [ ] Admin dashboard endpoints
- [ ] Real-time availability checking
- [ ] Rate limiting
- [ ] Input validation with schemas

---

## File Structure

```
backend/
├── app.py              # Main Flask application
├── database.py         # Database models and queries
├── app_config.py       # Configuration settings
├── requirements.txt    # Python dependencies
├── run.sh             # Quick start script
├── .env               # Environment variables (not in git)
├── .env.example       # Environment template
├── junkos.db          # SQLite database (auto-created)
└── README.md          # This file
```
