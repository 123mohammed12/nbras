#!/usr/bin/env python
"""
سكربت استيراد وإنشاء محتويات المنهج الدراسي (المواد، الوحدات، والدروس)
وربطها تلقائياً بالصفوف والأقسام والاترام الموجودة مسبقاً في قاعدة البيانات.
"""
import os
import sys
from pathlib import Path

# إعداد مسارات بايثون وبيئة Django
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# تحميل متغيرات البيئة إن وجدت
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

# تحديد ملف الإعدادات المناسب
if "DJANGO_SETTINGS_MODULE" not in os.environ:
    if (BASE_DIR / ".env").exists() or "PYTHONANYWHERE_DOMAIN" in os.environ or "PYTHONANYWHERE_SITE" in os.environ:
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.pythonanywhere"
    else:
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.development"

import django
django.setup()

from django.core.management import call_command

if __name__ == "__main__":
    print("================================================================")
    print(" 📚 تشغيل استيراد محتويات المنهج (المواد - الوحدات - الدروس)")
    print("================================================================")
    custom_path = sys.argv[1] if len(sys.argv) > 1 else None
    if custom_path:
        call_command("import_curriculum", custom_path)
    else:
        call_command("import_curriculum")
