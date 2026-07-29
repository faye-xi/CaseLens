from caselens.domain.models import Case


def find_missing_evidence(case: Case) -> list[str]:
    if case.refund_id is None:
        return ["refund_record"]

    return []
