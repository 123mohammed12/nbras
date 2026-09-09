"""
Custom User Manager.

Provides methods for creating regular users, guests, and superusers.
"""

from django.contrib.auth.models import BaseUserManager


class UserManager(BaseUserManager):
    """Custom manager for User model with phone-based authentication."""

    def create_user(self, phone=None, password=None, **extra_fields):
        """Create a regular registered user."""
        if phone:
            from apps.accounts.models.user import normalize_phone
            phone = normalize_phone(phone)

        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("account_type", "registered")

        user = self.model(phone=phone, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_guest(self, **extra_fields):
        """Create a guest user with no phone or password."""
        extra_fields["account_type"] = "guest"
        extra_fields["phone"] = None
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)

        user = self.model(**extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone=None, password=None, **extra_fields):
        """Create a superuser for Django admin."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("account_type", "registered")

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(phone=phone, password=password, **extra_fields)
