"""
Admin configuration for Accounts app.
"""

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField

from apps.accounts.models import (
    User,
    PhoneVerification,
    UserDevice,
    UserSession,
    AccountMerge,
    StudentProfile,
)


class StudentProfileInline(admin.StackedInline):
    model = StudentProfile
    extra = 0
    raw_id_fields = ("governorate", "district", "isolation", "school")


class UserAdminCreationForm(forms.ModelForm):
    """
    Custom creation form for UserAdmin in Django Admin.
    Replaces standard username with phone and handles secure password hashing.
    """
    password = forms.CharField(
        label="كلمة المرور",
        widget=forms.PasswordInput,
        strip=False,
        help_text="أدخل كلمة المرور للحساب الجديد.",
    )
    password_confirm = forms.CharField(
        label="تأكيد كلمة المرور",
        widget=forms.PasswordInput,
        strip=False,
        help_text="أعد إدخال كلمة المرور للتأكيد.",
    )

    class Meta:
        model = User
        fields = ("phone", "account_type", "is_staff", "is_superuser")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account_type"].initial = User.AccountType.REGISTERED

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("password")
        p2 = cleaned_data.get("password_confirm")
        if p1 and p2 and p1 != p2:
            self.add_error("password_confirm", "كلمتا المرور غير متطابقتين.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class UserAdminChangeForm(forms.ModelForm):
    """
    Custom change form for UserAdmin in Django Admin.
    Displays read-only password hash and provides a link to change the password.
    """
    password = ReadOnlyPasswordHashField(
        label="كلمة المرور",
        help_text=(
            "لا تُخزَّن كلمات المرور بنص صريح لأسباب أمنية. "
            "يمكنك تغيير كلمة المرور باستخدام <a href=\"../password/\">نموذج تغيير كلمة المرور</a>."
        ),
    )

    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm

    ordering = ("-date_joined",)
    list_display = (
        "public_code",
        "phone",
        "account_type",
        "is_active",
        "is_staff",
        "date_joined",
    )
    list_filter = ("account_type", "is_active", "is_staff")
    search_fields = ("phone", "public_code", "id")
    readonly_fields = (
        "id",
        "public_code",
        "date_joined",
        "last_login",
        "phone_verified_at",
        "upgraded_at",
        "created_at",
        "updated_at",
    )
    inlines = [StudentProfileInline]

    fieldsets = (
        ("المعلومات الأساسية", {"fields": ("id", "public_code", "phone", "password", "account_type")}),
        ("الصلاحيات والحالة", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("التواريخ", {"fields": ("date_joined", "last_login", "phone_verified_at", "upgraded_at", "created_at", "updated_at")}),
    )

    add_fieldsets = (
        (
            "بيانات الحساب الجديد",
            {
                "classes": ("wide",),
                "fields": (
                    "phone",
                    "password",
                    "password_confirm",
                    "account_type",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )

    def get_inlines(self, request, obj=None):
        if obj is None:
            return []
        return super().get_inlines(request, obj)


@admin.register(PhoneVerification)
class PhoneVerificationAdmin(admin.ModelAdmin):
    list_display = (
        "request_id",
        "phone",
        "purpose",
        "attempts_count",
        "resend_count",
        "expires_at",
        "verified_at",
        "consumed_at",
        "created_at",
    )
    list_filter = ("purpose", "verified_at", "consumed_at")
    search_fields = ("phone", "request_id")
    readonly_fields = (
        "id",
        "phone",
        "purpose",
        "code_hash",
        "verification_grant_hash",
        "request_id",
        "attempts_count",
        "resend_count",
        "expires_at",
        "verified_at",
        "consumed_at",
        "created_at",
        "last_sent_at",
        "request_ip",
        "installation_id",
    )

    def has_add_permission(self, request):
        return False


@admin.register(UserDevice)
class UserDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "installation_id",
        "user",
        "platform",
        "device_name",
        "app_version",
        "is_active",
        "last_seen_at",
    )
    list_filter = ("platform", "is_active")
    search_fields = ("installation_id", "device_name", "user__phone", "user__public_code")
    readonly_fields = ("id", "first_seen_at", "last_seen_at", "created_at", "updated_at", "push_token")


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "device",
        "expires_at",
        "revoked_at",
        "created_at",
    )
    list_filter = ("revoked_at",)
    search_fields = ("user__phone", "user__public_code", "refresh_token_jti")
    readonly_fields = (
        "id",
        "user",
        "device",
        "refresh_token_jti",
        "refresh_token_hash",
        "expires_at",
        "revoked_at",
        "created_at",
        "last_used_at",
        "last_ip",
        "user_agent",
    )

    def has_add_permission(self, request):
        return False


@admin.register(AccountMerge)
class AccountMergeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "source_guest",
        "target_user",
        "status",
        "started_at",
        "completed_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("source_guest__id", "target_user__phone", "target_user__public_code")
    readonly_fields = (
        "id",
        "source_guest",
        "target_user",
        "status",
        "started_at",
        "completed_at",
        "conflict_data",
        "error_message",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False
