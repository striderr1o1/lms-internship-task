from fastapi import APIRouter, Request, Response

from app.services import mux_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/mux", status_code=204)
async def mux_webhook(request: Request) -> Response:
    raw_body = await request.body()
    mux_service.handle_webhook(raw_body, request.headers.get("mux-signature"))
    return Response(status_code=204)
