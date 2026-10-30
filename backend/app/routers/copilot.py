import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.core.security import COOKIE_NAME, current_user
from app.models import CopilotConversation, User
from app.routers.auth import audit
from app.services import copilot

router = APIRouter(prefix="/copilot", tags=["copilote"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: int | None = None
    page: str = Field("", max_length=300)


class ActionLog(BaseModel):
    kind: str = Field(max_length=40)
    summary: str = Field("", max_length=300)
    applied: bool


def _own(db: Session, user: User, conv_id: int) -> CopilotConversation:
    conv = db.get(CopilotConversation, conv_id)
    if not conv or conv.user_id != user.id:  # chacun ne voit que ses conversations
        raise HTTPException(404, "Conversation introuvable")
    return conv


@router.get("/status")
def status(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return copilot.status(db)


@router.get("/conversations")
def conversations(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(
        select(CopilotConversation)
        .where(CopilotConversation.user_id == user.id)
        .order_by(CopilotConversation.updated_at.desc())
        .limit(50)
    )
    return [{"id": c.id, "title": c.title, "updated_at": c.updated_at} for c in rows]


@router.get("/conversations/{conv_id}")
def conversation(conv_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    conv = _own(db, user, conv_id)
    return {
        "id": conv.id,
        "title": conv.title,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "actions": json.loads(m.actions) if m.actions else [],
            }
            for m in conv.messages
        ],
    }


@router.delete("/conversations/{conv_id}", status_code=204)
def delete_conversation(conv_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.delete(_own(db, user, conv_id))
    db.commit()


@router.post("/chat")
def chat(body: ChatIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Réponse en flux (Server-Sent Events)."""
    if body.conversation_id:
        conv_id = _own(db, user, body.conversation_id).id
    else:
        conv = CopilotConversation(user_id=user.id)
        db.add(conv)
        db.commit()
        conv_id = conv.id
    user_id, token = user.id, request.cookies.get(COOKIE_NAME, "")

    async def stream():
        # Session propre au flux : celle de la requête est fermée avant la fin de la réponse.
        with SessionLocal() as s:
            u, c = s.get(User, user_id), s.get(CopilotConversation, conv_id)
            async for chunk in copilot.chat(s, u, c, body.message, body.page, token):
                yield chunk

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@router.post("/actions/log", status_code=204)
def log_action(body: ActionLog, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Trace dans le journal d'activité les propositions de l'IA validées ou ignorées."""
    audit(
        db,
        user.email,
        f"copilot_action_{'applied' if body.applied else 'dismissed'}",
        f"{body.kind}: {body.summary}",
    )
