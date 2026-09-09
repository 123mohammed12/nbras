import logging
from apps.accounts.models import User
from apps.synchronization.models import SyncOperation, SyncBatchReceipt

logger = logging.getLogger("synchronization.guest_merge")


def sync_merge_handler(source_guest: User, target_user: User) -> dict:
    """
    Re-assigns SyncOperations and SyncBatchReceipts from source_guest to target_user.
    Idempotent and handles unique SQL constraint conflicts gracefully.
    """
    ops_transferred = 0
    batches_transferred = 0

    # 1. Transfer SyncOperations
    guest_ops = SyncOperation.objects.filter(user=source_guest).select_for_update()
    for op in guest_ops:
        existing = SyncOperation.objects.filter(
            user=target_user,
            installation=op.installation,
            client_operation_id=op.client_operation_id,
        ).first()
        if existing:
            # Duplicate op already exists under target user, delete source record
            op.delete()
        else:
            op.user = target_user
            op.save(update_fields=["user", "updated_at"])
            ops_transferred += 1

    # 2. Transfer SyncBatchReceipts
    guest_batches = SyncBatchReceipt.objects.filter(user=source_guest).select_for_update()
    for batch in guest_batches:
        existing = SyncBatchReceipt.objects.filter(
            user=target_user,
            installation=batch.installation,
            client_batch_id=batch.client_batch_id,
        ).first()
        if existing:
            batch.delete()
        else:
            batch.user = target_user
            batch.save(update_fields=["user", "updated_at"])
            batches_transferred += 1

    logger.info(
        f"Guest merge sync handler completed: {ops_transferred} ops, {batches_transferred} batches transferred from {source_guest.id} to {target_user.id}"
    )

    return {
        "sync_ops_transferred": ops_transferred,
        "sync_batches_transferred": batches_transferred,
    }
