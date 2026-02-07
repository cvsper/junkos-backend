#!/bin/bash
# Quick local test script for production-ready backend

echo "🧪 Testing JunkOS Backend Locally"
echo "=================================="
echo ""

# Check Python
echo "📦 Checking Python..."
python3 --version || { echo "❌ Python 3 not found"; exit 1; }

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
echo "📦 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📦 Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚠️  No .env file found. Creating from example..."
    cat > .env << EOF
SECRET_KEY=dev-secret-key-for-testing
API_KEY=junkos-api-key-12345
DATABASE_PATH=junkos.db
FLASK_ENV=development
PORT=8080
CORS_ORIGINS=*
BASE_PRICE=50.0
EOF
    echo "✅ Created .env file"
fi

# Start the app
echo ""
echo "🚀 Starting Flask backend..."
echo "   URL: http://localhost:8080"
echo "   Health: http://localhost:8080/api/health"
echo ""
echo "Press Ctrl+C to stop"
echo ""

python3 app.py
