# 🚀 دليل نشر Smart Teacher API — الباكند

## المتطلبات الأساسية

| المتطلب | الإصدار المطلوب |
|---------|----------------|
| Python | 3.12+ |
| PostgreSQL | 16+ |
| Redis | 7+ |

---

## 🔧 خطوات النشر

### الخطوة 1: تجهيز السيرفر

```bash
# تحديث النظام
sudo apt update && sudo apt upgrade -y

# تثبيت المتطلبات
sudo apt install -y python3.12 python3.12-venv python3-pip \
    postgresql postgresql-contrib \
    redis-server \
    git curl build-essential libpq-dev
```

### الخطوة 2: إعداد قاعدة البيانات

```bash
# الدخول إلى PostgreSQL
sudo -u postgres psql

# إنشاء قاعدة البيانات والمستخدم
CREATE USER smart_teacher_user WITH PASSWORD 'كلمة-مرور-قوية';
CREATE DATABASE smart_teacher OWNER smart_teacher_user;
ALTER USER smart_teacher_user CREATEDB;
\q
```

### الخطوة 3: رفع الملفات

```bash
# إنشاء مجلد التطبيق
sudo mkdir -p /home/smart_teacher/deploy_backend
sudo chown -R $(whoami):$(whoami) /home/smart_teacher

# رفع الملفات عبر scp
scp -r ./* user@server:/home/smart_teacher/deploy_backend/
```

### الخطوة 4: إعداد ملف البيئة

```bash
cd /home/smart_teacher/deploy_backend

# نسخ قالب البيئة
cp .env.production .env

# تعديل القيم ⚠️ مهم جداً!
nano .env
```

**القيم التي يجب تغييرها:**

| المتغير | الوصف | كيفية التوليد |
|---------|-------|---------------|
| `SECRET_KEY` | مفتاح Django السري | `python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DB_PASSWORD` | كلمة مرور قاعدة البيانات | نفس الكلمة المستخدمة في الخطوة 2 |
| `ALLOWED_HOSTS` | الدومين/IP | `your-domain.com,www.your-domain.com` |
| `OTP_HASH_SECRET` | مفتاح تشفير OTP | `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `ACTIVATION_CODE_HMAC_SECRET` | مفتاح HMAC | `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |

### الخطوة 5: التثبيت والتشغيل

```bash
# إنشاء البيئة الافتراضية
python3 -m venv venv
source venv/bin/activate

# تثبيت المتطلبات
pip install --upgrade pip
pip install -r requirements.txt

# ترحيل قاعدة البيانات
python manage.py migrate --noinput

# جمع الملفات الثابتة
python manage.py collectstatic --noinput

# إنشاء مستخدم admin (اختياري)
python manage.py createsuperuser

# تشغيل السيرفر
python manage.py runserver 0.0.0.0:8000
```

---

## 📦 استيراد بيانات المنهج

```bash
source venv/bin/activate
python manage.py import_curriculum exported_curriculum_json/
```

---

## 🔍 التحقق من عمل الخدمة

```bash
# فحص الـ API
curl http://your-domain.com/api/v1/schema/

# عرض Swagger UI — افتح في المتصفح:
# http://your-domain.com/api/v1/docs/
```

---

## ⚠️ ملاحظات أمنية مهمة

1. **لا ترفع ملف `.env`** إلى Git
2. **غيّر جميع كلمات المرور والمفاتيح** قبل النشر
3. **قيّد `ALLOWED_HOSTS`** بالدومين الفعلي فقط
4. **النسخ الاحتياطي** لقاعدة البيانات بشكل يومي:
   ```bash
   pg_dump -U smart_teacher_user smart_teacher > backup_$(date +%Y%m%d).sql
   ```

---

## 📁 هيكل المجلدات

```
deploy_backend/
├── apps/                    # تطبيقات Django (19 تطبيق)
├── config/                  # إعدادات المشروع
│   ├── settings/
│   │   ├── base.py          # الإعدادات المشتركة
│   │   ├── production.py    # إعدادات الإنتاج ✓
│   │   ├── staging.py       # إعدادات التجريب
│   │   └── development.py   # إعدادات التطوير
│   ├── urls.py
│   ├── wsgi.py              # → production settings
│   └── asgi.py              # → production settings
├── exported_curriculum_json/ # بيانات المنهج
├── manage.py                # → production settings
├── requirements.txt         # المتطلبات
├── .env.production          # قالب متغيرات البيئة
├── .gitignore
├── pytest.ini               # إعدادات الاختبارات
└── README_DEPLOY.md         # هذا الدليل
```
