"""Admin-only Evaluation Dashboard APIs (read-only over Evaluation Framework v2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import require_admin
from app.evaluation import admin_service as svc

router = APIRouter(prefix="/admin/evaluations", tags=["admin-evaluations"])


@router.get("/summary")
def evaluation_summary(admin: dict = Depends(require_admin)):
    return svc.get_summary()


@router.get("/runs")
def list_evaluation_runs(
    admin: dict = Depends(require_admin),
    corpus: str | None = None,
    mock_mode: bool | None = None,
    embedding_model: str | None = None,
    generation_model: str | None = None,
    q: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return svc.list_runs(
        corpus=corpus,
        mock_mode=mock_mode,
        embedding_model=embedding_model,
        generation_model=generation_model,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}")
def get_evaluation_run(run_id: str, admin: dict = Depends(require_admin)):
    detail = svc.get_run_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return detail


@router.get("/runs/{run_id}/questions")
def list_evaluation_questions(
    run_id: str,
    admin: dict = Depends(require_admin),
    category: str | None = None,
    answerability: str | None = None,
    difficulty: str | None = None,
    decision: str | None = None,
    retrieval: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    result = svc.list_questions(
        run_id,
        category=category,
        answerability=answerability,
        difficulty=difficulty,
        decision=decision,
        retrieval=retrieval,
        status=status,
        q=q,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return result


@router.get("/runs/{run_id}/questions/{question_id}")
def get_evaluation_question(
    run_id: str,
    question_id: str,
    admin: dict = Depends(require_admin),
):
    detail = svc.get_question_detail(run_id, question_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Question result not found")
    return detail


@router.get("/runs/{run_id}/retrieval")
def get_retrieval_analysis(run_id: str, admin: dict = Depends(require_admin)):
    data = svc.get_retrieval_analysis(run_id)
    if not data:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return data


@router.get("/compare")
def compare_evaluation_runs(
    run_a: str = Query(...),
    run_b: str = Query(...),
    admin: dict = Depends(require_admin),
):
    if run_a == run_b:
        raise HTTPException(status_code=400, detail="run_a and run_b must differ")
    data = svc.compare_runs(run_a, run_b)
    if not data:
        raise HTTPException(status_code=404, detail="One or both evaluation runs not found")
    return data


@router.get("/experiments")
def evaluation_experiments(admin: dict = Depends(require_admin)):
    return svc.get_experiments_view()
