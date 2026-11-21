from time import perf_counter

from app.manifest import run_manifest
from app.modules.review.decisions import conclusion, decisions
from app.modules.review.reconcile import reconcile
from app.pipeline import Survey
from app.reasons import REASONS


def run_review(settings, store, options):
    started = perf_counter()
    survey = Survey(settings, options)
    manifest = run_manifest(survey, 0)
    # 批次键已含四份原件摘要、参数和规则版本；同键重跑只回读原快照，
    # 不重新认定，也不改写原件、对账和已有签审。
    existing = store.get(manifest['run_id'], required=False)
    if existing is not None:
        return existing, True
    ledger = reconcile(survey.intake, survey.pairing, survey.refit, survey.seams)
    reviews = decisions(survey.catalog, survey.refit, survey.seams)
    manifest['processing_ms'] = round((perf_counter() - started) * 1000, 3)
    return store.insert({'manifest': manifest, 'catalog': survey.catalog, 'ledger': ledger,
                         'conclusion': conclusion(reviews), 'reviews': reviews,
                         'intake': survey.intake['tables'], 'coordinates': survey.coordinates,
                         'pairing': survey.pairing, 'affine': survey.affine,
                         'refit': survey.refit, 'seams': survey.seams})


def evidence(snapshot):
    return {'format': 'map-register/evidence-1', **snapshot, 'reason_dictionary': REASONS}
