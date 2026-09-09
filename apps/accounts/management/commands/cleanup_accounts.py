"""
Management command to clean up expired OTP records, expired sessions, and inactive devices.

Usage:
    python manage.py cleanup_accounts [--expired-otp] [--expired-sessions] [--inactive-devices] [--dry-run] [--batch-size N] [--retention-days N]
"""

from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import PhoneVerification, UserDevice, UserSession


class Command(BaseCommand):
    help = "Clean up expired OTPs, revoked/expired sessions, and old inactive devices."

    def add_arguments(self, parser):
        parser.add_argument(
            "--expired-otp",
            action="store_true",
            help="Clean up expired or consumed OTP records.",
        )
        parser.add_argument(
            "--expired-sessions",
            action="store_true",
            help="Clean up expired or revoked session records.",
        )
        parser.add_argument(
            "--inactive-devices",
            action="store_true",
            help="Clean up inactive devices older than retention period.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform a dry run without actually deleting records.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Batch size for deletion (default: 1000).",
        )
        parser.add_argument(
            "--retention-days",
            type=int,
            default=None,
            help="Override default retention days.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        retention_days_arg = options["retention-days"]

        cleanup_all = not (
            options["expired_otp"] or options["expired_sessions"] or options["inactive_devices"]
        )

        if options["expired_otp"] or cleanup_all:
            days = retention_days_arg or getattr(settings, "ACCOUNTS_CLEANUP", {}).get("OTP_RETENTION_DAYS", 7)
            cutoff = timezone.now() - timedelta(days=days)
            qs = PhoneVerification.objects.filter(expires_at__lt=cutoff)
            count = qs.count()
            self.stdout.write(f"[OTP Cleanup] Found {count} records older than {days} days.")

            if not dry_run and count > 0:
                deleted, _ = qs[:batch_size]._raw_delete(qs.db) if hasattr(qs, "_raw_delete") else qs.filter(id__in=list(qs.values_list("id", flat=True)[:batch_size])).delete()
                self.stdout.write(self.style.SUCCESS(f"[OTP Cleanup] Deleted {deleted} records."))

        if options["expired_sessions"] or cleanup_all:
            days = retention_days_arg or getattr(settings, "ACCOUNTS_CLEANUP", {}).get("SESSION_RETENTION_DAYS", 90)
            cutoff = timezone.now() - timedelta(days=days)
            qs = UserSession.objects.filter(expires_at__lt=cutoff)
            count = qs.count()
            self.stdout.write(f"[Session Cleanup] Found {count} expired sessions older than {days} days.")

            if not dry_run and count > 0:
                deleted, _ = UserSession.objects.filter(id__in=list(qs.values_list("id", flat=True)[:batch_size])).delete()
                self.stdout.write(self.style.SUCCESS(f"[Session Cleanup] Deleted {deleted} sessions."))

        if options["inactive_devices"] or cleanup_all:
            days = retention_days_arg or getattr(settings, "ACCOUNTS_CLEANUP", {}).get("DEVICE_INACTIVE_DAYS", 365)
            cutoff = timezone.now() - timedelta(days=days)
            qs = UserDevice.objects.filter(is_active=False, last_seen_at__lt=cutoff)
            count = qs.count()
            self.stdout.write(f"[Device Cleanup] Found {count} inactive devices older than {days} days.")

            if not dry_run and count > 0:
                deleted, _ = UserDevice.objects.filter(id__in=list(qs.values_list("id", flat=True)[:batch_size])).delete()
                self.stdout.write(self.style.SUCCESS(f"[Device Cleanup] Deleted {deleted} devices."))

        self.stdout.write(self.style.SUCCESS("Cleanup completed successfully."))
