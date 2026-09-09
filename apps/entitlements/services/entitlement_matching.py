from typing import Any, Dict


def entitlement_matches_resource(entitlement: Any, resource_scope: Dict[str, Any]) -> bool:
    """
    Evaluates whether an Entitlement matches a resolved resource scope.
    
    resource_scope expected keys:
    - grade_id
    - section_id
    - subject_id
    - unit_id
    - assessment_id
    """
    if not entitlement or not entitlement.is_active:
        return False

    scope_type = entitlement.scope_type

    if scope_type == "platform":
        # Platform entitlement covers all published valid resources
        return True

    if scope_type == "grade":
        if not entitlement.grade_id or not resource_scope.get("grade_id"):
            return False
        return str(entitlement.grade_id) == str(resource_scope.get("grade_id"))

    if scope_type == "section":
        if not entitlement.grade_id or not entitlement.section_id:
            return False
        grade_match = str(entitlement.grade_id) == str(resource_scope.get("grade_id"))
        section_match = str(entitlement.section_id) == str(resource_scope.get("section_id"))
        return grade_match and section_match

    if scope_type == "subject":
        if not entitlement.subject_id or not resource_scope.get("subject_id"):
            return False
        return str(entitlement.subject_id) == str(resource_scope.get("subject_id"))

    if scope_type == "unit":
        if not entitlement.unit_id or not resource_scope.get("unit_id"):
            return False
        return str(entitlement.unit_id) == str(resource_scope.get("unit_id"))

    if scope_type == "assessment":
        if not entitlement.assessment_id or not resource_scope.get("assessment_id"):
            return False
        return str(entitlement.assessment_id) == str(resource_scope.get("assessment_id"))

    return False
