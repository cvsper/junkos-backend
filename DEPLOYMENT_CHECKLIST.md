# 📋 JunkOS Backend Deployment Checklist

Use this checklist to deploy your backend step by step.

---

## ✅ Pre-Deployment (COMPLETED)

- [x] Created `requirements.txt` with production dependencies
- [x] Created `Procfile` for Railway/Render
- [x] Created `runtime.txt` (Python 3.12.0)
- [x] Created `.gitignore` (excludes DB, .env, cache)
- [x] Created `railway.toml` deployment config
- [x] Created `render.yaml` deployment config
- [x] Updated `database.py` with PostgreSQL support
- [x] Updated `app_config.py` with environment variables
- [x] Updated `app.py` for production mode
- [x] Created `migrate_to_postgres.py` migration script
- [x] Created deployment documentation
- [x] Updated iOS `Config.swift`
- [x] Tested locally ✅

---

## 📝 Deployment Steps (YOUR TURN)

### 1. Git & GitHub Setup
```bash
cd ~/Documents/programs/webapps/junkos/backend
```

- [ ] Run: `git init`
- [ ] Run: `git add .`
- [ ] Run: `git commit -m "Production-ready backend"`
- [ ] Create GitHub repo: https://github.com/new
- [ ] Name it: `junkos-backend`
- [ ] Run: `git remote add origin https://github.com/YOUR_USERNAME/junkos-backend.git`
- [ ] Run: `git push -u origin main`

---

### 2. Generate Secrets

Run these commands and save the output:

```bash
# Generate SECRET_KEY
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"

# Generate API_KEY
python3 -c "import secrets; print('API_KEY=junkos-' + secrets.token_hex(16))"
```

- [ ] Copy SECRET_KEY: `_________________________________`
- [ ] Copy API_KEY: `_________________________________`

---

### 3. Deploy to Railway

- [ ] Go to: https://railway.app
- [ ] Sign in with GitHub
- [ ] Click **"New Project"**
- [ ] Click **"Deploy from GitHub repo"**
- [ ] Select `junkos-backend`
- [ ] Wait for initial deployment (~2 min)

---

### 4. Add PostgreSQL Database

- [ ] In Railway project, click **"+ New"**
- [ ] Click **"Database"**
- [ ] Click **"PostgreSQL"**
- [ ] Wait for database to provision (~1 min)
- [ ] Verify `DATABASE_URL` is auto-set in Variables tab

---

### 5. Set Environment Variables

In Railway → Variables tab, add:

- [ ] `FLASK_ENV` = `production`
- [ ] `SECRET_KEY` = `<paste from step 2>`
- [ ] `API_KEY` = `<paste from step 2>`
- [ ] `CORS_ORIGINS` = `*`

Click **"Deploy"** after adding variables.

---

### 6. Get Production URL

- [ ] Copy your Railway URL: `_________________________________`
  - Should look like: `https://junkos-backend-production.up.railway.app`

---

### 7. Test Production API

```bash
# Replace YOUR_URL with actual URL
curl https://YOUR_URL/api/health
```

- [ ] Health check returns: `{"status":"healthy","service":"JunkOS API"}`

```bash
# Replace YOUR_URL and YOUR_API_KEY
curl -H "X-API-Key: YOUR_API_KEY" https://YOUR_URL/api/services
```

- [ ] Services endpoint returns 10 items
- [ ] Each service has `id`, `name`, `base_price`

---

### 8. Update iOS App

Edit: `~/Documents/programs/webapps/junkos/JunkOS-Clean/JunkOS/Services/Config.swift`

Replace line 16 with your actual URL:
```swift
return "https://junkos-backend-production.up.railway.app"
```

- [ ] Updated `Config.swift` with production URL
- [ ] Verified API_KEY matches in both apps
- [ ] Rebuilt iOS app in Xcode

---

### 9. Test iOS App

- [ ] Launch iOS app in simulator/device
- [ ] Services load successfully
- [ ] Can create a quote
- [ ] Can create a booking
- [ ] No CORS errors in console

---

### 10. Optional: Migrate Data

If you have existing SQLite data:

```bash
# Set DATABASE_URL from Railway
export DATABASE_URL="<copy from Railway Variables tab>"

# Run migration
python3 migrate_to_postgres.py
```

- [ ] Migration completed successfully
- [ ] Verified data in PostgreSQL

---

## 🎯 Success Criteria

You're done when ALL of these are true:

- [ ] Backend is accessible at production URL
- [ ] Health check returns 200 OK
- [ ] Services endpoint works with API key
- [ ] PostgreSQL database connected
- [ ] iOS app loads services from production
- [ ] iOS app can create bookings
- [ ] No CORS errors

---

## 📊 Monitoring

Railway provides built-in monitoring:

- [ ] Check **Deployments** tab for deploy status
- [ ] Check **Logs** tab for application logs
- [ ] Check **Metrics** tab for CPU/memory usage
- [ ] Set up alerts (optional)

---

## 🐛 Troubleshooting

### App won't start
- Check Railway logs for errors
- Verify all environment variables are set
- Ensure PostgreSQL addon is running

### Database errors
- Verify `DATABASE_URL` is set (auto-set by PostgreSQL addon)
- Check database is running in Railway
- Review logs for connection errors

### iOS app can't connect
- Verify CORS_ORIGINS is set
- Check API_KEY matches in both apps
- Ensure using HTTPS (not HTTP) URL
- Check iOS console for specific errors

### 401 Unauthorized
- Verify API_KEY is set correctly in backend
- Check iOS app is sending `X-API-Key` header
- Ensure API_KEY matches between backend and iOS

---

## 📚 Reference Docs

- [ ] Read `DEPLOYMENT.md` for detailed guide
- [ ] Read `PRODUCTION_READY_REPORT.md` for technical details
- [ ] Check Railway docs: https://docs.railway.app

---

## ⏱️ Time Tracking

Estimated: 10-15 minutes

- Git setup: ___ min
- Railway deployment: ___ min
- Environment variables: ___ min
- Testing: ___ min
- iOS update: ___ min

**Total:** ___ minutes

---

## 🎉 Completion

**Deployed by:** _______________
**Date:** _______________
**Production URL:** _______________
**API Key:** _______________ (keep secret!)

---

**Status:** [ ] In Progress [ ] Deployed [ ] Tested [ ] Complete

---

Print this checklist or keep it open while deploying!
