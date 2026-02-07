# 🚀 Deploy JunkOS Backend to Render - Step by Step

## Step 1: Sign into Render (30 seconds)

1. Go to **https://render.com**
2. Click **"Get Started"** or **"Sign In"**
3. Sign in with GitHub (recommended) or email

---

## Step 2: Create Web Service (2 minutes)

1. **Click the "New +" button** (top right) → **"Web Service"**

2. **Connect GitHub repo:**
   - You'll see a list of your repos
   - Find and click **"Connect"** next to `cvsper/junkos-backend`
   - If you don't see it, click "Configure account" and grant access

3. **Configure the service:**

   **Name:** `junkos-backend`
   
   **Region:** `US East (Ohio)` (or closest to you)
   
   **Branch:** `main`
   
   **Root Directory:** (leave blank)
   
   **Runtime:** `Python 3`
   
   **Build Command:** `pip install -r requirements.txt`
   
   **Start Command:** `gunicorn app:app`
   
   **Instance Type:** **Starter** ($7/month - required for production, Free tier sleeps)

4. **Scroll down to "Environment Variables"**
   
   Click **"Add Environment Variable"** and add these **one by one:**

   ```
   FLASK_ENV=production
   SECRET_KEY=junkos-secret-key-change-in-production-12345
   API_KEY=junkos-api-key-12345
   PORT=10000
   ```

   (We'll add DATABASE_URL in the next step)

5. **Click "Create Web Service"**

   ⏳ Wait 2-3 minutes for initial deployment...

---

## Step 3: Add PostgreSQL Database (1 minute)

1. **Click "New +" button** (top right) → **"PostgreSQL"**

2. **Configure:**
   
   **Name:** `junkos-db`
   
   **Database:** `junkos`
   
   **User:** `junkos`
   
   **Region:** `US East (Ohio)` (same as web service!)
   
   **Instance Type:** **Starter** ($7/month - Free expires after 90 days)

3. **Click "Create Database"**

4. **Copy the Internal Database URL:**
   - After creation, you'll see "Internal Database URL"
   - It looks like: `postgresql://junkos:xxx@dpg-xxx.oregon-postgres.render.com/junkos_xxx`
   - Click the **copy icon** 📋

---

## Step 4: Connect Database to Web Service (30 seconds)

1. **Go back to your Web Service** (`junkos-backend`)
   - Click "Dashboard" (top left)
   - Click on `junkos-backend`

2. **Click "Environment" tab** (left sidebar)

3. **Add new environment variable:**
   - Click **"Add Environment Variable"**
   - **Key:** `DATABASE_URL`
   - **Value:** Paste the Internal Database URL you just copied
   - Click **"Save Changes"**

4. **Render will automatically redeploy** (takes ~2 minutes)

---

## Step 5: Verify Deployment (30 seconds)

Once deployment completes, you'll see your app URL at the top:

**Example:** `https://junkos-backend.onrender.com`

**Copy this URL!** You'll need it in a moment.

**Test the API:**

Open this in your browser (replace with your actual URL):
```
https://junkos-backend.onrender.com/api/health
```

You should see:
```json
{
  "status": "healthy",
  "database": "connected"
}
```

✅ **If you see this, deployment is successful!**

---

## Step 6: Update iOS App (I'll do this)

Once you give me your Render URL, I'll update the iOS app to use it.

---

## 💰 Pricing Summary

- **Web Service (Starter):** $7/month
- **PostgreSQL (Starter):** $7/month
- **Total:** $14/month

**Free Tier Option** (for testing only):
- Free tier spins down after 15 minutes
- First request takes 30-60 seconds to wake up
- Not recommended for production

---

## ⚠️ Important Notes

### Auto-Deploy
- Every time you push to `main` branch on GitHub, Render will automatically redeploy
- No manual steps needed after initial setup!

### Database Backups
- Starter tier includes daily backups
- Free tier has NO backups (risky!)

### Logs
- Click "Logs" tab in Render to see real-time logs
- Helpful for debugging

---

## 🆘 Troubleshooting

**"Build failed":**
- Check the "Logs" tab for errors
- Most common: missing dependency in requirements.txt

**"Application failed to respond":**
- Check that PORT=10000 is set in environment variables
- Check Start Command is: `gunicorn app:app`

**"Database connection failed":**
- Verify DATABASE_URL is set correctly
- Make sure database and web service are in the SAME region

---

## ✅ Next Steps After Deployment

1. **Give me your Render URL** (e.g., `https://junkos-backend.onrender.com`)
2. I'll update the iOS app to use it
3. Test the full flow: iOS app → Production API
4. Ready for TestFlight!

---

**Start with Step 1 and work your way down. Paste your Render URL when you're done!** 🚀
