# JunkOS Backend - Production Deployment Guide

## 📋 Prerequisites

- Git installed
- GitHub account
- Railway or Render account (free tier available)

## 🚀 Option 1: Deploy to Railway (Recommended)

Railway is the easiest option with excellent Git integration and PostgreSQL support.

### Step 1: Initialize Git Repository

```bash
cd ~/Documents/programs/webapps/junkos/backend

# Initialize git if not already done
git init

# Add all files
git add .

# Commit
git commit -m "Initial commit - production ready"
```

### Step 2: Push to GitHub

```bash
# Create a new repository on GitHub (https://github.com/new)
# Name it: junkos-backend

# Add remote
git remote add origin https://github.com/YOUR_USERNAME/junkos-backend.git

# Push
git branch -M main
git push -u origin main
```

### Step 3: Deploy to Railway

1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. Click **"New Project"** → **"Deploy from GitHub repo"**
3. Select your `junkos-backend` repository
4. Railway will automatically:
   - Detect Python
   - Install dependencies from `requirements.txt`
   - Use the `Procfile` to start Gunicorn

### Step 4: Add PostgreSQL Database

1. In your Railway project, click **"+ New"** → **"Database"** → **"PostgreSQL"**
2. Railway automatically sets the `DATABASE_URL` environment variable
3. Your app will automatically connect to PostgreSQL

### Step 5: Set Environment Variables

In Railway project settings → **Variables**, add:

```bash
FLASK_ENV=production
SECRET_KEY=<generate-a-random-secret-key>
API_KEY=<your-api-key-for-ios-app>
CORS_ORIGINS=*
BASE_PRICE=50.0
```

To generate a secure secret key:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Step 6: Migrate Data (Optional)

If you have existing data in SQLite:

```bash
# Get your Railway PostgreSQL connection string
# From Railway dashboard → PostgreSQL → Connect tab

# Set it locally
export DATABASE_URL="postgresql://user:pass@hostname:port/dbname"

# Run migration
python3 migrate_to_postgres.py
```

### Step 7: Get Your Production URL

Railway will provide a URL like: `https://junkos-backend-production.up.railway.app`

Test it:
```bash
curl https://your-app.railway.app/api/health
```

Expected response:
```json
{"status": "healthy", "service": "JunkOS API"}
```

---

## 🚀 Option 2: Deploy to Render

### Step 1-2: Same as Railway (Git + GitHub)

### Step 3: Deploy to Render

1. Go to [render.com](https://render.com) and sign in with GitHub
2. Click **"New +"** → **"Web Service"**
3. Connect your `junkos-backend` repository
4. Render will detect the `render.yaml` configuration

### Step 4: Render Auto-Configuration

Render will automatically:
- Create a PostgreSQL database
- Set `DATABASE_URL` environment variable
- Deploy your app

### Step 5: Set Additional Environment Variables

In Render dashboard → **Environment**, add:

```bash
SECRET_KEY=<generate-a-random-secret-key>
API_KEY=<your-api-key-for-ios-app>
```

### Step 6: Get Your Production URL

Render provides a URL like: `https://junkos-backend.onrender.com`

---

## 📱 Update iOS App

Update `Config.swift` in your iOS app:

```swift
enum Config {
    // Production API
    static let baseURL = "https://junkos-backend-production.up.railway.app"
    
    // Or for Render:
    // static let baseURL = "https://junkos-backend.onrender.com"
    
    static let apiKey = "your-api-key-here"  // Match backend API_KEY
}
```

---

## 🔍 Testing Your Production API

### 1. Health Check
```bash
curl https://your-production-url.com/api/health
```

### 2. Get Services
```bash
curl -H "X-API-Key: your-api-key" \
     https://your-production-url.com/api/services
```

### 3. Get Quote
```bash
curl -X POST \
     -H "X-API-Key: your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"services": [1, 2], "zip_code": "10001"}' \
     https://your-production-url.com/api/quote
```

### 4. Create Booking
```bash
curl -X POST \
     -H "X-API-Key: your-api-key" \
     -H "Content-Type: application/json" \
     -d '{
       "address": "123 Main St",
       "zip_code": "10001",
       "services": [1, 2],
       "scheduled_datetime": "2024-02-20 14:00",
       "customer": {
         "name": "John Doe",
         "email": "john@example.com",
         "phone": "555-0100"
       }
     }' \
     https://your-production-url.com/api/bookings
```

---

## 🔐 Security Checklist

- ✅ Generated strong `SECRET_KEY`
- ✅ Set unique `API_KEY`
- ✅ PostgreSQL database enabled
- ✅ HTTPS enabled (automatic on Railway/Render)
- ✅ SQLite database file excluded from Git (`.gitignore`)
- ✅ `.env` file excluded from Git

---

## 📊 Monitoring

### Railway
- View logs: Project → Deployments → Logs
- Monitor metrics: Project → Metrics

### Render
- View logs: Service → Logs
- Monitor metrics: Service → Metrics

---

## 🐛 Troubleshooting

### App won't start
1. Check logs for errors
2. Verify all environment variables are set
3. Make sure `DATABASE_URL` is set correctly

### Database connection fails
1. Verify PostgreSQL addon is running
2. Check `DATABASE_URL` format
3. Ensure `psycopg2-binary` is in `requirements.txt`

### API returns 500 errors
1. Check application logs
2. Verify database tables are created
3. Test database connection

### CORS errors from iOS app
1. Verify `CORS_ORIGINS` is set correctly
2. Make sure iOS app uses HTTPS URL
3. Check that `X-API-Key` header is sent

---

## 🔄 Updating Your Deployment

After making code changes:

```bash
cd ~/Documents/programs/webapps/junkos/backend

git add .
git commit -m "Your update message"
git push origin main
```

Railway/Render will automatically:
- Detect the push
- Rebuild your app
- Deploy the new version
- Zero-downtime deployment

---

## 📈 Scaling (Future)

Both Railway and Render support:
- Automatic scaling
- Custom domains
- Environment-specific deployments (staging, production)
- Database backups
- Health check monitoring

---

## 🆘 Support

- Railway Docs: https://docs.railway.app
- Render Docs: https://render.com/docs
- Flask Docs: https://flask.palletsprojects.com

---

## ✅ Deployment Checklist

- [ ] Code pushed to GitHub
- [ ] Railway/Render project created
- [ ] PostgreSQL database added
- [ ] Environment variables configured
- [ ] Production URL tested
- [ ] iOS app updated with production URL
- [ ] Test bookings created successfully
- [ ] Monitoring enabled

---

**🎉 Your JunkOS backend is now live in production!**
