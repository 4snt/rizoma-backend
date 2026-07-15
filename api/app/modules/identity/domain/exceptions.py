"""Exceções de domínio de identidade — `service.py` traduz para HTTP."""


class DomainNotAllowedError(Exception):
    """E-mail fora do domínio institucional permitido."""


class NotInvitedError(Exception):
    """Usuário novo sem convite pendente. Sem isso, qualquer pessoa do
    domínio criaria conta sozinha."""


class SlugTakenError(Exception):
    """Já existe organização com este slug."""


class AlreadyMemberError(Exception):
    """E-mail já é membro da organização — convite duplicado não faz sentido."""


class DuplicateInvitationError(Exception):
    """Já existe convite pendente para este e-mail nesta organização."""
