import json
import hashlib
import logging
from typing import Dict, Any, List, Tuple, Optional
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserDevice
from apps.curriculum.models import StudyEnrollment
from apps.synchronization.models import SyncOperation, SyncBatchReceipt, SyncStatus
from apps.progress.services.resource_tracking import (
    start_learning_resource,
    complete_learning_resource,
)
from apps.progress.services.session_tracking import (
    start_learning_session,
    heartbeat_learning_session,
    finish_learning_session,
)
from apps.common.exceptions import ApplicationError

logger = logging.getLogger("synchronization.dispatcher")

PROHIBITED_KEYS = {
    "phone",
    "name",
    "token",
    "authorization",
    "otp",
    "activation_code",
    "raw_answer",
    "answer_text",
    "essay_response",
    "score",
    "correct_count",
    "completion_percentage",
    "file_path",
    "storage_path",
}

UNSUPPORTED_OPERATIONS = {
    "answer_saved",
    "attempt_submitted",
    "offline_attempt_started",
    "assessment_submitted",
    "score_updated",
    "subscription_activated",
    "guest_merged",
}

SUPPORTED_OPERATIONS = {
    "resource_started",
    "resource_completed",
    "learning_session_started",
    "learning_session_heartbeat",
    "learning_session_finished",
}


def sanitize_and_check_prohibited_keys(payload: Any) -> bool:
    """
    Recursively inspects payload dict/list for prohibited keys (case-insensitive).
    Returns True if clean, False if prohibited keys are present.
    """
    if isinstance(payload, dict):
        for k, v in payload.items():
            if str(k).lower() in PROHIBITED_KEYS:
                return False
            if not sanitize_and_check_prohibited_keys(v):
                return False
    elif isinstance(payload, list):
        for item in payload:
            if not sanitize_and_check_prohibited_keys(item):
                return False
    return True


def compute_canonical_hash(data: Any) -> str:
    """
    Computes SHA-256 hash over canonical JSON serialization.
    """
    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class SyncOperationDispatcher:
    """
    Batch Dispatcher for Synchronization Operations.
    """

    def __init__(
        self,
        *,
        user,
        installation_id: str,
        enrollment: Optional[StudyEnrollment],
        raw_request_bytes: int,
    ):
        self.user = user
        self.installation_id = installation_id
        self.enrollment = enrollment
        self.raw_request_bytes = raw_request_bytes

    def dispatch_batch(
        self,
        *,
        client_batch_id: str,
        operations: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], int]:
        """
        Dispatches a batch of operations.
        Returns (response_dict, status_code).
        """
        max_batch_ops = getattr(settings, "SYNC_MAX_BATCH_OPERATIONS", 50)
        max_request_bytes = getattr(settings, "SYNC_MAX_REQUEST_BYTES", 524288)

        # 1. Byte and count limit checks
        if self.raw_request_bytes > max_request_bytes:
            return {
                "success": False,
                "error": {"code": "PAYLOAD_TOO_LARGE", "message": "حجم طلب الدفعة يتجاوز الحد الأقصى المسموح به."},
            }, 413

        if len(operations) > max_batch_ops:
            return {
                "success": False,
                "error": {"code": "TOO_MANY_OPERATIONS", "message": f"عدد العمليات يتجاوز الحد الأقصى ({max_batch_ops})."},
            }, 400

        if not operations:
            return {
                "success": False,
                "error": {"code": "EMPTY_BATCH", "message": "قائمة العمليات فارغة."},
            }, 400

        # 2. Installation resolution & ownership verification
        device = UserDevice.objects.filter(user=self.user, installation_id=self.installation_id, is_active=True).first()
        if not device:
            # Register device lazily for active user if installation_id valid
            device = UserDevice.objects.create(
                user=self.user,
                installation_id=self.installation_id,
                platform="android",
                is_active=True,
            )

        # 3. Batch Idempotency Check via SyncBatchReceipt
        batch_hash = compute_canonical_hash({"batch_id": str(client_batch_id), "ops": operations})
        existing_receipt = SyncBatchReceipt.objects.filter(
            user=self.user,
            installation=device,
            client_batch_id=client_batch_id,
        ).first()

        if existing_receipt:
            if existing_receipt.payload_hash == batch_hash:
                return existing_receipt.response_body, 200
            else:
                return {
                    "success": False,
                    "error": {
                        "code": "IDEMPOTENCY_CONFLICT",
                        "message": "تم استخدام نفس client_batch_id بمحتوى مختلف.",
                    },
                }, 409

        # 4. Batch Receipt Record
        batch_receipt = SyncBatchReceipt.objects.create(
            user=self.user,
            study_enrollment=self.enrollment,
            installation=device,
            client_batch_id=client_batch_id,
            payload_hash=batch_hash,
            operations_count=len(operations),
            status=SyncStatus.PROCESSING,
        )

        results = []
        completed_count = 0
        failed_count = 0
        conflict_count = 0

        # 5. Process operations in batch (Bulk fetch existing operations first for efficiency)
        op_ids = [op.get("client_operation_id") for op in operations if op.get("client_operation_id")]
        existing_ops_map = {
            str(op.client_operation_id): op
            for op in SyncOperation.objects.filter(
                user=self.user,
                installation=device,
                client_operation_id__in=op_ids,
            )
        }

        max_op_bytes = getattr(settings, "SYNC_MAX_OPERATION_BYTES", 8192)

        for op_data in operations:
            client_op_id = op_data.get("client_operation_id")
            op_type = op_data.get("operation_type", "unknown")

            if not client_op_id:
                results.append({
                    "client_operation_id": None,
                    "status": "failed",
                    "error": {"code": "MISSING_OPERATION_ID", "message": "حقل client_operation_id مطلوب."},
                })
                failed_count += 1
                continue

            client_op_str = str(client_op_id)
            op_json_bytes = len(json.dumps(op_data).encode("utf-8"))

            if op_json_bytes > max_op_bytes:
                results.append({
                    "client_operation_id": client_op_str,
                    "status": "failed",
                    "error": {"code": "OPERATION_PAYLOAD_TOO_LARGE", "message": "حجم العملية يتجاوز الحد الأقصى."},
                })
                failed_count += 1
                continue

            # Prohibited keys check
            if not sanitize_and_check_prohibited_keys(op_data):
                results.append({
                    "client_operation_id": client_op_str,
                    "status": "failed",
                    "error": {"code": "PROHIBITED_KEY_DETECTED", "message": "تحتوي العملية على حقول محظورة."},
                })
                failed_count += 1
                continue

            op_hash = compute_canonical_hash(op_data)

            # Check operation idempotency
            existing_op = existing_ops_map.get(client_op_str)
            if existing_op:
                if existing_op.payload_hash == op_hash:
                    results.append({
                        "client_operation_id": client_op_str,
                        "status": existing_op.status,
                        "response": existing_op.response_body or {},
                    })
                    if existing_op.status == SyncStatus.COMPLETED:
                        completed_count += 1
                    else:
                        failed_count += 1
                    continue
                else:
                    results.append({
                        "client_operation_id": client_op_str,
                        "status": "conflict",
                        "error": {
                            "code": "IDEMPOTENCY_CONFLICT",
                            "message": "تم استخدام client_operation_id بنص حمولة مختلف.",
                        },
                    })
                    conflict_count += 1
                    continue

            # Execute operation within an isolated atomic transaction
            op_result, op_status = self._execute_single_operation(
                device=device,
                op_data=op_data,
                client_op_id=client_op_id,
                op_type=op_type,
                op_hash=op_hash,
            )

            results.append(op_result)
            if op_status == SyncStatus.COMPLETED:
                completed_count += 1
            elif op_status == SyncStatus.CONFLICT:
                conflict_count += 1
            else:
                failed_count += 1

        response_payload = {
            "success": True,
            "data": {
                "client_batch_id": str(client_batch_id),
                "results": results,
                "summary": {
                    "completed": completed_count,
                    "failed": failed_count,
                    "conflict": conflict_count,
                },
            },
        }

        # Complete batch receipt
        batch_receipt.status = SyncStatus.COMPLETED
        batch_receipt.response_body = response_payload
        batch_receipt.completed_at = timezone.now()
        batch_receipt.save(update_fields=["status", "response_body", "completed_at", "updated_at"])

        return response_payload, 200

    def _execute_single_operation(
        self,
        *,
        device: UserDevice,
        op_data: Dict[str, Any],
        client_op_id: Any,
        op_type: str,
        op_hash: str,
    ) -> Tuple[Dict[str, Any], str]:
        """
        Executes a single operation inside transaction.atomic()
        """
        # Reject unsupported offline attempts explicitly
        if op_type in UNSUPPORTED_OPERATIONS:
            sync_op = SyncOperation.objects.create(
                user=self.user,
                study_enrollment=self.enrollment,
                installation=device,
                client_operation_id=client_op_id,
                operation_type=op_type,
                normalized_payload=op_data,
                payload_hash=op_hash,
                status=SyncStatus.UNSUPPORTED,
                error_code="OFFLINE_ATTEMPT_NOT_SUPPORTED",
                response_status=400,
                response_body={"error": "مزامنة المحاولات غير المتصلة غير مدعومة في هذه المرحلة."},
                processed_at=timezone.now(),
            )
            return {
                "client_operation_id": str(client_op_id),
                "status": "failed",
                "error": {
                    "code": "OFFLINE_ATTEMPT_NOT_SUPPORTED",
                    "message": "مزامنة المحاولات غير المتصلة غير مدعومة في هذه المرحلة.",
                },
            }, SyncStatus.FAILED

        if op_type not in SUPPORTED_OPERATIONS:
            sync_op = SyncOperation.objects.create(
                user=self.user,
                study_enrollment=self.enrollment,
                installation=device,
                client_operation_id=client_op_id,
                operation_type=op_type,
                normalized_payload=op_data,
                payload_hash=op_hash,
                status=SyncStatus.UNSUPPORTED,
                error_code="SYNC_OPERATION_NOT_SUPPORTED",
                response_status=400,
                response_body={"error": f"نوع العملية {op_type} غير مدعوم."},
                processed_at=timezone.now(),
            )
            return {
                "client_operation_id": str(client_op_id),
                "status": "failed",
                "error": {
                    "code": "SYNC_OPERATION_NOT_SUPPORTED",
                    "message": f"نوع العملية {op_type} غير مدعوم.",
                },
            }, SyncStatus.FAILED

        # Dispatch to business service in atomic transaction
        try:
            with transaction.atomic():
                res_body = self._call_business_service(op_type, op_data)
                
                sync_op = SyncOperation.objects.create(
                    user=self.user,
                    study_enrollment=self.enrollment,
                    installation=device,
                    client_operation_id=client_op_id,
                    operation_type=op_type,
                    normalized_payload=op_data,
                    payload_hash=op_hash,
                    status=SyncStatus.COMPLETED,
                    response_status=200,
                    response_body=res_body,
                    processed_at=timezone.now(),
                )
                return {
                    "client_operation_id": str(client_op_id),
                    "status": "completed",
                    "response": res_body,
                }, SyncStatus.COMPLETED

        except ApplicationError as ae:
            sync_op = SyncOperation.objects.create(
                user=self.user,
                study_enrollment=self.enrollment,
                installation=device,
                client_operation_id=client_op_id,
                operation_type=op_type,
                normalized_payload=op_data,
                payload_hash=op_hash,
                status=SyncStatus.FAILED,
                error_code=ae.code or "APPLICATION_ERROR",
                response_status=getattr(ae, "status_code", 400),
                response_body={"error": str(ae.message)},
                processed_at=timezone.now(),
            )
            return {
                "client_operation_id": str(client_op_id),
                "status": "failed",
                "error": {
                    "code": ae.code or "APPLICATION_ERROR",
                    "message": str(ae.message),
                },
            }, SyncStatus.FAILED

        except Exception as e:
            logger.exception(f"Unhandled error processing sync op {client_op_id}: {e}")
            sync_op = SyncOperation.objects.create(
                user=self.user,
                study_enrollment=self.enrollment,
                installation=device,
                client_operation_id=client_op_id,
                operation_type=op_type,
                normalized_payload=op_data,
                payload_hash=op_hash,
                status=SyncStatus.FAILED,
                error_code="INTERNAL_SERVER_ERROR",
                response_status=500,
                response_body={"error": "حدث خطأ غير متوقع أثناء معالجة العملية."},
                processed_at=timezone.now(),
            )
            return {
                "client_operation_id": str(client_op_id),
                "status": "failed",
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "حدث خطأ غير متوقع أثناء معالجة العملية.",
                },
            }, SyncStatus.FAILED

    def _call_business_service(self, op_type: str, op_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delegates supported operation to progress domain services.
        Supports payload parameters passed either in nested "payload" dict or at root level.
        """
        payload = op_data.get("payload") if isinstance(op_data.get("payload"), dict) else op_data

        if op_type == "resource_started":
            prog = start_learning_resource(
                user=self.user,
                resource_type=payload.get("resource_type", "lesson"),
                resource_id=str(payload.get("resource_id")),
                client_event_id=payload.get("client_event_id"),
            )
            return {"progress_id": str(prog.id), "status": prog.status}

        elif op_type == "resource_completed":
            prog = complete_learning_resource(
                user=self.user,
                resource_type=payload.get("resource_type", "lesson"),
                resource_id=str(payload.get("resource_id")),
                client_event_id=payload.get("client_event_id"),
            )
            return {"progress_id": str(prog.id), "status": prog.status}

        elif op_type == "learning_session_started":
            sess = start_learning_session(
                user=self.user,
                resource_type=payload.get("resource_type", "lesson"),
                resource_id=str(payload.get("resource_id")),
                client_session_id=str(payload.get("client_session_id")),
            )
            return {"session_id": str(sess.id), "status": sess.status}

        elif op_type == "learning_session_heartbeat":
            sess = heartbeat_learning_session(
                user=self.user,
                client_session_id=str(payload.get("client_session_id")),
            )
            return {"session_id": str(sess.id), "status": sess.status}

        elif op_type == "learning_session_finished":
            sess = finish_learning_session(
                user=self.user,
                client_session_id=str(payload.get("client_session_id")),
            )
            return {"session_id": str(sess.id), "status": sess.status}

        raise ApplicationError(f"نوع العملية {op_type} غير معروف.", code="UNKNOWN_OPERATION")
