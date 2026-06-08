from app.repositories.user_repo import UserRepo
from app.repositories.tenant_repo import TenantRepo
from app.repositories.kb_repo import KBRepo
from app.repositories.document_repo import DocumentRepo
from app.repositories.prompt_log_repo import PromptLogRepo
from app.repositories.job_log_repo import JobLogRepo

__all__ = ["UserRepo", "TenantRepo", "KBRepo", "DocumentRepo", "PromptLogRepo", "JobLogRepo"]
