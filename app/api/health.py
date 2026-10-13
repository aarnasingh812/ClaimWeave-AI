from fastapi import APIRouter, Depends
from app.core.security import current_user
from app.health import INSURERS

router = APIRouter(prefix='/api/v1/health', tags=['health guidance'])


@router.get('/insurers', dependencies=[Depends(current_user)])
def list_insurer_guidance():
    return INSURERS
