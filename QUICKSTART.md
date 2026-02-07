# JunkOS Backend - Quick Start Guide

## 🚀 Get Started in 5 Minutes

### 1. Install Dependencies

```bash
cd ~/Documents/programs/webapps/junkos/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your database credentials
nano .env
```

Minimum required configuration:
```env
DATABASE_URL=postgresql://username:password@localhost:5432/junkos_dev
SECRET_KEY=your-secret-key-here
```

### 3. Setup Database

```bash
# Create database
createdb junkos_dev

# Run schema
psql -U postgres -d junkos_dev -f ../junk_removal_schema.sql

# OR use Flask-Migrate
flask db upgrade
```

### 4. Seed Demo Data

```bash
flask seed-db
```

This creates:
- Demo tenant (slug: `demo`)
- Admin user: `admin@demo.com` / `Admin123!`
- Dispatcher: `dispatcher@demo.com` / `Dispatch123!`
- Driver: `driver@demo.com` / `Driver123!`
- Sample services

### 5. Run the Server

```bash
python run.py
```

Server runs at: `http://localhost:5000`

### 6. Test the API

```bash
# Health check
curl http://localhost:5000/health

# Login (get session cookie)
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: demo" \
  -d '{
    "email": "admin@demo.com",
    "password": "Admin123!"
  }' \
  -c cookies.txt

# Get current user
curl http://localhost:5000/api/auth/me \
  -H "X-Tenant-ID: demo" \
  -b cookies.txt

# List services
curl http://localhost:5000/api/admin/services \
  -H "X-Tenant-ID: demo" \
  -b cookies.txt
```

## 📋 What's Included

### ✅ Complete API Endpoints

- **Authentication:** `/api/auth/*` - Login, register, password management
- **Bookings:** `/api/bookings/*` - Create and manage bookings
- **Jobs:** `/api/jobs/*` - Job operations and status updates
- **Dispatch:** `/api/dispatch/*` - Driver assignments, routes, scheduling
- **Payments:** `/api/payments/*` - Invoices and payment processing
- **Admin:** `/api/admin/*` - User, customer, service, and settings management

### ✅ Features

- Multi-tenant architecture (subdomain or header-based)
- Role-based access control (admin, dispatcher, driver)
- SQLAlchemy models matching full schema
- Input validation and error handling
- Activity logging and audit trail
- Flask-Login authentication
- CORS support for frontend integration
- Production-ready configuration

### ✅ Database Models

All models from schema implemented:
- Tenant, User, Customer, Service
- Job, JobAssignment, Route
- Invoice, InvoiceLineItem, Payment
- Photo, ActivityLog, Notification, TenantSettings

## 📚 Next Steps

1. **Frontend Integration:** Configure CORS origins in `.env`
2. **Payment Setup:** Add Stripe keys for payment processing
3. **Email:** Configure SMTP for email notifications
4. **Deployment:** Use Gunicorn for production (`gunicorn -w 4 run:app`)

## 🔧 Common Commands

```bash
# Flask shell (with models auto-imported)
flask shell

# Database migrations
flask db migrate -m "Description"
flask db upgrade

# Re-seed database
flask seed-db

# Run with debug
flask run --debug
```

## 📖 Full Documentation

See `README.md` for:
- Complete API documentation
- Deployment guide
- Security checklist
- Troubleshooting

## 🆘 Troubleshooting

**Database connection failed:**
```bash
# Check PostgreSQL is running
pg_isready

# Verify DATABASE_URL in .env
```

**Import errors:**
```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

**Tenant not found:**
- Ensure you're sending `X-Tenant-ID: demo` header
- Or use `?tenant=demo` query parameter in development

---

**You're all set! 🎉**

Start building your frontend or test the API with the demo credentials above.
