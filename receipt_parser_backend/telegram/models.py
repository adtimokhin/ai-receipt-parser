"""Minimal Telegram Bot API webhook payload models.

Only the fields the pipeline actually reads (spec Section 3-8). Not a full
Bot API client schema — extend as later milestones need more fields (e.g.
callback queries are out of v1's scope entirely).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    id: int
    is_bot: bool = False
    first_name: str = ""
    username: str | None = None


class Chat(BaseModel):
    id: int
    type: str


class MessageEntity(BaseModel):
    type: str
    offset: int
    length: int


class PhotoSize(BaseModel):
    file_id: str
    file_unique_id: str
    width: int
    height: int
    file_size: int | None = None


class Document(BaseModel):
    file_id: str
    file_unique_id: str
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


class Message(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_id: int
    date: int
    chat: Chat
    from_user: User | None = Field(default=None, alias="from")
    text: str | None = None
    entities: list[MessageEntity] = Field(default_factory=list)
    document: Document | None = None
    photo: list[PhotoSize] = Field(default_factory=list)


class Update(BaseModel):
    update_id: int
    message: Message | None = None
