from pydantic import BaseModel, Field
from typing import List, Optional


class ParamInfo(BaseModel):
    name: str
    description: str = ""


class CommentItem(BaseModel):
    functionName: str = "anonymous"
    line: int = 1
    description: str = ""
    parameters: List[ParamInfo] = Field(default_factory=list)
    returns: str = ""
    comment: str = ""


class CommentResult(BaseModel):
    summary: str = ""
    comments: List[CommentItem] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class RegisterReq(BaseModel):
    username: str
    email: str
    password: str


class LoginReq(BaseModel):
    username: str
    password: str


class AdminCreateUserReq(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"


class AdminUpdateUserReq(BaseModel):
    disabled: Optional[bool] = None
    role: Optional[str] = None


class ChangePasswordReq(BaseModel):
    currentPassword: str
    newPassword: str


class FeedbackReq(BaseModel):
    generationId: str
    rating: str
    comment: str = ""


class GenerateReq(BaseModel):
    code: str
    language: str = "javascript"
    style: str = "default"
    task: str = "生成函数级代码注释"
