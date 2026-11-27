"""Compatibility responses for the retired cost and payment tracker."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .finance_helpers import BOOKS_ENTRY_MESSAGE
from .security import APPROVERS, FINANCE_READ, FINANCE_WRITE, permit

costs_router = APIRouter()
approvals_router = APIRouter()


class ReversalIn(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


@costs_router.get('/api/costs', dependencies=[Depends(permit(*FINANCE_READ))])
def get_costs():
    return []


@costs_router.post('/api/costs', dependencies=[Depends(permit(*FINANCE_WRITE))])
@costs_router.post('/api/payments', dependencies=[Depends(permit(*FINANCE_WRITE))])
def retired_tracker_entry():
    raise HTTPException(410, BOOKS_ENTRY_MESSAGE)


@costs_router.patch('/api/costs/{cost_id}/recognize', dependencies=[Depends(permit(*APPROVERS))])
def recognize_purchase(cost_id: int):
    raise HTTPException(410, BOOKS_ENTRY_MESSAGE)


@approvals_router.get('/api/approvals', dependencies=[Depends(permit(*APPROVERS))])
def pending_approvals():
    return {'costs': [], 'payments': []}


@approvals_router.post('/api/costs/{cost_id}/approve', dependencies=[Depends(permit(*APPROVERS))])
@approvals_router.post('/api/costs/{cost_id}/reject', dependencies=[Depends(permit(*APPROVERS))])
@approvals_router.post('/api/costs/{cost_id}/correct', dependencies=[Depends(permit(*APPROVERS))])
def retired_cost_action(cost_id: int):
    raise HTTPException(410, BOOKS_ENTRY_MESSAGE)


@approvals_router.post('/api/payments/{payment_id}/approve', dependencies=[Depends(permit(*APPROVERS))])
@approvals_router.post('/api/payments/{payment_id}/reject', dependencies=[Depends(permit(*APPROVERS))])
@approvals_router.post('/api/payments/{payment_id}/reverse', dependencies=[Depends(permit(*APPROVERS))])
def retired_payment_action(payment_id: int):
    raise HTTPException(410, BOOKS_ENTRY_MESSAGE)


@approvals_router.get('/api/payments', dependencies=[Depends(permit(*FINANCE_READ))])
def get_payments():
    return []
