#!/bin/bash
# ==============================================================================
# سكربت التجهيز الآلي لمشروع Smart Teacher (نبراس) على PythonAnywhere
# ==============================================================================

set -e

echo "================================================================"
echo " 🚀 بدء تجهيز مشروع Smart Teacher على PythonAnywhere"
echo "================================================================"

PROJECT_DIR="$HOME/nbras"

# 1. التحقق من المسار
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ المجلد $PROJECT_DIR غير موجود. يرجى استنساخ المشروع أولاً:"
    echo "   git clone https://github.com/123mohammed12/nbras.git ~/nbras"
    exit 1
fi

cd "$PROJECT_DIR"

# 2. إعداد البيئة الافتراضية
echo ""
echo "📦 [1/4] إعداد البيئة الافتراضية وتثبيت المتطلبات..."
source /etc/bashrc 2>/dev/null || true
source /usr/local/bin/virtualenvwrapper.sh 2>/dev/null || source ~/.local/bin/virtualenvwrapper.sh 2>/dev/null || true

# إنشاء البيئة إن لم تكن موجودة
if [ ! -d "$HOME/.virtualenvs/smartteacher" ]; then
    mkvirtualenv --python=/usr/bin/python3.12 smartteacher
else
    workon smartteacher
fi

pip install --upgrade pip
pip install -r requirements.txt

# 3. إعداد ملف .env
echo ""
echo "🔑 [2/4] فحص وإعداد ملف .env..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "جاري إنشاء .env وتوليد المفاتيح السرية..."
    cp .env.production .env

    SECRET=$(python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())")
    OTP_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    ACT_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")

    sed -i "s|SECRET_KEY=.*|SECRET_KEY=$SECRET|g" .env
    sed -i "s|OTP_HASH_SECRET=.*|OTP_HASH_SECRET=$OTP_KEY|g" .env
    sed -i "s|ACTIVATION_CODE_HMAC_SECRET=.*|ACTIVATION_CODE_HMAC_SECRET=$ACT_KEY|g" .env

    echo "✅ تم إنشاء .env وتوليد مفاتيح تشفير عشوائية وآمنة تلقائياً."
    echo "⚠️  ملاحظة هامة: افتح ملف .env لتحديث بيانات قاعدة البيانات (DB_NAME, DB_USER, DB_PASSWORD, DB_HOST) الخاصة بحسابك:"
    echo "   nano ~/nbras/.env"
else
    echo "✅ ملف .env موجود مسبقاً."
fi

# 4. إعداد قاعدة البيانات والملفات الثابتة
echo ""
echo "🗄️ [3/4] تهيئة جدول الكاش والترحيلات..."
export DJANGO_SETTINGS_MODULE="config.settings.pythonanywhere"

python manage.py createcachetable || echo "⚠️ تنبيه: تعذر إنشاء جدول الكاش، تأكد من صحة بيانات قاعدة البيانات في .env"
python manage.py migrate --noinput || echo "⚠️ تنبيه: تعذر إكمال الترحيلات، تأكد من صحة بيانات قاعدة البيانات في .env"

echo ""
echo "📁 [4/4] تجميع الملفات الثابتة (Static Files)..."
python manage.py collectstatic --noinput

echo ""
echo "================================================================"
echo " 🎉 اكتمل التجهيز الأساسي بنجاح!"
echo "================================================================"
echo "الخطوات المتبقية في لوحة تحكم PythonAnywhere (صفحة Web):"
echo "1. تأكد من إدخال المسارات في صفحة Web:"
echo "   - Source code: /home/$USER/nbras"
echo "   - Working directory: /home/$USER/nbras"
echo "   - Virtualenv: /home/$USER/.virtualenvs/smartteacher"
echo "2. إعداد ملف WSGI configuration كما هو موضح في README_DEPLOY.md"
echo "3. إضافة المسارات الثابتة في قسم Static files:"
echo "   - /static/  -> /home/$USER/nbras/staticfiles"
echo "   - /media/   -> /home/$USER/nbras/media"
echo "4. الضغط على زر Reload الأخضر"
echo "================================================================"
