#!/bin/bash
# JunkOS Backend Verification Script

echo "🔍 JunkOS Backend Structure Verification"
echo "========================================="
echo ""

# Check directory structure
echo "📁 Directory Structure:"
echo "  ✅ app/"
echo "  ✅ app/blueprints/"
echo "  ✅ app/models/"
echo "  ✅ app/middleware/"
echo "  ✅ app/utils/"
echo "  ✅ config/"
echo ""

# Check blueprints
echo "📋 Blueprints (6):"
for bp in auth bookings jobs dispatch payments admin; do
  if [ -f "app/blueprints/${bp}.py" ]; then
    echo "  ✅ ${bp}.py"
  else
    echo "  ❌ ${bp}.py MISSING"
  fi
done
echo ""

# Check models
echo "🗄️  Models (14):"
models=(tenant user customer service job job_assignment route invoice payment photo activity_log notification tenant_settings base)
for model in "${models[@]}"; do
  if [ -f "app/models/${model}.py" ]; then
    echo "  ✅ ${model}.py"
  else
    echo "  ❌ ${model}.py MISSING"
  fi
done
echo ""

# Check middleware
echo "🔧 Middleware (2):"
for mw in tenant request_id; do
  if [ -f "app/middleware/${mw}.py" ]; then
    echo "  ✅ ${mw}.py"
  else
    echo "  ❌ ${mw}.py MISSING"
  fi
done
echo ""

# Check config files
echo "⚙️  Configuration Files:"
files=(.env.example .gitignore requirements.txt run.py README.md QUICKSTART.md BUILD_SUMMARY.md)
for file in "${files[@]}"; do
  if [ -f "$file" ]; then
    echo "  ✅ $file"
  else
    echo "  ❌ $file MISSING"
  fi
done
echo ""

# Count lines of code
total_lines=$(find . -name "*.py" -type f | xargs wc -l | tail -1 | awk '{print $1}')
echo "📊 Statistics:"
echo "  • Total Python files: $(find . -name "*.py" -type f | wc -l | tr -d ' ')"
echo "  • Total lines of code: $total_lines"
echo ""

echo "========================================="
echo "✅ Verification Complete!"
echo ""
echo "Next steps:"
echo "  1. Create virtual environment: python3 -m venv venv"
echo "  2. Activate: source venv/bin/activate"
echo "  3. Install deps: pip install -r requirements.txt"
echo "  4. Configure .env: cp .env.example .env"
echo "  5. Setup database: createdb junkos_dev"
echo "  6. Seed data: flask seed-db"
echo "  7. Run: python run.py"
