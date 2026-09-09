import io
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from PIL import Image

CONTENT_MAX_PDF_BYTES = 26214400        # 25 MB
CONTENT_MAX_IMAGE_BYTES = 8388608        # 8 MB
CONTENT_MAX_IMAGE_PIXELS = 40000000     # 40 MegaPixels limit to prevent decompression bombs


def validate_pdf_file(file_obj: UploadedFile):
    """
    Validates uploaded PDF file size, extension, and magic bytes (%PDF-).
    """
    if not file_obj:
        return

    if file_obj.size > CONTENT_MAX_PDF_BYTES:
        raise ValidationError(f"حجم الملف يتجاوز الحد المسموح به ({CONTENT_MAX_PDF_BYTES // (1024 * 1024)} ميجابايت).")

    ext = file_obj.name.split(".")[-1].lower() if "." in file_obj.name else ""
    if ext != "pdf":
        raise ValidationError("امتداد الملف يجب أن يكون .pdf فقط.")

    # Check magic header
    file_obj.seek(0)
    header = file_obj.read(5)
    file_obj.seek(0)

    if header != b"%PDF-":
        raise ValidationError("محتوى الملف غير صالح أو لا يمثل ملف PDF حقيقي.")


def validate_image_file(image_obj: UploadedFile):
    """
    Validates uploaded image file using Pillow, checks size, pixel count, and format.
    Prohibits SVG and executables.
    """
    if not image_obj:
        return

    if image_obj.size > CONTENT_MAX_IMAGE_BYTES:
        raise ValidationError(f"حجم الصورة يتجاوز الحد المسموح به ({CONTENT_MAX_IMAGE_BYTES // (1024 * 1024)} ميجابايت).")

    ext = image_obj.name.split(".")[-1].lower() if "." in image_obj.name else ""
    allowed_exts = {"jpg", "jpeg", "png", "webp"}
    if ext not in allowed_exts:
        raise ValidationError("نوع الصورة غير مسموح به. يرجى اختيار صورة بصيغة (JPG, PNG, WebP).")

    image_obj.seek(0)
    try:
        with Image.open(image_obj) as img:
            img.verify()
            width, height = img.size
            if width * height > CONTENT_MAX_IMAGE_PIXELS:
                raise ValidationError("أبعاد الصورة كبيرة جداً وتتجاوز الحد المسموح به.")
            if img.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValidationError("صيغة الصورة غير مدعومة.")
    except Exception as e:
        if isinstance(e, ValidationError):
            raise e
        raise ValidationError("ملف الصورة تالف أو غير صالح.")
    finally:
        image_obj.seek(0)
