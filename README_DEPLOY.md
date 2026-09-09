# 🚀 دليل نشر Smart Teacher API — PythonAnywhere

## المتطلبات

| المتطلب | التفاصيل |
|---------|---------|
| حساب PythonAnywhere | خطة **Developer** ($10/شهر) |
| Python | 3.12 (متوفر على PythonAnywhere) |
| PostgreSQL | متوفر في الخطة المدفوعة |

---

## 📋 خطوات النشر

### الخطوة 1: إنشاء حساب PythonAnywhere

1. سجّل في [pythonanywhere.com](https://www.pythonanywhere.com)
2. ارقِ إلى خطة **Developer** ($10/شهر) — مطلوب لـ PostgreSQL والاتصال الخارجي

---

### الخطوة 2: إنشاء قاعدة بيانات PostgreSQL

1. من Dashboard → **Databases** tab
2. أنشئ كلمة مرور لـ PostgreSQL
3. أنشئ قاعدة بيانات جديدة باسم `smart_teacher`
4. **سجّل هذه المعلومات** (ستحتاجها لاحقاً):
   - **Host**: `YOUR_USERNAME-smart-teacher.postgres.pythonanywhere-services.com`
   - **Database name**: `YOUR_USERNAME$smart_teacher`
   - **Username**: `YOUR_USERNAME`
   - **Port**: الرقم المعروض في الصفحة

---

### الخطوة 3: استنساخ المشروع من GitHub

افتح **Bash Console** من Dashboard واكتب:

```bash
git clone https://github.com/123mohammed12/nbras.git
```

---

### الخطوة 4: إنشاء البيئة الافتراضية

```bash
mkvirtualenv --python=/usr/bin/python3.12 smartteacher
pip install -r nbras/requirements.txt
```

---

### الخطوة 5: إعداد ملف البيئة

```bash
cd ~/nbras
cp .env.production .env
nano .env
```

**عدّل القيم التالية** (استبدل `YOUR_USERNAME` باسم حسابك):

| المتغير | القيمة |
|---------|-------|
| `SECRET_KEY` | شغّل: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `ALLOWED_HOSTS` | `YOUR_USERNAME.pythonanywhere.com` |
| `DB_NAME` | `YOUR_USERNAME$smart_teacher` |
| `DB_USER` | `YOUR_USERNAME` |
| `DB_PASSWORD` | كلمة المرور التي أنشأتها في الخطوة 2 |
| `DB_HOST` | من صفحة Databases |
| `DB_PORT` | من صفحة Databases |
| `OTP_HASH_SECRET` | شغّل: `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `ACTIVATION_CODE_HMAC_SECRET` | شغّل: `python -c "import secrets; print(secrets.token_urlsafe(64))"` |

---

### الخطوة 6: تهيئة قاعدة البيانات

```bash
cd ~/nbras
workon smartteacher

# إنشاء جدول الكاش
DJANGO_SETTINGS_MODULE=config.settings.pythonanywhere python manage.py createcachetable

# تشغيل الترحيلات
DJANGO_SETTINGS_MODULE=config.settings.pythonanywhere python manage.py migrate

# جمع الملفات الثابتة
DJANGO_SETTINGS_MODULE=config.settings.pythonanywhere python manage.py collectstatic --noinput

# إنشاء مستخدم admin
DJANGO_SETTINGS_MODULE=config.settings.pythonanywhere python manage.py createsuperuser
```

---

### الخطوة 7: إعداد Web App

1. من Dashboard → **Web** tab → **Add a new web app**
2. اختر **Manual configuration**
3. اختر **Python 3.12**
4. في قسم **Virtualenv**:
   - أدخل: `/home/YOUR_USERNAME/.virtualenvs/smartteacher`
5. في قسم **Code**:
   - **Source code**: `/home/YOUR_USERNAME/nbras`
   - **Working directory**: `/home/YOUR_USERNAME/nbras`

---

### الخطوة 8: إعداد ملف WSGI

اضغط على رابط **WSGI configuration file** وامسح كل المحتوى واكتب:

```python
import os
import sys
from dotenv import load_dotenv

# ─── Load .env file ─────────────────────────────────
project_folder = os.path.expanduser('~/nbras')
load_dotenv(os.path.join(project_folder, '.env'))

# ─── Add project to path ────────────────────────────
path = '/home/YOUR_USERNAME/nbras'
if path not in sys.path:
    sys.path.insert(0, path)

# ─── Set settings module ────────────────────────────
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.pythonanywhere'

# ─── Start application ──────────────────────────────
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

⚠️ **استبدل `YOUR_USERNAME`** باسم حسابك الحقيقي!

---

### الخطوة 9: إعداد Static و Media Files

في **Web** tab، أضف في قسم **Static files**:

| URL | Directory |
|-----|-----------|
| `/static/` | `/home/YOUR_USERNAME/nbras/staticfiles` |
| `/media/` | `/home/YOUR_USERNAME/nbras/media` |

---

### الخطوة 10: إضافة python-dotenv

WSGI file يحتاج مكتبة `python-dotenv` لتحميل ملف `.env`:

```bash
workon smartteacher
pip install python-dotenv
```

---

### الخطوة 11: Reload وتجربة

1. اضغط زر **Reload** الأخضر في Web tab
2. افتح في المتصفح: `https://YOUR_USERNAME.pythonanywhere.com/api/v1/docs/`
3. يجب أن تظهر صفحة Swagger UI

---

## 📦 استيراد بيانات المنهج (اختياري)

```bash
cd ~/nbras
workon smartteacher
DJANGO_SETTINGS_MODULE=config.settings.pythonanywhere python manage.py import_curriculum exported_curriculum_json/
```

---

## 🔄 التحديثات المستقبلية

```bash
cd ~/nbras
git pull origin main
workon smartteacher
pip install -r requirements.txt
DJANGO_SETTINGS_MODULE=config.settings.pythonanywhere python manage.py migrate
DJANGO_SETTINGS_MODULE=config.settings.pythonanywhere python manage.py collectstatic --noinput
```

ثم اضغط **Reload** في Web tab.

---

## 🔍 حل المشاكل

### خطأ 502 Bad Gateway
- تحقق من **Error log** في Web tab
- تأكد من مسار الـ virtualenv صحيح

### خطأ "DisallowedHost"
- تأكد من `ALLOWED_HOSTS` في `.env` يحتوي اسم الدومين الصحيح

### خطأ في قاعدة البيانات
- تأكد من قيم `DB_HOST` و `DB_NAME` و `DB_PORT` من صفحة Databases

### خطأ "No module named..."
- تأكد أنك مفعّل الـ virtualenv الصحيح في Web tab

---

## 📁 هيكل المجلدات على PythonAnywhere

```
/home/YOUR_USERNAME/
├── nbras/                        # المشروع (من GitHub)
│   ├── apps/                     # 19 تطبيق Django
│   ├── config/
│   │   └── settings/
│   │       ├── base.py
│   │       ├── production.py
│   │       └── pythonanywhere.py  # ← الإعدادات المستخدمة
│   ├── exported_curriculum_json/
│   ├── staticfiles/              # ← يُنشأ بعد collectstatic
│   ├── media/                    # ← ملفات المستخدمين
│   ├── .env                      # ← ملف البيئة (محلي)
│   ├── manage.py
│   └── requirements.txt
└── .virtualenvs/
    └── smartteacher/             # البيئة الافتراضية
```
